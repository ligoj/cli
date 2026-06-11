# Release Guide — `ligoj-cli`

Releasing is driven entirely from `make`. The GitHub Actions workflows only build and publish
using [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC, no API token).

| Command             | Index                 | Workflow                                              | Purpose              |
| ------------------- | --------------------- | ----------------------------------------------------- | -------------------- |
| `make release-test` | https://test.pypi.org | [deploy-test.yml](.github/workflows/deploy-test.yml)  | Validate end-to-end  |
| `make release`      | https://pypi.org      | [deploy.yml](.github/workflows/deploy.yml)            | Final public release |

Both commands print step-by-step progress and **wait until the package is actually live** on the
index before reporting success.

---

## 1. Test publish (TestPyPI)

```bash
make release-test
```

Pushes the current `HEAD` to the `develop` branch, which triggers
[deploy-test.yml](.github/workflows/deploy-test.yml). That workflow appends a unique
`.dev<run-number>` suffix, builds, and uploads to TestPyPI. The command then polls TestPyPI until
the new build appears and prints its install line, e.g.:

```bash
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ \
    ligoj-cli==<X.Y.Z>.dev<N>
ligoj --version
```

> TestPyPI does not allow re-uploading the same version; each push gets a fresh `.dev<N>` suffix,
> so retries just work.

---

## 2. Release (PyPI)

```bash
make release              # bump the minor version (e.g. 1.0.2 -> 1.1.0)
make release PART=patch   # bump patch instead (PART = major | minor | patch)
make release YES=1        # skip the confirmation prompt (CI / unattended)
```

`make release` performs, in order, aborting on the first failure:

1. **Pre-flight** — must be on `main`, working tree clean, in sync with `origin/main`.
2. **Quality gate** — `ruff check`, `ruff format --check`, `flake8`, `build`, `twine check`.
3. **Bump** the version in [pyproject.toml](pyproject.toml) and ask for confirmation.
4. **Commit** `chore(release): vX.Y.Z`.
5. **Tag** `vX.Y.Z` and **push** the branch and tag.
6. **Create the GitHub Release** (`gh release create`), which triggers
   [deploy.yml](.github/workflows/deploy.yml) → build → publish to PyPI.
7. **Wait** until `ligoj-cli==X.Y.Z` is served by PyPI, then print the install line.

Nothing is pushed until after the confirmation in step 3, so it is safe to abort early.

---

## 0. One-time setup

Required before the very first publish.

### PyPI / TestPyPI Trusted Publishers
- TestPyPI → project `ligoj-cli` → *Publishing* → add a pending/existing publisher:
  Owner `ligoj`, Repository `cli`, Workflow `deploy-test.yml`, Environment `dev`.
- PyPI → same, but Workflow `deploy.yml` and Environment `dev` (matching the `environment:` in
  the job).

### GitHub repository environments
In `Settings → Environments`, create `dev` (add required reviewers if you want a manual gate before
the upload step runs).

---

## 3. Rollback / yank

PyPI releases cannot be deleted, but they can be **yanked** (kept for pinned installs, hidden from
resolvers):

```bash
# web UI: project page → Manage → Releases → Yank
# or with an API token (one-off, not Trusted Publishing):
python -m twine yank ligoj-cli==<X.Y.Z> -r pypi
```

Then ship a fixed release: `make release PART=patch`.

---

## 4. Troubleshooting

- **`uv not found` / `pyenv: version '3.11' is not installed`** — run `make init`; the Makefile
  resolves a real `uv` (skipping any pyenv shim) and installs it if missing.
- **`working tree is not clean` / `not on main` / `behind origin`** — the pre-flight refused; fix
  the reported condition and re-run.
- **`tag vX.Y.Z already exists`** — that version was already released; bump again
  (`make release PART=patch`).
- **`invalid-publisher` from OIDC** — the environment name on PyPI must match the `environment:`
  value in the workflow job (`dev`).
- **`File already exists`** — the version was already uploaded; bump, don't overwrite.
- **Timed out waiting for the index** — the upload usually appears within a minute or two; check the
  workflow run (the command prints its Actions URL) and PyPI/TestPyPI directly.
