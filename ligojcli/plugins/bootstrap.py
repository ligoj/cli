#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
import json

import dns.resolver
from jsonmerge import merge
from jsonschema import validate

from ligojcli.plugins import alfresco, argocd, gitlab, jenkins, ligoj, nexus, sonarqube, id, utils

includes: list[str] = []
excludes: list[str] = []
with_data: list[str] = []

DEFAULT_LDAP_OU_EXTERNAL_USERS = "external"
DEFAULT_LDAP_OU_TECHNICAL_USERS = "technical-users"
DEFAULT_PARENT_GROUP_SUFFIX = "-team"


def configure(subparser_service):

    # Bootstrap operations
    subparser_action = subparser_service.add_parser("bootstrap", help="Bundle of API calls for new groups or project").add_subparsers(title="action", help="Action", dest="action")

    # bootstrap init
    parser_action = subparser_action.add_parser("init", help="Create basic groups and scopes")
    parser_action.add_argument("--base-dn", help="LDAP Base DN", default="")
    parser_action.add_argument("--groups-base-dn", help="LDAP DN for all groups, starting from base-dn", default="")
    parser_action.add_argument("--projects-base-dn", help="LDAP DN of groups associated to projects, starting from groups-base-dn", default="")
    parser_action.add_argument("--technical-groups-base-dn", help="LDAP DN of technical groups, starting from groups-base-dn", default="")
    parser_action.add_argument("--users-base-dn", help="LDAP DN for users, starting from global base-dn", default="")
    parser_action.add_argument("--internal-users-base-dn", help="LDAP DN of internal users, starting from users-base-dn", default="")
    parser_action.add_argument("--technical-users-base-dn", help="LDAP DN of technical users, starting from users-base-dn", default="")
    parser_action.add_argument("--external-users-base-dn", help="LDAP DN of writable external users, starting from users-base-dn", default="")
    parser_action.add_argument("--technical-groups", help="List of technical groups", default="", nargs="*")

    # bootstrap welcome-user
    parser_action = subparser_action.add_parser("welcome-user", help="Create an new project for given administrator")
    parser_action.add_argument("--id", "-i", help="Username to create as administrator of project", default=False)
    parser_action.add_argument("--verify-project-with-dns", help="Verify the project name matches with the given DNS record format", required=False)
    parser_action.add_argument("--group-suffix", help="Suffix added to project name in created groups", default=DEFAULT_PARENT_GROUP_SUFFIX)
    parser_action.add_argument("--project", "-p", help="New project's key")
    parser_action.add_argument("--name", help="New project's name, default is derived from `project`", required=False)
    parser_action.add_argument("--sonar-create-node", help="Also create a SonarQube node in Ligoj to the given endpoint", required=False, action="store_true")
    parser_action.add_argument("--sonar-endpoint", "-S", help="SonarQube endpoint for Ligoj generated node", required=False)
    parser_action.add_argument("--sonar-api-token", help="SonarQube API token. When undefined a new one is generated for the reader user", required=False)
    parser_action.add_argument("--jenkins-create-node", help="Jenkins endpoint for Ligoj generated node", required=False, action="store_true")
    parser_action.add_argument("--jenkins-endpoint", "-J", help="Also register the given Jenkins endpoint to Ligoj", required=False)
    parser_action.add_argument("--jenkins-api-token", help="Jenkins API token. When undefined a new one is generated for the reader user", required=False)
    parser_action.add_argument("--reset-reader-password", "-r", help="If reader user already existed, reset its password", required=False, action="store_true")
    parser_action.add_argument("--script-custom-attributes", help="Custom attributes of script user that would be created", required=False)
    parser_action.add_argument("--reader-custom-attributes", help="Custom attributes of reader user that would be created", required=False)

    # bootstrap create-project
    parser_action = subparser_action.add_parser("create-project", help="Bundle of API calls for new project")
    parser_action.add_argument("--project", "-p", help="New project's key")
    parser_action.add_argument("--name", help="New project's name, default is derived from `project`", required=False)
    parser_action.add_argument("--group-suffix", help="Suffix added to project name in created groups", default=DEFAULT_PARENT_GROUP_SUFFIX)
    parser_action.add_argument("--groups", help="Primary identity `plugin-id` is used to create initial project's groups. Final group name is based on 'group-suffix'", nargs="*", default=["admin"])
    parser_action.add_argument("--parent-project", help="When defined, a context is put to the new project related to this parent project", required=False)
    parser_action.add_argument("--parent-admin", help="Username of checked user being one of the administrators of parent project. Default is session user", required=False)
    parser_action.add_argument("--team-leader", help="Username of target owner of the new project. Default is `parent-admin`")

    # bootstrap delete-project
    parser_action = subparser_action.add_parser("delete-project", help="Bundle of API calls for project deletion")
    parser_action.add_argument("--project", "-p", help="Project's key to delete")
    parser_action.add_argument("--parent-admin", help="Username of checked user being one of the administrators of parent project. Default is session user", required=False)

    # bootstrap create-nested-project
    parser_action = subparser_action.add_parser("create-nested-project", help="Bundle of API calls for groups inside a project")
    parser_action.add_argument("--project", "-p", help="New project's key")
    parser_action.add_argument("--group-suffix", help="Suffix added to project name in created groups", default=DEFAULT_PARENT_GROUP_SUFFIX)
    parser_action.add_argument("--groups", help="Group names to create. Final group name is based on 'group-suffix'", nargs="*", default=["admin"])
    parser_action.add_argument("--parent-project", help="When defined, a context is put to the new project related to this parent project", required=False)
    parser_action.add_argument("--parent-admin", help="Username of checked user being one of the administrators of parent project. Default is session user", required=False)
    parser_action.add_argument("--team-leader", help="Username of target owner of the new project. Default is session user")
    parser_action.add_argument("--script-custom-attributes", help="Custom attributes of script user that would be created", required=False)
    parser_action.add_argument("--reader-custom-attributes", help="Custom attributes of reader user that would be created", required=False)

    # bootstrap create-roles
    parser_action = subparser_action.add_parser("create-roles", help="Create role mappings and configurations in supported tools")
    parser_action.add_argument("--project", "-p", help="Associated project key")
    parser_action.add_argument("--group-suffix", help="Suffix added to project name in created groups", default=DEFAULT_PARENT_GROUP_SUFFIX)
    parser_action.add_argument("--groups", help="Group names to create. Final group name is based on 'group-suffix'. Overrides the groups defined in JSON file", nargs="*", default=[])
    parser_action.add_argument("--from", "-f", help="Configuration JSON URL or local file name")
    parser_action.add_argument("--schema", help="Optional JSON Schema definition applied to configuration, JSON, file or URL", required=False)
    parser_action.add_argument("--includes", help="Includes only some plugins. '*' for all", required=False, action="extend", nargs="+", type=str, default=["*"])
    parser_action.add_argument("--excludes", help="Excludes some plugins. '*' for all", required=False, action="extend", nargs="+", type=str, default=[])
    parser_action.add_argument("--sonar-endpoint", "-S", help="Endpoint of SonarQube", required=False)
    parser_action.add_argument("--sonar-api-token", help="SonarQube API token", required=False)
    parser_action.add_argument("--jenkins-home", "-H", help="JENKINS_HOME", required=False)
    parser_action.add_argument("--jenkins-crumb", "-C", help="Jenkins crumb mode; true, false, auto", default="auto")
    parser_action.add_argument("--jenkins-endpoint", "-J", help="Endpoint of Jenkins", required=False)
    parser_action.add_argument("--jenkins-api-user", help="Jenkins API user", required=False)
    parser_action.add_argument("--jenkins-api-token", help="Jenkins API token", required=False)
    parser_action.add_argument("--alfresco-endpoint", "-A", help="Endpoint of Alfresco", required=False)
    parser_action.add_argument("--alfresco-user", help="Alfresco username", required=False)
    parser_action.add_argument("--alfresco-password", help="Alfresco password", required=False)
    parser_action.add_argument("--alfresco-ticket", help="Alfresco ticket", required=False)
    parser_action.add_argument("--nexus-endpoint", "-N", help="Endpoint of Nexus", required=False)
    parser_action.add_argument("--nexus-user", help="Nexus username", required=False)
    parser_action.add_argument("--nexus-password", help="Nexus password", required=False)
    parser_action.add_argument("--gitlab-endpoint", "-G", help="Endpoint of Gitlab", required=False)
    parser_action.add_argument("--gitlab-token", help="GitLab API token. Must be the owner of base group", required=False)
    parser_action.add_argument("--gitlab-base-group", help=f"Optional GitLab base groups (path or id) where project groups are created, [{gitlab.DEFAULT_GITLAB_BASE_GROUP}]")
    parser_action.add_argument("--gitlab-project-group-prefix", help=f"Optional prefix of created GitLab project group (path)[{gitlab.DEFAULT_GITLAB_PROJECT_GROUP_PREFIX}]")
    parser_action.add_argument("--gitlab-wrapper-group", help=f"Optional GitLab group (path) of sub-groups. When '/', project group is the parent [{gitlab.DEFAULT_GITLAB_WRAPPER_GROUP}]")
    parser_action.add_argument("--gitlab-wrapper-group-name", help=f"Optional GitLab group name of sub-groups [{gitlab.DEFAULT_GITLAB_WRAPPER_GROUP_NAME}]")
    parser_action.add_argument("--gitlab-project-subgroup-prefix", help=f"Optional prefix of created GitLab sub-groups (path) [{gitlab.DEFAULT_GITLAB_PROJECT_SUBGROUP_PREFIX}]")

    # bootstrap delete-roles
    parser_action = subparser_action.add_parser("delete-roles", help="Delete role mappings and configurations from supported tools")
    parser_action.add_argument("--project", "-p", help="Associated project key")
    parser_action.add_argument("--group-suffix", help="Suffix added to project name in deleted groups", default=DEFAULT_PARENT_GROUP_SUFFIX)
    parser_action.add_argument("--groups", help="Group names to delete. Final group name is based on 'group-suffix'. Overrides the groups defined in JSON file", nargs="*", default=[])
    parser_action.add_argument("--from", "-f", help="Configuration JSON URL or local file name")
    parser_action.add_argument("--schema", help="Optional JSON Schema definition applied to configuration, JSON, file or URL", required=False)
    parser_action.add_argument("--with-data", help="Include data deletion, repositories, folders,... for some plugins. '*' for all", required=False, action="append", default=[])
    parser_action.add_argument("--includes", help="Includes only some plugins. '*' for all", required=False, action="extend", nargs="+", type=str, default=["*"])
    parser_action.add_argument("--excludes", help="Excludes some plugins. '*' for all", required=False, action="extend", nargs="+", type=str, default=[])
    parser_action.add_argument("--sonar-endpoint", "-S", help="Endpoint of SonarQube", required=False)
    parser_action.add_argument("--sonar-api-token", help="SonarQube API token", required=False)
    parser_action.add_argument("--jenkins-home", "-H", help="JENKINS_HOME", required=False)
    parser_action.add_argument("--jenkins-crumb", "-C", help="Jenkins crumb mode; true, false, auto", default="auto")
    parser_action.add_argument("--jenkins-endpoint", "-J", help="Endpoint of Jenkins", required=False)
    parser_action.add_argument("--jenkins-api-user", help="Jenkins API user", required=False)
    parser_action.add_argument("--jenkins-api-token", help="Jenkins API token", required=False)
    parser_action.add_argument("--alfresco-endpoint", "-A", help="Endpoint of Alfresco", required=False)
    parser_action.add_argument("--alfresco-user", help="Alfresco username", required=False)
    parser_action.add_argument("--alfresco-password", help="Alfresco password", required=False)
    parser_action.add_argument("--alfresco-ticket", help="Alfresco ticket", required=False)
    parser_action.add_argument("--nexus-endpoint", "-N", help="Endpoint of Nexus", required=False)
    parser_action.add_argument("--nexus-user", help="Nexus username", required=False)
    parser_action.add_argument("--nexus-password", help="Nexus password", required=False)
    parser_action.add_argument("--gitlab-endpoint", "-G", help="Endpoint of Gitlab", required=False)
    parser_action.add_argument("--gitlab-token", help="GitLab API token. Must be the owner of base group", required=False)
    parser_action.add_argument("--gitlab-base-group", help=f"Optional GitLab base groups (path or id) where project groups are deleted, [{gitlab.DEFAULT_GITLAB_BASE_GROUP}]")
    parser_action.add_argument("--gitlab-project-group-prefix", help=f"Optional prefix of deleted GitLab project group (path)[{gitlab.DEFAULT_GITLAB_PROJECT_GROUP_PREFIX}]")
    parser_action.add_argument("--gitlab-wrapper-group", help=f"Optional GitLab group (path) of sub-groups. When '/', project group is the parent [{gitlab.DEFAULT_GITLAB_WRAPPER_GROUP}]")
    parser_action.add_argument("--gitlab-wrapper-group-name", help=f"Optional GitLab group name of sub-groups [{gitlab.DEFAULT_GITLAB_WRAPPER_GROUP_NAME}]")
    parser_action.add_argument("--gitlab-project-subgroup-prefix", help=f"Optional prefix of deleted GitLab sub-groups (path) [{gitlab.DEFAULT_GITLAB_PROJECT_SUBGROUP_PREFIX}]")


