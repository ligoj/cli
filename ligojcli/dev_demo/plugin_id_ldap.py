#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-id-ldap: register the local LDAP node, make it the primary IAM, restart the
# context, then create the reference container scopes and technical groups.
#
# The structural OUs (ou=people, ou=groups, ou=tools, ...) are NOT created here: they are seeded in
# LDAP by `dev init` from docs/ldap/dev.ldif. Creating them again via the company API would fail
# with HTTP 406 {'code':'internal'} — ligoj's company create issues an LDAP add of `ou=<name>,<dn>`
# that the server's company-existence pre-check (companies-dn only) can't see, so for an OU that
# already exists (e.g. ou=groups from bitnami, ou=tools from the LDIF) the add raises NameAlreadyBound.
#
from ligojcli.dev_demo import _common, _subscribe
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

    # OUs come from the seed LDIF (see module docstring); only scopes and groups are created here.
    _create_company_scopes(root)
    _create_group_scopes(root)
    _create_technical_groups()


def subscribe(args, project):
    # The IAM subscription links a project to an existing LDAP group; create the group, then link it.
    _safe(f"group '{project}'", id_plugin.group_create, project, "Project")
    _subscribe.link(project, NODE, [{"parameter": "service:id:group", "text": project}])


def _safe(description, func, *args):
    # Best-effort step: keep configuring the rest of the demo if one item fails (already present,
    # a reserved name, or a server-side limitation). Idempotent re-runs.
    try:
        func(*args)
    except Exception as error:  # noqa: BLE001 - resilience is intended here
        utils.warn(f"[dev] {description}: {error}")


def _create_company_scopes(root):
    _safe(
        "company scope 'Unassigned'",
        id_plugin.container_scope_create,
        "Unassigned",
        "company",
        f"ou=people,{root}",
    )
    _safe(
        "company scope 'External'",
        id_plugin.container_scope_create,
        "External",
        "company",
        f"ou=external,ou=people,{root}",
    )
    _safe(
        "company scope 'Technical'",
        id_plugin.container_scope_create,
        "Technical",
        "company",
        f"ou=technical-users,ou=people,{root}",
    )


def _create_group_scopes(root):
    _safe(
        "group scope 'Unassigned'",
        id_plugin.container_scope_create,
        "Unassigned",
        "group",
        f"ou=groups,{root}",
    )
    _safe(
        "group scope 'Project'",
        id_plugin.container_scope_create,
        "Project",
        "group",
        f"ou=project,ou=groups,{root}",
    )
    _safe(
        "group scope 'Technical'",
        id_plugin.container_scope_create,
        "Technical",
        "group",
        f"ou=tools,ou=groups,{root}",
    )


def _create_technical_groups():
    _safe(
        "group 'jenkins-administrators'",
        id_plugin.group_create,
        "jenkins-administrators",
        "Technical",
    )
    _safe(
        "group 'nexus-administrators'", id_plugin.group_create, "nexus-administrators", "Technical"
    )
    _safe(
        "group 'nexus-administrators-paris'",
        id_plugin.group_create,
        "nexus-administrators-paris",
        "Technical",
        "nexus-administrators",
    )
    _safe(
        "group 'nexus-administrators-paris-8'",
        id_plugin.group_create,
        "nexus-administrators-paris-8",
        "Technical",
        "nexus-administrators-paris",
    )


def _set_param(params, key, value):
    for entry in params:
        if entry.get("parameter") == key:
            entry.pop("bool", None)
            entry["text"] = value
            return
    params.append({"parameter": key, "text": value})
