#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-prov-azure: register a local Azure provisioning node from the service-principal
# credentials in the [dev] section, then create an (empty) provisioning quote for the demo project.
#
# tenant / subscription / application (client id) / key (client secret) are node-level and mandatory;
# resource-group is optional (kept only when provided). The node is refined from the plugin's
# 'service:prov:azure' provider in CREATE mode. As for AWS, creating the quote needs a price catalog
# to have been imported first, so that step is best-effort and reported when the catalog is missing.
#
from ligojcli.dev_demo import _common, _subscribe

ARTIFACT = "plugin-prov-azure"
NODE = "service:prov:azure:local"

# Azure node parameter -> ([dev] credentials key, environment variable).
_PARAMS = {
    "service:prov:azure:tenant": ("azure_tenant_id", "AZURE_TENANT_ID"),
    "service:prov:azure:subscription": ("azure_subscription_id", "AZURE_SUBSCRIPTION_ID"),
    "service:prov:azure:application": ("azure_application_id", "AZURE_APPLICATION_ID"),
    "service:prov:azure:key": ("azure_client_secret", "AZURE_CLIENT_SECRET"),
    "service:prov:azure:resource-group": ("azure_resource_group", "AZURE_RESOURCE_GROUP"),
}
# Mandatory parameters (resource-group is optional); the node is skipped when any is missing.
_REQUIRED = [
    "service:prov:azure:tenant",
    "service:prov:azure:subscription",
    "service:prov:azure:application",
    "service:prov:azure:key",
]


def run(args):
    _common.upsert_node(
        NODE, "Provisioning Azure (CLI)", _node_params(args), required=_REQUIRED, mode="CREATE"
    )


def subscribe(args, project):
    params = _node_params(args)
    if not all(params.get(key) for key in _REQUIRED):
        return
    _subscribe.create(project, NODE)


def _node_params(args):
    return {param: _common.dev_value(args, key, env) for param, (key, env) in _PARAMS.items()}
