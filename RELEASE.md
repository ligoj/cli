# Release Guide — `ligoj-cli`

Publishing uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
(OIDC, no API token). The GitHub Actions workflow is
[.github/workflows/deploy.yml](.github/workflows/deploy.yml).

Two targets are used:

| Target       | Index                       | GitHub Environment | Purpose              |
| ------------ | --------------------------- | ------------------ | -------------------- |
| **Dev**      | https://test.pypi.org       | `dev`              | Validate end-to-end  |
| **Release**  | https://pypi.org            | `release`          | Final public release |

---

## 0. One-time setup

Before the very first publish, make sure the following are done.

### 0.1 PyPI / TestPyPI Trusted Publishers
- TestPyPI → project `ligoj-cli` → *Publishing* → add a pending/existing publisher:
  - Owner: `ligoj`, Repository: `cli`, Workflow: `deploy.yml`, Environment: `dev`.
- PyPI → same, but Environment: `release`.

### 0.2 GitHub repository environments
In `Settings → Environments`, create:
- `dev` — no reviewers required.
- `release` — add *required reviewers* and restrict to the `master` branch
  and tag pattern `v*`.

### 0.3 Complete `deploy.yml`
The committed workflow currently only contains the publish job. It still
needs:
- a `name:` and `on:` trigger (push tag `v*` for release, manual
  `workflow_dispatch` with an `environment` input for dev),
- a `build` job that runs `python -m build` and uploads the `dist/`
  artifact,
- the `pypi-publish` job must `needs: build`, `download-artifact` into
  `dist/`, and pass `repository-url: https://test.pypi.org/legacy/` when
  targeting `dev`.

---

## 1. Pre-flight checklist (every release)

- [ ] Working tree clean: `git status`.
- [ ] On `master`, up to date: `git pull --ff-only`.
- [ ] Bump `version` in [pyproject.toml](pyproject.toml) following
      [SemVer](https://semver.org/): `MAJOR.MINOR.PATCH`.
- [ ] Update `README.md` / changelog if relevant.
- [ ] Lint & format:
      ```bash
      ruff check .
      ruff format --check .
      flake8
      ```
- [ ] Tests pass: `make test`.
- [ ] Local build succeeds and artifacts look right:
      ```bash
      rm -rf dist/ build/ *.egg-info
      python -m pip install --upgrade build twine
      python -m build
      python -m twine check dist/*
      ```
- [ ] Commit the version bump:
      ```bash
      git add pyproject.toml
      git commit -m "chore(release): v<X.Y.Z>"
      git push origin master
      ```

---

## 2. Publish to **dev** (TestPyPI)

Goal: validate that the package installs and runs from an index before
cutting the real release.

1. Trigger the workflow against the `dev` environment:
   - GitHub UI → *Actions* → **deploy** → *Run workflow*
   - Branch: `master`, input `environment: dev`.
   - Or via CLI:
     ```bash
     gh workflow run deploy.yml -f environment=dev --ref master
     ```
2. Watch the run:
   ```bash
   gh run watch
   ```
3. Verify on TestPyPI: https://test.pypi.org/project/ligoj-cli/
4. Smoke-test install in a throwaway venv:
   ```bash
   python -m venv /tmp/ligoj-cli-dev && source /tmp/ligoj-cli-dev/bin/activate
   pip install -i https://test.pypi.org/simple/ \
       --extra-index-url https://pypi.org/simple/ \
       "ligoj-cli==<X.Y.Z>"
   ligoj --version
   ligoj --help
   deactivate && rm -rf /tmp/ligoj-cli-dev
   ```

> TestPyPI does **not** allow re-uploading the same version. If you need
> to retry, bump to `<X.Y.Z>.postN` or to the next patch.

---

## 3. Final release (PyPI)

Only once the dev run passes and the smoke-test is green.

1. Tag the release commit and push the tag:
   ```bash
   git tag -a v<X.Y.Z> -m "Release v<X.Y.Z>"
   git push origin v<X.Y.Z>
   ```
   Pushing the tag triggers the `release` job in `deploy.yml`.

2. Approve the deployment in GitHub if the `release` environment is
   gated by required reviewers.

3. Create the GitHub Release from the tag (auto-generated notes are
   fine):
   ```bash
   gh release create v<X.Y.Z> --generate-notes
   ```

4. Verify on PyPI: https://pypi.org/project/ligoj-cli/<X.Y.Z>/

5. Smoke-test install from the real index:
   ```bash
   python -m venv /tmp/ligoj-cli-rel && source /tmp/ligoj-cli-rel/bin/activate
   pip install "ligoj-cli==<X.Y.Z>"
   ligoj --version
   deactivate && rm -rf /tmp/ligoj-cli-rel
   ```

---

## 4. Rollback / yank

PyPI releases cannot be deleted, but they can be **yanked** (kept for
pinned installs, hidden from resolvers):

```bash
# via web UI: project page → Manage → Releases → Yank
# or with an API token (one-off, not Trusted Publishing):
python -m twine yank ligoj-cli==<X.Y.Z> -r pypi
```

Then publish a fixed `<X.Y.(Z+1)>` following sections 1–3.

---

## 5. Troubleshooting

- **`invalid-publisher` from OIDC** — environment name on PyPI does not
  match the `environment:` value in the job. They must be identical
  (`dev` / `release`).
- **`File already exists`** — version was already uploaded; bump the
  version, don't try to overwrite.
- **Workflow never starts on tag push** — tag didn't match the `on:
  push: tags:` pattern, or branch protection blocked the push.
- **Build is missing files** — check `[tool.setuptools] packages` in
  `pyproject.toml` and inspect `python -m build`'s sdist with
  `tar tzf dist/*.tar.gz`.
