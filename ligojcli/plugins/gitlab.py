#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
import re
import urllib.parse
from ligojcli.plugins import utils
from ligojcli.plugins import ligoj

PLUGIN_NAME = "gitlab"
DEFAULT_GITLAB_PROJECT_GROUP_PREFIX = ""
DEFAULT_GITLAB_PROJECT_SUBGROUP_PREFIX = "ligoj-"
DEFAULT_GITLAB_BASE_GROUP = "ligoj"
DEFAULT_GITLAB_WRAPPER_GROUP = "ligoj"
DEFAULT_GITLAB_WRAPPER_GROUP_NAME = "Ligoj"
GITLAB_SUB_GROUP_WITH_PREFIX = False  # When True, create sub group contains also the project id.
gitlab_endpoint: str | None = None
gitlab_token: str | None = None
gitlab_base_group: str | None = None
gitlab_project_group_prefix: str | None = None
gitlab_project_subgroup_prefix: str | None = None
gitlab_wrapper_group: str | None = None
gitlab_wrapper_group_name: str | None = None


def configure(subparser_service):
    subparser_action = subparser_service.add_parser("gitlab", help="GitLab operations").add_subparsers(title="action", help="Action", dest="action")

    # gitlab project
    parser_action = subparser_action.add_parser("project", help="Project operations").add_subparsers(title="sub-action", help="Sub Action", dest="sub_action")
    subparser_action_project = parser_action.add_parser("get", help="Get a project")
    subparser_action_project.add_argument("--path", "-p", help="Project path", required=True)

def execute_action(service, action, operation, args):
    if service == "gitlab":
        parse_remote_args(args)
        if action == "project":
            if args.get("sub_action") == "get":
                return gitlab_get_group(args["path"])
    return None

# Extract from args the parameters related to remote access API of GitLab
def parse_remote_args(args):
    global gitlab_endpoint
    global gitlab_token
    global gitlab_base_group
    global gitlab_project_group_prefix
    global gitlab_project_subgroup_prefix
    global gitlab_wrapper_group
    global gitlab_wrapper_group_name
    gitlab_endpoint = utils.get_config(args, "gitlab_endpoint", "GITLAB_ENDPOINT", None)
    gitlab_token = utils.get_secret(args, "gitlab_token", "GITLAB_TOKEN", None)
    gitlab_base_group = utils.get_config(args, "gitlab_base_group", "GITLAB_BASE_GROUP", DEFAULT_GITLAB_BASE_GROUP)
    gitlab_project_group_prefix = utils.get_config(args, "gitlab_project_group_prefix", "GITLAB_PROJECT_GROUP_PREFIX", DEFAULT_GITLAB_PROJECT_GROUP_PREFIX)
    gitlab_project_subgroup_prefix = utils.get_config(args, "gitlab_project_subgroup_prefix", "GITLAB_PROJECT_SUBGROUP_PREFIX", DEFAULT_GITLAB_PROJECT_SUBGROUP_PREFIX)
    gitlab_wrapper_group = utils.get_config(args, "gitlab_wrapper_group", "GITLAB_WRAPPER_GROUP", None)
    gitlab_wrapper_group_name = utils.get_config(args, "gitlab_wrapper_group_name", "GITLAB_WRAPPER_GROUP_NAME", None)


def call_gitlab_api(method, url, **kwargs):
    response = utils.call_rest_api(method, "gitlab", f"{gitlab_endpoint}/api/v4", url, None, kwargs | {"headers": {"PRIVATE-TOKEN": gitlab_token}})
    return response.json() if response else None


def gitlab_list_sub_groups(parent_path: str, data):
    utils.info(f"[gitlab] List sub-groups within the parent {parent_path} ...")
    path_no_slash = re.sub(r"^/", "", str(parent_path))
    return call_gitlab_api("GET", f"/groups/{urllib.parse.quote(path_no_slash, safe='')}/subgroups", data=data)


def gitlab_list_groups(options: dict = None):
    utils.info("[gitlab] List groups ...")
    return call_gitlab_api("/groups", options)


def gitlab_get_group(path_or_id: str, **kwargs) -> dict | None:
    utils.info(f"[gitlab] Get group details '{path_or_id}' ...")
    path_no_slash = re.sub(r"^/", "", str(path_or_id))
    return call_gitlab_api("GET", f'/groups/{urllib.parse.quote(path_no_slash, safe="")}', **kwargs)


