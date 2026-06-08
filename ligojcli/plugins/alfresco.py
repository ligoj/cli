#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
import base64

from unidecode import unidecode

from ligojcli.plugins import ligoj, utils

PLUGIN_NAME = "alfresco"
alfresco_endpoint: str | None = None
alfresco_ticket: str | None = None
alfresco_user: str | None = None
alfresco_password: str | None = None


def configure(subparser_service):
    # alfresco
    subparser_action = subparser_service.add_parser(
        "alfresco", help="Alfresco related operations"
    ).add_subparsers(title="action", help="Action", dest="action")
    subparser_service2 = subparser_action.add_parser("site", help="Site operations").add_subparsers(
        title="action", help="Action", dest="operation"
    )
    subparser_service2.add_parser("list", help="List sites")
    parser_action = subparser_service2.add_parser("create", help="Create site")
    parser_action.add_argument("--id", "-i", help="Site name")
    parser_action.add_argument("--title", help="Site title")
    parser_action.add_argument("--visibility", help="Visibility", choices=["PUBLIC", "PRIVATE"])
    parser_action.add_argument("--description", help="Description")
    parser_action = subparser_service2.add_parser("get", help="Get site")
    parser_action.add_argument("--id", help="Site name")
    parser_action = subparser_service2.add_parser("add-group", help="Add group to site with a role")
    parser_action.add_argument("--id", help="Site name")
    parser_action.add_argument("--group", help="Group name")
    parser_action.add_argument(
        "--role", help="Role name", choices=["SiteCollaborator", "SiteConsumer", "SiteManager"]
    )
    parser_action = subparser_service2.add_parser("remove-group", help="Remove group from site")
    parser_action.add_argument("--id", help="Site name")
    parser_action.add_argument("--group", help="Group name")
    subparser_service2 = subparser_action.add_parser(
        "group", help="Group operations"
    ).add_subparsers(title="action", help="Action", dest="operation")
    parser_action = subparser_service2.add_parser("create", help="Create group")
    parser_action.add_argument("--id", "-i", help="Group name")
    parser_action.add_argument("--display-name", help="Group display name")
    parser_action.add_argument(
        "--parents", help="Parent group identifiers", nargs="*", default=["admin"]
    )
    parser_action = subparser_service2.add_parser("delete", help="Delete group")
    parser_action.add_argument("--id", "-i", help="Group name")
    parser_action = subparser_service2.add_parser("get", help="Get group")
    parser_action.add_argument("--id", "-i", help="Group name")


def execute_action(service, action, operation, args):
    if service == "alfresco":
        parse_remote_args(args)

        if action == "site" and operation == "create":
            return alfresco_create_site(
                args.get("id"), args.get("title"), args.get("description"), args.get("visibility")
            )
        if action == "site" and operation == "list":
            return alfresco_list_sites()
        if action == "site" and operation == "get":
            return alfresco_get_site(args.get("id"))
        if action == "site" and operation == "add-group":
            return alfresco_set_permissions(args.get("group"), [args.get("role")], args.get("id"))
        if action == "site" and operation == "remove-group":
            return alfresco_remove_permissions(args.get("group"), args.get("id"))
        if action == "group" and operation == "create":
            return alfresco_create_group(
                args.get("id"), args.get("display_name"), args.get("parents")
            )
        if action == "group" and operation == "get":
            return alfresco_get_group(args.get("id"))
        if action == "group" and operation == "get":
            return alfresco_delete_group(args.get("id"))
    return None


# Extract from args the parameters related to remote access API of Alfresco
def parse_remote_args(args):
    global alfresco_endpoint
    global alfresco_ticket
    global alfresco_user
    global alfresco_password
    alfresco_endpoint = utils.get_config(args, "alfresco_endpoint", "ALFRESCO_ENDPOINT", None)
    alfresco_ticket = utils.get_secret(args, "alfresco_ticket", "ALFRESCO_TICKET", None)
    alfresco_user = utils.get_secret(args, "alfresco_user", "ALFRESCO_USER", None)
    alfresco_password = utils.get_secret(args, "alfresco_password", "ALFRESCO_PASSWORD", None)


