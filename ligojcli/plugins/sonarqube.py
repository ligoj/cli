#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
from ligojcli.plugins import ligoj, utils

PLUGIN_NAME = "sonar"
SONAR_PERMISSIONS_PROJECT = ["codeviewer", "issueadmin", "securityhotspotadmin", "scan", "user", "admin"]
SONAR_PERMISSIONS_GLOBAL = ["admin", "profileadmin", "gateadmin", "scan", "provisioning"]

sonar_endpoint: str | None = None
sonar_api_token: str | None = None


def configure(subparser_service):
    subparser_action = subparser_service.add_parser("sonar", help="SonarQube related operations").add_subparsers(title="action", help="Action", dest="action")
    subparser_service2 = subparser_action.add_parser("project", help="Project operations").add_subparsers(title="action", help="Action", dest="operation")
    subparser_service2.add_parser("list", help="List projects")
    parser_action = subparser_service2.add_parser("get", help="Get project")
    parser_action.add_argument("--name", help="Project name")
    parser_action = subparser_service2.add_parser("upsert", help="Create or update a project")
    parser_action.add_argument("--name", "-i", help="Project name")
    parser_action.add_argument("--description", help="Description")
    parser_action.add_argument("--visibility", help="Visibility")
    parser_action = subparser_service2.add_parser("delete", help="Delete project")
    parser_action.add_argument("--name", help="Project name")
    subparser_service2 = subparser_action.add_parser("session", help="Session operations").add_subparsers(title="action", help="Action", dest="operation")
    parser_action = subparser_service2.add_parser("login", help="Login")
    parser_action.add_argument("--user", help="User")
    parser_action.add_argument("--password", help="Password")
    parser_action = subparser_service2.add_parser("create-token", help="Create token")
    parser_action.add_argument("--user", help="User")
    parser_action.add_argument("--password", help="Password")
    parser_action.add_argument("--name", help="Token name")
    parser_action.add_argument("--target-user", help="Target user's owner of the token")


def execute_action(service, action, operation, args):

    # sonarqube
    if service == "sonar":
        parse_remote_args(args)
        if action == "project" and operation == "upsert":
            return sonar_create_project(args.get("name"), args.get("description"), args.get("visibility"))
        if action == "project" and operation == "list":
            return sonar_list_projects()
        if action == "project" and operation == "get":
            return sonar_get_project(args.get("name"))
        if action == "project" and operation == "delete":
            return sonar_delete_project(args.get("name"))
        if action == "session" and operation == "login":
            return sonar_login(args.get("user"), args.get("password"))
        if action == "session" and operation == "create-token":
            return sonar_create_user_token(args.get("user"), args.get("name"), args.get("target-user"), args.get("password"))
    return None


# Extract from args the parameters related to remote access API of SonarQube
def parse_remote_args(args):
    global sonar_endpoint
    global sonar_api_token
    sonar_endpoint = utils.get_config(args, "sonar_endpoint", "SONAR_ENDPOINT", None)
    sonar_api_token = utils.get_secret(args, "sonar_api_token", "SONAR_API_TOKEN", None)


def call_sonar_api(method, url, **kwargs):
    return utils.call_rest_api(method, "sonar", f"{sonar_endpoint}/api/", url, (sonar_api_token, ""), kwargs)


def sonar_login(user, password):
    utils.info(f"[sonar] Login of user '{user}' ...")
    return call_sonar_api("POST", "authentication/login", params={"login": user, "password": password}).json()


def sonar_create_user_token(user: str, name: str, login: str = None, password: str = None) -> str:
    utils.info(f"[sonar] Create token '{name}' for user '{user}', from user {login} ...")
    if password is not None:
        # User/password authentication mode
        utils.info(f"[sonar] Create token '{name}' for user '{user}' from user {login} ...")
        return utils.call_rest_api(
            "POST",
            "sonar",
            sonar_endpoint,
            "api/user_tokens/generate",
            (login, "password"),
            {"params": {"login": user, "name": name, "type": "USER_TOKEN"}},
        ).json()[
            "data"
        ]["tokenValue"]

    # API Token mode
    return call_sonar_api("POST", "user_tokens/generate", params={"login": user, "name": name, "type": "USER_TOKEN"}).json()


def sonar_create_user(user):
    utils.info(f"[sonar] Create user '{user}' ...")
    return call_sonar_api("POST", "users/create", params={"login": user, "name": user, "local": False}).json()


def sonar_create_group(name):
    utils.info(f"[sonar] Create group '{name}' ...")
    if sonar_get_group(name) is None:
        call_sonar_api("POST", "user_groups/create", params={"name": name})
    else:
        utils.debug(f"[sonar] Group {name} already exists ...")