def gitlab_add_group_member(path_or_id: int | str | None, user_id: str, access_level: int = 50, ignore_error=True):
    path_no_slash = re.sub(r"^/", "", str(path_or_id))
    return call_gitlab_api("POST", f'/groups/{urllib.parse.quote(path_no_slash, safe="")}/members', data={"user_id": user_id, "access_level": access_level}, ignore_error=ignore_error)


def gitlab_get_user_id(username: str):
    return call_gitlab_api("GET", "/users", params={"username": username}, ignore_error=True)


def gitlab_create_group(parent_id: int | str | None, path: str, definition, avatar: bool):
    utils.info(f"[gitlab] Create sub-group, parent={parent_id}: path={path} ...")
    path_no_slash = re.sub(r"^/", "", str(parent_id))
    response = call_gitlab_api("POST", "/groups/", data=definition |{"name": definition.get("name", path), "path": path, "parent_id": parent_id if not parent_id or type(parent_id) == int else urllib.parse.quote(path_no_slash, safe="")})
    if avatar:
        # Also upload the avatar
        call_gitlab_api("PUT", f"/groups/{response['id']}", files = {'avatar': open('customize/avatar.png', 'rb')} )
    return response

def gitlab_delete_group(path_or_id: int | str, ignore_error=True):
    utils.info(f"[gitlab] Delete group '{path_or_id} ...")
    path_no_slash = re.sub(r"^/", "", str(path_or_id))
    call_gitlab_api("DELETE", f"/groups/{urllib.parse.quote(path_no_slash, safe='')}", ignore_error=ignore_error)


def gitlab_create_project_roles(project_group_path: str, project_key: str, groups_by_name: dict[str, str], on_behalf_of: str | None, definition):
    utils.info("[gitlab] Create GitLab roles for projects ...")

    # Base group
    base_group_path = gitlab_base_group
    base_group_is_root = base_group_path == "/" or base_group_path == "" or not base_group_path
    base_group: dict | None = None
    if not base_group_is_root:
        # Locate project_group in the given base group
        utils.info(f"[gitlab] Locate base group '{base_group_path}' at root level")
        base_group = gitlab_get_group(base_group_path, ignore_error=True)
        if not base_group:
            raise ValueError(f"[gitlab] Base group path '{base_group_path}' is not found")

    # Project group
    gitlab_project_group_path = f"{gitlab_project_group_prefix or ''}{project_group_path}"
    gitlab_project_full_path = gitlab_project_group_path if base_group_is_root else f"{base_group_path}/{gitlab_project_group_path}"
    utils.info(f"[gitlab] Locate project group '{gitlab_project_full_path}'")
    project_group = gitlab_get_group(gitlab_project_full_path, ignore_error=True)
    if project_group:
        update_mode = definition.get("updateMode", utils.UPDATE_MODE_DEFAULT)
        if update_mode == utils.UPDATE_MODE_ONCE:
            utils.info(f"[gitlab] Project group '{project_group}'({project_group.get('id')}) already exists and update mode is '{utils.UPDATE_MODE_ONCE}', skip sub-groups creation")
            return
    else:
        if base_group:
            utils.info(f"[gitlab] Create project group '{gitlab_project_group_path}' inside '{base_group['full_path']}'")  # pylint: disable=unsubscriptable-object
            project_group = gitlab_create_group(base_group["id"], gitlab_project_group_path, {"name": project_key}, False)  # pylint: disable=unsubscriptable-object
        else:
            utils.info(f"[gitlab] Create project group '{gitlab_project_group_path}' at root level")
            project_group = gitlab_create_group(None, gitlab_project_group_path, {"name": project_key}, False)
        utils.debug(f"[gitlab] project_group_object {project_group}")

    # Wrapper
    wrapper_group_path = gitlab_wrapper_group if gitlab_wrapper_group and len(gitlab_wrapper_group) and gitlab_wrapper_group != "/" else None
    wrapper_group_name = gitlab_wrapper_group_name if wrapper_group_path and gitlab_wrapper_group_name and len(gitlab_wrapper_group_name) else wrapper_group_path
    utils.info(
        f"[gitlab] base_group_path={base_group_path}, wrapper_group_path={wrapper_group_path},wrapper_group_name={wrapper_group_name},base_group_is_root={base_group_is_root},gitlab_project_group_path={gitlab_project_group_path},gitlab_project_group_path={gitlab_project_group_path}"
    )

    # Wrapper project group
    project_wrapper_group = project_group
    project_wrapper_group_full_path = gitlab_project_full_path
    if wrapper_group_path:
        project_wrapper_group_full_path = f"{gitlab_project_full_path}/{wrapper_group_path}"
        utils.info(f"[gitlab] Locate project wrapper group '{project_wrapper_group_full_path}'")
        project_wrapper_group = gitlab_get_group(project_wrapper_group_full_path, ignore_error=True)
        if not project_wrapper_group:
            utils.info(f"[gitlab] Create project wrapper group '{wrapper_group_path}' inside '{gitlab_project_full_path}'")
            project_wrapper_group = gitlab_create_group(project_group.get("id") or None, wrapper_group_path, {"name": wrapper_group_name,"project_creation_level":"noone"}, True)
            utils.debug(f"[gitlab] project_wrapper_group_object {project_wrapper_group}")

    # Sub-groups
    for sub_group in definition.get("roles", {}).keys():
        role_definition = definition["roles"][sub_group]
        ldap_group_name = ligoj.get_ldap_group("gitlab", groups_by_name, sub_group)
        gitlab_subgroup_path = f"{gitlab_project_subgroup_prefix}{ldap_group_name}"
        gitlab_subgroup_name = f"{project_key} {role_definition.get('name', sub_group)}"

        utils.info(f"[gitlab] Search project sub groups matching '{gitlab_subgroup_path}' inside '{project_wrapper_group_full_path}' ...")
        gitlab_subgroup = gitlab_get_group(f"{project_wrapper_group_full_path}/{gitlab_subgroup_path}", ignore_error=True)

        if gitlab_subgroup:
            utils.info(f"[gitlab] Project sub group '{gitlab_subgroup_path}' already exists: '{gitlab_subgroup.get('id')}'")
        else:
            utils.info(f"[gitlab] Project sub group '{gitlab_subgroup_path}' does not exist, create it")
            gitlab_subgroup = gitlab_create_group(project_wrapper_group.get("id"), gitlab_subgroup_path, {"name": gitlab_subgroup_name, "project_creation_level": "noone"}, True)

        if sub_group == "admin":
            # Also add the team leader to this group right now without waiting for an LDAP synchronization
            team_leader = ligoj.user_find_by_id_or_mail(on_behalf_of) if on_behalf_of else ligoj.whoami()
            team_leader_id = gitlab_get_user_id(team_leader)
            if team_leader_id:
                gitlab_add_group_member(gitlab_subgroup.get("id"), team_leader_id)
            else:
                utils.warn(f"[gitlab] User '{team_leader}' cannot be found, and cannot be added to group '{gitlab_subgroup['full_path']}'")  # pylint: disable=unsubscriptable-object


