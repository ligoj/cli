#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-registry-harbor: register the local Harbor node.
#
from ligojcli.dev_demo import _common, _subscribe

ARTIFACT = "plugin-registry-harbor"
NODE = "service:registry:harbor:local"


def run(args):
    # Only url/user/password are node-level; type and registry are subscription-level parameters.
    _common.upsert_node(
        NODE,
        "Harbor Local (CLI)",
        {
            "service:registry:harbor:url": _common.dev_value(
                args, "harbor_endpoint", "HARBOR_ENDPOINT", "http://localhost:8088"
            ),
            "service:registry:harbor:user": _common.dev_value(
                args, "harbor_admin_user", "HARBOR_ADMIN_USER", "admin"
            ),
            "service:registry:harbor:password": _common.dev_value(
                args, "harbor_admin_password", "HARBOR_ADMIN_PASSWORD", None
            ),
        },
    )


def subscribe(args, project):
    # Harbor is docker/OCI only: create one project on Harbor and link it as a docker registry.
    endpoint = _common.dev_value(
        args, "harbor_endpoint", "HARBOR_ENDPOINT", "http://localhost:8088"
    )
    user = _common.dev_value(args, "harbor_admin_user", "HARBOR_ADMIN_USER", "admin")
    password = _common.dev_value(args, "harbor_admin_password", "HARBOR_ADMIN_PASSWORD", None)
    _subscribe.registry_subscribe(
        project,
        NODE,
        lambda rtype: _subscribe.harbor_ensure_project(endpoint, user, password, project),
    )
