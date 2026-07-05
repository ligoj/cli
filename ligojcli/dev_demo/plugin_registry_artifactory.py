#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-registry-artifactory: register the local Artifactory node.
#
# The node parameters start from the bundled sample docs/nodes/artifactory.local.json; the endpoint
# and credentials are then overridden with the live values from `dev init --only artifactory`
# (stored in the [dev] section). Only url/user/password are node-level; type and registry are
# subscription-level parameters.
#
from ligojcli.dev_demo import _common, _subscribe

ARTIFACT = "plugin-registry-artifactory"
NODE = "service:registry:artifactory:local"
SAMPLE = "artifactory.local.json"


def run(args):
    params = _common.load_node(SAMPLE)
    params["service:registry:artifactory:url"] = _common.dev_value(
        args,
        "artifactory_endpoint",
        "ARTIFACTORY_ENDPOINT",
        params.get("service:registry:artifactory:url"),
    )
    params["service:registry:artifactory:user"] = _common.dev_value(
        args,
        "artifactory_user",
        "ARTIFACTORY_USER",
        params.get("service:registry:artifactory:user"),
    )
    params["service:registry:artifactory:password"] = _common.dev_value(
        args,
        "artifactory_password",
        "ARTIFACTORY_PASSWORD",
        params.get("service:registry:artifactory:password"),
    )
    _common.upsert_node(NODE, "Artifactory Local (CLI)", params)


def subscribe(args, project):
    # Link one local repository per supported demo type. On Pro the repository is created first; on
    # OSS creation is Pro-only, so an existing repository (e.g. demo-1-maven created by hand in the
    # UI) is detected from the listing and linked, while Docker (absent from OSS) is skipped quietly.
    endpoint = _common.dev_value(
        args, "artifactory_endpoint", "ARTIFACTORY_ENDPOINT", "http://localhost:8082/artifactory"
    )
    user = _common.dev_value(args, "artifactory_user", "ARTIFACTORY_USER", "admin")
    password = _common.dev_value(args, "artifactory_password", "ARTIFACTORY_PASSWORD", "password")
    _subscribe.registry_subscribe(
        project,
        NODE,
        lambda rtype: _subscribe.artifactory_ensure_repo(
            endpoint, user, password, rtype, f"{project}-{rtype}"
        ),
    )
