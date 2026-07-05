#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-scm-github: register a GitHub node for the `ligoj` organisation and link the
# demo project to the real public `ligoj/plugin-ui` repository (link mode — it already exists on
# GitHub).
#
# GitHub's API needs a token: the `auth-key` parameter is mandatory and validated against github.com,
# so a repo cannot be linked anonymously. The token is read from [dev] `github_token` / GITHUB_TOKEN,
# falling back to the locally authenticated `gh` CLI; without one the GitHub demo is skipped.
#
import shutil
import subprocess

from ligojcli.dev_demo import _common, _subscribe
from ligojcli.plugins import utils

ARTIFACT = "plugin-scm-github"
NODE = "service:scm:github:ligoj"
# The owner of the linked repositories and the repositories themselves (bare names, owner from user).
GITHUB_OWNER = "ligoj"
REPOSITORIES = ["plugin-ui"]


def run(args):
    token = _github_token(args)
    if not token:
        utils.warn(
            "[dev] github: no token (set [dev] github_token / GITHUB_TOKEN, or authenticate the "
            "'gh' CLI); skipping the GitHub demo"
        )
        return
    _common.upsert_node(
        NODE,
        "GitHub Ligoj (CLI)",
        {
            "service:scm:github:user": _common.dev_value(
                args, "github_user", "GITHUB_USER", GITHUB_OWNER
            ),
            "service:scm:github:auth-key": token,
        },
    )


def subscribe(args, project):
    if not _github_token(args):
        return
    for repository in REPOSITORIES:
        _subscribe.link(
            project, NODE, [{"parameter": "service:scm:github:repository", "text": repository}]
        )


def _github_token(args):
    return _common.dev_value(args, "github_token", "GITHUB_TOKEN", None) or _gh_cli_token()


def _gh_cli_token():
    if shutil.which("gh") is None:
        return None
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None
