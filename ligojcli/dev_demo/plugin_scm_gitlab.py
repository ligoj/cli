#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-scm-gitlab: register the local GitLab node.
#
from ligojcli.dev_demo import _common, _subscribe

ARTIFACT = "plugin-scm-gitlab"
NODE = "service:scm:gitlab:local"


def run(args):
    # GitLab authenticates with a personal access token (auth-key). The dev environment only stores
    # the root password, so fall back to it (replace with a real PAT for write operations).
    auth_key = _common.dev_value(args, "gitlab_token", "GITLAB_TOKEN", None) or _common.dev_value(
        args, "gitlab_root_password", "GITLAB_ROOT_PASSWORD", None
    )
    _common.upsert_node(
        NODE,
        "GitLab Local (CLI)",
        {
            "service:scm:gitlab:url": _common.dev_value(
                args, "gitlab_endpoint", "GITLAB_ENDPOINT", "http://localhost:8929"
            ),
            "service:scm:gitlab:user": _common.dev_value(
                args, "gitlab_user", "GITLAB_USER", "root"
            ),
            "service:scm:gitlab:auth-key": auth_key,
        },
    )


def subscribe(args, project):
    # Create a GitLab project, then link the subscription by its reference.
    endpoint = _common.dev_value(
        args, "gitlab_endpoint", "GITLAB_ENDPOINT", "http://localhost:8929"
    )
    user = _common.dev_value(args, "gitlab_user", "GITLAB_USER", "root")
    token = _common.dev_value(args, "gitlab_token", "GITLAB_TOKEN", None) or _common.dev_value(
        args, "gitlab_root_password", "GITLAB_ROOT_PASSWORD", None
    )
    reference = _subscribe.gitlab_ensure_project(endpoint, user, token, project)
    if reference:
        _subscribe.link(
            project, NODE, [{"parameter": "service:scm:gitlab:repository", "text": reference}]
        )
