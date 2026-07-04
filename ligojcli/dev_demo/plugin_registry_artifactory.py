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
from ligojcli.dev_demo import _common

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