def execute_action(service, action, _operation, args):
    if service == "bootstrap":
        global includes, excludes, with_data
        excludes = args.get("excludes", [])
        includes = args.get("includes", ["*"])
        if len(includes) > 1 and includes[0] == "*":
            includes.pop(0)
        with_data = args.get("with_data", [])
        utils.debug(f"Inclusion options excludes={excludes}, includes={includes}, with_data={with_data}")
        if action == "init":
            return bootstrap_init(
                utils.get_config(args, "base_dn", "LIGOJ_LDAP_BASE_DN", None),
                utils.get_config(args, "groups_base_dn", "LIGOJ_LDAP_GROUPS_BASE_DN", None),
                utils.get_config(args, "projects_base_dn", "LIGOJ_LDAP_PROJECTS_BASE_DN", None),
                utils.get_config(args, "technical_groups_base_dn", "LIGOJ_LDAP_TECHNICAL_GROUPS_BASE_DN", None),
                utils.get_config(args, "users_base_dn", "LIGOJ_LDAP_USERS_BASE_DN", None),
                utils.get_config(args, "internal_users_base_dn", "LIGOJ_LDAP_INTERNAL_USERS_BASE_DN", None),
                utils.get_config(args, "technical_users_base_dn", "LIGOJ_LDAP_TECHNICAL_USERS_BASE_DN", None),
                utils.get_config(args, "external_users_base_dn", "LIGOJ_LDAP_EXTERNAL_USERS_BASE_DN", None),
                utils.get_config_list(args, "technical_groups", "LIGOJ_LDAP_TECHNICAL_GROUPS", []),
            )
        if action == "welcome-user":
            if args.get("sonar_create_node"):
                sonarqube.parse_remote_args(args)
            if args.get("jenkins_create_node"):
                jenkins.parse_remote_args(args)
            return bootstrap_welcome_user(
                utils.not_none(args.get("id"), "admin username"),
                utils.not_none(args.get("project"), "project key"),
                args.get("name"),
                args.get("verify_project_with_dns"),
                args.get("group_suffix"),
                args.get("reset_reader_password"),
                args.get("script_custom_attributes"),
                args.get("reader_custom_attributes"),
            )
        if action == "create-project":
            return bootstrap_create_project(
                action,
                utils.not_none(args.get("project"), "project key"),
                args.get("name"),
                args.get("group_suffix"),
                args.get("parent_project"),
                args.get("parent_admin"),
                args.get("team_leader"),
                args.get("groups"),
            )
        if action == "delete-project":
            return bootstrap_delete_project(utils.not_none(args.get("project"), "project key"), args.get("parent_admin"), args.get("on_behalf_of"))
        if action == "create-nested-project":
            return bootstrap_create_project(
                action,
                utils.not_none(args.get("project"), "project key"),
                None,
                args.get("group_suffix"),
                args.get("parent_project"),
                args.get("parent_admin"),
                args.get("team_leader"),
                utils.flat_map_group(args.get("groups")),
            )

        if action in ["create-roles", "delete-roles"]:
            jenkins.parse_remote_args(args)
            sonarqube.parse_remote_args(args)
            alfresco.parse_remote_args(args)
            gitlab.parse_remote_args(args)
            argocd.parse_remote_args(args)
            nexus.parse_remote_args(args)
            project_key = utils.not_none(args.get("project"), "project key")
            project = ligoj.project_get(project_key)
            if not project:
                utils.warn(f"[ligoj] Project '{project_key}' not found, partial context will be available in JSON")

            context: dict[str, str] = {"project": {"key": project_key} | ({"name": project_key, "id": 0} if project is None else {"name": project.get("name"), "id": project.get("id")})}
            definition_json = utils.load_json_from_url_or_file_with_interpolation(utils.not_none(args.get("from"), "configuration file/URL"), context)
            schema_base = utils.load_json_from_url_or_file_with_interpolation("./plugins/schema.json", context)
            schema_extension = utils.load_json_from_url_or_file_with_interpolation(args.get("schema"), context)
            schema = schema_base if schema_extension is None else merge(schema_base, schema_extension)
            validate(definition_json, schema)

            if action == "create-roles":
                return bootstrap_create_roles(
                    project_key,
                    utils.flat_map_group(args.get("groups")),
                    definition_json,
                    args.get("group_suffix"),
                    args.get("on_behalf_of"),
                )

            if action == "delete-roles":
                return bootstrap_delete_roles(project, utils.flat_map_group(args.get("groups")), definition_json, args.get("group_suffix"))


