#!/usr/bin/env python3
"""Release orchestrator for ligoj-cli.

Drives the whole release dance from the command line so the GitHub Actions
workflows only have to build and publish:

  * ``release``  — bump the version, run the local quality gate, commit, tag,
    push, create the GitHub Release (which triggers ``deploy.yml``) and wait
    until the version is actually live on PyPI.
  * ``test``     — push the current HEAD to ``develop`` (which triggers
    ``deploy-test.yml``) and wait until a fresh ``.devN`` build appears on
    TestPyPI.

Stdlib only. Invoked through the Makefile (``make release`` / ``make
release-test``); ``uv`` is taken from the ``UV`` environment variable.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

PACKAGE = "ligoj-cli"
MAIN_BRANCH = "main"
TEST_BRANCH = "develop"
PYPROJECT = "pyproject.toml"
LOCKFILE = "uv.lock"
PYPI_JSON = "https://pypi.org/pypi/{pkg}/json"
PYPI_VERSION_JSON = "https://pypi.org/pypi/{pkg}/{version}/json"
TESTPYPI_JSON = "https://test.pypi.org/pypi/{pkg}/json"
UV = os.environ.get("UV") or "uv"

# ── pretty console feedback ──────────────────────────────────────────────────
# Line-buffer stdout so steps stay ordered relative to stderr, even when piped.
try:
    sys.stdout.reconfigure(line_buffering=True)
except (AttributeError, OSError):
    pass

_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def _bold(t):  # noqa: E704
    return _c("1", t)


def _dim(t):  # noqa: E704
    return _c("2", t)


_STEP = 0
_TOTAL = 0


def steps(total: int) -> None:
    global _TOTAL, _STEP
    _TOTAL, _STEP = total, 0


def step(msg: str) -> None:
    global _STEP
    _STEP += 1
    print(f"\n{_c('36', _bold(f'[{_STEP}/{_TOTAL}]'))} {_bold(msg)}")


def ok(msg: str) -> None:
    print(f"  {_c('32', '✓')} {msg}")


def info(msg: str) -> None:
    print(f"  {_dim('·')} {_dim(msg)}")


def warn(msg: str) -> None:
    print(f"  {_c('33', '!')} {msg}")


def die(msg: str) -> "None":
    print(f"\n{_c('31', _bold('✗ ' + msg))}", file=sys.stderr)
    raise SystemExit(1)


def banner(title: str) -> None:
    line = "─" * (len(title) + 2)
    print(_c("36", f"\n┌{line}┐\n│ {_bold(title)} │\n└{line}┘"))


# ── shell helpers ────────────────────────────────────────────────────────────
def run(cmd: list[str], capture: bool = False, check: bool = True) -> str:
    info("$ " + " ".join(cmd))
    res = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )
    if check and res.returncode != 0:
        if capture and res.stderr:
            print(res.stderr, file=sys.stderr)
        die(f"command failed ({res.returncode}): {' '.join(cmd)}")
    return (res.stdout or "").strip()


def http_get(url: str) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, TimeoutError):
        return 0, b""


# ── version handling ─────────────────────────────────────────────────────────
def read_version() -> str:
    with open(PYPROJECT, encoding="utf-8") as f:
        m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.MULTILINE)
    if not m:
        die(f"could not find a version in {PYPROJECT}")
    return m.group(1)


def version_key(version: str) -> tuple[int, ...]:
    """Natural ordering for a version string, so '1.1.0.dev10' sorts after '1.1.0.dev9'.

    A plain string sort puts 'dev10' *before* 'dev9', which would report the wrong build once the
    dev counter reaches double digits. Comparing the numeric groups avoids that without pulling in
    `packaging` just for this.
    """
    return tuple(int(number) for number in re.findall(r"\d+", version))


def bump(version: str, part: str) -> str:
    try:
        major, minor, patch = (int(x) for x in version.split("."))
    except ValueError:
        die(f"version {version!r} is not MAJOR.MINOR.PATCH; cannot bump")
    return {
        "major": f"{major + 1}.0.0",
        "minor": f"{major}.{minor + 1}.0",
        "patch": f"{major}.{minor}.{patch + 1}",
    }[part]


def write_version(new: str) -> None:
    with open(PYPROJECT, encoding="utf-8") as f:
        text = f.read()
    text = re.sub(r'^(version\s*=\s*)"[^"]+"', rf'\g<1>"{new}"', text, count=1, flags=re.MULTILINE)
    with open(PYPROJECT, "w", encoding="utf-8") as f:
        f.write(text)


# ── waiting on the index ─────────────────────────────────────────────────────
def wait_until(predicate, what: str, timeout: int = 900, interval: int = 5) -> None:
    start = time.monotonic()
    spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    i = 0
    while True:
        if predicate():
            elapsed = int(time.monotonic() - start)
            sys.stdout.write("\r\033[K")
            ok(f"{what} (after {elapsed}s)")
            return
        elapsed = int(time.monotonic() - start)
        if elapsed >= timeout:
            sys.stdout.write("\r\033[K")
            die(f"timed out after {timeout}s waiting for {what}")
        if _COLOR:
            sys.stdout.write(f"\r  {spin[i % len(spin)]} waiting for {what}… {elapsed}s")
            sys.stdout.flush()
        i += 1
        time.sleep(interval)


def pypi_has_version(pkg: str, version: str) -> bool:
    status, _ = http_get(PYPI_VERSION_JSON.format(pkg=pkg, version=version))
    return status == 200


def testpypi_versions(pkg: str) -> set[str]:
    status, body = http_get(TESTPYPI_JSON.format(pkg=pkg))
    if status != 200:
        return set()
    try:
        return set(json.loads(body).get("releases", {}))
    except json.JSONDecodeError:
        return set()


# ── git / preflight ──────────────────────────────────────────────────────────
def current_branch() -> str:
    return run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True)


def preflight_clean() -> None:
    dirty = run(["git", "status", "--porcelain"], capture=True)
    if dirty:
        lines = [line for line in dirty.splitlines() if line.strip()]
        for line in lines[:10]:
            info(_dim(line))
        if len(lines) > 10:
            info(_dim(f"... and {len(lines) - 10} more"))
        # Single out the self-inflicted case: `uv run` regenerates uv.lock whenever pyproject's
        # version moved, so a release that committed only pyproject.toml leaves the lock stale and
        # every later run trips this check for a file the user never touched.
        if any(line.split()[-1] == LOCKFILE for line in lines):
            die(
                f"working tree is not clean — {LOCKFILE} is stale (a version bump was committed "
                f"without it). Run '{UV} lock' and commit {LOCKFILE}"
            )
        die("working tree is not clean — commit or stash first")
    ok("working tree clean")


def preflight_synced(branch: str) -> None:
    run(["git", "fetch", "--quiet", "origin", branch], check=False)
    behind = run(
        ["git", "rev-list", "--count", f"HEAD..origin/{branch}"], capture=True, check=False
    )
    if behind and behind != "0":
        die(
            f"local {branch} is {behind} commit(s) behind origin/{branch} — run 'git pull --ff-only'"
        )
    ok(f"in sync with origin/{branch}")


# ── quality gate ─────────────────────────────────────────────────────────────
def quality_gate() -> None:
    run([UV, "run", "ruff", "check", "."])
    run([UV, "run", "ruff", "format", "--check", "."])
    run([UV, "run", "flake8"])
    run(["rm", "-rf", "dist", "build"])
    run([UV, "build"])
    dists = glob.glob("dist/*")
    if not dists:
        die("build produced no artifacts in dist/")
    run([UV, "run", "--with", "twine", "twine", "check", *dists])
    ok("lint, format, build and twine check passed")


# ── commands ─────────────────────────────────────────────────────────────────
def cmd_release(part: str, yes: bool) -> None:
    banner(f"Release {PACKAGE} → PyPI")
    steps(8)

    step("Pre-flight checks")
    branch = current_branch()
    if branch != MAIN_BRANCH:
        die(f"must be on '{MAIN_BRANCH}' (currently on '{branch}')")
    ok(f"on '{MAIN_BRANCH}'")
    preflight_clean()
    preflight_synced(MAIN_BRANCH)

    step("Compute next version")
    current = read_version()
    new = bump(current, part)
    tag = f"v{new}"
    if run(["git", "tag", "--list", tag], capture=True):
        die(f"tag {tag} already exists")
    ok(f"{current} → {_bold(new)} ({part} bump), tag {tag}")
    if not yes:
        reply = input(f"\n  {_bold('Proceed with release ' + new + '?')} [y/N] ").strip().lower()
        if reply not in ("y", "yes"):
            die("aborted by user")

    step("Run quality gate")
    quality_gate()

    step("Bump version and commit")
    write_version(new)
    # uv.lock pins the project's OWN version, so it goes stale the instant pyproject.toml moves.
    # Refresh it and commit it WITH the bump: otherwise the next `uv run` (which is how this script
    # is launched) silently rewrites the lock, dirties the tree, and preflight_clean() aborts every
    # subsequent release — with no hint that the lockfile is the culprit.
    staged = [PYPROJECT]
    if os.path.exists(LOCKFILE):
        run([UV, "lock"])
        staged.append(LOCKFILE)
    run(["git", "add", *staged])
    run(["git", "commit", "-m", f"chore(release): {tag}"])
    ok(f"committed version bump to {new} ({', '.join(staged)})")

    step("Tag and push")
    run(["git", "tag", "-a", tag, "-m", f"Release {tag}"])
    run(["git", "push", "origin", MAIN_BRANCH])
    run(["git", "push", "origin", tag])
    ok(f"pushed {MAIN_BRANCH} and {tag}")

    step("Create the GitHub Release (triggers deploy.yml)")
    run(
        [
            "gh",
            "release",
            "create",
            tag,
            "--target",
            MAIN_BRANCH,
            "--title",
            tag,
            "--generate-notes",
        ]
    )
    ok(f"GitHub Release {tag} published")

    step("Wait until the version is live on PyPI")
    info("the publish workflow builds and uploads via Trusted Publishing…")
    wait_until(lambda: pypi_has_version(PACKAGE, new), f"{PACKAGE} {new} on PyPI", timeout=1200)

    step("Done")
    print()
    ok(f"Released {_bold(PACKAGE + ' ' + new)} 🎉")
    print(f"  {_dim('PyPI:')}    https://pypi.org/project/{PACKAGE}/{new}/")
    print(f"  {_dim('Release:')} https://github.com/ligoj/cli/releases/tag/{tag}")
    print(f"  {_dim('Install:')} pip install {PACKAGE}=={new}\n")


def cmd_test() -> None:
    banner(f"Test publish {PACKAGE} → TestPyPI")
    steps(4)

    step("Pre-flight checks")
    preflight_clean()
    head = run(["git", "rev-parse", "--short", "HEAD"], capture=True)
    ok(f"HEAD at {head} on '{current_branch()}'")

    step("Snapshot current TestPyPI versions")
    before = testpypi_versions(PACKAGE)
    info(f"{len(before)} version(s) currently on TestPyPI")

    step(f"Push HEAD to '{TEST_BRANCH}' (triggers deploy-test.yml)")
    run(["git", "fetch", "--quiet", "origin", TEST_BRANCH], check=False)
    run(["git", "push", "--force-with-lease", "origin", f"HEAD:{TEST_BRANCH}"])
    ok(f"pushed to '{TEST_BRANCH}'")
    info("workflow runs: https://github.com/ligoj/cli/actions/workflows/deploy-test.yml")

    step("Wait for a fresh .dev build on TestPyPI")

    # Keep what the poll actually saw. Re-querying the index afterwards is a race: the JSON API sits
    # behind a CDN, so a second call can land on a node still serving the pre-publish body — the
    # difference then comes back empty and picking the newest version blows up on an empty list.
    found: set[str] = set()

    def appeared() -> bool:
        found.update(testpypi_versions(PACKAGE) - before)
        return bool(found)

    wait_until(appeared, "a new TestPyPI build", timeout=1200)
    new = max(found, key=version_key)
    print()
    ok(f"Published {_bold(PACKAGE + ' ' + new)} to TestPyPI 🧪")
    print(f"  {_dim('TestPyPI:')} https://test.pypi.org/project/{PACKAGE}/{new}/")
    print(
        f"  {_dim('Install:')}  pip install -i https://test.pypi.org/simple/ "
        f"--extra-index-url https://pypi.org/simple/ {PACKAGE}=={new}\n"
    )


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("release", help="cut a real release to PyPI")
    pr.add_argument("--part", choices=("major", "minor", "patch"), default="minor")
    pr.add_argument("--yes", action="store_true", help="skip the confirmation prompt")

    sub.add_parser("test", help="publish a dev build to TestPyPI via the develop branch")

    args = p.parse_args()
    try:
        if args.cmd == "release":
            cmd_release(args.part, args.yes)
        else:
            cmd_test()
    except KeyboardInterrupt:
        die("interrupted")


if __name__ == "__main__":
    main()
