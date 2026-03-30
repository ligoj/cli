#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
import difflib
import json
import os
import shutil
import time
import urllib.parse
import uuid
from typing import Any

import yaml
from yaml.loader import SafeLoader

from ligojcli.plugins import ligoj, utils

# Jenkins
JENKINS_CREDENTIALS_TYPES = {
    "org.jenkinsci.plugins.plaincredentials.impl.StringCredentialsImpl": "Secret text",
    "com.cloudbees.plugins.credentials.impl.UsernamePasswordCredentialsImpl": "Username with password",
    "com.cloudbees.jenkins.plugins.sshcredentials.impl.BasicSSHUserPrivateKey": "SSH Username with private key",
}
PLUGIN_NAME = "jenkins"
JENKINS_CREDENTIALS_SCOPE = ["GLOBAL", "SYSTEM"]
JENKINS_MAX_FOLDER_DEPTH = 4
JENKINS_ADD_GLOBAL_CREDENTIALS = True
jenkins_api_user: str | None = None
jenkins_api_token: str | None = None
jenkins_endpoint: str | None = None
jenkins_home: str | None = None
jenkins_crumb: str | None = None  # true (always), false (never), auto/None (only on not GET)


def configure(subparser_service):
    subparser_action = subparser_service.add_parser("jenkins", help="Jenkins related operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("run", help="Run a job")
    parser_action.add_argument("--job", "-j", help="Job name")
    parser_action.add_argument("--branch", "-b", help="Optional branch name", required=False)
    parser_action.add_argument("--parameters", "-p", help="Key value job parameters", nargs="*", required=False)
    parser_action.add_argument("--jenkins-crumb", "-C", help="Jenkins crumb mode; true, false, auto", default="auto")
    parser_action.add_argument("--jenkins-endpoint", "-J", help="Endpoint of Jenkins", required=False)
    parser_action.add_argument("--jenkins-api-user", help="Jenkins API user", required=False)
    parser_action.add_argument("--jenkins-api-token", help="Jenkins API token", required=False)
    parser_action.add_argument(
        "--wait", "-w", type=int, help="Wait for status is available up to given duration in seconds, -1 for unlimited, 0 for immediate return. Must be used with -parameter", default=0
    )
    parser_action.add_argument("--wait-parameter", "-W", help="Name of Jenkins parameters user to track the actual executed build. Must be used with --wait", default=0)


def execute_action(service, action,_operation, args):
    if service == "jenkins":
        if action == "run":
            parse_remote_args(args)
            return jenkins_run_job(args["job"], args.get("branch"), args.get("parameters", []), args.get("wait", 0), args.get("wait_parameter"))
    return None

# Extract from args the parameters related to remote access API of Jenkins
def parse_remote_args(args):
    global jenkins_endpoint
    global jenkins_api_user
    global jenkins_api_token
    global jenkins_crumb
    global jenkins_home
    jenkins_endpoint = utils.get_config(args, "jenkins_endpoint", "JENKINS_ENDPOINT", None)
    jenkins_api_user = utils.get_secret(args, "jenkins_api_user", "JENKINS_API_USER", None)
    jenkins_api_token = utils.get_secret(args, "jenkins_api_token", "JENKINS_API_TOKEN", None)
    jenkins_crumb = utils.get_config(args, "jenkins_crumb", "JENKINS_CRUMB", "auto")
    jenkins_home = utils.get_config(args, "jenkins_home", "JENKINS_HOME", None)


def jenkins_run_job(job_name: str, branch: str | None, parameters: list, wait: int = 0, wait_parameter: str | None = None):
    utils.info(f"[jenkins] Run job {job_name}")
    wait_parameter_value = None
    parameters_jenkins = []
    if wait_parameter and wait == 0 or not wait_parameter and wait != 0:
        raise ValueError("[jenkins] --wait-parameter and --wait must be used together")
    for parameter in parameters:
        parameter_parts = parameter.split("=")
        parameter_name = parameter_parts[0]
        parameters_jenkins.append({"name": parameter_name, "value": parameter_parts[1]})
        if parameter_name == wait_parameter:
            wait_parameter_value = parameter_parts[2]
    if not wait_parameter_value:
        wait_parameter_value = uuid.uuid4().urn
        parameters_jenkins.append({"name": wait_parameter, "value": wait_parameter_value})
    job_path = f"job/{job_name}{f'/job/{branch}' if branch else ''}"
    call_jenkins_api(
        "POST",
        f"{job_path}/build",
        params={"json": json.dumps({"parameter": parameters_jenkins, "Submit": ""}, separators=(",", ":"))},
        headers={"Content-Type": utils.MIME_URL_ENCODED},
        ignore_output=True,
    )

    if wait != 0:
        start_time = time.time()
        build_status_xml = None
        utils.info(f"[jenkins] Wait for the job finishes, watch {wait_parameter}={wait_parameter_value} ...")
        while wait == -1 or (int(time.time() - start_time) < wait):
            try:
                build_status_xml = call_jenkins_api(
                    "GET",
                    f"{job_path}/api/xml",
                    params={
                        "tree": "builds[result,actions[parameters[*]]]",
                        "xpath": f'//build/action/parameter[name="{wait_parameter}"][value="{wait_parameter_value}"]/../../result/text()',
                        "wrapper": "r",
                    },
                ).text
                if build_status_xml == "<r>SUCCESS</r>":
                    break
            except Exception as _ignore:
                pass
            if build_status_xml and build_status_xml != "<r/>":
                raise ValueError(f"[jenkins] Job '{job_name}' did not succeed: {build_status_xml}")
            utils.debug(f"[jenkins] Wait for the job finishes, watch {wait_parameter}={wait_parameter_value}, status is: {build_status_xml}")
            time.sleep(2)
        if not build_status_xml or build_status_xml == "<r/>":
            raise ValueError(f"[jenkins] Job '{job_name}' did not succeed after {wait}s")

    return False


def jenkins_create_roles(groups_by_name, definition):
    # Create global roles
    jenkins_create_roles_scope(groups_by_name, definition, "globalRoles", {}, "")

    if utils.ADD_GLOBAL_ROLES:
        # Also assign 'admin' as fail-safe access
        jenkins_create_roles_scope(
            {"admin": "jenkins-administrators"},
            {"roles": {"admin": {"permissions": ["hudson.model.Hudson.Administer"]}}},
            "globalRoles",
            {},
            "",
        )

    if JENKINS_ADD_GLOBAL_CREDENTIALS:
        jenkins_create_credentials(definition, [])

    # Create folders and related roles
    jenkins_create_folders_rec(groups_by_name, definition, {}, [], 1)

    # Update CaC file is present
    jenkins_update_cac_file()


def jenkins_delete_roles(groups_by_name, definition, with_data):
    # Delete global roles
    jenkins_delete_roles_scope(groups_by_name, definition, "globalRoles", "")

    if JENKINS_ADD_GLOBAL_CREDENTIALS and with_data:
        jenkins_delete_credentials(definition, [])

    # Create folders and related roles
    jenkins_delete_folders_rec(groups_by_name, definition, [], with_data)

    # Update CaC file is present
    jenkins_update_cac_file()


def jenkins_create_api_token(name: str, login_user: str, login_password: str) -> str:
    crumb_response = jenkins_add_crumb("POST", {}, login_user, login_password)
    return utils.call_rest_api(
        "POST",
        "jenkins",
        f"{jenkins_endpoint}/",
        "/me/descriptorByName/jenkins.security.ApiTokenProperty/generateNewToken",
        None,
        {"params": {"newTokenName": name}, "headers": crumb_response[0] | {"Content-Type": utils.MIME_URL_ENCODED}, "ignore_output": True, "session": crumb_response[1]},
    ).json()["data"]["tokenValue"]


def jenkins_find_credential(base_url: str, c_id: str):
    item_credentials = call_jenkins_api("GET", f"{base_url}/api/json", params={"tree": "credentials[*]"}, headers={"Content-Type": utils.MIME_URL_ENCODED}, ignore_output=True).json()
    return next(filter(lambda r: r["id"] == c_id, item_credentials.get("credentials", [])), None)


def jenkins_create_credentials(definition, parents):
    credentials = definition.get("credentials", [])
    if len(credentials) == 0:
        # No credentials, no lookup
        return

    utils.info(f"[jenkins] Create credentials in parents {parents} ...")
    for credential_definition in credentials:
        if len(parents) == 0:
            base_url = "/manage/credentials/store/system/domain/_"
        else:
            base_url = f"{'/'.join(list(map(lambda p: f'job/{p}', parents)))}/credentials/store/folder/domain/_"

        c_id = credential_definition.get("id", "")
        if c_id == "":
            raise ValueError("[jenkins] Missing credential id")
        description = credential_definition.get("description", "")
        stapler_class = credential_definition.get("stapler-class", "")
        if stapler_class == "":
            raise ValueError("[jenkins] Missing credential class")
        attributes = credential_definition.get("attributes", {})

        scope = credential_definition.get("scope")
        if scope is not None and scope.upper() not in JENKINS_CREDENTIALS_SCOPE:
            raise ValueError(f"[jenkins] Unsupported scope {scope}, accept only {JENKINS_CREDENTIALS_SCOPE}")

        existing_credential = jenkins_find_credential(base_url, c_id)
        target_type_name = JENKINS_CREDENTIALS_TYPES.get("stapler_class")
        updating = existing_credential is not None and (
            existing_credential.get("description", "") != description or (target_type_name is not None and target_type_name != existing_credential.get("typeName"))
        )
        if target_type_name is None and existing_credential is not None:
            utils.info(f"[jenkins] Credential class {stapler_class} cannot be mapped to a built-in typeName, change report is not supported")
        # See https://github.com/jenkinsci/credentials-plugin/blob/master/docs/user.adoc
        call_jenkins_api(
            "POST",
            f"{base_url}/createCredentials",
            params={
                "json": json.dumps(
                    {
                        "": "0",
                        "credentials": {"id": c_id, "description": description, "stapler-class": stapler_class, "$class": stapler_class} | attributes,
                    }
                    | ({} if scope is None else {"scope": scope}),
                    separators=(",", ":"),
                )
            },
            headers={"Content-Type": utils.MIME_URL_ENCODED},
            ignore_output=True,
            report=("credential", "update" if updating is None else "upsert"),
        )


def jenkins_delete_credentials(definition, parents):
    credentials = definition.get("credentials", [])
    if len(credentials) == 0:
        # No credentials, no lookup
        return

    utils.info(f"[jenkins] Delete credentials from parents {parents} ...")
    for credential_definition in credentials:
        if len(parents) == 0:
            base_url = "/manage/credentials/store/system/domain/_/"
        else:
            base_url = f"{'/'.join(list(map(lambda p: f'job/{p}', parents)))}/credentials/store/folder/domain/_"

        c_id = credential_definition.get("id", "")
        if c_id == "":
            raise ValueError("[jenkins] Missing credential id")
        scope = credential_definition.get("scope")
        if scope is not None and scope.upper() not in JENKINS_CREDENTIALS_SCOPE:
            raise ValueError(f"[jenkins] Unsupported scope {scope}, accept only {JENKINS_CREDENTIALS_SCOPE}")

        existing_credential = jenkins_find_credential(base_url, c_id)
        if existing_credential:
            # See https://github.com/jenkinsci/credentials-plugin/blob/master/docs/user.adoc
            call_jenkins_api(
                "POST",
                f"{base_url}/credential/{urllib.parse.quote(c_id, safe='')}/doDelete",
                headers={"Content-Type": utils.MIME_URL_ENCODED},
                ignore_output=True,
                report=("credential", "delete"),
            )
        else:
            utils.info(f"[jenkins] Credential '{c_id}' does not exist, ignore")


def jenkins_create_folders_rec(groups_by_name, definition, distinct_folders: dict[str, True], parents: list[str], depth: int):
    if depth > JENKINS_MAX_FOLDER_DEPTH:
        raise ValueError(f"[jenkins] Maximal supported folders depth is {JENKINS_MAX_FOLDER_DEPTH}")

    for folder_definition in definition.get("folders", []):
        folder_name = folder_definition.get("name", "")
        if folder_name == "":
            raise ValueError("[jenkins] Missing Jenkins folder name")

        if folder_name in distinct_folders:
            raise ValueError(f"[jenkins] Duplicate folder {folder_name}, must me unique")

        recursive_folder_access = folder_definition.get("recursive", True)
        distinct_folders[folder_name] = True
        folder_description = folder_definition.get("description", "Créé par le script d'initialisation")
        folder_mode = folder_definition.get("mode", "com.cloudbees.hudson.plugins.folder.Folder")
        if folder_mode != "com.cloudbees.hudson.plugins.folder.Folder" and folder_mode != "jenkins.branch.OrganizationFolder":
            utils.warn(f"[jenkins] Unmanaged folder mode '{folder_mode}', might not work as expected")

        jenkins_create_folder(folder_name, folder_mode, folder_description, parents)

        # Recursive folder creation
        parents.append(folder_name)
        jenkins_create_roles_scope(
            groups_by_name,
            folder_definition,
            "projectRoles",
            {"pattern": f'(?i){"/".join(parents)}{"(/.*)?" if recursive_folder_access else ""}'},
            f'-{"/".join(parents)}',
        )
        jenkins_create_credentials(folder_definition, parents)
        jenkins_create_folders_rec(groups_by_name, folder_definition, distinct_folders, parents, depth + 1)
        parents.pop()


def jenkins_delete_folders_rec(groups_by_name, definition, parents: list[str], with_data: bool):
    for folder_definition in definition.get("folders", []):
        folder_name = folder_definition.get("name", "")
        if folder_name == "":
            raise ValueError("[jenkins] Missing Jenkins folder name")

        # Recursive folder creation
        parents.append(folder_name)
        jenkins_delete_roles_scope(
            groups_by_name,
            folder_definition,
            "projectRoles",
            f'-{"/".join(parents)}',
        )
        jenkins_delete_folders_rec(groups_by_name, folder_definition, parents, with_data)
        if with_data:
            jenkins_delete_folder_and_credentials(folder_definition, folder_name, parents)
        parents.pop()


def jenkins_create_roles_scope(groups_by_name, definition, role_type, additional_params, role_suffix: str):
    utils.info(f"[jenkins] Create roles in scope {role_type} with '{role_suffix}' suffix...")
    for jenkins_group in definition.get("roles", {}).keys():
        ldap_group = ligoj.get_ldap_group("jenkins", groups_by_name, jenkins_group)
        role_definition = definition["roles"][jenkins_group]
        permissions = role_definition.get("permissions", [])
        if len(permissions) == 0:
            raise ValueError(f"[jenkins] Missing Jenkins permissions in role [{role_type}]'{jenkins_group}'")
        role = f"{ldap_group}{role_suffix}"
        role_item = jenkins_create_role(role, permissions, role_type, additional_params)

        # Role mapping
        jenkins_assign_role(role_item, role, role_type, ldap_group)


def jenkins_delete_roles_scope(groups_by_name, definition, role_type, role_suffix: str):
    utils.info(f"[jenkins] Delete roles in scope {role_type} with '{role_suffix}' suffix...")
    for jenkins_group in definition.get("roles", {}).keys():
        ldap_group = ligoj.get_ldap_group("jenkins", groups_by_name, jenkins_group)
        role = f"{ldap_group}{role_suffix}"
        role_item = jenkins_get_role(role, role_type)
        if role_item:
            jenkins_unassign_role(role_item, role, role_type, ldap_group)
            jenkins_delete_role(role, role_type)


def jenkins_assign_role(role_item, role: str, role_type: str, ldap_group: str):
    utils.info(f"[jenkins] Assign role {role} to group {ldap_group} ...")
    if next(filter(lambda sid: sid == ldap_group or (sid.get("type") == "GROUP" and sid.get("sid") == ldap_group), role_item.get("sids", [])), None):
        # Already assigned
        utils.debug(f"[jenkins] {role} is already assigned to group {ldap_group}, ignore")
    else:
        call_jenkins_api(
            "POST",
            "role-strategy/strategy/assignGroupRole",
            params={"type": role_type, "roleName": role, "group": ldap_group},
            headers={"Content-Type": utils.MIME_URL_ENCODED},
            report=("role", "assign"),
        )


def jenkins_unassign_role(role_item, role: str, role_type: str, ldap_group: str):
    utils.info(f"[jenkins] Unassign role {role} from group {ldap_group} ...")
    if next(filter(lambda sid: sid == ldap_group or (sid.get("type") == "GROUP" and sid.get("sid") == ldap_group), role_item.get("sids", [])), None):
        call_jenkins_api("POST", "role-strategy/strategy/unassignGroupRole", params={"type": role_type, "roleName": role, "group": ldap_group}, headers={"Content-Type": utils.MIME_URL_ENCODED})
    else:
        # Already unassigned
        utils.debug(f"[jenkins] {role} is already unassigned from group {ldap_group}, ignore")


def jenkins_get_folder(folder):
    # Get items with depth = 4
    items = call_jenkins_api(
        "GET",
        "api/json",
        params={"tree": f'jobs{"[name,description,jobs"*JENKINS_MAX_FOLDER_DEPTH}{"]"*JENKINS_MAX_FOLDER_DEPTH}'},
        headers={"Content-Type": utils.MIME_URL_ENCODED},
    ).json()
    return find_job(items, folder)


def find_job(items, folder):
    for item in items["jobs"]:
        if item["_class"] == "com.cloudbees.hudson.plugins.folder.Folder" or item["_class"] == "jenkins.branch.OrganizationFolder":
            if item["name"] == folder:
                return item
            result = find_job(item, folder)
            if result is not None:
                return result
    # Not found
    return None


def jenkins_create_folder(name, mode, description, parents):
    utils.info(f"[jenkins] Create folder '{name}' in parents {parents} ...")
    existing_folder = jenkins_get_folder(name)
    if existing_folder is None:
        if len(parents) == 0:
            create_url = "createItem"
        else:
            create_url = f"{'/'.join(list(map(lambda p: f'job/{p}', parents)))}/createItem"
        call_jenkins_api(
            "POST",
            create_url,
            params={
                "name": name,
                "mode": mode,
            },
            headers={"Content-Type": utils.MIME_URL_ENCODED},
            ignore_output=True,
            report=("folder", "create"),
        )
    else:
        utils.info(f"[jenkins] Folder '{name}' already exists")

    # Update description as needed
    job_url = f"{'/'.join(list(map(lambda p: f'job/{p}', parents)))}/job/{name}"
    if description is not None and description != "":
        utils.info(f"[jenkins] Update description of folder '{name}' ...")
        call_jenkins_api(
            "POST",
            f"{job_url}/submitDescription",
            params={"description": description},
            headers={"Content-Type": utils.MIME_URL_ENCODED},
            ignore_output=True,
        )


def jenkins_delete_folder_and_credentials(folder_definition, name, parents):
    utils.info(f"[jenkins] Delete folder '{name}' from parents {parents} ...")
    existing_folder = jenkins_get_folder(name)
    if existing_folder:
        jenkins_delete_credentials(folder_definition, parents)
        if len(parents) == 0:
            delete_url = ""
        else:
            delete_url = f"{'/'.join(list(map(lambda p: f'job/{p}', parents)))}"
        call_jenkins_api(
            "POST",
            f"{delete_url}/doDelete",
            headers={"Content-Type": utils.MIME_URL_ENCODED},
            ignore_output=True,
            report=("folder", "create"),
        )
    else:
        utils.info(f"[jenkins] Folder '{name}' does not exist, ignore")


def jenkins_get_role(role_name, role_type):
    item = call_jenkins_api("GET", "role-strategy/strategy/getRole", params={"type": role_type, "roleName": role_name}).json()
    return None if len(item.keys()) == 0 else item


def jenkins_create_role(role_name, permission_ids, role_type, additional_params):
    utils.info(f"[jenkins] Create role [{role_type}]'{role_name}' ...")

    # Check the role exists
    role_item = jenkins_get_role(role_name, role_type)
    role_exists = role_item is not None
    if role_exists:
        permission_ids.sort()
        permissions_item = list(role_item.get("permissionIds", []).keys())
        permissions_item.sort()

        if permission_ids == permissions_item and next(filter(lambda p: additional_params[p] != role_item.get(p), additional_params.keys()), None) is None:
            utils.debug(f"[jenkins] Role [{role_type}]'{role_name}' already exists with the same permissions and pattern, ignore")
            return role_item
        utils.debug(f"[jenkins] Update role [{role_type}]'{role_name}' having different permissions/pattern ...")

    # Update or create the role
    permission_ids_as_string = ",".join(permission_ids)
    call_jenkins_api(
        "POST",
        "role-strategy/strategy/addRole",
        params={"type": role_type, "roleName": role_name, "permissionIds": permission_ids_as_string, "overwrite": "true"} | additional_params,
        headers={"Content-Type": utils.MIME_URL_ENCODED},
        report=("role", "update" if role_exists else "create"),
    )
    return {"permissionIds": permission_ids, "sids": []}


def jenkins_delete_role(role_name, role_type):
    utils.info(f"[jenkins] Delete role [{role_type}]'{role_name}' ...")

    # Check the role exists
    role_item = jenkins_get_role(role_name, role_type)
    role_exists = role_item is not None
    if role_exists:
        call_jenkins_api(
            "POST",
            "role-strategy/strategy/removeRoles",
            params={"type": role_type, "roleNames": role_name},
            headers={"Content-Type": utils.MIME_URL_ENCODED},
        )
    return role_item


def jenkins_update_cac_file():
    local_jenkins_home = jenkins_home if jenkins_home is not None and jenkins_home != "" else os.environ.get("JENKINS_HOME", f"{os.environ.get('HOME', '.')}/.jenkins")
    jenkins_file = utils.get_config({}, "jenkins_casc_file", "JENKINS_CASC_FILE", utils.get_config({}, "casc_jenkins_config", "CASC_JENKINS_CONFIG", f"{local_jenkins_home}/jenkins.yaml"))
    if not os.path.exists(jenkins_file):
        utils.warn(f"[jenkins] No CaC file '{jenkins_file}' found, ignore CaC update")
        return

    utils.info(f"[jenkins] Export CaC file {jenkins_file}")
    in_memory_cac_plain = call_jenkins_api("POST", "manage/configuration-as-code/export", ignore_output=True, params={"export": ""}).text
    in_memory_cac_nb_lines = in_memory_cac_plain.count("\n")
    utils.info(f"[jenkins] In-memory CaC file: {in_memory_cac_nb_lines} lines")
    in_memory_cac = yaml.load(in_memory_cac_plain, Loader=SafeLoader)
    with open(jenkins_file, "r", -1, "UTF-8") as f:
        original_cac = yaml.load(f, Loader=SafeLoader)
    original_cac_plain = yaml.dump(original_cac, sort_keys=False, default_flow_style=False)

    with open(jenkins_file, "r", -1, "UTF-8") as f:
        merged_cac = yaml.load(f, Loader=SafeLoader)
    try:
        merged_cac["jenkins"]["authorizationStrategy"]["roleBased"]["roles"] = in_memory_cac["jenkins"]["authorizationStrategy"]["roleBased"]["roles"]
    except KeyError as ke:
        utils.warn(f"[jenkins] CaC file does not contain role based plugin section, ignore CaC update: {str(ke)}")
        return
    except BaseException as err:
        raise ValueError(f"[jenkins] Unknown error while updating CaC file: {str(err)}") from err

    merged_cac_plain = yaml.dump(merged_cac, sort_keys=False, default_flow_style=False)
    cac_differences = difflib.unified_diff(
        list(map(lambda l: f"{l}\n", original_cac_plain.split("\n"))),
        list(map(lambda l: f"{l}\n", merged_cac_plain.split("\n"))),
        fromfile="Current",
        tofile="New",
        lineterm="",
        fromfiledate="",
        tofiledate="",
    )
    at_least_one_diff = False
    for cac_diff_line in cac_differences:
        if not at_least_one_diff:
            at_least_one_diff = True
            utils.debug("[jenkins] Found IaC differences, update YAML file is required")
        line_no_nl = cac_diff_line.replace("\n", "")
        utils.debug(f"[jenkins] {line_no_nl}")

    with open(f"{jenkins_file}.merged.tst", "w", -1, "UTF-8") as f:
        yaml.dump(merged_cac, f, sort_keys=False, default_flow_style=False)
    with open(f"{jenkins_file}.original.tst", "w", -1, "UTF-8") as f:
        yaml.dump(in_memory_cac, f, sort_keys=False, default_flow_style=False)

    if not at_least_one_diff:
        utils.debug("[jenkins] No difference found in CaC file, ignore CaC update")
        return

    jenkins_file_backup = f"{jenkins_file}.ligoj"
    utils.info(f"[jenkins] Backup CaC file to {jenkins_file_backup}")
    try:
        shutil.copy2(jenkins_file, jenkins_file_backup)
    except BaseException as err:
        raise ValueError(f"[jenkins] Unable to backup configuration file '{jenkins_file}' to '{jenkins_file_backup}'{str(err)}") from err

    utils.info(f"[jenkins] Write updated CaC file to {jenkins_file}")
    with open(jenkins_file, "w", -1, "UTF-8") as f:
        yaml.dump(merged_cac, f, sort_keys=False, default_flow_style=False)


def jenkins_add_crumb(method: str, headers: dict[str, str], user: str | None = None, password: str | None = None) -> tuple[dict[str, str], Any | None]:
    if jenkins_crumb == "true" or (jenkins_crumb == "auto" and method != "GET"):
        kwargs = {"params": {"xpath": 'concat(//crumbRequestField,":",//crumb)'}}
        crumb = utils.call_rest_api(
            "GET",
            "jenkins",
            f"{jenkins_endpoint}/",
            "crumbIssuer/api/xml",
            (user or jenkins_api_user, password or jenkins_api_token),
            kwargs,
        ).text
        crumb = crumb.split(":")[1]
        headers["Jenkins-Crumb"] = crumb
        return (headers, kwargs["session"])
    return (headers, None)


def call_jenkins_api(method, url, **kwargs):
    crumb_response = jenkins_add_crumb(method, kwargs.get("headers", {}))
    kwargs["headers"] = crumb_response[0]
    kwargs["session"] = crumb_response[1]
    return utils.call_rest_api(method, "jenkins", f"{jenkins_endpoint}/", url, (jenkins_api_user, jenkins_api_token), kwargs)


def welcome_user(node_base_id, ligoj_user_reader, ligoj_user_reader_password):
    global jenkins_api_token
    global jenkins_api_user
    node_id = f"service:build:jenkins:{node_base_id}"
    node_name = f"Jenkins {node_base_id}"
    node = None
    utils.info(f"[ligoj] Create node '{node_id}', endpoint='{jenkins_endpoint}', name='{node_name}'")
    if not ligoj_user_reader_password and (not jenkins_api_token or not jenkins_api_user):
        node = ligoj.node_get_by_id(node_id, "ALL", "map", True)
        if not node:
            raise ValueError("[ligoj] No available user reader password, regenerate it with '--reset-reader-password' or provide '--jenkins-api-token', cannot update/create Jenkins like from Ligoj")
    if node:
        jenkins_api_user = node["parameters"]["service:build:jenkins:user"]
        jenkins_api_token = node["parameters"]["service:build:jenkins:api-token"]
    elif not jenkins_api_token or not jenkins_api_user:
        jenkins_api_user = ligoj_user_reader
        jenkins_api_token = jenkins_create_api_token("ligoj", ligoj_user_reader, ligoj_user_reader_password)
    ligoj.node_upsert(node_id, node_name, {"service:build:jenkins:url": jenkins_endpoint, "service:build:jenkins:user": ligoj_user_reader, "service:build:jenkins:api-token": jenkins_api_token})