def is_plugin_included(definition_json, plugin) -> bool:
    plugin_name = getattr(plugin, "PLUGIN_NAME")
    endpoint = getattr(plugin, f"{plugin_name}_endpoint")
    included = plugin_name in definition_json and plugin_name not in excludes and "*" not in excludes and (plugin_name in includes or "*" in includes) and endpoint and len(endpoint) > 0
    if included:
        utils.check_endpoint(endpoint, plugin_name)
    return included


def is_plugin_with_data(plugin: str) -> bool:
    return plugin in with_data or "*" in with_data


##
# Activities
# -----
# For each tool, delete the related role
def bootstrap_delete_roles(project_key: str, groups: list[str], definition_json, group_suffix: str):
    (groups, groups_by_name, parent_group) = validate_schema("Delete", project_key, definition_json, groups, group_suffix)

    # Delete the roles for each tool
    if is_plugin_included(definition_json, jenkins):
        jenkins.jenkins_delete_roles(groups_by_name, definition_json["jenkins"], is_plugin_with_data("jenkins"))

    if is_plugin_included(definition_json, nexus):
        nexus.nexus_delete_roles(groups_by_name, definition_json["nexus"], is_plugin_with_data("nexus"))

    if is_plugin_included(definition_json, sonarqube):
        sonarqube.sonar_delete_roles(groups_by_name, definition_json["sonar"], is_plugin_with_data("sonar"))

    if is_plugin_included(definition_json, alfresco):
        alfresco.alfresco_delete_site_roles(groups_by_name, definition_json["alfresco"], is_plugin_with_data("alfresco"))

    if is_plugin_included(definition_json, argocd):
        argocd.argocd_delete_project_roles(groups_by_name, definition_json["argocd"], is_plugin_with_data("argocd"))

    if is_plugin_included(definition_json, gitlab):
        gitlab.gitlab_delete_project_roles(parent_group, groups_by_name, definition_json["gitlab"], is_plugin_with_data("gitlab"))

    utils.info("[bootstrap] Roles have been deleted as needed")
    return False


