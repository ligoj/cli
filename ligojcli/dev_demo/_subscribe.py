#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Shared helpers for the "link" phase of `dev demo`: create the demo projects and, for each demo
# tool node, create a subscription in **link** mode. Link mode means the referenced resource already
# exists on the remote tool, so every helper here first provisions that resource (a Nexus/Artifactory
# repository, a Harbor project, a GitLab project, an LDAP group) via the tool's own REST API using the
# credentials stored in the [dev] section, then hands the reference to Ligoj.
#
import requests

from ligojcli.plugins import ligoj, utils

# Ligoj project keys must match ^([a-z]|\d+-?[a-z])[a-z\d\-]*$ (no colon), so "demo:1" -> "demo-1".
PROJECTS = [("demo-1", "Démo #1"), ("demo-2", "Démo #2"), ("demo-3", "Démo #3")]
# Only this project receives link subscriptions; demo-2 / demo-3 stay empty.
LINK_PROJECT = "demo-1"
# Registry types the demo provisions and subscribes, when the tool actually supports them.
REGISTRY_TYPES = ["docker", "maven"]
_TIMEOUT = 30


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #
def ensure_projects(team_leader):
    """Create the three demo projects (idempotent). Returns the list of created/existing pkeys."""
    pkeys = []
    for pkey, name in PROJECTS:
        try:
            ligoj.project_create(team_leader, pkey, name, "Ligoj CLI demo project")
            pkeys.append(pkey)
        except Exception as error:  # noqa: BLE001 - one project must not abort the others
            utils.warn(f"[dev] project {pkey}: {error}")
    return pkeys


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #
def link(project, node, params):
    """Create (idempotent) a link-mode subscription and validate it. Returns its id or None."""
    try:
        result = ligoj.subscription_create(project, node, params, "link")
        # subscription_create returns the id of an existing match, or the POST response for a new one.
        sub_id = result.json() if hasattr(result, "json") else result
        status = _refresh(sub_id)
        utils.info(f"[dev] linked {node} -> {project} (subscription {sub_id}, status {status})")
        return sub_id
    except Exception as error:  # noqa: BLE001 - keep configuring the other nodes/types
        utils.warn(f"[dev] subscribe {node} -> {project}: {error}")
        return None


def create(project, node, params=None):
    """Create (idempotent) a 'create'-mode subscription (e.g. a provisioning quote). Returns id/None.

    Unlike `link`, this asks the tool to *create* its backing resource. A provisioning quote needs a
    price catalog to have been imported first; that specific case is reported as a (non-fatal) hint
    rather than a raw error, since it clears itself once the catalog exists.
    """
    try:
        result = ligoj.subscription_create(project, node, params or [], "create")
        sub_id = result.json() if hasattr(result, "json") else result
        status = _refresh(sub_id)
        utils.info(f"[dev] created {node} -> {project} (subscription {sub_id}, status {status})")
        return sub_id
    except Exception as error:  # noqa: BLE001 - keep configuring the other nodes/types
        if "catalog" in str(error).lower():
            utils.warn(
                f"[dev] {node}: cannot create the quote yet — import a price catalog first "
                "(prov UI or the catalog API), then re-run 'dev demo'"
            )
        else:
            utils.warn(f"[dev] subscribe {node} -> {project}: {error}")
        return None


def _refresh(sub_id):
    resp = ligoj.call_api(
        "GET", f"subscription/status/{sub_id}/refresh", ignore_error=True, ignore_output=True
    )
    try:
        return resp.json().get("status") if resp is not None else "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _link_params(node):
    """Discover the link-mode parameter definitions of a node as {parameter id: definition}."""
    resp = ligoj.call_api(
        "GET", f"node/{node}/parameter/link", ignore_error=True, ignore_output=True
    )
    return {p["id"]: p for p in resp.json()} if resp is not None else {}


def registry_subscribe(project, node, ensure_repo):
    """Provision and link one registry per demo type the tool supports.

    `ensure_repo(rtype)` creates the resource on the tool and returns its reference name (or None to
    skip). The registry `type` is a Ligoj select, so it is sent as the index of the discovered value.
    """
    stem = node.rsplit(":", 1)[0]  # e.g. service:registry:nexus
    type_param, registry_param = f"{stem}:type", f"{stem}:registry"
    supported = (_link_params(node).get(type_param) or {}).get("values") or []
    for rtype in REGISTRY_TYPES:
        if rtype not in supported:
            continue
        reference = ensure_repo(rtype)
        if not reference:
            continue
        link(
            project,
            node,
            [
                {"parameter": type_param, "index": supported.index(rtype)},
                {"parameter": registry_param, "text": reference},
            ],
        )


# --------------------------------------------------------------------------- #
# Remote tool resources (created so the link mode has something to reference)
# --------------------------------------------------------------------------- #
def _call(method, url, **kwargs):
    try:
        return requests.request(method, url, timeout=_TIMEOUT, **kwargs)
    except requests.RequestException as error:
        utils.warn(f"[dev] {method} {url}: {error}")
        return None


