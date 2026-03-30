#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
import re
import json
import time
import itertools
from typing import Any
import urllib.parse
from unidecode import unidecode
import pytimeparse
from datetime import datetime, timedelta
from ligojcli.plugins import utils

PLUGIN_NAME = "ligoj"
DEFAULT_LIGOJ_API_USER = "ligoj-admin"
DEFAULT_LIGOJ_ENDPOINT = "http://localhost:8080/ligoj"
DEFAULT_PARENT_GROUP_SUFFIX = "-team"
DEFAULT_LDAP_OU_TECHNICAL_USERS = "technical-users"
DEFAULT_LDAP_OU_EXTERNAL_USERS = "external"
LIGOJ_SYSTEM_ROLE_PATH = "system/security/role"
ligoj_endpoint: str | None = None
ligoj_api_key: str | None = None
ligoj_api_user: str | None = None
ligoj_api_run_as_user: str | None = None


def configure(subparser_service):

    # info
    subparser_action = subparser_service.add_parser("info", help="Server information").add_subparsers(title="action", help="Action", dest="action")
    subparser_action.add_parser("version", help="Server version")
    subparser_action.add_parser("all", help="Server information")
    parser_action = subparser_action.add_parser("status", help="Server status")
    parser_action.add_argument("--wait", "-w", type=int, help="Wait for status is available  up to given duration in seconds, -1 for unlimited, 0 for immediate return", default=0)
    parser_action = subparser_action.add_parser("api", help="API information")
    parser_action.add_argument("--output", "-o", choices=["openapi", "wadl", "swagger"], help="API Format", default="openapi")
    parser_action.add_argument("--print", "-p", choices=["content", "url"], help="Content display", default="content")

    # user
    subparser_action = subparser_service.add_parser("user", help="System user operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("get", help="Return system user information")
    parser_action.add_argument("--id", "-i", help="User id/login")
    parser_action = subparser_action.add_parser("reset-password", help="Reset user password")
    parser_action.add_argument("--id", "-i", help="User id/login. By default, the current user")
    parser_action = subparser_action.add_parser("delete", help="Delete a system user")
    parser_action.add_argument("--id", "-i", help="User id/login")
    parser_action = subparser_action.add_parser("list", help="Return system users")
    parser_action.add_argument("--with-roles", "-r", help="Also return user roles", action="store_true")
    parser_action = subparser_action.add_parser("upsert", help="Create or update a system user")
    parser_action.add_argument("--id", "-i", help="User id")
    parser_action.add_argument("--roles", "-r", help="Roles names or identifier", nargs="*", default=[])
    parser_action.add_argument("--api_key_name", "-k", help="Create and return an API key with the given name", required=False)

    # session
    subparser_action = subparser_service.add_parser("session", help="Session operations").add_subparsers(title="action", help="Action", dest="action")
    subparser_action.add_parser("get", help="Return session details")
    subparser_action.add_parser("logout", help="Remove session data")
    subparser_action.add_parser("whoami", help="Return current user identifier")
    parser_action = subparser_action.add_parser("login", help="Validate credentials and return session")
    parser_action.add_argument("--password", "-p", help="User password for login authentication. Only returned cookies are saved in home", required=False, default="")

    # token
    subparser_action = subparser_service.add_parser("token", help="API token operations").add_subparsers(title="action", help="Action", dest="action")
    subparser_action.add_parser("list", help="List token of current user")
    parser_action = subparser_action.add_parser("get", help="Return a token value")
    parser_action.add_argument("--id", "-i", help="Token name", required=False, default="")
    parser_action = subparser_action.add_parser("create", help="Generate a new token")
    parser_action.add_argument("--id", "-i", help="Token name", required=False, default="")
    parser_action.add_argument("--expiration", "-e", help="Token expiration date or duration (e.g. 1d, 2w, 3m, 4y)", required=False, default="")
    parser_action.add_argument("--save", "-s", help="When set, token is instead output in credentials file", default=False, action="store_true")
    parser_action = subparser_action.add_parser("delete", help="Delete a token")
    parser_action.add_argument("--id", "-i", help="Token name", required=False, default="")
    parser_action = subparser_action.add_parser("purge", help="Purge all expired tokens of principal user")
    parser_action = subparser_action.add_parser("purge-all", help="Purge all expired tokens. Only available for administrators")

    # role
    subparser_action = subparser_service.add_parser("role", help="System role operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("get", help="Return system role information")
    parser_action.add_argument("--id", "-i", help="Role id. Exclusive with --name", required=False)
    parser_action.add_argument("--name", "-n", help="Role name. Exclusive with --id", required=False)
    subparser_action.add_parser("list", help="Return system roles")
    parser_action = subparser_action.add_parser("create", help="Create system role")
    parser_action.add_argument("--id", "-i", help="[deprecated, use '--name'] Role name", required=False)
    parser_action.add_argument("--name", "-n", help="Role name", required=False)
    parser_action.add_argument("--api", help="API patterns", nargs="*", default=[])
    parser_action.add_argument("--ui", help="UI patterns", nargs="*", default=[])
    parser_action = subparser_action.add_parser("delete", help="Delete a role")
    parser_action.add_argument("--id", "-i", help="Role id. Exclusive with --name", required=False)
    parser_action.add_argument("--name", "-n", help="Role name. Exclusive with --id", required=False)

    # plugin
    subparser_action = subparser_service.add_parser("plugin", help="Plugins operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("list", help="List installed plugin")
    parser_action = subparser_action.add_parser("install", help="Install plugin")
    parser_action.add_argument("--id", "-i", help="Maven artifact-id of the plugin")
    parser_action.add_argument("--version", "-v", help="Maven artifact-id of the plugin. 'LATEST' to check the repository.", required=False)
    parser_action.add_argument("--repository", "-r", help="Maven repository manager such as 'central' and 'nexus'.", default="central")
    parser_action.add_argument("--javadoc", "-j", help="Install Javadoc with this plugin for OpenAPI completeness", action="store_true", default=False)
    parser_action.add_argument("--force", help="Force reinstallation of the plugin", action="store_true", default=False)
    parser_action = subparser_action.add_parser("upload", help="Install plugin")
    parser_action.add_argument("--id", "-i", help="Maven artifact-id of the plugin")
    parser_action.add_argument("--version", "-v", help="Maven artifact-id of the plugin. 'LATEST' to check the repository")
    parser_action.add_argument("--from", "-f", help="Plugin jar URL or local file name")
    parser_action.add_argument("--force", help="Force reinstallation of the plugin", action="store_true", default=False)
    parser_action = subparser_action.add_parser("javadoc", help="Install Javadoc of all plugins and built-in endpoints")
    parser_action.add_argument("--repository", "-r", help="Maven repository manager such as 'central' and 'nexus'.", default="central")
    parser_action = subparser_action.add_parser("restart", help="Restart remote API server")
    parser_action.add_argument("--wait", "-w", type=int, help="Wait for the status is available up to given duration in seconds, -1 for unlimited, 0 for immediate return", default=0)

    # node
    subparser_action = subparser_service.add_parser("node", help="Node operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("get", help="Return node information")
    parser_action.add_argument("--id", "-i", help="Node identifier")
    parser_action.add_argument("--parameters-mode", "-m", choices=["all", "create", "link", "none"], help="Retrieve parameters options. By default, no parameters are returned", default="none")
    parser_action.add_argument("--parameters-output", "-c", choices=["full", "list", "map"], default="list", help="Parameter output mode and structure")
    parser_action.add_argument("--parameters-secured", "-s", action="store_true", help="Return secured parameter values", default=False)
    parser_action = subparser_action.add_parser("list", help="Return nodes filtered by criteria")
    parser_action.add_argument("--mode", "-M", help="Filtered node's mode", choices=["all", "create", "link"], required=False)
    parser_action.add_argument("--search", "-S", help="Filtered node's name (contains)", required=False)
    parser_action.add_argument("--depth", "-D", help="Refinement depth. 0 is the top level. -1 for any depths", type=int, default=-1)
    parser_action.add_argument("--refined", "-R", help="Filtered node's parent id", required=False)
    parser_action.add_argument("--parameters-mode", "-m", choices=["all", "create", "link", "none"], help="Retrieve parameters options. By default, no parameters are returned", default="none")
    parser_action.add_argument("--parameters-output", "-c", choices=["full", "list", "map"], default="list", help="Parameter output mode and structure")
    parser_action.add_argument("--parameters-secured", "-s", action="store_true", help="Return secured parameter values", default=False)
    parser_action = subparser_action.add_parser("status", help="Return node information")
    parser_action.add_argument("--id", "-i", help="Node identifier")
    parser_action = subparser_action.add_parser("create", help="Create or update new node")
    parser_action.add_argument("--id", "-i", help="[deprecated, use 'upsert'] Node identifier. Related plugin must be previously installed")
    parser_action.add_argument("--name", "-n", help="Node name")
    parser_action.add_argument("--from", "-f", help="Parameters JSON URL or local file name")
    parser_action = subparser_action.add_parser("upsert", help="Create or update new node")
    parser_action.add_argument("--id", "-i", help="Node identifier. Related plugin must be previously installed")
    parser_action.add_argument("--name", "-n", help="Node name")
    parser_action.add_argument("--from", "-f", help="Parameters JSON URL or local file name")
    parser_action = subparser_action.add_parser("delete", help="Delete a new node")
    parser_action.add_argument("--id", "-i", help="Node identifier", required=False)

    # subscription
    subparser_action = subparser_service.add_parser("subscription", help="Subscription operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("get", help="Return subscription information")
    parser_action.add_argument("--id", "-i", help="Subscription identifier", type=int)
    parser_action.add_argument("--details", "-d", help="When set more details are returned", action="store_true")
    parser_action = subparser_action.add_parser("list", help="Return subscriptions filtered by criteria")
    parser_action.add_argument("--node", "-n", help="Node identifier, ie. `service:id:ldap:remote1`", required=False)
    parser_action.add_argument("--tool", "-t", help="Tool identifier, ie. `service:id:ldap`", required=False)
    parser_action.add_argument("--service", "-s", dest="service_id", help="Ligoj service identifier, ie. `service:id`", required=False)
    parser_action.add_argument("--project", "-p", help="Project key or identifier", required=False)
    parser_action = subparser_action.add_parser("create", help="Create a subscription")
    parser_action.add_argument("--node", "-n", help="Node identifier, ie. `service:id:ldap:remote1`", required=False)
    parser_action.add_argument("--project", "-p", help="Project key or identifier", required=False)
    parser_action.add_argument("--from", "-f", help="Parameters JSON URL or local file name")
    parser_action = subparser_action.add_parser("delete", help="Delete by its identifier")
    parser_action.add_argument("--id", "-i", help="Subscription identifier")
    parser_action.add_argument("--with-data", "-d", help="When set, remote data created by the subscription is also deleted", action="store_true")
    parser_action = subparser_action.add_parser("status", help="Retrieve last status")
    parser_action.add_argument("--project", "-p", help="Project key or identifier")
    parser_action = subparser_action.add_parser("refresh", help="Refresh status and validate link")
    parser_action.add_argument("--id", "-i", help="Subscription identifier to refresh", required=False)

    # project
    subparser_action = subparser_service.add_parser("project", help="Project operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("get", help="Return project information")
    parser_action.add_argument("--id", "-i", help="Project key or identifier")
    parser_action = subparser_action.add_parser("list", help="List projects")
    parser_action.add_argument("--search", "-s", help="Filtered project's name, description or pkey (contains)", required=False)
    parser_action = subparser_action.add_parser("delete", help="Delete both the project and its associated subscriptions")
    parser_action.add_argument("--id", "-i", help="Project key or identifier")
    parser_action.add_argument("--with-data", "-w", help="When activated, subscriptions are deleted along with data they have generated", action="store_true", default=False)
    parser_action = subparser_action.add_parser("create", help="Create a new project")
    parser_action.add_argument("--team-leader", "-t", help="Assigned team leader, by default, the current API user", required=False)
    parser_action.add_argument("--pkey", "-k", help="Name")
    parser_action.add_argument("--name", "-n", help="Key. By default, is the project's name", required=False)
    parser_action.add_argument("--description", "-d", help="Description.", default="")
    parser_action.add_argument("--context", "-c", help="Context data for this entity", required=False)

    # delegate node
    subparser_action = subparser_service.add_parser("delegate-node", help="Delegate node operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("list", help="List delegates")
    parser_action.add_argument("--node", "-n", help="Node identifier to filter", required=False)
    parser_action = subparser_action.add_parser("get", help="Return delegate node information")
    parser_action.add_argument("--id", "-i", help="Delegate node identifier", type=int)
    parser_action = subparser_action.add_parser("create", help="Create a new delegate node")
    parser_action.add_argument("--node", "-n", help="Node identifier to delegate", required=False)
    parser_action.add_argument("--can-subscribe", "-S", help="Can create subscription related to this node", action="store_true", default=False)
    parser_action.add_argument("--can-write", "-W", help="Can update this node", action="store_true", default=False)
    parser_action.add_argument("--can-admin", "-A", help="Can share this delegate", action="store_true", default=False)
    parser_action.add_argument("--receiver", "-R", help="Receiver identifier")
    parser_action.add_argument("--receiver-type", "-T", choices=["user", "group", "company"], help="Receiver type")
    parser_action = subparser_action.add_parser("delete", help="Delete a new delegate node")
    parser_action.add_argument("--id", "-i", help="Ligoj node identifier", required=False, type=int)

    # delegate org
    subparser_action = subparser_service.add_parser("delegate-org", help="Delegate organization operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("get", help="Return delegate organization information")
    parser_action.add_argument("--id", "-i", help="Organization delegate organization identifier", required=False, type=int)
    parser_action.add_argument("--name", "-n", help="Organization identifier or DN for tree to filter", required=False)
    parser_action.add_argument("--type", "-t", choices=["tree", "group", "company"], help="Organization type to delegate", required=False)
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

    # configuration
    subparser_action = subparser_service.add_parser("configuration", help="Configuration related operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("get", help="Return configuration value or values")
    parser_action.add_argument("--id", "-i", help="Configuration name")
    parser_action = subparser_action.add_parser("set", help="Set configuration value")
    parser_action.add_argument("--id", "-i", help="Configuration name")
    parser_action.add_argument("--value", "-v", help="Configuration value")
    parser_action.add_argument("--system", "-S", help="When true, the value is also stored at system level", action="store_true")
    parser_action = subparser_action.add_parser("delete", help="Delete configuration")
    parser_action.add_argument("--id", "-i", help="Configuration name")

    # cache
    subparser_action = subparser_service.add_parser("cache", help="Cache related operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("list", help="Return caches")
    parser_action = subparser_action.add_parser("get", help="Return configuration value or values")
    parser_action.add_argument("--id", "-i", help="Cache name to retrieve")
    parser_action = subparser_action.add_parser("invalidate", help="Invalidate one or all caches")
    parser_action.add_argument("--id", "-i", help="Cache name. When empty, all caches are invalidated", required=False)

    # hook
    subparser_action = subparser_service.add_parser("hook", help="Hook operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("upsert", help="Update of create a hook")
    parser_action.add_argument("--id", "-i", required=False, help="Hook identifier to update", type=int)
    parser_action.add_argument("--name", "-n", required=True, help="Hook name to create or update (unique)")
    parser_action.add_argument("--directory", "-d", required=True, help="Working directory of executed command. Must not contain spaces")
    parser_action.add_argument(
        "--command", "-c", required=True, help="Command to execute, split by ` ` char to separate program from its arguments. Must be allowed by `ligoj.hook.path` configuration."
    )
    parser_action.add_argument("--match", "-m", required=True, help='Hook JSON structure. Currently supports only path and optionally method filtering. ie. {"path": "rest/path/to", "method": "GET"}')
    parser_action.add_argument("--inject", help='Can relate to any configuration name supported by the "configuration get" command. Decrypted as needed.', action="append", default=[])
    parser_action.add_argument("--timeout", "-t", default=10, type=int, help="Maximum integration time in second")
    parser_action.add_argument("--delay", default=1, type=int, help="Delay in second before execution. Use 0 for synchronous execution")
    parser_action = subparser_action.add_parser("delete", help="Update of create a hook")
    parser_action.add_argument("--id", "-i", help="Hook identifier to delete", type=int, required=False)
    parser_action.add_argument("--name", "-n", help="Hook name to delete", required=False)
    parser_action = subparser_action.add_parser("get", help="Return hook details")
    parser_action.add_argument("--id", "-i", help="Hook identifier to return", type=int, required=False)
    parser_action.add_argument("--name", "-n", help="Hook name to return", required=False)
    subparser_action.add_parser("list", help="Return hooks")

    # file
    subparser_action = subparser_service.add_parser("file", help="File operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("put", help="Create or update a file")
    parser_action.add_argument("--from", "-f", help="Import URL or local file name")
    parser_action.add_argument("--path", "-n", help="Remote file path. Must be allowed by `ligoj.file.path` configuration.")
    parser_action.add_argument("--executable", "-x", help="With executable right", action="store_true", default=False)
    parser_action = subparser_action.add_parser("delete", help="Delete a file")
    parser_action.add_argument("--path", "-p", help="File path to delete. Must be allowed by `ligoj.file.path` configuration.")
    parser_action = subparser_action.add_parser("get", help="Return file content")
    parser_action.add_argument("--path", "-p", help="File path to return. Must be allowed by `ligoj.file.path` configuration.")
    parser_action.add_argument("--out", "-o", help="Target local file name")

    # plugin:id user
    subparser_action = subparser_service.add_parser("id:user", help="Plugin id user operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("create", help="Create a new user mapped to groups created as needed")
    parser_action.add_argument("--id", "-i", help="User name")
    parser_action.add_argument("--firstname", "-f", help="firstName")
    parser_action.add_argument("--lastname", "-l", help="lastName")
    parser_action.add_argument("--mail", "-m", help="mail")
    parser_action.add_argument("--company", "-c", help="company")
    parser_action.add_argument("--groups", "-g", help="groups", nargs="*", default=[])
    parser_action.add_argument("--custom-attributes", "-A", help="Custom attributes. Case might be sensitive", default=False)
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
    parser_action.add_argument("--type", "-t", help="Scope type. Required with name", required=False, choices=["company", "group"])
    parser_action = subparser_action.add_parser("list", help="List container scopes")
    parser_action.add_argument("--type", "-t", help="Filtered scope type", required=True, choices=["company", "group"])
    parser_action = subparser_action.add_parser("delete", help="Delete a container scope or by identifier")
    parser_action.add_argument("--id", "-i", help="Container scope identifier", required=False)
    parser_action.add_argument("--name", "-n", help="Container scope name, exclusive with id", required=False)
    parser_action.add_argument("--type", "-t", help="Scope type. Required with name", required=False, choices=["company", "group"])

    # plugin:id ou
    subparser_action = subparser_service.add_parser("id:ou", help="Plugin id Organizational Unit operations").add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser("create", help="Create a new OU")
    parser_action.add_argument("--name", "-n", help="OU name", required=True)
    parser_action.add_argument("--parent-dn", "-d", help="Parent DN", required=True)
    parser_action = subparser_action.add_parser("delete", help="Delete an OU")
    parser_action.add_argument("--name", "-n", help="OU name", required=False)


def parse_remote_args(args):
    global ligoj_api_key
    global ligoj_api_user
    global ligoj_api_run_as_user
    global ligoj_endpoint

    ligoj_api_key = utils.get_secret(args, "api_key", "LIGOJ_API_KEY", None)
    ligoj_api_user = utils.get_config(args, "api_user", "LIGOJ_API_USER", DEFAULT_LIGOJ_API_USER)
    ligoj_api_run_as_user = utils.get_config(args, "api_run_as_user", "LIGOJ_API_RUN_AS_USER", None)
    ligoj_endpoint = utils.get_config(args, "endpoint", "LIGOJ_ENDPOINT", DEFAULT_LIGOJ_ENDPOINT)


def execute_action(service, action, _, args):
    if service == "session":
        if action == "get":
            return session_get()
        if action == "whoami":
            return whoami()
        if action == "login":
            password = utils.get_secret(args, "password", "LIGOJ_PWD", None)
            if password is not None:
                return session_login_password(utils.not_none(password, "password"))
            if ligoj_api_key is not None:
                return session_login_api_key()
            raise ValueError("[ligoj] Missing credentials, api key or password")
        if action == "logout":
            return session_logout()
    elif service == "info":
        if action == "status":
            return info_status(args.get("wait", 0))
        if action == "version":
            return info_version()
        if action == "all":
            return info_all()
        if action == "api":
            return info_api(args.get("output", 0), args.get("print", 0))
    elif service == "plugin":
        if action == "list":
            return plugin_list()
        if action == "install":
            return plugin_install(args["id"], args.get("version", "LATEST"), args["repository"], None, args["javadoc"], args.get("force", False))
        if action == "upload":
            return plugin_install(args["id"], args.get("version"), None, args.get("from"), False, args.get("force", False))
        if action == "restart":
            return plugin_restart_context(args.get("wait", 0))
        if action == "javadoc":
            return plugin_install_javadoc(args["repository"])
    elif service == "node":
        if action in ["create", "upsert"]:
            if action == "create":
                utils.warn("Action 'create' is deprecated, use 'upsert' instead")
            node_name = utils.not_none(args.get("name"), "node name")
            node_create_definition = utils.load_json_from_url_or_file_with_interpolation(utils.not_none(args["from"], "node file/URL definition"), {"action": action, "node_name": node_name})
            return node_upsert(args["id"], node_name, node_create_definition)
        if action == "get":
            return node_get_by_id(args["id"], args["parameters_mode"], args["parameters_output"], args["parameters_secured"])
        if action == "list":
            return node_list(args.get("search"), args.get("refined"), args.get("mode"), args.get("depth", -1))
        if action == "delete":
            return node_delete(args["id"])
        if action == "status":
            node_id = args["id"]
            return node_get_status(node_id)
    elif service == "subscription":
        if action == "get":
            return subscription_get_by_id(args["id"], args["details"])
        if action == "list":
            return subscription_list(args.get("node"), args.get("tool"), args.get("service_id"), args.get("project"))
        if action == "create":
            project = args.get("project")
            node_id = args.get("node")
            subscription_parameters = utils.load_json_from_url_or_file_with_interpolation(args["from"], {"project": project, "node_id": node_id})
            return subscription_create(project, node_id, subscription_parameters)
        if action == "delete":
            return subscription_delete(args["id"], args.get("with_data"))
        if action == "status":
            return subscription_status(utils.not_none(args.get("project"), "subscription identifier"))
        if action == "refresh":
            return subscription_refresh(args.get("id"))
    elif service == "project":
        if action == "list":
            return project_list(args.get("search"))
        if action == "get":
            return project_get(int(args.get("id")))
        if action == "create":
            return project_create(args.get("team_leader", ligoj_api_user), args.get("pkey", args["name"]), args["name"], args.get("description"), args.get("context"))
        if action == "delete":
            if args.get("id", "").isnumeric():
                return project_delete_by_id(int(args.get("id"), args.get("with_data")))
            return project_delete_by_pkey(args.get("id"), args.get("with_data"))
    elif service == "delegate-node":
        if action == "list":
            return delegate_node_filter_by_node(args.get("node"))
        if action == "create":
            return delegate_node_create(args.get("node"), args.get("can_subscribe"), args.get("can_write"), args.get("can_admin"), args.get("receiver"), args.get("receiver_type"))
        if action == "get":
            return delegate_node_get_by_id(args.get("id"))
        if action == "delete":
            return delegate_node_delete(args["id"])
    elif service == "delegate-org":
        if action == "create":
            return delegate_org_create(args["node"], args.get("can_subscribe"), args.get("can_write"), args.get("can_admin"), args.get("receiver"), args.get("receiver_type"))
        if action == "get":
            if args.get("id") is not None:
                return delegate_org_get_by_id(args.get("id"))
            return delegate_org_filter_by_resource(args.get("type"), args.get("name"))
        if action == "delete":
            return delegate_org_delete(args["id"])
    elif service == "configuration":
        if action == "set":
            return configuration_set(utils.not_none(args.get("id"), "configuration name"), utils.not_none(args.get("value"), "configuration value"), args.get("system", False))
        if action == "get":
            return configuration_get(args.get("id"))
        if action == "delete":
            return configuration_delete(utils.not_none(args.get("id"), "configuration name"))
    elif service == "token":
        if action == "create":
            return token_create(utils.not_none(args.get("id"), "token name"), args.get("expiration", ""), args.get("save", False))
        if action == "list":
            return token_list()
        if action == "get":
            return token_get(utils.not_none(args.get("id"), "token name"))
        if action == "delete":
            return token_delete(utils.not_none(args.get("id"), "token name"))
        if action == "purge":
            return token_purge()
        if action == "purge-all":
            return token_purge_all()
    elif service == "cache":
        if action == "invalidate":
            return cache_invalidate(args.get("id"))
        if action == "get":
            return cache_get(args.get("id"))
        if action == "list":
            return cache_list()
    elif service == "hook":
        if action == "get":
            return hook_get(args.get("id", None), args.get("name"))
        if action == "list":
            return hook_list()
        if action == "delete":
            return hook_delete(args.get("id"), args.get("name"))
        if action == "upsert":
            return hook_upsert(
                args.get("id"),
                utils.not_none(args.get("name"), "hook name"),
                utils.not_none(args.get("directory"), "working directory"),
                utils.not_none(args.get("command"), "hook command"),
                utils.not_none(args.get("match"), "JSON match"),
                list(itertools.chain.from_iterable(args.get("inject", []))),
                args.get("timeout"),
                args.get("delay"),
            )
    elif service == "file":
        if action == "get":
            return file_get(args.get("path"), args.get("out"))
        if action == "delete":
            return file_delete(args.get("path"))
        if action == "put":
            return file_put(args.get("from"), args.get("path"), args.get("executable"))
    elif service == "role":
        if action == "create":
            role_name = utils.not_none(args.get("name") or args.get("id"), "role name")
            utils.info(f"Create system role '{role_name}', api={args.get('api')}, ui={args.get('ui')} ...")
            return create_system_role(role_name, utils.not_none(args.get("api"), "API patterns"), utils.not_none(args.get("ui"), "UI patterns"))
        if action == "list":
            return system_role_list()
        if action == "get":
            if args.get("id") is not None:
                return system_role_get(args.get("id"))
            return system_role_get_by_name(utils.not_none(args.get("name"), "role id or name"))
        if action == "delete":
            if args.get("id") is not None:
                return system_role_delete(args.get("id"))
            return system_role_delete_by_name(utils.not_none(args.get("name"), "role id or name"))
    elif service == "user":
        if action == "upsert":
            return system_user_upsert(utils.not_none(args.get("id"), "user id"), list(itertools.chain.from_iterable(args.get("roles", []))), args.get("api_key_name"))
        if action == "list":
            return system_user_list(args.get("with_roles", False))
        if action == "get":
            return system_user_get(utils.not_none(args.get("id"), "user id"))
        if action == "delete":
            return system_user_delete(utils.not_none(args.get("id"), "user id"))
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
            return user_list(args.get("company"), args.get("group"), args.get("criteria"), args.get("page"), args.get("page_length"))
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
            return create_group(args["name"], scope, args.get("parent"))
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
                return get_container_scope_by_id(utils.not_none(args.get("id")))
            return get_container_scope_by_name(utils.not_none(args.get("name"), "name"), utils.not_none(args.get("type"), "type"))
        if action == "list":
            return list_container_scopes(utils.not_none(args.get("type"), "type"))
        if action == "create":
            return create_container_scope(utils.not_none(args.get("name"), "name"), utils.not_none(args.get("type"), "type"), utils.not_none(args.get("dn"), "dn"))
        if action == "delete":
            if args.get("id") is None and (args.get("name") is None or args.get("type") is None):
                raise ValueError("[ligoj] When scope id is not provided, scope name and scope type are required")
            if args.get("id"):
                return delete_container_scope_by_id(utils.not_none(args.get("id"), "id"))
            return delete_container_scope_by_name(utils.not_none(args.get("name"), "name"), utils.not_none(args.get("type"), "type"))
    elif service == "id:ou":
        if action == "create":
            return create_ou(utils.not_none(args.get("name"), "name"), utils.not_none(args.get("parent_dn"), "parent-dn"))
        if action == "delete":
            return delete_ou(utils.not_none(args.get("name"), "name"))

    return None


def get_user_id(args, must_exist=False):
    if args.get("id"):
        return user["id"]
    elif args.get("mail"):
        user = user_find_by_mail(args.get("mail"))
        if user:
            return user["id"]
    else:
        raise ValueError("[ligoj] User id or mail is required")
    if must_exist:
        raise ValueError(f"[ligoj] User '{args.get('id') or args.get('mail')}' not found")
    return None


def call_api(method, url, **kwargs):
    headers = kwargs["headers"] if "headers" in kwargs and kwargs["headers"] else {}
    if ligoj_api_user is not None and ligoj_api_key is not None:
        # API key protocol
        if ligoj_api_run_as_user is not None and ligoj_api_key is not None:
            kwargs["headers"] = {"x-api-user": ligoj_api_run_as_user, "x-api-via-user": ligoj_api_user, "x-api-key": ligoj_api_key} | headers
        else:
            kwargs["headers"] = {"x-api-user": ligoj_api_user, "x-api-key": ligoj_api_key} | headers
    elif utils.cookie_session is not None:
        kwargs["cookies"] = {"JSESSIONID": utils.cookie_session}
    else:
        raise ValueError("[ligoj] No enough credential materials, no session and no API key pair found")
    response = utils.call_rest_api(method, "ligoj", f"{ligoj_endpoint}{'/' if url.startswith('/') else '/rest/'}", url.removeprefix("/"), None, kwargs)

    # Check hook status within all X-Ligoj-Hook-* and print the error message
    if response:
        for header in response.headers:
            if header.startswith("X-Ligoj-Hook-") and not header.endswith("-Message"):
                hook = header.removeprefix("X-Ligoj-Hook-")
                status = response.headers.get(header)
                message = response.headers.get(header + "-Message")
                if message:
                    hook_log = f"[ligoj] Hook '{hook}' status: {status}: {message}"
                else:
                    hook_log = f"[ligoj] Hook '{hook}' status: {status}"
                if utils.fail_on_hook_error and status == "FAILED":
                    raise ValueError(hook_log)
                else:
                    utils.debug(hook_log)
    return response


def whoami():
    return session_get().json().get("userName")


def get_ldap_group(component, groups_by_name, local_role_name):
    ldap_group = groups_by_name.get(local_role_name, "")
    if ldap_group == "":
        raise ValueError(f"[{component}] Referenced group '{local_role_name}' has not been declared")
    if local_role_name != unidecode(local_role_name):
        raise ValueError(f"[{component}] Group name '{local_role_name}' cannot contain non ASCII chars")

    return ldap_group


def plugins_list(repository: str):
    utils.info("[ligoj] List plugins ...")
    response = call_api("GET", "system/plugin", params={"repository": repository})
    return None if response is None else response.json()


def plugins_search(artifact_id: str, repository: str):
    utils.info(f"[ligoj] Search plugin '{artifact_id}' in repository ...")
    response = call_api("GET", "system/plugin/search", params={"repository": repository, "q": artifact_id})
    return None if response is None else response.json()


def plugin_search_latest_version(artifact_id: str, repository: str):
    search_result = plugins_search(artifact_id, repository)
    search_result = next(filter(lambda p: p["artifact"] == artifact_id, search_result), None)
    return search_result["version"] if search_result is not None else None


def plugin_install_internal(artifact_id: str, target_version: str, repository: str, from_location: str | None, javadoc: bool):
    utils.info(f"[ligoj] Plugin '{artifact_id}:{target_version}' is being to be installed")
    if from_location:
        upload_file = utils.get_temp_file_from(from_location)
        with open(upload_file, "rb") as file:
            call_api("PUT", "system/plugin/upload", files={"plugin-file": file}, data={"plugin-id": artifact_id, "plugin-version": target_version})
        utils.delete_temp_file_from(from_location, upload_file)
    else:
        call_api("POST", f"system/plugin/{artifact_id}/{target_version}", params={"repository": repository, "javadoc": javadoc})


def plugin_install_javadoc(repository: str):
    utils.info("[ligoj] Javadoc install all")
    call_api("POST", "system/plugin/javadoc/install", params={"repository": repository})

    # No output
    return False


def plugin_list():
    utils.info("[ligoj] List installed plugins ...")
    response = call_api("GET", "system/plugin")
    return None if response is None else response.json()


def plugin_install(artifact_id: str, target_version: str, repository: str | None, from_location: str | None, javadoc: bool, force: bool):
    if target_version == "LATEST":
        target_version = None
    params = {}
    installed = False
    if from_location:
        if not target_version or target_version == "LATEST":
            raise ValueError("[ligoj] A non 'LATEST' version is required while uploading a plugin")
        utils.info(f"[ligoj] Install plugin '{artifact_id}:{target_version}' from '{from_location}' ...")
    else:
        params["repository"] = repository.strip()
        utils.info(f"[ligoj] Install plugin '{artifact_id}:{'LATEST' if target_version is None else target_version}@{repository}' ...")

    # Check node format
    artifact_parts = artifact_id.split("-")
    if len(artifact_parts) < 2:
        raise ValueError(f"[ligoj] Invalid artifact id format '{artifact_id}', must be 'plugin-$service' or 'plugin-$service:$tool'")

    plugins = plugins_list(repository)
    if not plugins:
        if not target_version:
            raise ValueError(f"[ligoj] Plugin '{artifact_id}' is not detected, and the repository is unavailable")

        utils.warn(f"[ligoj] Plugin '{artifact_id}' is not detected, and the repository is unavailable but a version is specified")
        plugins = []

    installed_plugin = next(filter(lambda p: "plugin" in p and p["plugin"]["artifact"] == artifact_id, plugins), None)
    if installed_plugin:
        latest_version = installed_plugin.get("newVersion")
        current_version = installed_plugin["plugin"].get("version")
        latest_local_version = installed_plugin.get("latestLocalVersion")
        if not current_version:
            if not latest_local_version:
                if force:
                    utils.info(f"[ligoj] Plugin '{artifact_id}' is already installed, but in an unknown state {installed_plugin}. '--force' enabled, reinstalling")
                    plugin_install_internal(artifact_id, latest_version, repository, from_location, javadoc)
                    installed = True
                else:
                    raise ValueError(f"[ligoj] Plugin '{artifact_id}' is already installed but in an unknown state {installed_plugin}. Use '--force' to reinstall")
            else:
                utils.info(f"[ligoj] Plugin '{artifact_id}:{latest_local_version}' is installed but requires a restart to be available")
        elif not target_version and not latest_version:
            if force:
                utils.info(f"[ligoj] Plugin '{artifact_id}' is already installed, but in an unknown state {installed_plugin}. '--force' enabled, reinstalling")
                plugin_install_internal(artifact_id, latest_version, repository, from_location, javadoc)
                installed = True
            else:
                utils.info(f"[ligoj] Plugin '{artifact_id}:{current_version}' is already installed with the latest version, skipping. Use '--force' to reinstall")
        elif not target_version:
            if force:
                utils.info(f"[ligoj] Plugin '{artifact_id}:{current_version}' is already installed, but a newest version is available -> {latest_version}. '--force' enabled, reinstalling")
                plugin_install_internal(artifact_id, latest_version, repository, from_location, javadoc)
                installed = True
            else:
                utils.info(f"[ligoj] Plugin '{artifact_id}:{current_version}' is already installed, but a newest version is available -> {latest_version}")
            plugin_install_internal(artifact_id, latest_version, repository, from_location, javadoc)
            installed = True
        elif target_version == current_version and not target_version.endswith("-SNAPSHOT"):
            if force:
                utils.info(f"[ligoj] Plugin '{artifact_id}:{target_version}' is already installed with the desired version. '--force' enabled, reinstalling")
                plugin_install_internal(artifact_id, target_version, repository, from_location, javadoc)
                installed = True
            else:
                utils.info(f"[ligoj] Plugin '{artifact_id}:{target_version}' is already installed with the desired version, skipping. Use '--force' to reinstall")
        elif target_version:
            utils.info(f"[ligoj] Plugin '{artifact_id}:{current_version}' is already installed, but need to be updated -> {target_version}")
            plugin_install_internal(artifact_id, target_version, repository, from_location, javadoc)
            installed = True
        else:
            utils.info(f"[ligoj] Plugin '{artifact_id}:{current_version}' is installed, but no latest version can be resolved")
    elif target_version:
        utils.info(f"[ligoj] Plugin '{artifact_id}:{target_version}' is not yet installed")
        plugin_install_internal(artifact_id, target_version, repository, from_location, javadoc)
        installed = True
    else:
        # Find the latest version
        target_version = plugin_search_latest_version(artifact_id, repository)
        if not target_version:
            raise ValueError(f"[ligoj] Plugin '{artifact_id}' has not been found in repository")

        plugin_install_internal(artifact_id, target_version, repository, from_location, javadoc)
        installed = True
    if installed:
        utils.info(f"[ligoj] Plugin '{artifact_id}' has been installed/updated, a restart is required")

    # No output
    return False


def plugin_restart_context(wait: int = 0):
    utils.info("[ligoj] Restart context ...")
    call_api("PUT", "system/plugin/restart")
    if wait != 0:
        return info_status(wait)
    utils.info("[ligoj] Restart requested, few seconds may be necessary")
    return False


def token_create(name: str, expiration: str, save: bool):
    expiration_date = None
    if expiration:
        try:
            expiration_date = int(datetime.fromisoformat(expiration).timestamp())
        except:
            try:
                parsed_date = pytimeparse.parse(expiration)
                expiration_date = int((datetime.now() + timedelta(seconds=parsed_date)).timestamp())
            except ValueError:
                raise ValueError(utils.error(f"[ligoj] Invalid expiration value '{expiration}'"))
        utils.info(f"[ligoj] Create token '{name}' expiring at {datetime.fromtimestamp(expiration_date)} ...")
        response = call_api("POST", f"api/token", data={"name": name, "expiration": expiration_date}).json()
    else:
        utils.info(f"[ligoj] Create token '{name}' without expiration ...")
        response = call_api("POST", f"api/token/{name}").json()
    if save:
        if not utils.ini_credentials.has_section(utils.ini_profile):
            utils.ini_credentials.add_section(utils.ini_profile)
        utils.ini_credentials.set(utils.ini_profile, "api_key", response["id"])
        utils.ini_credentials_write()
        utils.info(f"[ligoj] Token saved into profile '{utils.ini_profile}', file {utils.INI_CREDENTIALS_FILE}")
        return False
    return response


def token_list():
    utils.info("[ligoj] List all tokens ...")
    return call_api("GET", "api/token")


def token_purge_all():
    utils.info("[ligoj] Purge all expired tokens ...")
    return call_api("DELETE", "api/token/all")


def token_purge():
    utils.info("[ligoj] Purge all expired tokens of current user ...")
    return call_api("DELETE", "api/token/my")


def token_get(name: str | None):
    utils.info(f"[ligoj] Get token '{name}' ...")
    response = call_api("GET", f"api/token/{name}")
    return None if response is None else {"value": response.text}


def token_delete(name: str):
    utils.info(f"[ligoj] Delete token '{name}' ...")
    call_api("DELETE", f"api/token/{name}")
    return False


def configuration_set(name: str, value, system: bool = False):
    utils.info(f"[ligoj] Configure configuration '{name}' ...")
    call_api("POST", "system/configuration", data={"name": name, "value": value, "system": system})
    return False


def configuration_get(name: str | None):
    if name is None or name == "":
        utils.info("[ligoj] Get all configurations ...")
        return call_api("GET", "system/configuration")
    utils.info(f"[ligoj] Get configuration '{name}' ...")
    response = call_api("GET", f"system/configuration/{name}", headers={"Accept": "text"})
    return {"value": None} if response is None else {"value": response.text}


def configuration_delete(name: str):
    utils.info(f"[ligoj] Delete configuration '{name}' ...")
    call_api("DELETE", f"system/configuration/{name}")
    return False


def hook_delete(hook_id: str | None, name: str | None):
    utils.info("[ligoj] Delete hooks ...")
    if (name is None or name == "") and (hook_id is None or hook_id == ""):
        raise ValueError("[ligoj] Hook 'id' or 'name' is required for deletion")

    if hook_id is not None and hook_id != "":
        call_api("DELETE", f"system/hook/{hook_id}")
        return None

    response = call_api("GET", "system/hook", params={"rows": 1000})
    if response is None:
        return None
    hooks = response.json().get("data", [])
    hook = next(filter(lambda h: h.get("name") == name, hooks), None)
    if hook is None:
        raise ValueError(f"[ligoj] Hook '{name}' does not exist")
    call_api("DELETE", f"system/hook/{hook['id']}")
    return None


def hook_upsert(hook_id: str | None, name: str, directory: str, command: str, match: str, inject: list, timeout: int, delay: int):
    utils.info(f"[ligoj] Update/create hook '{name}' ...")
    try:
        match_obj = json.loads(match)
        if not isinstance(match_obj.get("path"), str):
            raise ValueError(f"[ligoj] Hook '{name}', missing mandatory 'path' property")
        if match_obj.get("method", "GET") not in ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT", "TRACE"]:
            raise ValueError(f"[ligoj] Hook '{name}', invalid optional 'method' property")

    except Exception as err:
        raise ValueError(f"[ligoj] Hook '{name}', invalid JSON syntax for match") from err

    if not hook_id:
        hook_response = call_api("GET", f"system/hook/name/{name}", ignore_error=True)
        if hook_response:
            hook_id = hook_response.json()["id"]

    return call_api(
        "PUT" if hook_id else "POST",
        "system/hook",
        data={"name": name, "id": hook_id, "workingDirectory": directory, "command": command, "match": match, "inject": inject, "timeout": timeout, "delay": delay},
    )


def hook_get(hook_id: str | None, name: str | None):
    utils.info("[ligoj] Get hooks ...")
    response = call_api("GET", "system/hook", params={"rows": 1000})
    if response is None:
        return None
    hooks = response.json().get("data", [])
    return list(filter(lambda h: ((name is None or name == "") and (hook_id is None or hook_id == "")) or h.get("name") == name or str(h.get("id")) == hook_id, hooks))


def hook_list():
    utils.info("[ligoj] List hooks ...")
    return call_api("GET", "system/hook", params={"rows": 1000})


def file_delete(path: str):
    utils.info(f"[ligoj] Delete file {path}...")
    call_api("DELETE", "system/file", params={"path": path})
    return False


def file_get(path: str, to_file: str):
    response = call_api("GET", "system/file", params={"path": path}, stream=True)
    utils.download_file(response, to_file)
    return False


def file_put(from_location: str, to_path: str, executable: bool = False):
    utils.info(f"[ligoj] Upload from '{from_location}' to file '{to_path}'")
    upload_file = utils.get_temp_file_from(from_location)
    with open(upload_file, "rb") as file:
        call_api("PUT", "system/file", files={"content": file}, data={"path": to_path, "executable": executable})
    utils.delete_temp_file_from(from_location, upload_file)
    return False


def cache_invalidate(name: str | None):
    if name is None or name == "":
        utils.info("[ligoj] Invalidate all caches ...")
        return call_api("DELETE", "system/cache")
    utils.info(f"[ligoj] Invalidate cache '{name}' ...")
    return call_api("POST", f"system/cache/{name}")


def cache_get(name: str | None):
    utils.info(f"[ligoj] Statistics of cache '{name}' ...")
    return call_api("GET", f"system/cache/{name}")


def cache_list():
    utils.info("[ligoj] List caches ...")
    return call_api("GET", "system/cache")


def session_get():
    utils.info("[ligoj] Get session ...")
    return call_api("GET", "session")


def info_status(wait: int = 0):
    utils.info("[ligoj] Get status ...")
    if wait == 0:
        details = call_api("GET", "/manage/health", ignore_error=True)
    else:
        start_time = time.time()
        while wait == -1 or (int(time.time() - start_time) < wait):
            try:
                details = call_api("GET", "/manage/health", ignore_error=True)
                if details is not None:
                    return details
            except Exception as _ignore:
                pass
            time.sleep(2)
        utils.warn(f"[ligoj] No valid status retrieved after {wait}s")

    if details is None:
        return {"status": "DOWN"}
    return details


def info_version():
    utils.info("[ligoj] Get version ...")
    details = call_api("GET", "/manage/info")
    return {"version": details.json()["app"]["version"]}


def info_all():
    utils.info("[ligoj] Get info ...")
    return call_api("GET", "/manage/info")


def info_api(output: str, print_mode: str) -> str:
    if output == "wadl":
        url = "/rest?_wadl"
    elif output == "swagger":
        url = "#/api"
    else:
        url = "/rest/openapi.json"
    if print_mode == "url" or output == "swagger":
        print(f"{ligoj_endpoint}{url}")
    else:
        response = call_api("GET", url)
        print(response.text)


def session_login_password(password: str):
    utils.info(f"[ligoj] Login {ligoj_api_user} with password ...")
    result = utils.call_rest_api("POST", "ligoj", ligoj_endpoint, "/login", None, {"params": {"username": ligoj_api_user, "password": password}, "headers": {"Content-Type": utils.MIME_URL_ENCODED}})
    session = next(filter(lambda c: c.name == "JSESSIONID", result.cookies), None)
    if session is not None and session.value is not None:
        if not utils.ini_sessions.has_section(utils.ini_profile):
            utils.ini_sessions.add_section(utils.ini_profile)
        utils.ini_sessions.set(utils.ini_profile, "session", session.value)
        utils.ini_sessions.set(utils.ini_profile, "api_user", ligoj_api_user)
        utils.ini_sessions_write()
        utils.info(f"[ligoj] Session stored in {utils.INI_SESSIONS_FILE}, logout to remove it")
    return False


def session_login_api_key():
    utils.info(f"[ligoj] Save API key of {ligoj_api_user} ...")
    call_api("GET", "/manage/info")
    if not utils.ini_sessions.has_section(utils.ini_profile):
        utils.ini_sessions.add_section(utils.ini_profile)
    utils.ini_sessions.set(utils.ini_profile, "api_key", ligoj_api_key)
    utils.ini_sessions.set(utils.ini_profile, "api_user", ligoj_api_user)
    utils.ini_sessions_write()
    utils.info(f"[ligoj] API key stored in {utils.INI_SESSIONS_FILE}, logout to remove it")
    return False


def session_logout():
    utils.info(f"[ligoj] Logout {ligoj_api_user} ...")
    call_api("POST", "/logout")
    if utils.ini_sessions.has_section(utils.ini_profile):
        utils.ini_sessions.remove_section(utils.ini_profile)
        utils.ini_sessions_write()
        utils.info(f"[ligoj] Session removed from {utils.INI_SESSIONS_FILE}")
    else:
        utils.info(f"[ligoj] No session found in {utils.INI_SESSIONS_FILE}")
    return False


def get_parameter_type(parameter: str):
    for p_type in ["bool", "text", "multiple", "integer", "date", "tags"]:
        if p_type in parameter:
            return p_type
    return None


def delegate_node_get_by_id(delegate_id: int):
    return call_api("GET", f"node/delegate/{delegate_id}")


def delegate_node_filter_by_node(node_id: str):
    items = call_api("GET", "node/delegate").json()["data"]
    return list(filter(lambda x: node_id is None or node_id == "" or x["name"] == node_id, items))


def delegate_node_delete(delegate_id: int):
    call_api("DELETE", f"node/delegate/{delegate_id}", ignore_error=True, ignore_output=True)
    return False


def delegate_node_list():
    return call_api("GET", "node/delegate").json()["data"]


def delegate_node_create(node_id: str, can_subscribe: bool, can_write: bool, can_admin: bool, receiver: str, receiver_type: str) -> int:
    return call_api("POST", "node/delegate", data={"name": node_id, "canSubscribe": can_subscribe, "canWrite": can_write, "canAdmin": can_admin, "receiver": receiver, "receiverType": receiver_type})


def node_list(search: str | None, refined: str | None, mode: str | None, depth: int, parameters_mode: str | None = None, parameters_output: str | None = None, return_secured_parameters=False):
    response = call_api("GET", "node", params={"search[value]": search, "refined": refined, "mode": mode, "depth": depth})
    return node_get_parameters(response, parameters_mode, parameters_output, return_secured_parameters)


def node_get_by_id(node_id: str | None, parameters_mode: str | None = None, parameters_output: str | None = None, return_secured_parameters=False):
    if node_id is None:
        return node_list(None, parameters_mode, parameters_output, return_secured_parameters)
    response = call_api("GET", f"node/{node_id}", ignore_error=True, ignore_output=True)
    return node_get_parameters(response, parameters_mode, parameters_output, return_secured_parameters)


def node_upsert(node_id: str, name: str, parameters: list | dict[str, Any], mode: str | None = "ALL"):
    utils.info(f"[ligoj] Create or update node '{node_id}' ...")
    # Check node format
    node_parts = node_id.split(":")
    if not re.match(r"service(:[a-z0-9]{1,50}){3}", node_id):
        raise ValueError(f"[ligoj] Invalid node id format '{node_id}', must be 'service:$service:$tool:$name'")
    if len(name.strip()) == 0:
        raise ValueError(f"[ligoj] Invalid node name '{name}'")

    parent_id = ":".join(node_parts[:-1])
    parent_node_details = node_get_by_id(parent_id)
    if parent_node_details is None:
        raise ValueError(f"[ligoj] Parent node id not found '{node_id}', maybe the corresponding plugins 'plugin-{node_parts[1]}' or 'plugin-{node_parts[1]}-{node_parts[2]}' are not installed")

    node_details = node_get_by_id(node_id)
    if node_details is None:
        utils.info(f"[ligoj] Create node '{node_id}' ...")
        method = "POST"
    else:
        utils.info(f"[ligoj] Update node '{node_id}' ...")
        method = "PUT"

    parameters_as_list = parameters if isinstance(parameters, list) else node_parameters_as_list(parameters)

    call_api(method, "node", data={"id": node_id, "name": name, "node": parent_id, "mode": mode, "untouchedParameters": False, "parameters": parameters_as_list})
    if not node_details:
        node_details = node_get_by_id(node_id)
    return node_details


def node_get_parameters(response, parameters_mode: str | None = None, parameters_output: str | None = None, return_secured_parameters=False):
    if response is None:
        return None
    result = response.json()
    if parameters_mode is not None or parameters_mode == "":
        secured_path = "/secured" if return_secured_parameters else ""
        nodes = result["data"] if "data" in result else [result]
        for some_node in nodes:
            some_node_id = some_node["id"]
            p_response = call_api("GET", f"node/{some_node_id}/parameter-value/{parameters_mode}{secured_path}", ignore_error=True, ignore_output=True)
            if parameters_output == "list":
                some_node["parameters"] = list(
                    filter(
                        get_parameter_type,
                        map(lambda p: p | {"parameter": p["parameter"]["id"]}, p_response.json()),
                    )
                )
            elif parameters_output == "map":
                some_node["parameters"] = node_parameters_as_dict(p_response.json())
            else:
                some_node["parameters"] = p_response.json()
    return result


def node_parameters_as_dict(parameters_as_list):
    parameters_as_dict = {}
    for parameter in parameters_as_list:
        if get_parameter_type(parameter):
            parameter_obj = parameter["parameter"]
            parameter_id = parameter_obj if isinstance(parameter_obj, str) else parameter["parameter"]["id"]
            parameters_as_dict[parameter_id] = parameter.get("text", parameter.get("selections", parameter.get("integer", parameter.get("date", parameter.get("index", parameter.get("bool"))))))

    return parameters_as_dict


def node_parameters_as_list(parameters_as_dict):
    parameters_as_list = []
    for parameter_id in parameters_as_dict.keys():
        value = parameters_as_dict[parameter_id]
        if isinstance(value, bool):
            parameter_type = "boolean"
        elif isinstance(value, str):
            parameter_type = "text"
        elif isinstance(value, int):
            parameter_type = "integer"
        elif isinstance(value, list):
            parameter_type = "selections"
        else:
            raise ValueError(f"[ligoj] Unsupported parameter type for value '{value}'")
        parameters_as_list.append({"parameter": parameter_id, parameter_type: value})
    return parameters_as_list


def node_delete(node_id: str):
    call_api("DELETE", f"node/{node_id}", ignore_error=True, ignore_output=True)
    return False


def node_get_status(node_id: str):
    response = call_api("GET", f"node/status/{node_id}", ignore_error=True, ignore_output=True)
    return None if response is None else response.json()


def create_system_role(role_name, api_patterns, ui_patterns):
    utils.info(f"[ligoj] Create system role '{role_name}' ...")
    roles = call_api("GET", LIGOJ_SYSTEM_ROLE_PATH).json()["data"]
    role = next(filter(lambda x: x["name"] == role_name, roles), None)
    if role is None:
        return call_api(
            "POST",
            LIGOJ_SYSTEM_ROLE_PATH,
            data={
                "name": role_name,
                "authorizations": [{"pattern": p, "type": "api"} for p in api_patterns] + [{"pattern": p, "type": "ui"} for p in ui_patterns],
            },
        ).json()
    utils.debug(f"[ligoj] System role '{role_name}' already exists, update permissions ...")
    call_api(
        "PUT",
        LIGOJ_SYSTEM_ROLE_PATH,
        data={
            "id": role["id"],
            "name": role_name,
            "authorizations": [{"pattern": p, "type": "api"} for p in api_patterns] + [{"pattern": p, "type": "ui"} for p in ui_patterns],
        },
    )
    return role["id"]


def system_role_get_by_name(name):
    return call_api("GET", f"system/security/role/name/{name}")


def system_role_get(role_id):
    return call_api("GET", f"system/security/role/{role_id}")


def system_role_delete_by_name(name):
    role = system_role_get_by_name(name)
    if role is None:
        utils.debug(f"[ligoj] Role '{name}' does not exist")
        return None
    return system_role_delete(role["id"])


def system_role_delete(role_id):
    return call_api("DELETE", f"system/security/role/{role_id}")


def system_role_list():
    return call_api("GET", "system/security/role")


def system_user_upsert(user, roles, api_key_name: str = None):
    utils.info(f"[ligoj] Create system user '{user}' with roles {roles} ...")
    roles = list(map(lambda r: r if isinstance(r, int) else system_role_get_by_name(r).json()["id"], roles))
    return call_api("POST", "system/user", data={"login": user, "roles": roles} | ({} if api_key_name is None else {"apiToken": api_key_name}))


def system_user_get(user):
    utils.info(f"[ligoj] Get system user '{user}' ...")
    return call_api("GET", f"system/user/{user}").json()


def system_user_delete(user):
    utils.info(f"[ligoj] Delete system user '{user}' ...")
    return call_api("DELETE", f"system/user/{user}")


def system_user_list(with_roles: bool = False):
    utils.info("[ligoj] List system users ...")
    return call_api("GET", f"system/user{'/roles' if with_roles else ''}").json()


def user_reset_password(user):
    utils.info(f"[ligoj] Reset password of user '{user}' ...")
    return call_api("PUT", f"service/id/user/{user}/reset", headers={"Accept": "text/plain"}).text


def user_create(user_details):
    user = user_details["id"]
    utils.info(f"[ligoj] Create user '{user}' ...")
    response = call_api("GET", f"service/id/user/{user}", ignore_error=True)
    if response is not None:
        utils.debug(f"[ligoj] User '{user}' already exists")
        return None

    return call_api("POST", "service/id/user", data=user_details)


def user_get(user: str) -> dict | None:
    utils.info(f"[ligoj] Fetch user '{user}' ...")
    response = call_api("GET", f"service/id/user/{user}", ignore_error=True)
    if response is None:
        return None
    return response.json()


def user_list(company: str | None = None, group: str | None = None, criteria: str | None = None, page: int | None = None, page_size: int | None = None) -> dict | None:
    utils.info(f"[ligoj] Fetch user list ...")
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
    response = call_api("GET", f"service/id/user", params=params)
    if response is None:
        return None
    return response.json()


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
    items = call_api("GET", "service/id/user", ignore_error=True, params={"search[value]": mail}).json()["data"]
    return next(filter(lambda x: "mails" in x and mail in x["mails"], items), None)


def group_import(csv_file):
    utils.info("[ligoj] Import groups ...")
    return call_api("POST", "service/id/group/batch", data={"csv-file": csv_file, "encoding": "UTF-8", "columns": ["name", "scope", "parent", "department", "owner", "assistant"]}).json()


def get_container_scope_id(name_or_id: str | int, container_type: str | None, required: bool = True) -> int:
    if isinstance(name_or_id, int):
        return name_or_id
    if isinstance(name_or_id, str) and name_or_id.isdigit():
        return int(name_or_id)
    if not container_type:
        raise ValueError("[ligoj] Scope type is required when scope name is provided instead of scope identifier")
    utils.info(f"[ligoj] Fetch container scope '{name_or_id}' [{container_type}] ...")
    response = call_api("GET", f"service/id/container-scope/name/{name_or_id}/{container_type}", ignore_error=True)
    if not response:
        if required:
            raise ValueError(f"[ligoj] Scope '{name_or_id}' not found in type '{container_type}'")
        return None
    return response.json()["id"]


def get_container_scope_by_id(id: int):
    utils.info(f"[ligoj] Fetch container scope '{id}' ...")
    return call_api("GET", f"service/id/container-scope/{id}").json()


def get_container_scope_by_name(name: str, container_type: str):
    utils.info(f"[ligoj] Fetch container scope '{name}' [{container_type}] ...")
    return call_api("GET", f"service/id/container-scope/name/{name}/{container_type}").json()


def list_container_scopes(container_type: str):
    utils.info(f"[ligoj] Fetch container scopes [{container_type}] ...")
    return call_api("GET", f"service/id/container-scope/{container_type}").json()


def delete_container_scope_by_id(id: int):
    utils.info(f"[ligoj] Delete container scope '{id}' ...")
    return call_api("DELETE", f"service/id/container-scope/{id}")


def delete_container_scope_by_name(name: str, container_type: str):
    utils.info(f"[ligoj] Delete container scope '{name}' [{container_type}] ...")
    container_scope = get_container_scope_id(name, container_type, False)
    if container_scope is None:
        return None
    return call_api("DELETE", f"service/id/container-scope/{container_scope}").json()


def create_container_scope(name: str, container_type: str, dn: str) -> int:
    utils.info(f"[ligoj] Create container scope '{name}'[{container_type}] associated to DN '{dn}' ...")
    container_response = call_api("GET", f"service/id/container-scope/name/{name}/{container_type}", ignore_error=True)
    if container_response is not None:
        existing_id = container_response.json()["id"]
        if container_response.json()["dn"] == dn:
            utils.debug(f"[ligoj] Container scope '{name}' already exists with id '{existing_id}' with identical DN")
        else:
            # Update DN
            utils.debug(f"[ligoj] Container scope '{name}' already exists with id '{existing_id}', update it's DN from '{container_response.json()['dn']}' to '{dn}' ...")
            call_api("PUT", "service/id/container-scope", data={"id": existing_id, "dn": dn, "name": name, "type": container_type})
        return existing_id

    return call_api("POST", "service/id/container-scope", data={"dn": dn, "name": name, "type": container_type}).json()


def create_company(name: str | int, container_scope: str | int, **kwargs):
    utils.info(f"[ligoj] Create company '{name}' in scope id '{container_scope}' ...")
    container_response = call_api("GET", f"service/id/company/{name}", ignore_error=True)
    if container_response:
        utils.debug(f"[ligoj] Company '{name}' already exists'")
        return

    return call_api("POST", "service/id/company", data=kwargs.get("data", {}) | {"name": name, "scope": container_scope}, ignore_error=kwargs.get("ignore_error", False))


def create_ou(name: str, parent_dn: str, **kwargs):
    utils.info(f"[ligoj] Create LDAP OU'{name}' in parent DN '{parent_dn}' ...")
    container_response = call_api("GET", f"service/id/company/{name}", ignore_error=True)
    if container_response:
        utils.debug(f"[ligoj] OU '{name}' already exists'")
        return container_response

    container_scope_id = create_container_scope(f"temporary-scope-{name}", "company", parent_dn)
    ou_response = call_api("POST", "service/id/company", data={"name": name, "scope": container_scope_id}, ignore_error=kwargs.get("ignore_error", False))
    delete_container_scope_by_id(container_scope_id)
    return ou_response


def delete_ou(name: str):
    utils.info(f"[ligoj] Delete LDAP OU '{name}' ...")
    return call_api("DELETE", "service/id/company", data={"name": name})


def create_group(name: str, container_scope_name_or_id: str | int, parent_name: str | None = None):
    utils.info(f"[ligoj] Create group '{'' if parent_name is None else f'{parent_name}/'}/{name}' in scope '{container_scope_name_or_id}' ...")
    if unidecode(name) != name:
        raise ValueError(f"[ligoj] Group name '{name}' cannot contain non ASCII chars")
    container_scope_id = get_container_scope_id(container_scope_name_or_id, "group")
    container_response = call_api("GET", f"service/id/group/{urllib.parse.quote(name, safe='')}", ignore_error=True)
    if container_response is not None:
        utils.debug(f"[ligoj] Group '{name}' already exists'")
        return container_response

    return call_api("POST", "service/id/group", data={"name": name, "scope": container_scope_id, "parent": parent_name})


def project_get(project_key_or_id, headers=None):
    response = call_api("GET", f"project/{project_key_or_id}", ignore_error=True, ignore_output=True, headers=headers)
    if response is None:
        return None
    return response.json()


def group_get_by_name(group):
    if unidecode(group) != group:
        raise ValueError(f"[ligoj] Group name '{group}' cannot contain non ASCII chars")

    response = call_api("GET", f"service/id/group/{urllib.parse.quote(group, safe='')}", ignore_error=True)
    return None if response is None else response.json()


def group_delete(group: str):
    utils.info(f"[ligoj] Delete group '{group}' ...")
    group_result = group_get_by_name(group)
    if group_result is None:
        utils.debug(f"[ligoj] Group '{group}' does not exist")
        return None
    return call_api("DELETE", f"service/id/group/{group_result['id']}")


def group_list():
    response = call_api("GET", "service/id/group", ignore_error=True)
    return None if response is None else response.json()


def user_add_to_group(user, group):
    utils.info(f"[ligoj] Add user '{user}' to group '{group}' ...")
    user_response = call_api("GET", f"service/id/user/{user}", ignore_error=True)
    if user_response is None:
        raise ValueError(f"[ligoj] User '{user}' does not exist")

    user_details = user_response.json()
    if group not in user_details["groups"]:
        return call_api("PUT", f"service/id/user/{user}/group/{group}")
    utils.info(f"[ligoj] User '{user}' is already in group '{group}'")
    return None


def user_remove_from_group(user, group):
    utils.info(f"[ligoj] Remove user '{user}' from group '{group}' ...")
    user_response = call_api("GET", f"service/id/user/{user}", ignore_error=True)
    if user_response is None:
        raise ValueError(f"[ligoj] User '{user}' does not exist")

    user_details = user_response.json()
    if group in user_details["groups"]:
        return call_api("DELETE", f"service/id/user/{user}/group/{group}")
    utils.info(f"[ligoj] User '{user}' is not in group '{group}'")
    return None


def user_delete(user):
    if not user:
        return False
    utils.info(f"[ligoj] Delete user '{user}' ...")
    user_response = call_api("GET", f"service/id/user/{user}", ignore_404=True)
    if user_response is None:
        utils.info(f"[ligoj] User '{user}' does not exist")
    return call_api("DELETE", f"service/id/user/{user}")


def project_create(team_leader: str, project_key: str, project_name: str, description="", context: dict | str | None = None):
    utils.info(f"[ligoj] Create project '{project_key}' having user '{team_leader}' as manager ...")
    project_details = project_get(project_key)
    if project_details is None:
        new_project = {"pkey": project_key, "name": project_name, "teamLeader": team_leader, "description": description}
        if context:
            new_project["creationContext"] = json.dumps(context) if isinstance(context, dict) else context
        call_api("POST", "project", data=new_project)
        project_details = project_get(project_key)
    return project_details


def project_delete_by_pkey(project_key: str, with_data: bool = False):
    utils.info(f"[ligoj] Delete project '{project_key}' ...")
    project_details = project_get(project_key)
    if project_details is None:
        utils.info(f"[ligoj] Project '{project_key}' does not exist or is not visible")
        return False
    return project_delete_internal(project_details["id"], with_data)


def project_delete_by_id(project_id: int, with_data: bool = False):
    utils.info(f"[ligoj] Delete project '{project_id}' ...")
    return project_delete_internal(project_id, with_data)


def project_delete_internal(project_id: int, with_data: bool = False):
    call_api("DELETE", f"project/{project_id}", params={"deleteRemoteData": with_data})
    return False


def project_list(search=str | None):
    return call_api("GET", "project", params={"search[value]": search}).json()


def delegate_org_create(managed_type, managed_id, receiver_type, receiver_id, admin_privilege, write_privilege):
    utils.info(
        f"[ligoj] Create delegate to '{receiver_type}' '{receiver_id}' to manage '{managed_type}' '{managed_id}' with admin_privilege={admin_privilege} and write_privilege={write_privilege}  ..."
    )
    delegates = call_api("GET", f"security/delegate?type={managed_type}&q={receiver_id}").json()["data"]
    if any(filter(lambda x: x["receiverType"] == receiver_type and x["name"] == managed_id, delegates)):
        utils.debug(f"[ligoj] Delegate already exists for '{receiver_id}'  ...")
    else:
        call_api(
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
    return call_api("GET", f"security/delegate/{delegate_id}")


def delegate_org_filter_by_resource(resource_type: str, resource_id: str | None):
    items = call_api("GET", "security/delegate", params={"type": resource_type}).json()["data"]
    return list(filter(lambda x: resource_id is None or resource_id == "" or x["name"] == resource_id, items))


def delegate_org_delete(delegate_id: int):
    call_api("DELETE", f"security/delegate/{delegate_id}", ignore_error=True, ignore_output=True)
    return False


def subscription_get_by_id(subscription_id: int, with_details: bool):
    utils.info(f"[ligoj] Get subscription by id '{subscription_id}' ...")
    return call_api("GET", f"subscription/{subscription_id}{'/configuration' if with_details else ''}").json()


def subscription_refresh(subscription_id: int | None):
    utils.info(f"[ligoj] Refresh subscription '{subscription_id}' ...")
    if subscription_id:
        return call_api("GET", f"subscription/status/{subscription_id}/refresh").json()
    return call_api("GET", "subscription/status/refresh").json()


def subscription_status(project: int | str | None):
    utils.info(f"[ligoj] Get subscription statuses of project '{project}' ...")
    return call_api("GET", f"subscription/status/{project}").json()


def subscription_list(node_id: str | None, tool: str | None, service: str | None, project: str | int | None) -> list:
    filters_log = {}
    if node_id:
        filters_log["node"] = node_id
    if tool:
        filters_log["node.tool"] = tool
    if service:
        filters_log["node.tool.service"] = service
    if project:
        filters_log["project"] = project
    utils.info(f"[ligoj] List subscriptions filtered by {filters_log}  ...")
    items = call_api("GET", "subscription").json()
    nodes = {n["id"]: n for n in items["nodes"]}
    projects = {p["id"]: p for p in items["projects"]}
    return list(
        filter(
            lambda s: (not node_id or node_id == s["node"])
            and (not tool or tool == nodes[s["node"]].get("refined"))
            and (not service or nodes[s["node"]].get("refined") and service == nodes[nodes[s["node"]]["refined"]].get("refined"))
            and (not project or project == projects[s["project"]]["pkey"] or project == s["project"]),
            items["subscriptions"],
        )
    )


def subscription_delete(subscription_id: int, with_data: bool | None = False):
    with_data = bool(with_data)
    utils.info(f"[ligoj] Delete subscription '{subscription_id}', with_data={with_data} ...")
    return call_api("DELETE", f"subscription/{subscription_id}/{str(with_data).lower()}", ignore_error=True)


def subscription_create(project: str | int | None, node_id: str, parameters: dict | list) -> int:
    utils.info(f"[ligoj] Create subscription related to project '{project}' and node '{node_id}' ...")
    project_details = project_get(project)
    if not project_details:
        raise ValueError(f"[ligoj] Given project {project} does not exist or is not visible")

    parameters_as_dict = node_parameters_as_dict(parameters) if isinstance(parameters, list) else parameters
    parameters_as_list = parameters if isinstance(parameters, list) else node_parameters_as_list(parameters)

    for other_subscription in subscription_list(node_id, None, None, project):
        other_subscription_details = subscription_get_by_id(other_subscription["id"], True)
        other_parameters = other_subscription_details["parameters"]
        same_parameters = True
        for parameter_id in parameters_as_dict.keys():
            if other_parameters.get(parameter_id) != parameters_as_dict[parameter_id]:
                same_parameters = False

        if same_parameters:
            utils.info(f"[ligoj] Subscription {other_subscription['id']} already exists with these parameters")
            return other_subscription["id"]

    # Need to be created
    return call_api("POST", "subscription", data={"mode": "create", "project": project_details["id"], "node": node_id, "parameters": parameters_as_list})


# Create the LDAP subscription if it does not exist yet
def subscription_create_id_group(project_id: int, project_key: str, ldap_node: str, group, parent_group=None):
    group_details = group_get_by_name(group)
    if group_details is not None:
        utils.info(f"[ligoj] Group '{group}' already exists, ignore subscription request to project '{project_key}'")
        return False

    utils.info(f"[ligoj] Group '{group}' does not already exist, create subscription to project '{project_key}'({project_id}) to node '{ldap_node}' ...")
    parameters = [{"parameter": "service:id:group", "text": group}, {"parameter": "service:id:ou", "text": project_key}]
    if parent_group is not None:
        parameters.append({"parameter": "service:id:parent-group", "text": parent_group})

    return bool(subscription_create(project_id, ldap_node, parameters))


def ldap_concat(prefix1: str, prefix2: str, base_dn: str) -> str:
    result = base_dn
    if prefix2 is not None and prefix2 != "":
        result = f"{prefix2},{result}"
    if prefix1 is not None and prefix1 != "":
        result = f"{prefix1},{result}"
    return result