##
# Activities
# -----
# For each tool, create the related role
def bootstrap_create_roles(project_key: str, groups: list[str], definition_json, group_suffix: str, on_behalf_of: str | None):
    (groups, groups_by_name, parent_group) = validate_schema("Create", project_key, definition_json, groups, group_suffix)

    # Create the roles for each tool
    if is_plugin_included(definition_json, jenkins):
        jenkins.jenkins_create_roles(groups_by_name, definition_json["jenkins"])

    if is_plugin_included(definition_json, nexus):
        nexus.nexus_create_roles(groups_by_name, definition_json["nexus"])

    if is_plugin_included(definition_json, sonarqube):
        sonarqube.sonar_create_roles(groups_by_name, definition_json["sonar"])

    if is_plugin_included(definition_json, alfresco):
        alfresco.alfresco_create_site_roles(groups_by_name, definition_json["alfresco"])

    if is_plugin_included(definition_json, argocd):
        argocd.argocd_create_project_roles(groups_by_name, definition_json["argocd"])

    if is_plugin_included(definition_json, gitlab):
        gitlab.gitlab_create_project_roles(parent_group, project_key, groups_by_name, on_behalf_of, definition_json["gitlab"])

    utils.info("[bootstrap] Roles have been created as needed")
    return False


##
# Activities
# -----
# Create container scope "Unassigned"[group] as needed (ou=groups)
# Create container scope "Project"[group] as needed (ou=project,ou=groups)
# Create container scope "Technical Group"[group] as needed (ou=technical-groups,ou=groups)
# Create container scope "Global Sub Groups"[company] as needed (ou=groups)
# Create container scope "Unassigned"[company] as needed (ou=people)
# Create container scope "Internal"[company] as needed (ou=internal,ou=people)
# Create container scope "Technical"[company] as needed (ou=technical-users,ou=people)
# Create LDAP OU "technical-groups" in scope "Global Sub Groups"[group]
# Create LDAP OU "technical-users" in scope "Unassigned"[company]
# Create groups as need within "technical-groups"
def bootstrap_init(
    base_dn: str,
    groups_base_dn: str,
    projects_base_dn: str,
    technical_groups_base_dn: str,
    users_base_dn: str,
    internal_users_base_dn: str,
    technical_users_base_dn: str,
    external_users_base_dn: str,
    technical_groups: list[str],
):
    # Companies
    scope_unassigned_company = id.container_scope_create("Unassigned", "company", id.ldap_concat(users_base_dn, "", base_dn))
    id.container_scope_create("Internal", "company", id.ldap_concat(internal_users_base_dn, users_base_dn, base_dn))
    id.container_scope_create("External", "company", id.ldap_concat(external_users_base_dn, users_base_dn, base_dn))
    id.container_scope_create("Technical", "company", id.ldap_concat(technical_users_base_dn, users_base_dn, base_dn))
    id.company_create(DEFAULT_LDAP_OU_TECHNICAL_USERS, scope_unassigned_company)
    id.company_create(DEFAULT_LDAP_OU_EXTERNAL_USERS, scope_unassigned_company)

    # Groups
    scope_unassigned_group = id.container_scope_create("Unassigned", "group", id.ldap_concat(groups_base_dn, "", base_dn))
    id.container_scope_create("Project", "group", id.ldap_concat(projects_base_dn, groups_base_dn, base_dn))

    # Cross instances administrator access
    if technical_groups_base_dn and not technical_groups.empty():
        scope_technical_group = id.container_scope_create("Technical", "group", id.ldap_concat(technical_groups_base_dn, groups_base_dn, base_dn))
        id.ou_create("technical-groups", scope_unassigned_group, "group")
        for technical_group in technical_groups:
            id.group_create(technical_group, scope_technical_group)


