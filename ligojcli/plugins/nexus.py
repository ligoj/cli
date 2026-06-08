#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
import urllib.parse

from ligojcli.plugins import ligoj, utils

PLUGIN_NAME = "nexus"
nexus_endpoint: str | None = None
nexus_user: str | None = None
nexus_password: str | None = None


def configure(subparser_service):
    subparser_action = subparser_service.add_parser(
        "nexus", help="Nexus operations"
    ).add_subparsers(title="action", help="Action", dest="action")
    subparser_service2 = subparser_action.add_parser(
        "repository", help="Nexus repository operations"
    ).add_subparsers(title="sub-action", help="Sub Action", dest="sub_action")
    parser_action = subparser_service2.add_parser("get", help="Get a Nexus repository")
    parser_action.add_argument("--id", "-i", help="Repository id", required=True)
    parser_action.add_argument("--format", "-f", help="Repository format", required=True)
    parser_action.add_argument("--mode", "-m", help="Repository mode", required=True)
    parser_action = subparser_service2.add_parser("delete", help="Delete a Nexus repository")
    parser_action.add_argument("--id", "-i", help="Repository id", required=True)
    parser_action.add_argument("--format", "-f", help="Repository format", required=True)
    parser_action.add_argument("--mode", "-m", help="Repository mode", required=True)
    subparser_service2 = subparser_action.add_parser(
        "role", help="Nexus role operations"
    ).add_subparsers(title="sub-action", help="Sub Action", dest="sub_action")
    parser_action = subparser_service2.add_parser("get", help="Get a Nexus role")
    parser_action.add_argument("--id", "-i", help="Role id", required=True)
    parser_action = subparser_service2.add_parser("delete", help="Delete a Nexus role")
    parser_action.add_argument("--id", "-i", help="Role id", required=True)


def execute_action(service, action, operation, args):
    parse_remote_args(args)
    if args["action"] == "repository":
        nexus_repository_action(args)
    elif args["action"] == "role":
        nexus_role_action(args)


def nexus_repository_action(args):
    if args["sub_action"] == "get":
        nexus_get_repository(args["id"], args["format"], args["mode"])
    elif args["sub_action"] == "delete":
        nexus_delete_repository(args["id"], args["format"], args["mode"])


def nexus_role_action(args):
    if args["sub_action"] == "get":
        nexus_get_role(args["id"])
    elif args["sub_action"] == "delete":
        nexus_delete_role(args["id"])


# Extract from args the parameters related to remote access API of Nexus
def parse_remote_args(args):
    global nexus_endpoint
    global nexus_user
    global nexus_password
    nexus_endpoint = utils.get_config(args, "nexus_endpoint", "NEXUS_ENDPOINT", None)
    nexus_user = utils.get_secret(args, "nexus_user", "NEXUS_USER", "admin")
    nexus_password = utils.get_secret(args, "nexus_password", "NEXUS_PASSWORD", None)


def call_nexus_api(method, url, **kwargs):
    response = utils.call_rest_api(
        method, "nexus", f"{nexus_endpoint}/service/", url, (nexus_user, nexus_password), kwargs
    )
    errors = None
    try:
        if response is not None and not isinstance(response, str) and "result" in response.json():
            result = response.json()["result"]
            if "success" in result and result["success"] is False and "errors" in result:
                errors = result["errors"]
    except BaseException as err:
        utils.debug(f"[nexus] Not JSON response, {str(err)}")

    if errors is not None:
        raise ValueError(f"[nexus] API call {method} {url} failed: {errors}")

    return response


def nexus_create_roles(groups_by_name, definition):
    utils.info("[nexus] Create Nexus roles ...")
    for repository in definition.get("repositories", []):
        # Create the repository as needed, including optional provided attributes
        repository_id = repository.get("id", "")
        repository_format = repository.get("format", "")
        if repository_id == "":
            raise ValueError("[nexus] Missing nexus repository id")
        if repository_format == "":
            raise ValueError(
                f"[nexus] Missing nexus repository format in repository {repository_id}"
            )

        repository_mode = repository.get("mode", "hosted")
        if repository_format == "maven2" or repository_format == "maven":
            repository_format = "maven2"
            attributes = {
                "name": repository_id,
                "online": True,
                "storage": {
                    "blobStoreName": "default",
                    "strictContentTypeValidation": True,
                    "writePolicy": "allow_once",
                },
                "cleanup": {"policyNames": []},
                "component": {"proprietaryComponents": False},
                "maven": {
                    "versionPolicy": "RELEASE",
                    "layoutPolicy": "STRICT",
                    "contentDisposition": "INLINE",
                },
            }
        elif repository_format == "docker":
            attributes = {
                "name": repository_id,
                "online": True,
                "storage": {
                    "blobStoreName": "default",
                    "strictContentTypeValidation": True,
                    "writePolicy": "ALLOW",
                    "latestPolicy": False,
                },
                "cleanup": {"policyNames": []},
                "component": {"proprietaryComponents": False},
                "docker": {"forceBasicAuth": True, "v1Enabled": False},
            }
        else:
            raise ValueError(
                f"[nexus] Unsupported format {repository_format} in repository {repository_id}"
            )

        nexus_create_repository(
            repository_id,
            repository_format,
            repository_mode,
            attributes | repository.get("attributes", {}),
        )
        # Create/update the related roles
        for nexus_group in repository.get("roles", {}).keys():
            ldap_group = ligoj.get_ldap_group("nexus", groups_by_name, nexus_group)
            role_definition = repository["roles"][nexus_group]
            nexus_create_role(ldap_group)
            nexus_set_permissions(ldap_group, repository_id, repository_format, role_definition)

    if utils.ADD_GLOBAL_ROLES:
        # Also add Nexus global admin role
        nexus_create_role("nexus-administrators")
        call_nexus_api(
            "PUT",
            "rest/v1/security/roles/nexus-administrators",
            data={
                "id": "nexus-administrators",
                "source": "default",
                "name": "nexus-administrators",
                "description": "Permissions pour le groupe nexus-administrators",
                "readOnly": False,
                "privileges": ["nx-all"],
                "roles": [],
            },
        )


