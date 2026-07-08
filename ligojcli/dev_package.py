#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# `dev package` — build the two Ligoj application container images (ligoj-api + ligoj-ui) LOCALLY,
# straight from their Dockerfiles with podman (or docker). The API image is built with all three JDBC
# drivers forced in (db-postgresql, db-mysql, db-mariadb) so it can reach the dev PostgreSQL instead of
# failing at boot with ClassNotFoundException. Nothing is pushed — the result is exactly what
# `dev test start` runs. A full release (deploy, tags, Docker Hub) is out of scope: use the release
# helper (commands/release.sh) for that.
#
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from ligojcli.plugins import dev, utils

_DEFAULT_PROJECT = "~/git/ligoj"
_API_IMAGE = "ligoj/ligoj-api"
_UI_IMAGE = "ligoj/ligoj-ui"

# The three JDBC-driver Maven profiles. They are <activeByDefault> in app-api/pom.xml, but Maven
# disables every default profile as soon as a settings.xml <activeProfiles> is in play — which
# silently drops the drivers from the war. Forcing them here (Dockerfile ARG MAVEN_PROFILES) keeps the
# image DB-capable regardless of the build's settings.xml.
_DRIVER_PROFILES = "db-postgresql,db-mysql,db-mariadb"

# The plugin-vendors truststore (public certs) bundled into the API image, and its password sources.
_VENDORS_P12 = "~/.ligoj/plugin-vendors.p12"
_VENDORS_KEYCHAIN = "ligoj.release.vendors-storepass"

# label -> (image, Dockerfile context sub-dir, image-specific build-args)
_IMAGES = {
    "api": (_API_IMAGE, "app-api", {"MAVEN_PROFILES": _DRIVER_PROFILES}),
    "ui": (_UI_IMAGE, "app-ui", {}),
}


# --------------------------------------------------------------------------- #
# Configuration resolution: CLI flag -> env -> ~/.ligoj/config -> ~/.ligoj/credentials -> default
# --------------------------------------------------------------------------- #
def _resolve(value, env, config_key, default=None):
    if value not in (None, ""):
        return value
    env_value = os.environ.get(env)
    if env_value not in (None, ""):
        return env_value
    for store, section in (
        (utils.ini_config, utils.ini_profile),
        (utils.ini_credentials, dev.DEV_SECTION),
    ):
        if section and store.has_section(section):
            found = store.get(section, config_key, fallback=None)
            if found not in (None, ""):
                return utils.cleanup_ini_value(found)
    return default


def _runtime(preference):
    if preference:
        if shutil.which(preference) is None:
            raise ValueError(f"[package] container runtime '{preference}' not found on PATH")
        return preference
    for candidate in ("docker", "podman"):
        if shutil.which(candidate):
            return candidate
    raise ValueError("[package] neither 'docker' nor 'podman' found on PATH")


