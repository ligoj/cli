#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-id-ldap: register the local LDAP node, make it the primary IAM, restart the
# context, then create the reference OUs, container scopes and technical groups.
#
from ligojcli.dev_demo import _common
from ligojcli.plugins import id as id_plugin
from ligojcli.plugins import ligoj, utils

ARTIFACT = "plugin-id-ldap"
NODE = "service:id:ldap:local"
NODE_NAME = "TestLocalCLI"


def run(args):
    root = _common.dev_value(args, "ldap_root", "LDAP_ROOT", "dc=sample,dc=com")
    port = _common.dev_value(args, "ldap_port", "LDAP_PORT", "1389")
    admin_user = _common.dev_value(args, "ldap_admin_user", "LDAP_ADMIN_USERNAME", "Manager")
    password = _common.dev_value(args, "ldap_admin_password", "LDAP_ADMIN_PASSWORD", None)

    # Start from the bundled node definition, then reflect the actual running LDAP configuration.
    params = utils.load_json_from_url_or_file_with_interpolation(
        _common.bundled_path("docs", "nodes", "ldap.local.json"), {}
    )
    _set_param(params, "service:id:ldap:url", f"ldap://localhost:{port}")
    _set_param(params, "service:id:ldap:user-dn", f"cn={admin_user},{root}")
    if password:
        _set_param(params, "service:id:ldap:password", password)
    else:
        utils.warn("[dev] No LDAP admin password in [dev]; using the bundled placeholder")

    ligoj.node_upsert(NODE, NODE_NAME, params, "ALL")
    ligoj.node_get_by_id(NODE, return_secured_parameters=True)
    ligoj.configuration_set("feature:iam:node:primary", NODE, system=True)

    wait = args.get("wait")
    ligoj.plugin_restart_context(60 if wait is None else wait)

    _create_organizational_units(root)
    _create_company_scopes(root)
    _create_group_scopes(root)
    _create_technical_groups()


def _create_organizational_units(root):
    id_plugin.ou_create("people", root)
    id_plugin.ou_create("external", f"ou=people,{root}")
    id_plugin.ou_create("technical-users", f"ou=people,{root}")
    # Group intermediate OUs.
    id_plugin.ou_create("groups", root)
    id_plugin.ou_create("projects", f"ou=groups,{root}")
    id_plugin.ou_create("tools", f"ou=groups,{root}")


def _create_company_scopes(root):
    id_plugin.container_scope_create("Unassigned", "company", f"ou=people,{root}")
    id_plugin.container_scope_create("External", "company", f"ou=external,ou=people,{root}")
    id_plugin.container_scope_create("Technical", "company", f"ou=technical-users,ou=people,{root}")


def _create_group_scopes(root):
    id_plugin.container_scope_create("Unassigned", "group", f"ou=groups,{root}")
    id_plugin.container_scope_create("Project", "group", f"ou=project,ou=groups,{root}")
    id_plugin.container_scope_create("Technical", "group", f"ou=tools,ou=groups,{root}")


def _create_technical_groups():
    id_plugin.group_create("jenkins-administrators", "Technical")
    id_plugin.group_create("nexus-administrators", "Technical")
    id_plugin.group_create("nexus-administrators-paris", "Technical", "nexus-administrators")
    id_plugin.group_create(
        "nexus-administrators-paris-8", "Technical", "nexus-administrators-paris"
    )


def _set_param(params, key, value):
    for entry in params:
        if entry.get("parameter") == key:
            entry.pop("bool", None)
            entry["text"] = value
            return
    params.append({"parameter": key, "text": value})