def call_alfresco_api(method, definition, url, **kwargs):
    global alfresco_ticket
    if not alfresco_ticket:
        if not alfresco_user or not alfresco_password:
            raise ValueError("[alfresco] No ticket and no user/password provided")
        alfresco_ticket = alfresco_login(alfresco_user, alfresco_password)
    return utils.call_rest_api(
        method,
        "alfresco",
        f"{alfresco_endpoint}/{definition}/versions/1/",
        url,
        None,
        kwargs
        | {
            "headers": {
                "Authorization": f"Basic {base64.b64encode(alfresco_ticket.encode('ascii')).decode()}"
            }
        },
    )


def alfresco_login(user, password):
    utils.info(f"[alfresco] Login of user '{user}' ...")
    return utils.call_rest_api(
        "POST",
        "alfresco",
        f"{alfresco_endpoint}/authentication/versions/1/",
        "tickets",
        None,
        {"data": {"userId": user, "password": password}},
    ).json()["entry"]["id"]


def alfresco_internal_group_name(name):
    return name if name.startswith("GROUP_") else f"GROUP_{name}"


def alfresco_get_group(name):
    utils.info(f"[alfresco] Get group {name} ...")
    name = alfresco_internal_group_name(name)
    response = call_alfresco_api("GET", "alfresco", f"groups/{name}", ignore_error=True)
    return response and response.json() or None


def alfresco_delete_group(name):
    utils.info(f"[alfresco] Delete group {name} ...")
    name = alfresco_internal_group_name(name)
    response = call_alfresco_api("DELETE", "alfresco", f"groups/{name}", ignore_error=True)
    return response and response.json() or None


def alfresco_list_groups():
    utils.info("[alfresco] List groups ...")
    return call_alfresco_api("GET", "alfresco", "groups")


def alfresco_create_group(name: str, display_name: str, parents=None):
    utils.info(f"[alfresco] Create group '{name}' ...")
    if alfresco_get_group(name):
        utils.debug(f"[alfresco] Group {name} already exists ...")
    else:
        call_alfresco_api(
            "POST",
            "alfresco",
            "groups",
            data={"id": name, "displayName": display_name, "parentIds": parents or []},
        )


def alfresco_list_sites():
    utils.info("[alfresco] List sites ...")
    return call_alfresco_api("GET", "alfresco", "sites")


def alfresco_get_site(name):
    utils.info(f"[alfresco] Get site {name} ...")
    response = call_alfresco_api("GET", "alfresco", f"sites/{name}", ignore_error=True)
    return response and response.json()["entry"] or None


def alfresco_create_site(name, title, description, visibility="PRIVATE"):
    if name != unidecode(name):
        raise ValueError("[alfresco] Site identifier can contain only ASCII chars")

    utils.info(f"[alfresco] Create site '{name}', '{title}' ({visibility}) ...")
    site_details = alfresco_get_site(name)
    if not title:
        title = name
    if site_details is None:
        call_alfresco_api(
            "POST",
            "alfresco",
            "sites",
            data={"id": name, "title": title, "description": description, "visibility": visibility},
        )
        return

    utils.info(f"[alfresco] Site {name} already exists")
    current_title = site_details.get("title", "")
    current_description = site_details.get("description", "")
    current_visibility = site_details["visibility"]
    if (
        current_title != (title or "")
        or current_description != (description or "")
        or current_visibility != visibility
    ):
        # Update to the new key
        utils.debug(f"[alfresco] Update site '{name}' title, description or visibility ...")
        call_alfresco_api(
            "PUT",
            "alfresco",
            f"sites/{name}",
            data={"title": title, "description": description, "visibility": visibility},
        )


def alfresco_delete_site(site_id, site_details, remove_from_trash):
    utils.info(f"[alfresco] Delete site {site_id} ...")
    if site_details is None:
        utils.info(f"[alfresco] Site {site_id} does not exist, ignore")
    else:
        call_alfresco_api("DELETE", "alfresco", f"sites/{site_id}")

    if remove_from_trash:
        nodes = call_alfresco_api(
            "GET", "alfresco", "deleted-nodes", data={"maxItems": 100000}
        ).json()["list"]["entries"]
        node_entry = next(
            filter(
                lambda x: x["entry"]["nodeType"] == "st:site" and x["entry"]["name"] == site_id,
                nodes,
            ),
            None,
        )
        if node_entry:
            # Also remote site from trash
            node_id = node_entry["entry"]["id"]
            utils.info(f"[alfresco] Delete site {site_id} from trash, node_id={node_id} ...")
            call_alfresco_api("DELETE", "alfresco", f"deleted-nodes/{node_id}")
        elif site_details:
            utils.warn(
                f"[alfresco] Site {site_id} has been deleted, however it is not found in trash"
            )


