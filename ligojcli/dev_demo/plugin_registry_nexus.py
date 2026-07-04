#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-registry-nexus: register the local Nexus node.
#
# The endpoint and credentials come from `dev init --only nexus` (stored in the [dev] section); the
# defaults below apply when Nexus was not initialized by this CLI. Only url/user/password are
# node-level; type and registry are subscription-level parameters.
#
from ligojcli.dev_demo import _common

ARTIFACT = "plugin-registry-nexus"
NODE = "service:registry:nexus:local"


def run(args):
    _common.upsert_node(
        NODE,
        "Nexus Local (CLI)",
        {
            "service:registry:nexus:url": _common.dev_value(
                args, "nexus_endpoint", "NEXUS_ENDPOINT", "http://localhost:8181"
            ),
            "service:registry:nexus:user": _common.dev_value(
                args, "nexus_admin_user", "NEXUS_ADMIN_USER", "admin"
            ),
            "service:registry:nexus:password": _common.dev_value(
                args, "nexus_admin_password", "NEXUS_ADMIN_PASSWORD", None
            ),
        },
    )
