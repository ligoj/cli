#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
import json

from ligojcli.plugins import utils

PLUGIN_NAME = "harbor"
harbor_endpoint: str | None = None
harbor_user: str | None = None
harbor_password: str | None = None

# Robot Account 'robot$ligoj-cli'
# fD6LZlMWXMt6uO1AjuIWLNXG7Zl31sgb


# Role mapping
ROLE_MAPPING = {"Project Admin": 1, "Developer": 2, "Guest": 3, "Maintainer": 4, "Limited Guest": 5}


def configure(subparser_service):
    # harbor
    subparser_action = subparser_service.add_parser("harbor", help="Harbor operations").add_subparsers(title="action", help="Action", dest="action")

    # harbor project
    parser_action = subparser_action.add_parser("project", help="Project operations").add_subparsers(title="sub-action", help="Sub Action", dest="sub_action")
    subparser_action_project = parser_action.add_parser("create", help="Create a new project")
    subparser_action_project.add_argument("--name", "-n", help="Project name", required=True)
    subparser_action_project.add_argument("--public", "-p", help="Public project", action="store_true", default=False)
    subparser_action_project = parser_action.add_parser("delete", help="Delete a project")
    subparser_action_project.add_argument("--id", "-i", help="Project identifier or name", required=True)
    subparser_action_project = parser_action.add_parser("get", help="Get a project")
    subparser_action_project.add_argument("--id", "-i", help="Project identifier or name", required=True)
    subparser_action_project = parser_action.add_parser("list", help="List projects")
    subparser_action_project.add_argument("--search", "-s", help="Search criteria", required=False)

    # harbor member
    parser_action = subparser_action.add_parser("member", help="Member operations").add_subparsers(title="sub-action", help="Sub Action", dest="sub_action")
    subparser_action_member = parser_action.add_parser("add", help="Add a member to a project")
    subparser_action_member.add_argument("--project", "-p", help="Project identifier or name", required=True)
    subparser_action_member.add_argument("--group", "-g", help="Group name", required=True)
    subparser_action_member.add_argument("--role", "-r", help="Role name", choices=["Project Admin", "Maintainer", "Developer", "Guest", "Limited Guest"], required=True)
    subparser_action_member = parser_action.add_parser("remove", help="Remove a member from a project")
    subparser_action_member.add_argument("--project", "-p", help="Project identifier or name", required=True)
    subparser_action_member.add_argument("--group", "-g", help="Group name", required=True)
    subparser_action_member = parser_action.add_parser("list", help="List members of a project")
    subparser_action_member.add_argument("--project", "-p", help="Project identifier or name", required=True)


def parse_remote_args(args):
    global harbor_endpoint
    global harbor_user
    global harbor_password
    harbor_endpoint = utils.get_config(args, "harbor_endpoint", "HARBOR_ENDPOINT", None)
    harbor_user = utils.get_secret(args, "harbor_user", "HARBOR_USER", "admin")
    harbor_password = utils.get_secret(args, "harbor_password", "HARBOR_PASSWORD", None)


def execute_action(service, action, operation, args):
    if service == "harbor":
        parse_remote_args(args)
        if action == "project":
            if args.get("sub_action") == "create":
                return project_create(args["name"], args["public"])
            if args.get("sub_action") == "delete":
                return project_delete(args["id"])
            if args.get("sub_action") == "get":
                return project_get(args["id"])
            if args.get("sub_action") == "list":
                return project_list(args.get("search"))
        elif action == "member":
            if args.get("sub_action") == "add":
                return project_member_add(args["project"], args["group"], args["role"])
            if args.get("sub_action") == "remove":
                return project_member_remove(args["project"], args["group"])
            if args.get("sub_action") == "list":
                return project_member_list(args["project"])
    return None


def call_harbor_api(method, url, **kwargs):
    """
    Call Harbor API v2.0
    """
    if not harbor_endpoint:
        raise ValueError("[harbor] Harbor endpoint is not configured")

    response = utils.call_rest_api(method, "harbor", harbor_endpoint, url, (harbor_user, harbor_password), kwargs)

    if response is None:
        return None

    if isinstance(response, str):
        pass

    if not response.ok:
        try:
            error_json = response.json()
            if "errors" in error_json:
                raise ValueError(f"[harbor] API call failed: {error_json['errors']}")
        except json.JSONDecodeError:
            pass
        response.raise_for_status()

    return response


def project_create(name: str, public: bool = False):
    utils.info(f"[harbor] Create project '{name}' (public={public}) ...")
    data = {"project_name": name, "public": public, "metadata": {"public": str(public).lower()}}
    call_harbor_api("POST", "projects", json=data)
    return False


def project_delete(id_or_name: str):
    utils.info(f"[harbor] Delete project '{id_or_name}' ...")
    call_harbor_api("DELETE", f"projects/{id_or_name}")
    return False


def project_get(id_or_name: str):
    utils.info(f"[harbor] Get project '{id_or_name}' ...")
    response = call_harbor_api("GET", f"projects/{id_or_name}")
    return response.json() if response else None


def project_list(search: str | None = None):
    utils.info("[harbor] List projects ...")
    params = {}
    if search:
        params["name"] = search
    response = call_harbor_api("GET", "projects", params=params)
    return response.json() if response else []


def project_member_add(project_name_or_id: str, group_name: str, role_name: str):
    utils.info(f"[harbor] Add member group '{group_name}' to project '{project_name_or_id}' as '{role_name}' ...")

    role_id = ROLE_MAPPING.get(role_name)
    if not role_id:
        raise ValueError(f"[harbor] Invalid role '{role_name}'. Valid roles are: {list(ROLE_MAPPING.keys())}")

    data = {"role_id": role_id, "member_group": {"group_name": group_name, "group_type": 1}}

    call_harbor_api("POST", f"projects/{project_name_or_id}/members", json=data)
    return False


def project_member_remove(project_name_or_id: str, group_name: str):
    utils.info(f"[harbor] Remove member group '{group_name}' from project '{project_name_or_id}' ...")

    members = project_member_list(project_name_or_id)
    member_id = None
    for member in members:
        if "entity_name" in member and member["entity_name"] == group_name and member["entity_type"] == "g":
            member_id = member["id"]
            break

    if not member_id:
        utils.warn(f"[harbor] Member group '{group_name}' not found in project '{project_name_or_id}'")
        return False

    call_harbor_api("DELETE", f"projects/{project_name_or_id}/members/{member_id}")
    return False


def project_member_list(project_name_or_id: str):
    utils.info(f"[harbor] List members of project '{project_name_or_id}' ...")
    response = call_harbor_api("GET", f"projects/{project_name_or_id}/members")
    return response.json() if response else []
