#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-registry-nexus: register the local Nexus node.
#
# The node parameters start from the bundled sample docs/nodes/nexus.local.json; the endpoint and
# credentials are then overridden with the live values from `dev init --only nexus` (stored in the
# [dev] section). Only url/user/password are node-level; type and registry are subscription-level.
#
from ligojcli.dev_demo import _common, _subscribe

ARTIFACT = "plugin-registry-nexus"
NODE = "service:registry:nexus:local"
SAMPLE = "nexus.local.json"


def run(args):
    params = _common.load_node(SAMPLE)
    params["service:registry:nexus:url"] = _common.dev_value(
        args, "nexus_endpoint", "NEXUS_ENDPOINT", params.get("service:registry:nexus:url")
    )
    params["service:registry:nexus:user"] = _common.dev_value(
        args, "nexus_admin_user", "NEXUS_ADMIN_USER", params.get("service:registry:nexus:user")
    )
    params["service:registry:nexus:password"] = _common.dev_value(
        args,
        "nexus_admin_password",
        "NEXUS_ADMIN_PASSWORD",
        params.get("service:registry:nexus:password"),
    )
    _common.upsert_node(NODE, "Nexus Local (CLI)", params)


def subscribe(args, project):
    # Link one hosted repository per supported demo type (docker, maven), created on Nexus first.
    endpoint = _common.dev_value(args, "nexus_endpoint", "NEXUS_ENDPOINT", "http://localhost:8181")
    user = _common.dev_value(args, "nexus_admin_user", "NEXUS_ADMIN_USER", "admin")
    password = _common.dev_value(args, "nexus_admin_password", "NEXUS_ADMIN_PASSWORD", "admin")
    _subscribe.registry_subscribe(
        project,
        NODE,
        lambda rtype: _subscribe.nexus_ensure_repo(
            endpoint, user, password, rtype, f"{project}-{rtype}"
        ),
    )