##
# Activities
# -----
# Check project "admin" users exists
# Validate the DNS record from the given format
# Create "project_admin" system role
# Create user "script-admin" and along with its API key
# Create user "script-reader" and along with its API key
# Associate "script-admin" and user to the "project_admin" system role
# Create project "project" with "admin" as team leader
# Create LDAP subscription to this project "project"
# Add "admin" user as member of the created group "project"
# Add "script-admin" user as member of the created group "project"
# Create LDAP sub-group "project-admin"
# Add "admin" user as member of the created group "project-admin"
# Add "script-admin" user as member of the created group "project-admin"
# Add delegation to "project-admin" group to manage the parent group "project" with "Administration" and "Write" privileges
# Create Jenkins/SonarQube nodes (option)
def bootstrap_welcome_user(
    admin_user,
    project_key,
    project_name: str | None,
    verify_project_with_dns: str | None,
    group_suffix: str,
    reset_reader_password: bool,
    script_custom_attributes: dict,
    reader_custom_attributes: dict,
):
    # Check the user exists in directory
    user_details = id.user_find_by_id_or_mail(admin_user)
    admin_user = user_details["id"]

    # Check DNS record
    if verify_project_with_dns is None:
        utils.info(f"[ligoj] No DNS validation for '{project_key}'")
    else:
        dns_record_formats = verify_project_with_dns.split(",")
        validated = False
        for dns_record_format in dns_record_formats:
            dns_record = dns_record_format.replace("PROJECT_KEY", project_key)
            utils.info(f"[ligoj] Validate DNS A record '{dns_record}' ...")
            try:
                dns_result = dns.resolver.resolve(dns_record, "A")
                for rr in dns_result:
                    utils.info(f"[ligoj] Validating DNS A record '{dns_record}' succeed': {rr}")
                    validated = True
                    break
            except BaseException:
                pass
            if validated:
                break
        if not validated:
            raise ValueError(f"[ligoj] All DNS A records validation failed for project {project_key}")

    # Create technical script admin user
    ligoj_user_script = f"{project_key}-script"
    id.user_create(
        {
            "id": ligoj_user_script,
            "firstName": "Jenkins script",
            "lastName": project_key,
            "mail": f"{ligoj_user_script}@localhost",
            "company": DEFAULT_LDAP_OU_TECHNICAL_USERS,
            "groups": ["full-read"],
            "customAttributes": script_custom_attributes and json.loads(script_custom_attributes) or None,
        }
    )
    role_name = f"ADMIN_{project_key.upper()}"
    role = ligoj.system_role_create(role_name, [".*"], [".*"])
    user_api_key = ligoj.system_user_upsert(ligoj_user_script, [role], f"cli-{utils.now_str}")
    if user_api_key is None:
        utils.info(f"[ligoj] User '{ligoj_user_script}' has been created with api_key")
    else:
        user_api_key = user_api_key.json()
        utils.info(f"[ligoj] User '{ligoj_user_script}' had already an api_key and will not be displayed there")

    # Create technical LDAP reader user
    ligoj_user_reader = f"{project_key}-reader"
    ligoj_user_reader_password = id.user_create(
        {
            "id": ligoj_user_reader,
            "firstName": "Reader",
            "lastName": project_key,
            "mail": f"{ligoj_user_reader}@localhost",
            "company": DEFAULT_LDAP_OU_TECHNICAL_USERS,
            "groups": [],
            "returnGeneratePassword": True,
            "customAttributes": json.loads(reader_custom_attributes) if reader_custom_attributes else None,
        }
    )
    if ligoj_user_reader_password is None:
        if reset_reader_password:
            ligoj_user_reader_password = id.user_reset_password(ligoj_user_reader)
            utils.info(f"[ligoj] User '{ligoj_user_reader}' was already created with password, and reset to a new one")
        else:
            utils.info(f"[ligoj] User '{ligoj_user_reader}' was already created with password (cannot be retrieved again)")
    else:
        ligoj_user_reader_password = ligoj_user_reader_password.text
        utils.warn(f"[ligoj] User '{ligoj_user_reader}' has been created with password, add LDAP ACL for the following DN: uid={ligoj_user_reader}(base_dn)")

    # Create the project
    project_id = ligoj.project_create(admin_user, project_key, f"Principal {project_key}" if project_name is None else project_name, f"Projet principal de {project_key}")["id"]

    # Retrieve the primary node
    ldap_node = ligoj.configuration_get("feature:iam:node:primary").get("value")
    utils.debug(f"[ligoj] Create LDAP groups in node {ldap_node}, detected from configuration 'feature:iam:node:primary'")

    # Create LDAP parent group
    group = f"{project_key}{group_suffix}"
    id.subscription_create_id_group(project_id, project_key, ldap_node, group)
    id.user_add_to_group(admin_user, group)
    id.user_add_to_group(ligoj_user_script, group)

    # Create LDAP admin group inside the project
    group_admin = f"{group}-admin"
    id.subscription_create_id_group(project_id, project_key, ldap_node, group_admin, group)
    id.user_add_to_group(admin_user, group_admin)
    id.user_add_to_group(ligoj_user_script, group_admin)

    # Create LDAP reader group inside the project
    group_readers = f"{group}-readers"
    id.subscription_create_id_group(project_id, project_key, ldap_node, group_readers, group)
    id.user_add_to_group(admin_user, group_readers)
    id.user_add_to_group(ligoj_user_script, group_readers)

    # Create A+W delegate to admin group to manage the parent group
    id.delegate_org_create("group", group, "group", group_admin, True, True)
    id.delegate_org_create("group", group, "group", group_readers, False, False)

    # Create Ligoj nodes related to supported tool
    node_base_id = project_key.replace(":", "-").lower()
    if jenkins.jenkins_endpoint:
        jenkins.welcome_user(node_base_id, ligoj_user_reader, ligoj_user_reader_password)
    if sonarqube.sonar_endpoint:
        sonarqube.welcome_user(node_base_id, ligoj_user_reader, ligoj_user_reader_password)

    result = {
        "admin_user": admin_user,
        "admin_user_mails": user_details.get("mails"),
        "script_user": ligoj_user_script,
        "script_api_key": user_api_key,
        "reader_user": ligoj_user_reader,
        "reader_password": ligoj_user_reader_password,
        "project_key": project_key,
        "project_id": project_id,
        "project_url": f"{ligoj.ligoj_endpoint}/#/home/project/{project_id}",
    }
    return result


