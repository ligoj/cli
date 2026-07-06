#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-prov-aws: register a local AWS provisioning node from the account credentials
# in the [dev] section, then create an (empty) provisioning quote for the demo project.
#
# The three parameters (access key id, secret access key, account id) are node-level and mandatory, so
# the node is skipped when any is absent. The node is refined from the plugin's 'service:prov:aws'
# provider in CREATE mode (you *create* a quote — there is nothing external to link). Creating the
# quote needs a price catalog to have been imported first (Ligoj answers 'prov-no-catalog' otherwise),
# so that step is best-effort and simply reported when the catalog is missing.
#
from ligojcli.dev_demo import _common, _subscribe

ARTIFACT = "plugin-prov-aws"
NODE = "service:prov:aws:local"

# AWS node parameter -> ([dev] credentials key, environment variable). All three are mandatory.
_PARAMS = {
    "service:prov:aws:access-key-id": ("aws_access_key_id", "AWS_ACCESS_KEY_ID"),
    "service:prov:aws:secret-access-key": ("aws_secret_access_key", "AWS_SECRET_ACCESS_KEY"),
    "service:prov:aws:account": ("aws_account_id", "AWS_ACCOUNT_ID"),
}


def run(args):
    _common.upsert_node(NODE, "Provisioning AWS (CLI)", _node_params(args), mode="CREATE")


def subscribe(args, project):
    # Only attempt the quote when the node was actually created (all credentials present).
    if not all(_node_params(args).values()):
        return
    _subscribe.create(project, NODE)


def _node_params(args):
    return {param: _common.dev_value(args, key, env) for param, (key, env) in _PARAMS.items()}