def alfresco_create_site_roles(groups_by_name: dict[str, str], definition):
    utils.info("[alfresco] Create Alfresco roles for sites ...")

    for alfresco_site in definition.get("sites", []):
        alfresco_site_id = alfresco_site.get("id", "")
        alfresco_site_title = alfresco_site.get("title", "")
        alfresco_site_description = alfresco_site.get("description", "")
        alfresco_site_visibility = alfresco_site.get("visibility", "public").upper()
        if alfresco_site_id == "":
            raise ValueError("[alfresco] Missing Alfresco site id")
        if alfresco_site_title == "":
            alfresco_site_title = alfresco_site_id
        if alfresco_site_visibility not in ["PUBLIC", "PRIVATE"]:
            raise ValueError("[alfresco] Invalid Alfresco visibility in site '{alfresco_site_id}'")
        alfresco_create_site(
            alfresco_site_id,
            alfresco_site_title,
            alfresco_site_description,
            alfresco_site_visibility,
        )
        alfresco_create_roles_scope(groups_by_name, alfresco_site, alfresco_site_id)


def alfresco_delete_site_roles(groups_by_name: dict[str, str], definition, with_data: bool):
    utils.info("[alfresco] Delete Alfresco roles for sites ...")

    for alfresco_site in definition.get("sites", []):
        alfresco_site_id = alfresco_site.get("id", "")
        if alfresco_site_id == "":
            raise ValueError("[alfresco] Missing Alfresco site id")
        site_details = alfresco_get_site(alfresco_site_id)

        if site_details:
            alfresco_delete_roles_scope(groups_by_name, alfresco_site, alfresco_site_id)
        if with_data:
            alfresco_delete_site(alfresco_site_id, site_details, True)


def alfresco_create_roles_scope(groups_by_name: dict[str, str], definition, site_id):
    for alfresco_group in definition.get("roles", {}).keys():
        ldap_group = ligoj.get_ldap_group("alfresco", groups_by_name, alfresco_group)
        role_definition = definition["roles"][alfresco_group]
        permissions = role_definition.get("permissions", [])
        if len(permissions) == 0:
            raise ValueError(f"[alfresco] Missing Alfresco permissions in role '{alfresco_group}'")
        alfresco_create_group(ldap_group, ldap_group)
        alfresco_set_permissions(ldap_group, permissions, site_id)


def alfresco_delete_roles_scope(groups_by_name: dict[str, str], definition, site_id):
    for alfresco_group in definition.get("roles", {}).keys():
        ldap_group = ligoj.get_ldap_group("alfresco", groups_by_name, alfresco_group)
        alfresco_remove_permissions(ldap_group, site_id)
        alfresco_delete_group(ldap_group)


def alfresco_set_permissions(group, permissions, site_id):
    for permission in permissions:
        utils.info(
            f"[alfresco] Set permission '{permission}' to group '{group}' on site '{site_id}' ..."
        )
        group = alfresco_internal_group_name(group)
        member = call_alfresco_api(
            "GET", "alfresco", f"sites/{site_id}/group-members/{group}", ignore_400=True
        )
        if member:
            call_alfresco_api(
                "PUT",
                "alfresco",
                f"sites/{site_id}/group-members/{group}",
                data={"role": permission},
            )
        else:
            call_alfresco_api(
                "POST",
                "alfresco",
                f"sites/{site_id}/group-members",
                data={"id": group, "role": permission},
            )


def alfresco_remove_permissions(group, site_id):
    utils.info(f"[alfresco] Remove group '{group}' from site '{site_id}' ...")
    group = alfresco_internal_group_name(group)
    call_alfresco_api(
        "DELETE", "alfresco", f"sites/{site_id}/group-members/{group}", ignore_409=True
    )