##
# Activities
# -----
# Check the project
# For each group, create LDAP sub-group "project-$1"
def bootstrap_create_project(action: str, project_key: str, project_name: str | None, group_suffix: str, parent_project: str | None, parent_admin: str | None, team_leader: str | None, groups):
    team_leader = team_leader or parent_admin or ligoj.ligoj_api_user
    if action == "create-project":
        if parent_project is None:
            utils.info(f"[ligoj] Create new project {project_key} and its groups... ")
        elif parent_admin is None:
            utils.info(f"[ligoj] Create new project {project_key} and its groups with a relation to {parent_admin}... ")
        else:
            utils.info(f"[ligoj] Create new project {project_key} and its groups with a relation to {parent_admin} where {parent_admin} must be a manager... ")
    else:
        utils.info(f"[ligoj] Create groups for nested project {project_key} inside {parent_project} ... ")

    # Check the child project
    if parent_project is None:
        utils.info(f"[ligoj] Validate project {project_key} ... ")
        project_details = ligoj.project_get(project_key)
        if project_details is None:
            raise ValueError(f"[ligoj] No project '{project_key}' found")
        if project_details["manageSubscriptions"] is not True:
            raise ValueError(f"[ligoj] Project '{project_key}' is not managed by current user")
        project_id = project_details["id"]
    else:
        utils.info(f"[ligoj] Validate parent project {parent_project} ... ")
        headers = None
        team_leader_details = id.user_find_by_id_or_mail(team_leader)
        team_leader = team_leader_details["id"]
        if parent_admin:
            # Use run-as capability
            if parent_admin != team_leader:
                parent_admin_details = id.user_find_by_id_or_mail(parent_admin)
                parent_admin = parent_admin_details["id"]
            headers = {"x-api-run-as-user": parent_admin}

        parent_project_details = id.project_get(parent_project, headers=headers)
        if parent_project_details is None:
            raise ValueError(f"[ligoj] Project '{parent_project}' does not exists or not visible to user {team_leader}")
        if parent_project_details["manageSubscriptions"] is not True:
            raise ValueError(f"[ligoj] Project '{parent_project}' is not managed by user {team_leader}")

        child_project_details = ligoj.project_get(project_key, headers=headers)
        if child_project_details is None:
            project_id = ligoj.project_create(
                team_leader, project_key, f"Principal {project_key}" if project_name is None else project_name, f"Projet principal de {project_key}", json.dumps({"parent-project": parent_project})
            )["id"]
        elif child_project_details["manageSubscriptions"] is True:
            project_id = child_project_details["id"]
            utils.debug(f"[ligoj] Project {project_key} already exists with id {project_id}")
        else:
            raise ValueError(f"[ligoj] Parent project '{project_key}' already exists and is not managed by {team_leader}")

    # Retrieve the primary node
    ldap_node = ligoj.configuration_get("feature:iam:node:primary").get("value")
    utils.debug(f"[ligoj] Create LDAP groups in node {ldap_node}, detected from configuration 'feature:iam:node:primary'")

    # Create the LDAP groups
    if "admin" not in groups:
        groups.append("admin")
    utils.info(f"[ligoj] Create groups ({len(groups)}) for project {project_key}({project_id}) ... ")

    parent_group = f"{project_key}{group_suffix}"
    created_groups = 0
    expected_groups = 0
    if parent_project is not None:
        # Create LDAP parent group for this new project
        expected_groups = expected_groups + 1
        if id.subscription_create_id_group(project_id, project_key, ldap_node, parent_group):
            created_groups = created_groups + 1

        # Create LDAP admin group inside the project
        group_admin = f"{parent_group}-admin"
        expected_groups = expected_groups + 1
        if id.subscription_create_id_group(project_id, project_key, ldap_node, group_admin, parent_group):
            created_groups = created_groups + 1

        id.user_add_to_group(team_leader, group_admin)

        # Create A+W delegate to admin group to manage the parent group
        id.delegate_org_create("group", parent_group, "group", group_admin, True, True)

    for group in groups:
        if group.startswith(f"{parent_group}-"):
            utils.warn(f"[ligoj] Provided group '{group}' already starts by required prefix '{parent_group}-'")
            ldap_group = group
            base_group = group[len(f"{parent_group}-") :]
        elif group.startswith(f"{project_key}-"):
            raise ValueError(f"[ligoj] Invalid group name '{group}', must start with '{parent_group}-' or not starts with '{project_key}-'")
        else:
            base_group = group
            ldap_group = f"{parent_group}-{group}"
        if base_group != "admin":
            expected_groups = expected_groups + 1
            if id.subscription_create_id_group(project_id, project_key, ldap_node, ldap_group, parent_group):
                created_groups = created_groups + 1

    utils.info(f"[ligoj] {created_groups}/{expected_groups} groups have been created")
    return False