def _capture(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def _git(project, *args):
    result = _capture(["git", "-C", project, *args])
    return result.stdout.strip() if result.returncode == 0 else ""


def _keychain_secret(name):
    """A macOS login-keychain generic-password value, or None (matches the release helper's source)."""
    if sys.platform == "darwin":
        result = _capture(["security", "find-generic-password", "-s", name, "-w"])
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


def _project_version(project):
    """The Maven project <version> (direct child of <project>, not the <parent> one) from pom.xml."""
    pom = os.path.join(project, "pom.xml")
    try:
        root = ET.parse(pom).getroot()
    except (OSError, ET.ParseError) as error:
        raise ValueError(f"[package] cannot read {pom}: {error}")
    node = root.find("{*}version")  # a DIRECT child; the parent's <version> is nested in <parent>
    version = (node.text or "").strip() if node is not None else ""
    if not version:
        raise ValueError(f"[package] no project <version> in {pom}")
    return version


def _platforms(value):
    """[] = the host's native arch (fast); 'all' or a comma/space list = an explicit platform set."""
    if not value:
        return []
    if value.strip().lower() == "all":
        return ["linux/amd64", "linux/arm64"]
    return [part.strip() for part in value.replace(",", " ").split() if part.strip()]


def _declared_build_args(dockerfile):
    """The ARG names declared anywhere in a Dockerfile, so only consumed build-args are passed."""
    declared = set()
    try:
        with open(dockerfile, encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped.startswith("ARG "):
                    name = stripped[4:].split("=", 1)[0].strip()
                    if name:
                        declared.add(name)
    except OSError:
        pass
    return declared


def _build_image(runtime, context, image, extra_args, version, tag, platforms, provenance, vendors):
    dockerfile = os.path.join(context, "Dockerfile")
    if not os.path.isfile(dockerfile):
        raise ValueError(f"[package] {dockerfile} not found — is --project a Ligoj checkout?")
    declared = _declared_build_args(dockerfile)
    build_args = {
        "VERSION": version,
        "PLUGIN_VENDORS_STOREPASS": vendors,
        **provenance,
        **extra_args,
    }
    ref = f"{image}:{tag}"

    argv = [runtime, "build"]
    if len(platforms) > 1:
        # A multi-arch image is a manifest list; only podman builds one straight from `build`.
        if os.path.basename(runtime) != "podman":
            raise ValueError(
                "[package] multi-arch build needs podman (docker requires buildx); "
                "use --platform <single-arch> or the native default"
            )
        _capture([runtime, "manifest", "rm", ref])  # best-effort: drop a stale manifest of this tag
        for platform in platforms:
            argv += ["--platform", platform]
        argv += ["--manifest", ref]
    else:
        if platforms:
            argv += ["--platform", platforms[0]]
        argv += ["--tag", ref]
    for key, val in build_args.items():
        if key in declared and val:
            argv += ["--build-arg", f"{key}={val}"]
    argv.append(".")

    utils.info(
        f"[package] Build {ref} from {context} "
        f"({'native arch' if not platforms else ' '.join(platforms)}) ..."
    )
    result = subprocess.run(argv, cwd=context)  # inherit stdio: stream the (long) build live
    if result.returncode != 0:
        raise ValueError(f"[package] {runtime} build failed for {ref} (exit {result.returncode})")
    return ref


def _build_api(runtime, context, image, extra_args, version, tag, platforms, provenance, vendors):
    """Build the API image, bundling ~/.ligoj/plugin-vendors.p12 into the context when present."""
    vendors_src = os.path.expanduser(_VENDORS_P12)
    vendors_dir = os.path.join(context, "plugin-vendors")
    vendors_dst = os.path.join(vendors_dir, "plugin-vendors-default.p12")
    copied = False
    if os.path.isfile(vendors_src):
        os.makedirs(vendors_dir, exist_ok=True)
        shutil.copyfile(vendors_src, vendors_dst)
        copied = True
        utils.info(f"[package] Bundling {vendors_src} into the API image")
    try:
        return _build_image(
            runtime, context, image, extra_args, version, tag, platforms, provenance, vendors
        )
    finally:
        if copied:
            try:
                os.remove(vendors_dst)
                os.rmdir(vendors_dir)
            except OSError:
                pass


def execute(args):
    project = os.path.expanduser(
        _resolve(args.get("project"), "LIGOJ_DIR", "ligoj_dir", _DEFAULT_PROJECT)
    )
    if not os.path.isdir(project):
        raise ValueError(
            f"[package] project directory not found: {project} "
            "(set --project, LIGOJ_DIR or [dev] ligoj_dir)"
        )
    runtime = _runtime(_resolve(args.get("runtime"), "LIGOJ_TEST_RUNTIME", "ligoj_test_runtime"))
    version = _project_version(project)
    default_tag = version[: -len("-SNAPSHOT")] if version.endswith("-SNAPSHOT") else version
    tag = _resolve(args.get("tag"), "LIGOJ_PACKAGE_TAG", "ligoj_package_tag", default_tag)
    platforms = _platforms(args.get("platform"))
    only = args.get("only")
    targets = [only] if only else ["api", "ui"]

    provenance = {
        "GIT_COMMIT": _git(project, "rev-parse", "HEAD") or "0",
        "GIT_BRANCH": _git(project, "rev-parse", "--abbrev-ref", "HEAD") or "UNKNOWN_BRANCH",
        "GIT_COMMIT_TIME": _git(project, "show", "-s", "--format=%cI", "HEAD")
        or "1970-01-01T00:00:00Z",
    }
    vendors = (
        os.environ.get("PLUGIN_VENDORS_STOREPASS")
        or _keychain_secret(_VENDORS_KEYCHAIN)
        or "changeit"
    )

    utils.info(
        f"[package] {os.path.basename(runtime)} build [{', '.join(targets)}] tag '{tag}' "
        f"({'native arch' if not platforms else ' '.join(platforms)}) from {project} ..."
    )
    built = []
    for label in targets:
        image, subdir, extra = _IMAGES[label]
        context = os.path.join(project, subdir)
        builder = _build_api if label == "api" else _build_image
        built.append(
            builder(runtime, context, image, extra, version, tag, platforms, provenance, vendors)
        )
    utils.info(f"[package] Built {', '.join(built)} locally — run 'ligoj dev test start' to launch")
    return False


# --------------------------------------------------------------------------- #
# Help / notes (surfaced on 'dev package' and 'dev package -h')
# --------------------------------------------------------------------------- #
HELP = """\
dev package — build the Ligoj application container images locally (ligoj-api + ligoj-ui).

  Builds both images straight from the app-api/ and app-ui/ Dockerfiles with podman (or docker) and
  bundles all three JDBC drivers into the API (db-postgresql, db-mysql, db-mariadb) so it can reach
  the dev PostgreSQL. Nothing is pushed; the result is exactly what 'dev test start' runs.

Options:
  --project DIR      Ligoj checkout to build from   (default ~/git/ligoj, LIGOJ_DIR / [dev] ligoj_dir)
  --tag TAG          Image tag                       (default: project version without -SNAPSHOT,
                                                      LIGOJ_PACKAGE_TAG / [dev] ligoj_package_tag)
  --only api|ui      Build only one image            (default: both)
  --platform LIST    Target arch: a single arch (e.g. linux/arm64), a comma list, or 'all' for a
                     multi-arch manifest (podman). Default: the host's native arch (fast).
  --runtime docker|podman   Container runtime        (default: docker if present, else podman)

Notes:
  * The API image bundles the PostgreSQL/MySQL/MariaDB JDBC drivers (the build forces those Maven
    profiles), so it won't fail at boot with ClassNotFoundException like a default MySQL-only build.
  * ~/.ligoj/plugin-vendors.p12 is bundled into the API image when present (password from
    PLUGIN_VENDORS_STOREPASS, the 'ligoj.release.vendors-storepass' keychain entry, or 'changeit').
  * Local images only. For a full release (deploy, tags, Docker Hub) use commands/release.sh.
"""