def nexus_ensure_repo(endpoint, user, password, rtype, name, docker_http_port=None):
    """Create/update a Nexus hosted repository of the given format. Returns its name, or None.

    For docker, `docker_http_port` opens a registry connector on that port so images can be pushed;
    an existing repo is updated (PUT) to make sure the connector is present.
    """
    recipe = {"maven": "maven/hosted", "docker": "docker/hosted"}.get(rtype)
    if not recipe:
        return None
    body = {
        "name": name,
        "online": True,
        "storage": {
            "blobStoreName": "default",
            "strictContentTypeValidation": True,
            "writePolicy": "ALLOW",
        },
    }
    if rtype == "maven":
        body["maven"] = {
            "versionPolicy": "MIXED",
            "layoutPolicy": "STRICT",
            "contentDisposition": "INLINE",
        }
    else:  # docker
        body["docker"] = {"v1Enabled": False, "forceBasicAuth": True}
        if docker_http_port:
            body["docker"]["httpPort"] = int(docker_http_port)
    base = f"{endpoint}/service/rest/v1/repositories/{recipe}"
    resp = _call("POST", base, auth=(user, password), json=body)
    if resp is not None and resp.status_code == 201:
        return name
    if resp is not None and _already_exists(resp):
        # Ensure an existing docker repo has (the right) connector port.
        if rtype == "docker" and docker_http_port:
            _call("PUT", f"{base}/{name}", auth=(user, password), json=body)
        return name
    _warn_resource("nexus repo", name, rtype, resp)
    return None


def artifactory_ensure_repo(endpoint, user, password, rtype, key):
    """Resolve an Artifactory local repository for a link subscription. Returns its key, or None.

    On Artifactory Pro a missing repository is created via REST. On OSS both repository creation and
    per-repository reads are Pro-only, so an existing repository (e.g. created by hand in the UI) is
    detected through the OSS-compatible listing instead; Docker — which OSS does not support at all —
    is skipped without noise.
    """
    if _artifactory_repo_exists(endpoint, user, password, key):
        return key
    resp = _call(
        "PUT",
        f"{endpoint}/api/repositories/{key}",
        auth=(user, password),
        json={"rclass": "local", "packageType": rtype},
        headers={"Content-Type": "application/json"},
    )
    if resp is not None and (resp.status_code in (200, 201) or _already_exists(resp)):
        return key
    if resp is not None and "artifactory pro" in (resp.text or "").lower():
        # Artifactory OSS: no repository-creation REST API.
        if rtype == "docker":
            return None  # OSS has no Docker package type; nothing to manage, skip quietly.
        utils.warn(
            f"[dev] artifactory: '{key}' ({rtype}) not found — create it once in the OSS UI "
            "(OSS cannot create repositories via REST); it is then detected and linked on the "
            "next 'dev demo' run"
        )
        return None
    _warn_resource("artifactory repo", key, rtype, resp)
    return None


def _artifactory_repo_exists(endpoint, user, password, key):
    """True when the repository exists, via the listing (OSS-compatible, unlike the per-repo read)."""
    resp = _call("GET", f"{endpoint}/api/repositories", auth=(user, password))
    if resp is None or resp.status_code != 200:
        return False
    try:
        return any(repo.get("key") == key for repo in resp.json())
    except ValueError:
        return False


def harbor_ensure_project(endpoint, user, password, name):
    """Create a Harbor project (docker/OCI). Returns its name, or None."""
    resp = _call(
        "POST",
        f"{endpoint}/api/v2.0/projects",
        auth=(user, password),
        json={"project_name": name, "public": True, "metadata": {"public": "true"}},
    )
    if resp is not None and (resp.status_code in (200, 201) or resp.status_code == 409):
        return name
    _warn_resource("harbor project", name, "docker", resp)
    return None


def gitlab_ensure_project(endpoint, user, token, path):
    """Create a GitLab project owned by `user`. Returns its path (the Ligoj reference), or None."""
    headers = {"PRIVATE-TOKEN": token}
    resp = _call(
        "POST",
        f"{endpoint}/api/v4/projects",
        headers=headers,
        json={"name": path, "path": path, "visibility": "private"},
    )
    if resp is not None and resp.status_code in (200, 201):
        return path
    # Already exists (or no create rights): confirm it is reachable at <user>/<path>.
    look = _call(
        "GET",
        f"{endpoint}/api/v4/projects/{requests.utils.quote(f'{user}/{path}', safe='')}",
        headers=headers,
    )
    if look is not None and look.status_code == 200:
        return path
    _warn_resource("gitlab project", path, "git", resp)
    return None


_JENKINS_JOB_XML = (
    "<?xml version='1.1' encoding='UTF-8'?>\n"
    "<project><description>Ligoj CLI demo</description><keepDependencies>false</keepDependencies>"
    "<scm class='hudson.scm.NullSCM'/><canRoam>true</canRoam><disabled>false</disabled>"
    "<triggers/><builders/><publishers/><buildWrappers/></project>"
)


def jenkins_ensure_job(endpoint, user, token, name):
    """Create a Jenkins free-style job (best effort). Returns its name, or None."""
    resp = _call(
        "POST",
        f"{endpoint}/createItem?name={requests.utils.quote(name)}",
        auth=(user, token),
        headers={"Content-Type": "application/xml"},
        data=_JENKINS_JOB_XML.encode("utf-8"),
    )
    if resp is not None and (resp.status_code in (200, 201) or resp.status_code == 400):
        return name  # 400 => a job with this name already exists
    _warn_resource("jenkins job", name, "job", resp)
    return None


def _already_exists(resp):
    if resp is None or resp.status_code not in (400, 409):
        return False
    text = (resp.text or "").lower()
    return any(
        phrase in text
        for phrase in ("already exist", "already used", "already in use", "must be unique")
    )


def _warn_resource(kind, name, rtype, resp):
    code = getattr(resp, "status_code", "no-response")
    body = (getattr(resp, "text", "") or "")[:150]
    utils.warn(f"[dev] {kind} '{name}' ({rtype}) not created: {code} {body}")