def sonar_delete_group(name):
    utils.info(f"[sonar] Delete group '{name}' ...")
    if sonar_get_group(name) is None:
        utils.debug(f"[sonar] Group {name} does not exist, ignore")
    else:
        call_sonar_api("POST", "user_groups/delete", params={"name": name})


def sonar_create_project(name, key, visibility):
    utils.info(f"[sonar] Create project '{name}', '{key}' ({visibility}) ...")
    project_details = sonar_get_project(name)
    if project_details is None:
        call_sonar_api("POST", "projects/create", params={"name": name, "project": key})
    else:
        current_key = project_details["key"]
        current_visibility = project_details["visibility"]

        utils.debug(f"[sonar] Project {name} already exists")
        if current_key != key:
            # Update to the new key
            utils.debug(f"[sonar] Update project {name}'s key from {current_key} to {key} ...")
            call_sonar_api("POST", "projects/update_key", params={"name": name, "from": current_key, "to": key})
        if current_visibility != visibility:
            # Update to the new visibility
            utils.debug(f"[sonar] Update project {name}'s visibility from {current_visibility} to {visibility} ...")
            call_sonar_api("POST", "projects/update_visibility", params={"name": name, "visibility": visibility})


def sonar_delete_project(name):
    utils.info(f"[sonar] Delete project '{name}' ...")
    project_details = sonar_get_project(name)
    if project_details is None:
        utils.debug(f"[sonar] Project {name} does not exist, ignore")
    else:
        call_sonar_api("POST", "projects/delete", params={"project": project_details["key"]})


def sonar_get_group(name):
    utils.info(f"[sonar] Fetch group '{name}' ...")
    items = call_sonar_api("GET", "user_groups/search", params={"q": name}).json()["groups"]
    return next(filter(lambda x: x["name"] == name, items), None)


def sonar_get_project(name):
    utils.info(f"[sonar] Fetch project '{name}' ...")
    items = call_sonar_api("GET", "projects/search", params={"q": name}).json()["components"]
    return next(filter(lambda x: x["name"] == name, items), None)


def sonar_list_projects():
    utils.info("[sonar] List projects ...")
    items = call_sonar_api("GET", "projects/search").json()["components"]
    return items


def sonar_get_template(name):
    utils.info(f"[sonar] Fetch template '{name}' ...")
    items = call_sonar_api("GET", "permissions/search_templates", params={"q": name}).json()["permissionTemplates"]
    return next(filter(lambda x: x["name"] == name, items), None)


def sonar_create_template(name, project_key_pattern):
    utils.info(f"[sonar] Create template '{name}' ...")
    details = sonar_get_template(name)
    if details is None:
        call_sonar_api("POST", "permissions/create_template", params={"name": name, "projectKeyPattern": project_key_pattern})
    else:
        utils.debug(f"[sonar] Template {name} already exists")


def sonar_delete_template(name):
    utils.info(f"[sonar] Delete template '{name}' ...")
    details = sonar_get_template(name)
    if details is None:
        utils.debug(f"[sonar] Template {name} does not exist, ignore")
    else:
        call_sonar_api("POST", "permissions/delete_template", params={"templateName": name})


def sonar_create_roles(groups_by_name: dict[str, str], definition):
    utils.info("[sonar] Create SonarQube roles for project...")

    # Global roles
    sonar_create_roles_scope(groups_by_name, definition, "add_group", "remove_group", {}, SONAR_PERMISSIONS_GLOBAL)

    if utils.ADD_GLOBAL_ROLES:
        # Also add global administrator
        sonar_set_permissions("sonar-administrators", ["admin"], "add_group", "remove_group", {}, SONAR_PERMISSIONS_GLOBAL)

    # Template roles
    for sonar_template in definition.get("templates", []):
        sonar_template_name = sonar_template.get("name", "")
        project_key_pattern = sonar_template.get("projectPattern", "")
        if sonar_template_name == "":
            raise ValueError("[sonar] Missing SonarQube template name")
        if project_key_pattern == "":
            raise ValueError(f"[sonar] Missing SonarQube project pattern in template {sonar_template_name}")
        sonar_create_template(sonar_template_name, project_key_pattern)
        sonar_create_roles_scope(groups_by_name, sonar_template, "add_group_to_template", "remove_group_from_template", {"templateName": sonar_template_name}, SONAR_PERMISSIONS_PROJECT)

    for sonar_project in definition.get("projects", []):
        sonar_project_name = sonar_project.get("name", "")
        sonar_project_key = sonar_project.get("key", "")
        sonar_visibility = sonar_project.get("visibility", "public")
        if sonar_project_name == "":
            raise ValueError("[sonar] Missing SonarQube project name")
        if sonar_project_key == "":
            raise ValueError(f"[sonar] Missing SonarQube project key in project '{sonar_project_name}'")
        if sonar_visibility not in ["public", "private"]:
            raise ValueError("[sonar] Invalid SonarQube project visibility in project '{sonar_project_name}'")
        sonar_create_project(sonar_project_name, sonar_project_key, sonar_visibility)
        sonar_create_roles_scope(groups_by_name, sonar_project, "add_group", "remove_group", {"projectKey": sonar_project_key}, SONAR_PERMISSIONS_PROJECT)


