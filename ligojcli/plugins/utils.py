#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
import sys
import re
import os
import json

from configparser import ConfigParser
from os.path import expanduser
from datetime import datetime
from typing import Any
import argparse
import requests

from jinja2 import Environment, BaseLoader
from colorama import Fore, Style
import urllib3

# python -m pip install requests colorama

# Global options
user_home: str = expanduser("~")
INI_CONFIG_FILE1 = f"{user_home}/.ligoj/config"
INI_CONFIG_FILE2 = f"{user_home}/.ligoj/cli-config"
INI_CREDENTIALS_FILE = f"{user_home}/.ligoj/credentials"
INI_SESSIONS_FILE = f"{user_home}/.ligoj/sessions"
ADD_GLOBAL_ROLES = True
UPDATE_MODE_ONCE = "once"  # Roles are created only the first time. No update or addition
UPDATE_MODE_CREATE = "create"  # Roles are created and updated as necessary. No deletion. Default mode.
UPDATE_MODE_DEFAULT = UPDATE_MODE_CREATE
MIME_JSON = "application/json"
MIME_URL_ENCODED = "application/x-www-form-urlencoded"
DEFAULT_LIGOJ_PROFILE = "default"

log_level: str = "INFO"
no_color: bool = True
insecure: bool = False
buffer_log: bool = False
cookie_session = None
now_str: str = datetime.now().strftime("%Y-%m-%d-%H%M%S")
ini_profile: str | None = None
ini_config = ConfigParser()
ini_credentials = ConfigParser()
ini_sessions = ConfigParser()


def init() -> tuple[argparse.ArgumentParser, argparse._SubParsersAction]:

    # See https://docs.python.org/3/library/argparse.html
    parser = argparse.ArgumentParser(prog="Ligoj CLI", description="Ligoj CLI for REST API", allow_abbrev=False)
    parser.add_argument("--endpoint", "-e", help="Ligoj Endpoint", default=None)
    parser.add_argument("--api-user", "-u", help="Username", default=None)
    parser.add_argument("--api-run-user", "-U", help="Run as username, only when API user is an administrator", default=None)
    parser.add_argument("--api-key", help="API key", default=None)
    parser.add_argument("--profile", help="Profile name", default=None)
    parser.add_argument("--version", "-v", help="Version", action="store_true")
    parser.add_argument("--no-color", help="Disable colors in messages", action="store_true", default=False)
    parser.add_argument("--verbose", "-V", help="Enable TRACE level", action="store_true", default=False)
    parser.add_argument("--trace", "-T", help="Enable TRACE level", action="store_true", default=False)
    parser.add_argument("--debug", "-G", help="Enable DEBUG level", action="store_true", default=False)
    parser.add_argument("--log-level", "-L", choices=["TRACE", "DEBUG", "INFO", "WARN", "ERROR"], help="Specific log level", default=None)
    parser.add_argument("--output", "-o", choices=["text", "json"], help="Output mode", default=None)
    parser.add_argument("--buffer-log", "-B", help="Enable log buffering, error and output might be out of sync", default=False, action="store_true")
    parser.add_argument("--insecure", "-k", help="Allow insecure server connections when using SSL", action="store_true", default=None)
    subparser_service = parser.add_subparsers(title="service", help="Service API", dest="service")
    return (parser, subparser_service)


def configure(parser: argparse.ArgumentParser) -> tuple[str, dict[str, Any]]:
    global no_color
    global insecure
    global ini_profile
    global buffer_log
    global cookie_session
    global log_level
    args = parser.parse_args()
    args = vars(args)

    ini_read()

    ini_profile = get_config(args, "profile", "LIGOJ_PROFILE", DEFAULT_LIGOJ_PROFILE)
    no_color = args["no_color"]
    buffer_log = str(get_config(args, "buffer-log", "LIGOJ_BUFFER_LOG", "True")).lower() in ["true", "1", "yes"]
    init_logger()
    insecure = str(get_config(args, "insecure", "LIGOJ_INSECURE", "False")).lower() in ["true", "1", "yes"]
    cookie_session = get_secret(args, "session", "LIGOJ_COOKIE_SESSION", None)
    if args["verbose"] is True or args["trace"] is True:
        log_level = "TRACE"
    elif args["debug"] is True:
        log_level = "DEBUG"
    else:
        log_level = get_config(args, "log_level", "LIGOJ_LOG_LEVEL", "INFO").upper()

    if insecure is True:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    output = get_config(args, "output", "LIGOJ_OUTPUT", "json")

    return (args, output)


