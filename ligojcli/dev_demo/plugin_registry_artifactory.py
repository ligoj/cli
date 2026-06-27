#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-registry-artifactory: register the local Artifactory node.
#
# Artifactory is not part of `dev init`, so this uses generic localhost defaults (override with the
# ARTIFACTORY_* env vars or the [dev] credentials section). Parameters mirror the sibling registry
# plugins (url/user/password).
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
                "http://localhost:8081/artifactory",
            ),
            "service:registry:artifactory:user": _common.dev_value(
                args, "artifactory_user", "ARTIFACTORY_USER", "admin"
            ),
            "service:registry:artifactory:password": _common.dev_value(
                args, "artifactory_password", "ARTIFACTORY_PASSWORD", "password"
            ),
        },
    )
