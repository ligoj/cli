#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-qa-sonarqube: register a local SonarQube node and link the demo project to the
# plugin-ui analysis.
#
# Ligoj's SonarQube plugin authenticates with a login + password (not a token) and requires that user
# to have administration rights (the `sonar-login` / `sonar-rights` validations). The `dev init` admin
# password is not reused here (it becomes unreliable once Sonar is recreated), so — using the API token
# from `dev init` — the demo provisions a dedicated `ligoj` user, sets a known password and grants it
# global admin. The linked Sonar project is created empty first (link mode needs it to pre-exist); the
# seed phase's `sonar:sonar` fills it in afterwards.
#
import requests

from ligojcli.dev_demo import _common, _subscribe
from ligojcli.plugins import utils

ARTIFACT = "plugin-qa-sonarqube"
NODE = "service:qa:sonarqube:local"
# The Sonar project linked to the demo project (matches the plugin-ui analysis run by the seed phase).
PROJECT_KEY = "org.ligoj.plugin:plugin-ui"
PROJECT_NAME = "Ligoj - Plugin UI"
_TIMEOUT = 30


def run(args):
    token = _token(args)
    if not token:
        utils.warn(
            "[dev] sonar: no API token in [dev] (sonar_api_token); skipping the SonarQube demo"
        )
        return
    url = _url(args)
    user = _common.dev_value(args, "sonar_demo_user", "SONAR_DEMO_USER", "ligoj")
    # SonarQube enforces a strong policy (>= 12 chars, upper + lower + digit + special), so the
    # default is deliberately compliant.
    password = _common.dev_value(
        args, "sonar_demo_password", "SONAR_DEMO_PASSWORD", "Ligoj-Demo-Pass1!"
    )
    _ensure_admin_user(url, token, user, password)
    _common.upsert_node(
        NODE,
        "SonarQube Local (CLI)",
        {
            "service:qa:sonarqube:url": url,
            "service:qa:sonarqube:user": user,
            "service:qa:sonarqube:password": password,
        },
    )


def subscribe(args, project):
    token = _token(args)
    if not token:
        return
    # Link mode needs the Sonar project to pre-exist; create it empty (the seed's analysis fills it).
    _post(_url(args), token, "/api/projects/create", {"project": PROJECT_KEY, "name": PROJECT_NAME})
    _subscribe.link(
        project, NODE, [{"parameter": "service:qa:sonarqube:project", "text": PROJECT_KEY}]
    )


def _token(args):
    return _common.dev_value(args, "sonar_api_token", "SONAR_API_TOKEN", None)


def _url(args):
    return _common.dev_value(
        args, "sonar_endpoint", "SONAR_ENDPOINT", "http://localhost:9000"
    ).rstrip("/")


def _ensure_admin_user(url, token, user, password):
    """Create (idempotent) a dedicated Sonar user with a known password and global admin rights."""
    created = _post(
        url, token, "/api/users/create", {"login": user, "name": user, "password": password}
    )
    if created is not None and created.status_code == 200:
        utils.info(f"[dev] sonar: created user '{user}'")
    elif created is not None and created.status_code == 400:
        # User already exists: (re)set the known password (admin token, no previous password needed).
        # A "must be different" rejection just means it already had this password — harmless.
        changed = _post(
            url, token, "/api/users/change_password", {"login": user, "password": password}
        )
        if (
            changed is not None
            and changed.status_code not in (200, 204)
            and "different" not in (changed.text or "").lower()
        ):
            utils.warn(f"[dev] sonar: set password for '{user}': {(changed.text or '')[:120]}")
    elif created is not None:
        utils.warn(
            f"[dev] sonar: create user '{user}': {created.status_code} {(created.text or '')[:120]}"
        )
    _post(url, token, "/api/permissions/add_user", {"login": user, "permission": "admin"})


def _post(url, token, path, params):
    """POST to the Sonar API authenticated with the token as login (empty password)."""
    try:
        return requests.post(f"{url}{path}", params=params, auth=(token, ""), timeout=_TIMEOUT)
    except requests.RequestException as error:
        utils.warn(f"[dev] sonar: POST {path}: {error}")
        return None
