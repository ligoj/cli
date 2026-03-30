#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
import json

from unidecode import unidecode

from ligojcli.plugins import ligoj, utils

PLUGIN_NAME = "argocd"
ARGOCD_ALLOWED_ACTIONS = ["get", "create", "sync", "override", "delete", "*"]
argocd_endpoint: str | None = None
argocd_token: str | None = None
argocd_user: str | None = None
argocd_password: str | None = None


def configure(subparser_service):

    # argocd
    subparser_action = subparser_service.add_parser("argocd", help="Argo CD related operations").add_subparsers(title="action", help="Action", dest="action")
    subparser_service2 = subparser_action.add_parser("project", help="Project operations").add_subparsers(title="action", help="Action", dest="operation")
    subparser_service2.add_parser("list", help="List projects")
    parser_action = subparser_service2.add_parser("upsert", help="Create or update a project")
    parser_action.add_argument("--name", "-i", help="Project name")
    parser_action.add_argument("--description", help="Description")
    parser_action = subparser_service2.add_parser("get", help="Get project")
    parser_action.add_argument("--name", help="Project name")


def execute_action(service, action, operation, args):

    # argocd
    if service == "argocd":
        parse_remote_args(args)
        if action == "project" and operation == "upsert":
            return argocd_upsert_project(args.get("name"), args.get("description"))
        if action == "project" and operation == "list":
            return argocd_list_projects()
        if action == "project" and operation == "get":
            return argocd_get_project(args.get("name"))
    return None


# Extract from args the parameters related to remote access API of ArgoCD
def parse_remote_args(args):
    global argocd_endpoint
    global argocd_token
    global argocd_user
    global argocd_password
    argocd_endpoint = utils.get_config(args, "argocd_endpoint", "ARGOCD_ENDPOINT", None)
    argocd_token = utils.get_secret(args, "argocd_token", "ARGOCD_TOKEN", None)
    argocd_user = utils.get_secret(args, "argocd_user", "ARGOCD_API_TOKEN", None)
    argocd_password = utils.get_secret(args, "argocd_password", "ARGOCD_PASSWORD", None)


def argocd_list_projects():
    utils.info("[argocd] List projects ...")
    return call_argocd_api("GET", "projects").json()["items"]


def argocd_get_project(name):
    utils.info(f"[argocd] Get project {name} ...")
    response = call_argocd_api("GET", f"projects/{name}/detailed", ignore_error=True)
    return response and response.json() or None


def argocd_upsert_project(name, description: str | None = None):
    if name != unidecode(name):
        raise ValueError("[argocd] Project identifier can contain only ASCII chars")

    utils.info(f"[argocd] Create project '{name}' ...")
    project_details = argocd_get_project(name)
    if not description:
        description = name
    if project_details is None:
        call_argocd_api("POST", "projects", data={"project": {"metadata": {"name": name}, "spec": {"description": description}}})
        return argocd_get_project(name)

    utils.info(f"[argocd] Project '{name}' already exists")
    spec = project_details["project"].get("spec")
    if not spec:
        spec = {}
        project_details["spec"] = spec
    current_description = spec.get("description")
    if current_description != (description or ""):
        # Update to the new key
        utils.debug(f"[argocd] Update project '{name}' description ...")
        spec["description"] = description
        call_argocd_api("PUT", f"projects/{name}", data=project_details)
    return project_details


def argocd_login(user, password):
    utils.info(f"[argocd] Login of user '{user}' ...")
    return utils.call_rest_api("POST", "argocd", f"{argocd_endpoint}/api/v1", "session", None, {"username": user, "password": password}).json()["token"]


def call_argocd_api(method, url, **kwargs):
    global argocd_token
    if not argocd_token:
        if not argocd_user or not argocd_password:
            raise ValueError("[argocd] No token and no user/password provided")
        argocd_token = argocd_login(argocd_user, argocd_password)
    return utils.call_rest_api(method, "argocd", f"{argocd_endpoint}/api/v1", url, None, kwargs | {"headers": {"Content-Type": "application/json"}, "cookies": {"argocd.token": argocd_token}})