def nexus_delete_roles(groups_by_name, definition, with_data):
    utils.info("[nexus] Delete Nexus roles ...")
    for repository in definition.get("repositories", []):
        # Create the repository as needed, including optional provided attributes
        repository_id = repository.get("id", "")
        repository_format = repository.get("format", "")
        if repository_id == "":
            raise ValueError("[nexus] Missing nexus repository id")
        if repository_format == "":
            raise ValueError(
                f"[nexus] Missing nexus repository format in repository {repository_id}"
            )

        repository_mode = repository.get("mode", "hosted")
        if repository_format == "maven2" or repository_format == "maven":
            repository_format = "maven2"
        elif repository_format != "docker":
            raise ValueError(
                f"[nexus] Unsupported format {repository_format} in repository {repository_id}"
            )

        # Create/update the related roles
        for nexus_group in repository.get("roles", {}).keys():
            ldap_group = ligoj.get_ldap_group("nexus", groups_by_name, nexus_group)
            nexus_delete_role(ldap_group)

        if with_data:
            nexus_delete_repository(repository_id, repository_format, repository_mode)


def nexus_get_repository(repository_id, repository_format, repository_mode):
    internal_format = "maven" if repository_format == "maven2" else repository_format
    utils.info(f"[nexus] Fetch repository {repository_id}[{internal_format}] ...")
    response = call_nexus_api(
        "GET",
        f"rest/v1/repositories/{internal_format}/{repository_mode}/{repository_id}",
        ignore_error=True,
    )
    if response:
        return response.json()
    return None


def nexus_create_repository(repository_id, repository_format, repository_mode, data):
    internal_format = "maven" if repository_format == "maven2" else repository_format
    utils.info(
        f"[nexus] Create repository {repository_id}[{internal_format}] with data '{data}' ..."
    )
    details = nexus_get_repository(repository_id, internal_format, repository_mode)
    if details is None:
        call_nexus_api(
            "POST", f"rest/v1/repositories/{internal_format}/{repository_mode}", data=data
        )
    else:
        utils.debug(f"[nexus] Repository {repository_id}[{internal_format}] already exists")


def nexus_delete_repository(repository_id, repository_format, repository_mode):
    internal_format = "maven" if repository_format == "maven2" else repository_format
    details = nexus_get_repository(repository_id, internal_format, repository_mode)
    if details is None:
        utils.debug(f"[nexus] Repository {repository_id} does not exist, ignore")
    else:
        utils.info(f"[nexus] Delete repository {repository_id} ...")
        call_nexus_api("DELETE", f"rest/v1/repositories/{repository_id}")


def nexus_get_role(group):
    utils.info(f"[nexus] Fetch role associated to group '{group}' ...")
    items = call_nexus_api("GET", "rest/v1/security/roles", params={"source": "default"}).json()
    return next(filter(lambda x: x["id"] == group, items), None)


def nexus_create_role(group):
    utils.info(f"[nexus] Create role for group '{group}' ...")
    details = nexus_get_role(group)
    if details is None:
        call_nexus_api(
            "POST",
            "rest/v1/security/roles",
            data={
                "id": group,
                "source": "default",
                "name": group,
                "description": "",
                "readOnly": False,
                "privileges": [],
                "roles": [],
            },
        )
    else:
        utils.debug(f"[nexus] Role {group} already exists ...")


def nexus_delete_role(group):
    utils.info(f"[nexus] Delete role for group '{group}' ...")
    details = nexus_get_role(group)
    if details is None:
        utils.debug(f"[nexus] Role {group} does not exist, ignore")
    else:
        call_nexus_api("DELETE", f"rest/v1/security/roles/{group}")


def nexus_set_permissions(group, repository_id, repository_format, permissions):
    utils.info(
        f"[nexus] Assign permissions on {repository_id}[{repository_format}] to '{group}' with {permissions} ..."
    )
    privileges = []
    for permission in permissions.get("admin-permissions", []):
        privileges.append(f"nx-repository-admin-{repository_format}-{repository_id}-{permission}")

    for permission in permissions.get("view-permissions", []):
        privileges.append(f"nx-repository-view-{repository_format}-{repository_id}-{permission}")

    call_nexus_api(
        "PUT",
        f"rest/v1/security/roles/{urllib.parse.quote(group, safe='')}",
        data={
            "id": group,
            "source": "default",
            "name": group,
            "description": f"Permissions pour le groupe {group}",
            "readOnly": False,
            "privileges": privileges,
            "roles": [],
        },
    )