##
# Activities
# -----
# Check the project's permissions:
#   - Retrieve the project's details with "@on_behalf_of" identity and "@project_key" identifier.
#   - If not found
#       - Retrieve the project's details with full privileges
#       - If exists and "parent-project" context is present:
#           - Retrieve the parent project's ("parent-project") details with "@parent_admin" identity
#           - If parent project has ""manageSubscriptions" permission => OK
#   - Else if project has "manageSubscriptions" permission => OK
# Delete the project, including all subscriptions with data mode and cascade deletion of LDAP groups
# Delete tools' data
def bootstrap_delete_project(project_key: str, parent_admin: str | None, on_behalf_of: str | None):
    utils.info(f"[ligoj] Delete project {project_key} and its groups... ")
    headers = None
    project_details = None

    if on_behalf_of:
        # Resolve the project using the "on_behalf" owner
        on_behalf_of = id.user_find_by_id_or_mail(on_behalf_of)
        headers = {"x-api-run-as-user": on_behalf_of}
        project_details = ligoj.project_get(project_key, headers=headers)

    if not project_details:
        project_details = ligoj.project_get(project_key)

    if project_details and parent_admin:
        # Resolve the project using the "parent_admin" owner
        parent_admin = id.user_find_by_id_or_mail(parent_admin)

        context = project_details.get("context")
        utils.debug(f"[ligoj] Project context {context}, typeof: {type(context)}")
        context = json.loads(context) if context and isinstance(context, str) else context
        if context and isinstance(context, dict) and isinstance(context.get("parent-project"), str):
            # Check the related parent project is visible
            headers = {"x-api-run-as-user": parent_admin}
            project_details = ligoj.project_get(context.get("parent-project"), headers=headers)

    if not project_details:
        utils.info(f"[ligoj] Project {project_key} does not exists")
        return

    ligoj.project_delete_by_pkey(project_key, True)


def validate_schema(mode, project_key, definition_json, groups: list[str], group_suffix: str) -> tuple[list[str], dict[str, str], str]:
    # Check the groups
    if not groups or len(groups) == 0:
        # No provided inline groups, check the one in JSON
        if "groups" not in definition_json or not isinstance(definition_json["groups"], list) or len(definition_json["groups"]) == 0:
            raise ValueError("[ligoj] Empty or not array 'groups'")
        groups = definition_json["groups"]

    # Create the LDAP groups
    utils.info(f"[ligoj] {mode} roles based on {len(groups)} group(s) for project '{project_key}' ... ")
    groups_by_name: dict[str, str] = {}

    parent_group = f"{project_key}{group_suffix}"
    for group in groups:
        if group.startswith(f"{parent_group}-"):
            utils.warn(f"[ligoj] Provided group '{group}' starts already by required prefix '{parent_group}-'")
            ldap_group = group
        elif group.startswith(f"{project_key}-"):
            raise ValueError(f"[ligoj] Invalid group name '{group}', must start with '{parent_group}-' or not starts with '{project_key}-'")
        else:
            ldap_group = f"{parent_group}-{group}"
        groups_by_name[group] = ldap_group

    return groups, groups_by_name, parent_group