def not_none(value: str | None, name: str) -> str:
    if value is None or isinstance(value, str) and len(value) == 0:
        raise ValueError(f"[ligoj] Missing {name}")
    return value


def log(level: str, message, color=None, file=None):
    if level is None or level == "":
        level_str = ""
    elif no_color:
        level_str = ""
    else:
        level_str = f'[{Style.BRIGHT}{level}{Style.NORMAL}{"".rjust(5-len(level), " ")}]'
    print(f"{'' if no_color or color is None else color}{level_str} {message}{'' if no_color or color is None else Style.RESET_ALL}", file=file)


def trace(message):
    if log_level in ["TRACE"]:
        log("TRACE", message, Fore.CYAN)


def debug(message):
    if log_level in ["DEBUG", "TRACE"]:
        log("DEBUG", message, Fore.BLUE)


def info(message):
    if log_level in ["INFO", "DEBUG", "TRACE"]:
        log("INFO", message, Fore.GREEN)


def warn(message):
    if log_level in ["INFO", "DEBUG", "TRACE", "WARN"]:
        log("WARN", message, Fore.YELLOW)


def error(message):
    log("ERROR", message, Fore.RED, sys.stderr)


def get_temp_file_from(from_location):
    if from_location.startswith("http:") or from_location.startswith("https:"):
        response = requests.get(from_location, stream=True, verify=not insecure, timeout=30)
        upload_file = ".temp.jar"
        download_file(response, upload_file)
    else:
        upload_file = from_location
    return upload_file


def download_file(response, upload_file):
    chunk_size = 10 * 1024 * 1024
    with open(upload_file, "wb") as out:
        for chunk in response.iter_content(chunk_size=chunk_size):
            out.write(chunk)


def delete_temp_file_from(from_location, upload_file):
    if from_location.startswith("http:") or from_location.startswith("https:"):
        os.remove(upload_file)
    return upload_file


