#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-registry-harbor: register the local Harbor node.
#
from ligojcli.dev_demo import _common

ARTIFACT = "plugin-registry-harbor"
NODE = "service:registry:harbor:local"


def run(args):
    url = _common.dev_value(args, "harbor_endpoint", "HARBOR_ENDPOINT", "http://localhost:8088")
    _common.upsert_node(
        NODE,
        "Harbor Local (CLI)",
        {
            "service:registry:harbor:url": url,
            "service:registry:harbor:user": _common.dev_value(
                args, "harbor_admin_user", "HARBOR_ADMIN_USER", "admin"
            ),
            "service:registry:harbor:password": _common.dev_value(
                args, "harbor_admin_password", "HARBOR_ADMIN_PASSWORD", None
            ),
            "service:registry:harbor:type": "docker",
            "service:registry:harbor:registry": _common.host_of(url),
        },
    )
