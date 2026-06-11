#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
import json
import urllib.parse

from unidecode import unidecode

from ligojcli.plugins import ligoj, utils


def configure(subparser_service):

    # plugin:id delegate node
    subparser_action = subparser_service.add_parser("id:delegate-node", help="Delegate node operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("list", help="List delegates")
    parser_action.add_argument("--node", "-n", help="Node identifier to filter", required=False)
    parser_action = subparser_action.add_parser("get", help="Return delegate node information")
    parser_action.add_argument("--id", "-i", help="Delegate node identifier", type=int)
    parser_action = subparser_action.add_parser("create", help="Create a new delegate node")
    parser_action.add_argument("--node", "-n", help="Node identifier to delegate", required=False)
    parser_action.add_argument(
        "--can-subscribe",
        "-S",
        help="Can create subscription related to this node",
        action="store_true",
        default=False,
    )
    parser_action.add_argument("--can-write", "-W", help="Can update this node", action="store_true", default=False)
    parser_action.add_argument("--can-admin", "-A", help="Can share this delegate", action="store_true", default=False)
    parser_action.add_argument("--receiver", "-R", help="Receiver identifier")
    parser_action.add_argument("--receiver-type", "-T", choices=["user", "group", "company"], help="Receiver type")
    parser_action = subparser_action.add_parser("delete", help="Delete a new delegate node")
    parser_action.add_argument("--id", "-i", help="Ligoj node identifier", required=False, type=int)

    # plugin:id delegate org
    subparser_action = subparser_service.add_parser("id:delegate-org", help="Delegate organization operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("get", help="Return delegate organization information")
    parser_action.add_argument("--id", "-i", help="Organization delegate organization identifier", required=False, type=int)
    parser_action.add_argument("--name", "-n", help="Organization identifier or DN for tree to filter", required=False)
    parser_action.add_argument(
        "--type",
        "-t",
        choices=["tree", "group", "company"],
        help="Organization type to delegate",
        required=False,
    )
    parser_action = subparser_action.add_parser("create", help="Create a new delegate organization")
    parser_action.add_argument("--id", "-i", help="Ligoj delegate organization identifier", type=int)
    parser_action.add_argument("--name", "-n", help="Organization identifier or DN for tree")
    parser_action.add_argument("--type", "-t", choices=["tree", "group", "company"], help="Organization type to delegate")
    parser_action.add_argument("--can-write", "-W", help="Can update this organization", action="store_true", default=False)
    parser_action.add_argument("--can-admin", "-A", help="Can share this delegate", action="store_true", default=False)
    parser_action.add_argument("--receiver", "-R", help="Receiver identifier", default=False)
    parser_action.add_argument("--receiver-type", "-T", choices=["user", "group", "company"], help="Receiver type")
    parser_action = subparser_action.add_parser("delete", help="Delete a new delegate organization")
    parser_action.add_argument("--id", "-i", help="Ligoj organization identifier", required=False, type=int)

    # plugin:id user
    subparser_action = subparser_service.add_parser("id:user", help="Plugin id user operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("create", help="Create a new user mapped to groups created as needed")
    parser_action.add_argument("--id", "-i", help="User name")
    parser_action.add_argument("--firstname", "-f", help="firstName")
    parser_action.add_argument("--lastname", "-l", help="lastName")
    parser_action.add_argument("--mail", "-m", help="mail")
    parser_action.add_argument("--company", "-c", help="company")
    parser_action.add_argument("--groups", "-g", help="groups", nargs="*", default=[])
    parser_action.add_argument(
        "--custom-attributes",
        "-A",
        help="Custom attributes. Case might be sensitive",
        default=False,
    )
    parser_action = subparser_action.add_parser("get", help="Return a user by id or by mail")
    parser_action.add_argument("--id", "-i", help="User name", required=False)
    parser_action.add_argument("--mail", "-m", help="User mail", required=False)
    parser_action = subparser_action.add_parser("list", help="Return a list users filtered by id and/or by mail")
    parser_action.add_argument("--company", "-c", help="Company name", required=False)
    parser_action.add_argument("--group", "-g", help="Group name", required=False)
    parser_action.add_argument("--criteria", "-s", help="Criteria", required=False)
    parser_action.add_argument("--page", "-p", help="Page number", required=False)
    parser_action.add_argument("--page-length", "-l", help="Page length", required=False)
    parser_action = subparser_action.add_parser("delete", help="Delete a user")
    parser_action.add_argument("--id", "-i", help="User name", required=False)
    parser_action.add_argument("--mail", "-m", help="User mail", required=False)
    parser_action = subparser_action.add_parser("add", help="Add user to groups")
    parser_action.add_argument("--id", "-i", help="User name", required=False)
    parser_action.add_argument("--mail", "-m", help="User mail", required=False)
    parser_action.add_argument("--groups", "-g", help="groups", nargs="+")
    parser_action = subparser_action.add_parser("remove", help="Remove user from groups")
    parser_action.add_argument("--id", "-i", help="User name", required=False)
    parser_action.add_argument("--mail", "-m", help="User mail", required=False)
    parser_action.add_argument("--groups", "-g", help="groups", nargs="+")

    # plugin:id group
    subparser_action = subparser_service.add_parser("id:group", help="Plugin id group operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("create", help="Create a new group")
    parser_action.add_argument("--name", "-n", help="Group name", required=True)
    parser_action.add_argument("--scope", "-s", help="Scope groupe name or identifier.", required=True)
    parser_action.add_argument("--parent", "-p", help="Parent group name")
    parser_action = subparser_action.add_parser("import", help="Import groups")
    parser_action.add_argument("--from", "-f", help="Import URL or local file name", required=True)
    parser_action = subparser_action.add_parser("get", help="Get group by name")
    parser_action.add_argument("--name", "-n", help="Group name", required=True)
    parser_action = subparser_action.add_parser("list", help="List groups")
    parser_action = subparser_action.add_parser("delete", help="Delete a group")
    parser_action.add_argument("--name", "-n", help="Group name", required=True)

    # plugin:id container scope
    subparser_action = subparser_service.add_parser("id:scope", help="Plugin id container scope operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("create", help="Create a new container scope")
    parser_action.add_argument("--name", "-n", help="Container scope name", required=True)
    parser_action.add_argument("--type", "-t", help="Scope type", required=True, choices=["company", "group"])
    parser_action.add_argument("--dn", help="Container scope DN")
    parser_action = subparser_action.add_parser("get", help="Get container scope by name or identifier")
    parser_action.add_argument("--id", "-i", help="Container scope identifier", required=False)
    parser_action.add_argument("--name", "-n", help="Container scope name, exclusive with id", required=False)
    parser_action.add_argument(
        "--type",
        "-t",
        help="Scope type. Required with name",
        required=False,
        choices=["company", "group"],
    )
    parser_action = subparser_action.add_parser("list", help="List container scopes")
    parser_action.add_argument("--type", "-t", help="Filtered scope type", required=True, choices=["company", "group"])
    parser_action = subparser_action.add_parser("delete", help="Delete a container scope or by identifier")
    parser_action.add_argument("--id", "-i", help="Container scope identifier", required=False)
    parser_action.add_argument("--name", "-n", help="Container scope name, exclusive with id", required=False)
    parser_action.add_argument(
        "--type",
        "-t",
        help="Scope type. Required with name",
        required=False,
        choices=["company", "group"],
    )

    # plugin:id ou
    subparser_action = subparser_service.add_parser("id:ou", help="Plugin id Organizational Unit operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("create", help="Create a new OU")
    parser_action.add_argument("--name", "-n", help="OU name", required=True)
    parser_action.add_argument("--parent-dn", "-d", help="Parent DN", required=True)
    parser_action = subparser_action.add_parser("delete", help="Delete an OU")
    parser_action.add_argument("--name", "-n", help="OU name", required=False)


def execute_action(service, action, _, args):
    if service == "id:delegate-node":
        if action == "list":
            return delegate_node_filter_by_node(args.get("node"))
        if action == "create":
            return delegate_node_create(
                args.get("node"),
                args.get("can_subscribe"),
                args.get("can_write"),
                args.get("can_admin"),
                args.get("receiver"),
                args.get("receiver_type"),
            )
        if action == "get":
            return delegate_node_get_by_id(args.get("id"))
        if action == "delete":
            return delegate_node_delete(args["id"])
    elif service == "id:delegate-org":
        if action == "create":
            return delegate_org_create(
                args["node"],
                args.get("can_subscribe"),
                args.get("can_write"),
                args.get("can_admin"),
                args.get("receiver"),
                args.get("receiver_type"),
            )
        if action == "get":
            if args.get("id") is not None:
                return delegate_org_get_by_id(args.get("id"))
            return delegate_org_filter_by_resource(args.get("type"), args.get("name"))
        if action == "delete":
            return delegate_org_delete(args["id"])
    elif service == "id:user":
        if action == "create":
            return user_create(
                {
                    "id": args["id"],
                    "firstName": args.get("firstname"),
                    "lastName": args.get("lastname"),
                    "mail": args.get("mail"),
                    "company": utils.not_none(args.get("company"), "user company"),
                    "groups": utils.flat_map_group(args.get("groups")),
                    "customAttributes": json.loads(args.get("custom_attributes", "{}")),
                }
            )
        if action == "get":
            return (args.get("id") and user_get(args.get("id"))) or (args.get("mail") and user_find_by_mail(args.get("mail")))
        if action == "list":
            return user_list(
                args.get("company"),
                args.get("group"),
                args.get("criteria"),
                args.get("page"),
                args.get("page_length"),
            )
        if action == "add":
            user_id = get_user_id(args, True)
            for group in utils.flat_map_group(args.get("groups")):
                user_add_to_group(user_id, group)
            return False
        if action == "remove":
            user_id = get_user_id(args, True)
            for group in utils.flat_map_group(args.get("groups")):
                user_remove_from_group(user_id, group)
            return False
        if action == "delete":
            return user_delete(get_user_id(args))
        if action == "reset-password":
            user_id = get_user_id(args, True)
            return user_reset_password(user_id)
    elif service == "id:group":
        if action == "get":
            return group_get_by_name(args["name"])
        if action == "list":
            return group_list()
        if action == "create":
            scope = utils.not_none(args.get("scope"), "scope")
            return group_create(args["name"], scope, args.get("parent"))
        if action == "import":
            group_import_file = utils.load_json_from_url_or_file_with_interpolation(utils.not_none(args.get("from"), "Import file/URL"), {})
            return group_import(group_import_file)
        if action == "delete":
            return group_delete(args["name"])
    elif service == "id:scope":
        if action == "get":
            if args.get("id") is None and (args.get("name") is None or args.get("type") is None):
                raise ValueError("[ligoj] When id is not provided, name and type are required")
            if args.get("id"):
                return container_scope_get_by_id(utils.not_none(args.get("id"), "id"))
            return container_scope_get_by_name(utils.not_none(args.get("name"), "name"), utils.not_none(args.get("type"), "type"))
        if action == "list":
            return container_scope_list(utils.not_none(args.get("type"), "type"))
        if action == "create":
            return container_scope_create(
                utils.not_none(args.get("name"), "name"),
                utils.not_none(args.get("type"), "type"),
                utils.not_none(args.get("dn"), "dn"),
            )
        if action == "delete":
            if args.get("id") is None and (args.get("name") is None or args.get("type") is None):
                raise ValueError("[ligoj] When scope id is not provided, scope name and scope type are required")
            if args.get("id"):
                return container_scope_delete_by_id(utils.not_none(args.get("id"), "id"))
            return container_scope_delete_by_name(utils.not_none(args.get("name"), "name"), utils.not_none(args.get("type"), "type"))
    elif service == "id:ou":
        if action == "create":
            return ou_create(
                utils.not_none(args.get("name"), "name"),
                utils.not_none(args.get("parent_dn"), "parent-dn"),
            )
        if action == "delete":
            return ou_delete(utils.not_none(args.get("name"), "name"))

    return None


def get_user_id(args, must_exist=False):
    if args.get("id"):
        return args.get("id")
    elif args.get("mail"):
        user = user_find_by_mail(args.get("mail"))
        if user:
            return user["id"]
    else:
        raise ValueError("[ligoj] User id or mail is required")
    if must_exist:
        raise ValueError(f"[ligoj] User '{args.get('id') or args.get('mail')}' not found")
    return None


def get_ldap_group(component, groups_by_name, local_role_name):
    ldap_group = groups_by_name.get(local_role_name, "")
    if ldap_group == "":
        raise ValueError(f"[{component}] Referenced group '{local_role_name}' has not been declared")
    if local_role_name != unidecode(local_role_name):
        raise ValueError(f"[{component}] Group name '{local_role_name}' cannot contain non ASCII chars")

    return ldap_group


def delegate_node_get_by_id(delegate_id: int):
    return ligoj.call_api("GET", f"node/delegate/{delegate_id}")


def delegate_node_filter_by_node(node_id: str):
    items = ligoj.call_api("GET", "node/delegate").json()["data"]
    return list(filter(lambda x: node_id is None or node_id == "" or x["name"] == node_id, items))


def delegate_node_delete(delegate_id: int):
    ligoj.call_api("DELETE", f"node/delegate/{delegate_id}", ignore_error=True, ignore_output=True)
    return False


def delegate_node_list():
    return ligoj.call_api("GET", "node/delegate").json()["data"]


def delegate_node_create(
    node_id: str,
    can_subscribe: bool,
    can_write: bool,
    can_admin: bool,
    receiver: str,
    receiver_type: str,
) -> int:
    return ligoj.call_api(
        "POST",
        "node/delegate",
        data={
            "name": node_id,
            "canSubscribe": can_subscribe,
            "canWrite": can_write,
            "canAdmin": can_admin,
            "receiver": receiver,
            "receiverType": receiver_type,
        },
    )


def user_reset_password(user):
    utils.info(f"[ligoj] Reset password of user '{user}' ...")
    return ligoj.call_api(
        "PUT",
        f"service/id/user/{urllib.parse.quote(user, safe='')}/reset",
        headers={"Accept": "text/plain"},
    ).text


def user_create(user_details):
    user = user_details["id"]
    utils.info(f"[ligoj] Create user '{user}' ...")
    response = ligoj.call_api("GET", f"service/id/user/{urllib.parse.quote(user, safe='')}", ignore_error=True)
    if response is not None:
        utils.debug(f"[ligoj] User '{user}' already exists")
        return None

    return ligoj.call_api("POST", "service/id/user", data=user_details)


def user_get(user: str) -> dict | None:
    utils.info(f"[ligoj] Fetch user '{user}' ...")
    response = ligoj.call_api("GET", f"service/id/user/{urllib.parse.quote(user, safe='')}", ignore_404=True)
    return None if response is None else response.json()


def user_list(
    company: str | None = None,
    group: str | None = None,
    criteria: str | None = None,
    page: int | None = None,
    page_size: int | None = None,
) -> dict | None:
    utils.info("[ligoj] Fetch user list ...")
    params = {}
    if company:
        params["company"] = company
    if group:
        params["group"] = group
    if criteria:
        params["search[value]"] = criteria
    if page:
        params["page"] = page
    if page_size:
        params["length"] = page_size
    response = ligoj.call_api("GET", "service/id/user", params=params)
    return None if response is None else response.json()


def user_find_by_id_or_mail(id_or_mail: str, required: bool | None = True) -> dict | None:
    user_details = user_get(id_or_mail) or user_find_by_mail(id_or_mail)
    if user_details is None:
        if required:
            raise ValueError(f"[ligoj] User '{id_or_mail}' does not exist")
        return None
    resolved_id = user_details["id"]
    if resolved_id != id_or_mail:
        utils.debug(f"[ligoj] Resolved user id from '{id_or_mail}' is '{resolved_id}'")
    return user_details


def user_find_by_mail(mail: str) -> dict | None:
    utils.info(f"[ligoj] Fetch user by mail '{mail}' ...")
    items = ligoj.call_api("GET", "service/id/user", ignore_error=True, params={"search[value]": mail}).json()["data"]
    return next(filter(lambda x: "mails" in x and mail in x["mails"], items), None)


def group_import(csv_file):
    utils.info("[ligoj] Import groups ...")
    return ligoj.call_api(
        "POST",
        "service/id/group/batch",
        data={
            "csv-file": csv_file,
            "encoding": "UTF-8",
            "columns": ["name", "scope", "parent", "department", "owner", "assistant"],
        },
    ).json()


def container_scope_get_id(name_or_id: str | int, container_type: str | None, required: bool = True) -> int:
    if isinstance(name_or_id, int):
        return name_or_id
    if isinstance(name_or_id, str) and name_or_id.isdigit():
        return int(name_or_id)
    if not container_type:
        raise ValueError("[ligoj] Scope type is required when scope name is provided instead of scope identifier")
    utils.info(f"[ligoj] Fetch container scope '{name_or_id}' [{container_type}] ...")
    response = ligoj.call_api(
        "GET",
        f"service/id/container-scope/name/{urllib.parse.quote(name_or_id, safe='')}/{container_type}",
        ignore_error=True,
    )
    if not response:
        if required:
            raise ValueError(f"[ligoj] Scope '{name_or_id}' not found in type '{container_type}'")
        return None
    return response.json()["id"]


def container_scope_get_by_id(id: int):
    utils.info(f"[ligoj] Fetch container scope '{id}' ...")
    return ligoj.call_api("GET", f"service/id/container-scope/{id}").json()


def container_scope_get_by_name(name: str, container_type: str):
    utils.info(f"[ligoj] Fetch container scope '{name}' [{container_type}] ...")
    return ligoj.call_api(
        "GET",
        f"service/id/container-scope/name/{urllib.parse.quote(name, safe='')}/{container_type}",
    ).json()


def container_scope_list(container_type: str):
    utils.info(f"[ligoj] Fetch container scopes [{container_type}] ...")
    return ligoj.call_api("GET", f"service/id/container-scope/{container_type}").json()


def container_scope_delete_by_id(id: int):
    utils.info(f"[ligoj] Delete container scope '{id}' ...")
    return ligoj.call_api("DELETE", f"service/id/container-scope/{id}")


def container_scope_delete_by_name(name: str, container_type: str):
    utils.info(f"[ligoj] Delete container scope '{name}' [{container_type}] ...")
    container_scope = container_scope_get_id(name, container_type, False)
    if container_scope is None:
        return None
    return ligoj.call_api("DELETE", f"service/id/container-scope/{container_scope}").json()


def container_scope_create(name: str, container_type: str, dn: str) -> int:
    utils.info(f"[ligoj] Create container scope '{name}'[{container_type}] associated to DN '{dn}' ...")
    container_response = ligoj.call_api(
        "GET",
        f"service/id/container-scope/name/{urllib.parse.quote(name, safe='')}/{container_type}",
        ignore_error=True,
    )
    if container_response is not None:
        existing_id = container_response.json()["id"]
        if container_response.json()["dn"] == dn:
            utils.debug(f"[ligoj] Container scope '{name}' already exists with id '{existing_id}' with identical DN")
        else:
            # Update DN
            utils.debug(f"[ligoj] Container scope '{name}' already exists with id '{existing_id}', update it's DN from '{container_response.json()['dn']}' to '{dn}' ...")
            ligoj.call_api(
                "PUT",
                "service/id/container-scope",
                data={"id": existing_id, "dn": dn, "name": name, "type": container_type},
            )
        return existing_id

    return ligoj.call_api("POST", "service/id/container-scope", data={"dn": dn, "name": name, "type": container_type}).json()


def company_create(name: str | int, container_scope: str | int, **kwargs):
    utils.info(f"[ligoj] Create company '{name}' in scope id '{container_scope}' ...")
    container_response = ligoj.call_api("GET", f"service/id/company/{urllib.parse.quote(name, safe='')}", ignore_error=True)
    if container_response:
        utils.debug(f"[ligoj] Company '{name}' already exists'")
        return

    return ligoj.call_api(
        "POST",
        "service/id/company",
        data=kwargs.get("data", {}) | {"name": name, "scope": container_scope},
        ignore_error=kwargs.get("ignore_error", False),
    )


def ou_create(name: str, parent_dn: str, **kwargs):
    utils.info(f"[ligoj] Create LDAP OU'{name}' in parent DN '{parent_dn}' ...")
    container_response = ligoj.call_api("GET", f"service/id/company/{urllib.parse.quote(name, safe='')}", ignore_error=True)
    if container_response:
        utils.debug(f"[ligoj] OU '{name}' already exists'")
        return container_response

    container_scope_id = container_scope_create(f"temporary-scope-{name}", "company", parent_dn)
    try:
        ou_response = ligoj.call_api(
            "POST",
            "service/id/company",
            data={"name": name, "scope": container_scope_id},
            ignore_error=kwargs.get("ignore_error", False),
        )
    finally:
        container_scope_delete_by_id(container_scope_id)
    return ou_response


def ou_delete(name: str):
    utils.info(f"[ligoj] Delete LDAP OU '{name}' ...")
    return ligoj.call_api("DELETE", "service/id/company", data={"name": name})


def group_create(name: str, container_scope_name_or_id: str | int, parent_name: str | None = None):
    utils.info(f"[ligoj] Create group '{'' if parent_name is None else f'{parent_name}/'}/{name}' in scope '{container_scope_name_or_id}' ...")
    if unidecode(name) != name:
        raise ValueError(f"[ligoj] Group name '{name}' cannot contain non ASCII chars")
    container_scope_id = container_scope_get_id(container_scope_name_or_id, "group")
    container_response = ligoj.call_api("GET", f"service/id/group/{urllib.parse.quote(name, safe='')}", ignore_error=True)
    if container_response is not None:
        utils.debug(f"[ligoj] Group '{name}' already exists'")
        return container_response

    return ligoj.call_api(
        "POST",
        "service/id/group",
        data={"name": name, "scope": container_scope_id, "parent": parent_name},
    )


def project_get(project_key_or_id, headers=None):
    response = ligoj.call_api(
        "GET",
        f"project/{project_key_or_id}",
        ignore_error=True,
        ignore_output=True,
        headers=headers,
    )
    if response is None:
        return None
    return response.json()


def group_get_by_name(group):
    if unidecode(group) != group:
        raise ValueError(f"[ligoj] Group name '{group}' cannot contain non ASCII chars")

    response = ligoj.call_api("GET", f"service/id/group/{urllib.parse.quote(group, safe='')}", ignore_error=True)
    return None if response is None else response.json()


def group_delete(group: str):
    utils.info(f"[ligoj] Delete group '{group}' ...")
    group_result = group_get_by_name(group)
    if group_result is None:
        utils.debug(f"[ligoj] Group '{group}' does not exist")
        return None
    return ligoj.call_api("DELETE", f"service/id/group/{group_result['id']}")


def group_list():
    response = ligoj.call_api("GET", "service/id/group", ignore_error=True)
    return None if response is None else response.json()


def user_add_to_group(user, group):
    utils.info(f"[ligoj] Add user '{user}' to group '{group}' ...")
    user_response = ligoj.call_api("GET", f"service/id/user/{urllib.parse.quote(user, safe='')}", ignore_error=True)
    if user_response is None:
        raise ValueError(f"[ligoj] User '{user}' does not exist")

    user_details = user_response.json()
    if group not in user_details["groups"]:
        return ligoj.call_api(
            "PUT",
            f"service/id/user/{urllib.parse.quote(user, safe='')}/group/{urllib.parse.quote(group, safe='')}",
        )
    utils.info(f"[ligoj] User '{user}' is already in group '{group}'")
    return None


def user_remove_from_group(user, group):
    utils.info(f"[ligoj] Remove user '{user}' from group '{group}' ...")
    user_response = ligoj.call_api("GET", f"service/id/user/{urllib.parse.quote(user, safe='')}", ignore_error=True)
    if user_response is None:
        raise ValueError(f"[ligoj] User '{user}' does not exist")

    user_details = user_response.json()
    if group in user_details["groups"]:
        return ligoj.call_api(
            "DELETE",
            f"service/id/user/{urllib.parse.quote(user, safe='')}/group/{urllib.parse.quote(group, safe='')}",
        )
    utils.info(f"[ligoj] User '{user}' is not in group '{group}'")
    return None


def user_delete(user):
    if not user:
        return False
    utils.info(f"[ligoj] Delete user '{user}' ...")
    user = user_get(user)
    if user is None:
        utils.info(f"[ligoj] User '{user}' does not exist")
        return None
    return ligoj.call_api("DELETE", f"service/id/user/{user['id']}")


def delegate_org_create(managed_type, managed_id, receiver_type, receiver_id, admin_privilege, write_privilege):
    utils.info(
        f"[ligoj] Create delegate to '{receiver_type}' '{receiver_id}' to manage '{managed_type}' '{managed_id}' with admin_privilege={admin_privilege} and write_privilege={write_privilege}  ..."
    )
    delegates = ligoj.call_api("GET", f"security/delegate?type={managed_type}&q={urllib.parse.quote(receiver_id, safe='')}").json()["data"]
    if any(filter(lambda x: x["receiverType"] == receiver_type and x["name"] == managed_id, delegates)):
        utils.debug(f"[ligoj] Delegate already exists for '{receiver_id}'  ...")
    else:
        ligoj.call_api(
            "POST",
            "security/delegate",
            data={
                "receiver": receiver_id,
                "receiverType": receiver_type,
                "type": managed_type,
                "name": managed_id,
                "canAdmin": admin_privilege,
                "canWrite": write_privilege,
            },
        )


def delegate_org_get_by_id(delegate_id: int):
    return ligoj.call_api("GET", f"security/delegate/{delegate_id}").json()


def delegate_org_filter_by_resource(resource_type: str, resource_id: str | None):
    items = ligoj.call_api("GET", "security/delegate", params={"type": resource_type}).json()["data"]
    return list(filter(lambda x: resource_id is None or resource_id == "" or x["name"] == resource_id, items))


def delegate_org_delete(delegate_id: int):
    ligoj.call_api("DELETE", f"security/delegate/{delegate_id}", ignore_error=True, ignore_output=True)
    return False


def ldap_concat(prefix1: str, prefix2: str, base_dn: str) -> str:
    result = base_dn
    if prefix2 is not None and prefix2 != "":
        result = f"{prefix2},{result}"
    if prefix1 is not None and prefix1 != "":
        result = f"{prefix1},{result}"
    return result


# Create the LDAP subscription if it does not exist yet
def subscription_create_id_group(project_id: int, project_key: str, ldap_node: str, group, parent_group=None):
    group_details = group_get_by_name(group)
    if group_details is not None:
        utils.info(f"[ligoj] Group '{group}' already exists, ignore subscription request to project '{project_key}'")
        return False

    utils.info(f"[ligoj] Group '{group}' does not already exist, create subscription to project '{project_key}'({project_id}) to node '{ldap_node}' ...")
    parameters = [
        {"parameter": "service:id:group", "text": group},
        {"parameter": "service:id:ou", "text": project_key},
    ]
    if parent_group is not None:
        parameters.append({"parameter": "service:id:parent-group", "text": parent_group})

    return bool(ligoj.subscription_create(project_id, ldap_node, parameters))