def call_rest_api(method: str, component: str, endpoint: str, url: str, auth: tuple[str] | None, kwargs=None):
    if kwargs is None:
        kwargs = {}
    dict_data = kwargs.get("data", {})
    query_parameters = kwargs.get("params", {})
    headers = kwargs["headers"] if "headers" in kwargs else {}
    ignore_error = kwargs.get("ignore_error", False) is True
    ignore_500 = kwargs.get("ignore_500", False) is True
    ignore_412 = kwargs.get("ignore_412", False) is True
    ignore_409 = kwargs.get("ignore_409", False) is True
    ignore_404 = kwargs.get("ignore_404", False) is True
    ignore_400 = kwargs.get("ignore_400", False) is True
    full_url = re.sub("([^:]/)/", "\\1", re.sub("([^:]/)/", "\\1", f"{endpoint}/{url}"))
    message_url = f"[{component}] API call {method} {full_url if log_level in ['TRACE'] else url}"
    message_req = f"{message_url}{f' ?{query_parameters}' if len(query_parameters.keys()) else ''} {dict_data if isinstance(dict_data, dict) and len(dict_data.keys()) else ''}"
    if log_level in ["TRACE"]:
        trace(f"{message_req} -- {headers if len(headers.keys()) else ''} -- {kwargs.get('cookies') if len(kwargs.get('cookies', {}).keys()) else ''} ...")
    else:
        debug(f"{message_req} ...")

    session = kwargs.get("session")
    if session is None or session is True or session is False:
        session = requests.Session()
        kwargs["session"] = session
        session.auth = auth
    if kwargs.get("files"):
        request_headers = headers
    elif isinstance(dict_data, dict):
        request_headers = {"Content-Type": MIME_JSON, "Accept": MIME_JSON} | headers
    else:
        request_headers = {"Content-Type": MIME_URL_ENCODED, "Accept": MIME_JSON} | headers

    try:
        if (dict_data is None or isinstance(dict_data, dict)) and "files" not in kwargs:
            response = session.request(
                method, full_url, params=query_parameters, json=dict_data, stream=kwargs.get("stream", False), headers=request_headers, verify=not insecure, cookies=kwargs.get("cookies")
            )
        else:
            response = session.request(
                method,
                full_url,
                params=query_parameters,
                data=dict_data,
                files=kwargs.get("files"),
                stream=kwargs.get("stream", False),
                headers=request_headers,
                verify=not insecure,
                cookies=kwargs.get("cookies"),
            )
    except Exception as e:
        raise ValueError(f"[{component}] API call failed", e) from e

    # Unconditional exit codes
    if response.status_code == 504:
        raise ValueError(f"{message_url} ({response.status_code}), failed with internal timeout")
    if response.status_code in [501, 502, 503]:
        raise ValueError(f"{message_url} ({response.status_code}), failed with technical error, {response.text}")
    if response.status_code == 403:
        raise ValueError(f"{message_url} ({response.status_code}), check your credentials, {response.text}")
    if response.status_code == 405:
        raise ValueError(f"{message_url} ({response.status_code}) is not a valid path or method, {response.text}")
    if response.status_code == 401:
        raise ValueError(f"{message_url} ({response.status_code}), check your authorizations, {response.text}")

    # Escapable codes
    if response.status_code in [412, 409]:
        if ignore_error or ignore_412 or ignore_409:
            trace(f"{message_url} {response.status_code}, object was previously created, {response.text}")
        else:
            raise ValueError(f"{message_url} ({response.status_code}), object was previously created")
        return None
    elif response.status_code == 404:
        if ignore_error or ignore_404:
            trace(f"{message_url} {response.status_code}, object not found, {response.text}")
        else:
            raise ValueError(f"{message_url} ({response.status_code}), object not found, {response.text}")
        return None
    elif response.status_code == 400:
        if ignore_error or ignore_400:
            trace(f"{message_url} {response.status_code}, invalid input, {response.text}")
        else:
            raise ValueError(f"{message_url} ({response.status_code}), invalid input, {response.text}")
        return None
    elif response.status_code == 204:
        trace(f"{message_url} ({response.status_code}), no result")
        return None

    if response.status_code not in [200, 201, 202, 204, 400, 404, 409, 412]:
        message = ""
        try:
            message = response.json()
        except BaseException as _ignore:
            try:
                message = response.text
            except BaseException as _ignore2:
                message = str(response)
        if ignore_error or ignore_500:
            trace(f"{message_url} failed with code {response.status_code}, message={message} (ignored error)")
            return None
        raise ValueError(f"{message_url} failed with code {response.status_code}, message={message}")
    try:
        trace(f"{message_url} ({response.status_code}), {'(ignored output)' if kwargs.get('ignore_output', False) else response.json()}")
    except BaseException as _ignore:
        try:
            trace(f"{message_url} ({response.status_code}), {'(ignored output)' if kwargs.get('ignore_output', False) else response.text}")
        except BaseException as _ignore2:
            trace(f"{message_url} ({response.status_code}), (no response)")

    if kwargs.get("return_headers", False):
        return response.headers
    return response


def flat_map_group(groups):
    if groups is None:
        return []
    return list(filter(lambda x: len(x) > 0, (y for g in groups for y in re.split("[, ;]", g))))