def sonar_delete_roles(groups_by_name: dict[str, str], definition, with_data: bool):
    utils.info("[sonar] Delete SonarQube roles for project...")

    if with_data:
        # Template roles
        for sonar_template in definition.get("templates", []):
            sonar_template_name = sonar_template.get("name", "")
            if sonar_template_name == "":
                raise ValueError("[sonar] Missing SonarQube template name")
            sonar_delete_template(sonar_template_name)

        for sonar_project in definition.get("projects", []):
            sonar_project_name = sonar_project.get("name", "")
            if sonar_project_name == "":
                raise ValueError("[sonar] Missing SonarQube project name")
            sonar_delete_project(sonar_project_name)
    sonar_delete_groups(groups_by_name)


def sonar_create_roles_scope(groups_by_name: dict[str, str], definition, permission_add_path, permission_remove_path, target, all_permissions):
    for sonar_group in definition.get("roles", {}).keys():
        ldap_group = ligoj.get_ldap_group("sonar", groups_by_name, sonar_group)
        role_definition = definition["roles"][sonar_group]
        permissions = role_definition.get("permissions", [])
        if len(permissions) == 0:
            raise ValueError(f"[sonar] Missing SonarQube permissions in role '{sonar_group}'")
        sonar_create_group(ldap_group)
        sonar_set_permissions(ldap_group, permissions, permission_add_path, permission_remove_path, target, all_permissions)


def sonar_delete_roles_scope(groups_by_name: dict[str, str], definition, permission_path, target):
    for sonar_group in definition.get("roles", {}).keys():
        ldap_group = ligoj.get_ldap_group("sonar", groups_by_name, sonar_group)
        role_definition = definition["roles"][sonar_group]
        permissions = role_definition.get("permissions", [])
        sonar_delete_permissions(ldap_group, permissions, permission_path, target)
        sonar_delete_group(ldap_group)


def sonar_delete_groups(groups_by_name: dict[str, str]):
    for sonar_group in groups_by_name.keys():
        ldap_group = groups_by_name[sonar_group]
        sonar_delete_group(ldap_group)


def sonar_set_permissions(group, permissions, permission_add_path, permission_remove_path, target, all_permissions):
    for permission in permissions:
        utils.info(f"[sonar] Add permission '{permission}' to group '{group}' ...")
        call_sonar_api("POST", f"permissions/{permission_add_path}", params={"groupName": group, "permission": permission} | target, ignore_error=True)
    for permission in list(filter(lambda p: p not in permissions, all_permissions)):
        utils.trace(f"[sonar] Remove permission '{permission}' from group '{group}' ...")
        call_sonar_api("POST", f"permissions/{permission_remove_path}", params={"groupName": group, "permission": permission} | target, ignore_error=True)


def sonar_delete_permissions(group, permissions, permission_path, target):
    for permission in permissions:
        utils.info(f"[sonar] Delete permission '{permission}' from group '{group}' ...")
        call_sonar_api("POST", f"permissions/{permission_path}", params={"groupName": group, "permission": permission} | target, ignore_error=True)


def welcome_user(node_base_id, ligoj_user_reader, ligoj_user_reader_password):
    global sonar_api_token
    node_id = f"service:qa:sonarqube:{node_base_id}"
    node_name = f"SonarQube {node_base_id}"
    node = None
    utils.info(f"[ligoj] Create node '{node_id}', endpoint='{sonar_endpoint}', name='{node_name}'")
    if not ligoj_user_reader_password and not sonar_api_token:
        node = ligoj.node_get_by_id(node_id, "ALL", "map", True)
        if not node:
            raise ValueError("[ligoj] No available user reader password, regenerate one with '--reset-reader-password' or provide '--sonar-api-token', cannot update/create SonarQube like from Ligoj")
    if node:
        sonar_api_token = node["parameters"]["service:qa:sonarqube:password"]
    elif not sonar_api_token:
        sonar_api_token = sonar_create_user_token(ligoj_user_reader, "ligoj", ligoj_user_reader, ligoj_user_reader_password)
    ligoj.node_upsert(node_id, node_name, {"service:qa:sonarqube:url": sonar_endpoint, "service:qa:sonarqube:user": ligoj_user_reader, "service:qa:sonarqube:password": sonar_api_token}, "LINK")
