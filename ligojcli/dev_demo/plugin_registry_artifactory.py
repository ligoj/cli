#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-registry-artifactory: register the local Artifactory node.
#
# The endpoint and credentials come from `dev init --only artifactory` (stored in the [dev] section);
# the defaults below apply when Artifactory was not initialized by this CLI. Only url/user/password
# are node-level; type and registry are subscription-level parameters.
#
from ligojcli.dev_demo import _common

ARTIFACT = "plugin-registry-artifactory"
NODE = "service:registry:artifactory:local"


def run(args):
    _common.upsert_node(
        NODE,
        "Artifactory Local (CLI)",
        {
            "service:registry:artifactory:url": _common.dev_value(
                args,
                "artifactory_endpoint",
                "ARTIFACTORY_ENDPOINT",
                "http://localhost:8082/artifactory",
            ),
            "service:registry:artifactory:user": _common.dev_value(
                args, "artifactory_user", "ARTIFACTORY_USER", "admin"
            ),
            "service:registry:artifactory:password": _common.dev_value(
                args, "artifactory_password", "ARTIFACTORY_PASSWORD", "password"
            ),
        },
    )