def ini_read():
    # Parse local configuration files
    ini_config.read(INI_CONFIG_FILE1 if os.path.isfile(INI_CONFIG_FILE1) else INI_CONFIG_FILE2)
    ini_credentials.read(INI_CREDENTIALS_FILE)
    ini_sessions.read(INI_SESSIONS_FILE)


def ini_credentials_write():
    with open(INI_CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        ini_credentials.write(f)


def ini_sessions_write():
    with open(INI_SESSIONS_FILE, "w", encoding="utf-8") as f:
        ini_sessions.write(f)


def cleanup_ini_value(value: str | None) -> str | bool:
    if isinstance(value, str) and (value.startswith("'") and value.endswith("'") or value.startswith('"') and value.endswith('"')):
        value = value[1:-1]
    return None if isinstance(value, str) and len(value) == 0 else value


# Return secret from options, environment variable, credentials file or configuration file.
def get_secret(args, name: str, env_variable_name: str, default: str | None) -> str:
    value = args.get(name)
    if value is None:
        value = os.environ.get(env_variable_name)
        if value is None or isinstance(value, str) and len(value) == 0:
            value = ini_sessions.get(ini_profile, name, fallback=None)
        if value is None or isinstance(value, str) and len(value) == 0:
            value = ini_credentials.get(ini_profile, name, fallback=None)
        if value is None or isinstance(value, str) and len(value) == 0:
            value = ini_config.get(ini_profile, name, fallback=default)
    return cleanup_ini_value(value)


# Return configuration value from options, environment variable or configuration file.
def get_config(args, name: str, env_variable_name: str, default: str | None) -> str | bool:
    value = args.get(name)
    if value is None:
        value = os.environ.get(env_variable_name)
        if value is None or isinstance(value, str) and len(value) == 0:
            value = ini_config.get(ini_profile, name, fallback=default)
    return cleanup_ini_value(value)


def is_true(value: str | bool | None) -> bool:
    return value == "True" or value == "true" or value == "1" or value is True


def init_logger():
    if not buffer_log:

        class Unbuffered:
            def __init__(self, stream):
                self.stream = stream

            def write(self, data):
                self.stream.write(data)
                self.stream.flush()

            def writelines(self, data):
                self.stream.writelines(data)
                self.stream.flush()

            def __getattr__(self, attr):
                return getattr(self.stream, attr)

        # Disable output buffering
        sys.stdout.flush()
        sys.stdout = Unbuffered(sys.stdout)


def interpolate(input_string: str, context):
    pattern = r"\{\{\s*(\w+)\s*\}\}"

    # Function to replace each match
    def replace_match(match):
        property_name = match.group(1)
        return str(context.get(property_name, "")) if context.get(property_name) is not None else ""

    # Substitute all matches in the input_string using the replace_match function
    result = re.sub(pattern, replace_match, input_string)
    return result


def load_json_from_url_or_file_with_interpolation(location: str | None, context: dict[str, str | None]):
    obj = load_json_from_url_or_file(location)
    if obj:
        template_as_string = json.dumps(obj)
        template = Environment(loader=BaseLoader).from_string(template_as_string)
        return json.loads(template.render({"env": os.environ} | (context or {})))
    return obj


def load_json_from_url_or_file(location: str | None) -> dict[str, Any] | None:
    if location is None:
        return None
    if location.startswith("http:") or location.startswith("https:"):
        return json.loads(requests.get(location, verify=not insecure, timeout=5).text)
    if location.startswith("{") or location.startswith("["):
        return json.loads(location)
    with open(location, "r", -1, "UTF-8") as f:
        return json.load(f)


# Check the given endpoint is not a resource URL
def check_endpoint(url: str, name: str):
    if re.match(r".*\.[A-Za-z0-9]{3,4}$", url):
        raise ValueError(f"[ligoj] Given URL for {name} does not look like a valid endpoint. Extension detected")
    if not re.match(r"^https?://.*$", url):
        raise ValueError(f"[ligoj] Given URL for {name} does not look like a valid endpoint. No valid scheme")