def gitlab_delete_project_roles(project_group_path: str, groups_by_name: dict[str, str], definition, with_data: bool):
    utils.info("[gitlab] Delete GitLab roles for projects ...")

    # Base group
    base_group_path = gitlab_base_group
    base_group_is_root = base_group_path == "/" or base_group_path == "" or not base_group_path

    # Project group
    gitlab_project_group_path = f"{gitlab_project_group_prefix}{project_group_path}"
    gitlab_project_full_path = gitlab_project_group_path if base_group_is_root else f"{base_group_path}/{gitlab_project_group_path}"
    utils.info(f"[gitlab] Locate project group '{gitlab_project_full_path}'")
    project_group = gitlab_get_group(gitlab_project_full_path, ignore_error=True)
    if not project_group:
        utils.info(f"[gitlab] Project group '{gitlab_project_full_path}' does not exist, ignore")
        return

    if with_data:
        gitlab_delete_group(project_group["id"], ignore_error=True)  # pylint: disable=unsubscriptable-object
        return

    # Only roles are deleted, including the wrapper
    # Wrapper
    wrapper_group_path = gitlab_wrapper_group if gitlab_wrapper_group and len(gitlab_wrapper_group) and gitlab_wrapper_group != "/" else None
    if wrapper_group_path:
        project_wrapper_group_full_path = f"{gitlab_project_full_path}/{wrapper_group_path}"
        gitlab_delete_group(project_wrapper_group_full_path, ignore_error=True)
    else:
        # Delete sub-groups since there is no wrapper easy to delete
        for sub_group in definition.get("roles", {}).keys():
            ldap_group_name = ligoj.get_ldap_group("gitlab", groups_by_name, sub_group)
            gitlab_subgroup_path = f"{gitlab_project_subgroup_prefix}{ldap_group_name}"
            gitlab_delete_group(f"{gitlab_project_full_path}/{gitlab_subgroup_path}", ignore_error=True)