def argocd_create_project_roles(groups_by_name: dict[str, str], definition):
    utils.info("[argocd] Create ArgoCD roles for projects ...")

    for argocd_project in definition.get("projects", []):
        argocd_project_id = argocd_project.get("name", "")
        argocd_project_description = argocd_project.get("description", "")
        if argocd_project_id == "":
            raise ValueError("[argocd] Missing ArgoCD project name")
        if argocd_project_description == "":
            argocd_project_description = argocd_project_id
        project_details = argocd_upsert_project(argocd_project_id, argocd_project_description)
        argocd_create_roles_scope(groups_by_name, argocd_project, argocd_project_id, project_details)


def argocd_delete_project_roles(groups_by_name: dict[str, str], definition, with_data):
    utils.info("[argocd] Delete ArgoCD roles for projects ...")

    for argocd_project in definition.get("projects", []):
        argocd_project_id = argocd_project.get("name", "")
        if argocd_project_id == "":
            raise ValueError("[argocd] Missing ArgoCD project name")
        project_details = argocd_get_project(argocd_project_id)
        if project_details:
            argocd_delete_roles_scope(groups_by_name, argocd_project, argocd_project_id, project_details)

            if with_data:
                call_argocd_api("DELETE", f"projects/{argocd_project_id}")
        else:
            utils.info(f"[argocd] Project {argocd_project_id} does not exist, ignore")


def argocd_create_roles_scope(groups_by_name: dict[str, str], definition, project_id, project_details):
    current_project_json = json.dumps(project_details)
    for argocd_group in definition.get("roles", {}).keys():
        ldap_group = ligoj.get_ldap_group("argocd", groups_by_name, argocd_group)
        role_definition = definition["roles"][argocd_group]
        permissions = role_definition.get("permissions", [])
        if len(permissions) == 0:
            raise ValueError(f"[argocd] Missing ArgoCD permissions in role '{argocd_group}'")
        argocd_role = argocd_complete_role(ldap_group, project_details)
        argocd_complete_permissions(ldap_group, permissions, project_id, argocd_role)

    new_project_json = json.dumps(project_details)
    if new_project_json != current_project_json:
        # at least one change in this project
        utils.debug(f"[argocd] Update project '{project_id}' permissions ...")
        call_argocd_api("PUT", f"projects/{project_id}", data=project_details)


def argocd_delete_roles_scope(groups_by_name: dict[str, str], definition, project_id, project_details):
    current_project_json = json.dumps(project_details)
    for argocd_group in definition.get("roles", {}).keys():
        ldap_group = ligoj.get_ldap_group("argocd", groups_by_name, argocd_group)
        argocd_complete_role_delete(ldap_group, project_details)

    new_project_json = json.dumps(project_details)
    if new_project_json != current_project_json:
        # at least one change in this project
        utils.debug(f"[argocd] Update project '{project_id}', delete permissions ...")
        call_argocd_api("PUT", f"projects/{project_id}", data=project_details)


def argocd_complete_role(group, project_details):
    roles = project_details["project"]["spec"].get("roles")
    if not roles:
        roles = []
        project_details["project"]["spec"]["roles"] = roles

    role = next(filter(lambda r: r["name"] == group, roles), None)
    if not role:
        # Add a new role
        role = {"name": group}
        roles.append(role)
    return role


def argocd_complete_role_delete(group, project_details):
    roles = project_details["project"]["spec"].get("roles", [])
    project_details["project"]["spec"]["roles"] = list(filter(lambda r: r["name"] != group, roles))


def argocd_complete_permissions(group, permissions, project_id, argocd_role):
    policies = []
    for permission in permissions:
        if "action" not in permission:
            raise ValueError("[argocd] Missing ArgoCD permission action")
        action = permission["action"]
        if action not in ARGOCD_ALLOWED_ACTIONS:
            raise ValueError(f"[argocd] Invalid ArgoCD permission action, allowed: {ARGOCD_ALLOWED_ACTIONS}")
        action_permission = permission.get("permission", "allow")
        if action_permission != "allow" and action_permission != "deny":
            raise ValueError("[argocd] Invalid ArgoCD permission type, allowed: deny/allow")
        application = permission.get("application", "*")
        policies.append(f"p, proj:{project_id}:{group}, applications, {action}, {project_id}/{application}, {action_permission}")

    # Replace previous groups and policies
    argocd_role["groups"] = [group.lower()]
    argocd_role["policies"] = policies
