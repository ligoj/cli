#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# `dev update` — bring the demo services created by `dev init` to a newer version, keeping their
# data and the credentials stored in [dev].
#
# For each service, in `dev init` order (PostgreSQL first, the kind services last):
#   * read the version it runs: the image tag, or for a floating tag (':latest', 'postgres:17') the
#     image itself (env, label, or the GitLab VERSION file);
#   * list the upstream releases ('podman search --list-tags', 'helm search repo') and pick the
#     target within the safe range (see dev_update_versions): same PostgreSQL major, one GitLab
#     required stop, same Artifactory major, same chart major for Harbor/ArgoCD;
#   * `--check` stops there and only reports;
#   * otherwise pull the image (always: a floating tag gets its newest build), and when it differs
#     from the running one, replay the pod manifest written by `dev init` with the new image only —
#     same volumes, same env, so no password or token is regenerated — and save the image in [dev]
#     right away (its data may already be migrated); then wait for health and run the post-upgrade
#     step of the service. A pod that was stopped is stopped again;
#   * `--force` crosses the safe range, after a snapshot under ~/.ligoj/dev/snapshots (volumes, the
#     dedicated database of a shared-PostgreSQL service, the pod manifest) whose restore commands are
#     logged and saved in RESTORE.txt. A new PostgreSQL major is a dump/restore into a new volume,
#     the old one being kept. Helm releases rely on 'helm rollback'.
#
import json
import os
import re
import shutil
import subprocess
import time

import requests
import yaml

from ligojcli import dev_update_versions as versions
from ligojcli.plugins import dev, utils

SNAPSHOT_DIR = os.path.join(utils.user_home, ".ligoj", "dev", "snapshots")
# Services keeping their data in the shared PostgreSQL, stopped while it changes major.
SHARED_DB_SERVICES = ("keycloak", "sonarqube", "artifactory")
# What this run started only as a dependency ("postgresql", "kind"), stopped again at the end, and
# the services left running because their (re)start was not confirmed healthy (--wait 0, timeout).
_STARTED = set()
_LEFT_RUNNING = set()
GITLAB_UPGRADE_PATH_URL = (
    "https://gitlab.com/gitlab-org/gitlab/-/raw/master/config/upgrade_path.yml"
)

# Podman pods: service -> (pod, [dev] image key, dedicated database in the shared PostgreSQL)
PODS = {
    "postgresql": (dev.POSTGRES_CONTAINER, "db_image", None),
    "openldap": ("openldap", "ldap_image", None),
    "keycloak": (dev.KEYCLOAK_CONTAINER, "keycloak_image", "keycloak"),
    "jenkins": ("jenkins", "jenkins_image", None),
    "sonarqube": ("sonarqube", "sonar_image", "sonarqube"),
    "gitlab": ("gitlab", "gitlab_image", None),
    "nexus": ("nexus", "nexus_image", None),
    "artifactory": ("artifactory", "artifactory_image", "artifactory"),
}
# Helm releases on the kind cluster: service -> (release, namespace, chart, repo, repo URL, [dev] key)
CHARTS = {
    "harbor": (
        dev.HARBOR_RELEASE,
        dev.HARBOR_NAMESPACE,
        dev.HARBOR_CHART,
        dev.HARBOR_REPO_NAME,
        dev.HARBOR_REPO_URL,
        "harbor_chart_version",
    ),
    "argocd": (
        dev.ARGOCD_RELEASE,
        dev.ARGOCD_NAMESPACE,
        dev.ARGOCD_CHART,
        dev.ARGOCD_REPO_NAME,
        dev.ARGOCD_REPO_URL,
        "argocd_chart_version",
    ),
}
# Environment a pod manifest written by an older 'dev init' may lack, added when its image is swapped.
MANIFEST_ENV = {
    # Recent OSS images enable JFrog Connect without shipping it: the UI then hangs (see dev.py).
    "artifactory": {"JF_JFCONNECT_ENABLED": "false"},
}
# Where the real version of a floating tag is read from, in the image the container runs.
_PROBES = {
    "postgresql": ("env", "PG_VERSION"),
    "openldap": ("env", "APP_VERSION"),
    "jenkins": ("env", "JENKINS_VERSION"),
    "nexus": ("label", "release"),
    "gitlab": ("file", "/opt/gitlab/embedded/service/gitlab-rails/VERSION"),
}
_COLUMNS = ["service", "current", "target", "newest", "result", "reason"]
_RESULT_LEVELS = {
    "update available": "warn",
    "updated": "ok",
    "refreshed": "ok",
    "pinned": "ok",
    "up to date": "ok",
    "held back": "warn",
    "skipped": "warn",
    "failed": "bad",
}


def execute(args):
    requested = list(args.get("update_service") or []) or list(dev.SERVICES)
    # 'dev init' order, the kind services (sharing one node) last.
    services = [service for service in dev.SERVICES if service in requested]
    services = [s for s in services if s not in CHARTS] + [s for s in services if s in CHARTS]
    force = bool(args.get("force"))
    if args.get("check"):
        render([check_row(service, force) for service in services], args)
        return False
    _STARTED.clear()
    _LEFT_RUNNING.clear()
    rows = []
    for service in services:
        failed_db = any(r["service"] == "postgresql" and r["result"] == "failed" for r in rows)
        if failed_db and service in SHARED_DB_SERVICES and not _postgres_ready():
            # Their data is in the shared PostgreSQL, which is not answering.
            rows.append(_row(service, result="skipped", reason="postgresql failed, not ready"))
            continue
        rows.append(update_row(service, force, args))
    _stop_started()
    render(rows, args)
    failed = [row["service"] for row in rows if row["result"] == "failed"]
    if failed:
        raise ValueError(f"[dev] Update failed for: {', '.join(failed)}")
    return False


# --------------------------------------------------------------------------- #
# Current state
# --------------------------------------------------------------------------- #
def pod_state(service):
    """{image, image_id, repository, tag, version, running} of a service pod; None when absent."""
    pod = PODS[service][0]
    container = dev._pod_container(pod)
    if not dev._pod_exists(pod) or not dev._container_exists(container):
        return None
    image = dev._container_image(container)
    image_id = dev._podman("inspect", "--format", "{{.Image}}", container).stdout.strip()
    pinned = _manifest_image(pod)
    if pinned and pinned != image and _image_id(pinned) == image_id:
        image = pinned  # pinned by a previous 'dev update' without restarting the pod
    repository, tag = _split_image(image)
    floating = versions.shape_of(tag) is None
    return {
        "image": image,
        "image_id": image_id,
        "repository": repository,
        "tag": tag,
        "version": probe_version(service, image_id) if floating else None,
        "running": dev._pod_running(pod),
    }


def _manifest_image(pod):
    path = dev._manifest_path(pod)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["spec"]["containers"][0].get("image")


def _image_id(image):
    result = dev._podman("image", "inspect", "--format", "{{.Id}}", image, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _split_image(image):
    # 'host:5000/repo:tag' -> ('host:5000/repo', 'tag'); a tag never contains '/'.
    repository, sep, tag = image.rpartition(":")
    if not sep or "/" in tag:
        return image, "latest"
    return repository, tag


def probe_version(service, image):
    """Real version of a floating-tag image (by name or id), None when unknown."""
    kind, name = _PROBES.get(service, (None, None))
    if kind == "env":
        env = dev._podman(
            "image", "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}", image
        ).stdout.splitlines()
        value = next((line.split("=", 1)[1] for line in env if line.startswith(f"{name}=")), "")
    elif kind == "label":
        value = dev._podman(
            "image", "inspect", "--format", f'{{{{index .Labels "{name}"}}}}', image
        ).stdout
    elif kind == "file":
        value = dev._podman("run", "--rm", "--entrypoint", "cat", image, name, check=False).stdout
    else:
        return None
    found = re.match(r"\d+(?:\.\d+)*", (value or "").strip())
    return versions.parse_version(found.group(0)) if found else None


def chart_state(service):
    """{version, running} of a kind Helm release; None when the cluster or the release is absent.

    A stopped kind node cannot answer helm: the version saved in [dev] is used, if any.
    """
    release, namespace, chart, _repo, _url, key = CHARTS[service]
    if shutil.which("kind") is None or shutil.which("helm") is None:
        return None
    if dev.KIND_CLUSTER not in dev._kind("get", "clusters", check=False).stdout.split():
        return None
    if not dev._container_is_running(f"{dev.KIND_CLUSTER}-control-plane"):
        return {"version": dev._dev_stored(key), "running": False}
    listed = dev._helm(
        "list",
        "--namespace",
        namespace,
        "--kube-context",
        f"kind-{dev.KIND_CLUSTER}",
        "--output",
        "json",
        "--filter",
        f"^{release}$",
    ).stdout
    releases = json.loads(listed or "[]")
    if not releases:
        return None
    return {
        "version": releases[0]["chart"].removeprefix(chart.split("/")[-1] + "-"),
        "running": True,
    }


# --------------------------------------------------------------------------- #
# Upstream releases
# --------------------------------------------------------------------------- #
def upstream_tags(repository):
    result = dev._podman(
        "search", "--list-tags", "--limit", "100000", "--format", "{{.Tag}}", repository
    )
    return result.stdout.split()


def chart_versions(service):
    _release, _namespace, chart, repo, url, _key = CHARTS[service]
    # Captured, not streamed: '-o json' output must stay parseable.
    dev._helm("repo", "add", repo, url, check=False)
    dev._helm("repo", "update", repo)
    found = dev._helm("search", "repo", chart, "--versions", "--output", "json").stdout
    return [entry["version"] for entry in json.loads(found or "[]")]


def gitlab_stops():
    response = requests.get(GITLAB_UPGRADE_PATH_URL, timeout=30)
    response.raise_for_status()
    return versions.parse_stops(response.text)


# --------------------------------------------------------------------------- #
# Check
# --------------------------------------------------------------------------- #
def _row(service, current="", target="", newest="", result="", reason=""):
    return {
        "service": service,
        "current": current,
        "target": target,
        "newest": newest,
        "result": result,
        "reason": reason,
    }


def _current_label(state):
    if state.get("version") is None:
        return state["tag"]
    return f"{state['tag']} ({'.'.join(map(str, state['version']))})"


def plan_service(service, force):
    """(state, decision, crosses) of a service; state None when it was never created by 'dev init'.

    'crosses' tells the forced decision goes beyond the safe range, so a snapshot comes first.
    """
    if service in CHARTS:
        state = chart_state(service)
        if state is None:
            return None, None, False
        if state["version"] is None:
            return (
                state,
                versions.Decision(
                    held=f"kind node stopped, current chart version unknown ('dev start {service}')"
                ),
                False,
            )
        state["tag"] = state["version"]
        state["version"] = None
        tags, stops = chart_versions(service), None
    else:
        state = pod_state(service)
        if state is None:
            return None, None, False
        stops = gitlab_stops() if service == "gitlab" else None
        tags = [] if service in versions.LEGACY else upstream_tags(state["repository"])
    decision = versions.decide(service, state["tag"], state["version"], tags, force, stops)
    safe = versions.decide(service, state["tag"], state["version"], tags, False, stops)
    return state, decision, force and decision.targets != safe.targets


def check_row(service, force):
    try:
        state, decision, crosses = plan_service(service, force)
    except (ValueError, requests.RequestException) as error:
        return _row(service, result="failed", reason=str(error).splitlines()[0])
    if state is None:
        return _row(service, result="skipped", reason=f"run 'ligoj dev init {service}' first")
    current = _current_label(state) if "tag" in state else ""
    target = decision.targets[-1] if decision.targets else ""
    if target and _is_newer(target, state):
        result = "update available"
    elif target or service in versions.LEGACY:
        result = "up to date"
    elif decision.held and "--force" in decision.held:
        result = "held back"
    elif decision.held:
        result = "skipped"  # nothing to compare with: unknown version, tag or upstream
    else:
        result = "up to date"
    reason = decision.held or ""
    if target and not _is_newer(target, state) and target != state.get("tag"):
        reason = f"pins '{state['tag']}' to '{target}'"
    if crosses:
        reason = "crosses the safe range: snapshot first" + (f"; {reason}" if reason else "")
    return _row(service, current, target, decision.newest or "", result, reason)


def _is_newer(target, state):
    shape = versions.shape_of(target)
    target_version = shape.match(target) if shape else None
    current = state.get("version")
    if current is None:
        current_shape = versions.shape_of(state.get("tag", ""))
        current = current_shape.match(state["tag"]) if current_shape else None
    return target_version is not None and (current is None or target_version > current)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def render(rows, args):
    """Table (default), tab-separated text or JSON, like 'dev backup list'."""
    mode = args.get("output") or "table"
    if mode == "json":
        print(json.dumps(rows, indent=2))
        return
    if mode == "text":
        for row in rows:
            print("\t".join(str(row[key]) for key in _COLUMNS))
        return
    headers = [key.upper() for key in _COLUMNS]
    data = [[str(row[key]) for key in _COLUMNS] for row in rows]
    widths = [max(len(headers[i]), *(len(line[i]) for line in data)) for i in range(len(headers))]
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))).rstrip())
    print("  ".join("-" * width for width in widths))
    result_index = _COLUMNS.index("result")
    for row, line in zip(rows, data):
        cells = [cell.ljust(widths[i]) for i, cell in enumerate(line)]
        cells[result_index] = dev._color(cells[result_index], _RESULT_LEVELS.get(row["result"]))
        print("  ".join(cells).rstrip())
    utils.debug(f"[dev] {len(rows)} service(s) checked")


# --------------------------------------------------------------------------- #
# Update
# --------------------------------------------------------------------------- #
def update_row(service, force, args):
    utils.info(f"[dev] === Update {service} ===")
    try:
        if service in CHARTS:
            _ensure_kind_node()
        state, decision, crosses = plan_service(service, force)
    except (ValueError, requests.RequestException) as error:
        utils.warn(f"[dev] {service}: {error}")
        return _row(service, result="failed", reason=str(error).splitlines()[0])
    if state is None:
        return _row(service, result="skipped", reason=f"run 'ligoj dev init {service}' first")
    try:
        return _apply(service, state, decision, crosses, args)
    except (ValueError, requests.RequestException) as error:
        utils.warn(f"[dev] {service}: {error}")
        fallback = (
            f"fallback: 'ligoj dev init {service} --recreate', or --force for a snapshot first"
        )
        if crosses:
            fallback = "see the snapshot RESTORE.txt"
        return _row(
            service,
            _current_label(state),
            result="failed",
            reason=f"{str(error).splitlines()[0]}; {fallback}",
        )


def _apply(service, state, decision, crosses, args):
    if service in CHARTS:
        row = update_chart(service, state, decision, args)
        if crosses:
            release, namespace = CHARTS[service][:2]
            rollback = (
                f"helm rollback {release} --namespace {namespace} "
                f"--kube-context kind-{dev.KIND_CLUSTER}"
            )
            utils.info(f"[dev] {service}: to go back to the previous chart, run: {rollback}")
            row["reason"] = "; ".join(filter(None, [row["reason"], f"rollback: {rollback}"]))
        return row
    if service in SHARED_DB_SERVICES:
        _ensure_postgres_running()  # their data is there: they cannot start without it
    if not crosses:
        return update_pod(service, state, decision, args)
    for tag in decision.targets:
        pull(f"{state['repository']}:{tag}")  # before the snapshot stops anything
    folder = snapshot(service, state)
    if service == "postgresql":
        image = f"{state['repository']}:{decision.targets[-1]}"
        postgres_major_upgrade(state, image, folder, args)
        return _row(
            service,
            _current_label(state),
            decision.targets[-1],
            decision.newest or "",
            "updated",
            f"snapshot {folder}",
        )
    pod = PODS[service][0]
    try:
        row = update_pod(service, state, decision, args)
    except (ValueError, requests.RequestException):
        if state["running"] and dev._pod_exists(pod) and not dev._pod_running(pod):
            dev._start_service(service)  # stopped by the snapshot
        raise
    row["reason"] = "; ".join(filter(None, [f"snapshot {folder}", row["reason"]]))
    return row


def pull(image):
    """Pull an image (always, so a floating tag gets its newest build) and return its id."""
    utils.info(f"[dev] Pull image '{image}' ...")
    dev._podman("pull", image, stream=True)
    return dev._podman("image", "inspect", "--format", "{{.Id}}", image).stdout.strip()


def swap_image(service, image, replay=True):
    """Set the image of the pod manifest written by 'dev init', then replay it (volumes are kept)."""
    pod = PODS[service][0]
    path = _require_manifest(service)
    with open(path, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    container = manifest["spec"]["containers"][0]
    container["image"] = image
    env = container.setdefault("env", [])
    for name, value in MANIFEST_ENV.get(service, {}).items():
        if not any(e["name"] == name for e in env):
            env.append({"name": name, "value": value})
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    if replay:
        utils.info(f"[dev] Replace pod '{pod}' with image '{image}' ...")
        dev._podman("kube", "play", "--replace", path, stream=True)


def _require_manifest(service):
    path = dev._manifest_path(PODS[service][0])
    if not os.path.isfile(path):
        raise ValueError(
            f"[dev] {service}: no manifest {path}, run 'ligoj dev init {service} --recreate' once"
        )
    return path


def update_pod(service, state, decision, args):
    """Update a pod; on failure, a pod this update started is stopped again, unless it already runs
    the new image (stopping it could interrupt its boot migrations): then it is reported."""
    try:
        return _update_pod(service, state, decision, args)
    except (ValueError, requests.RequestException) as error:
        pod = PODS[service][0]
        if state["running"] or not dev._pod_running(pod):
            raise
        container = dev._pod_container(pod)
        running_id = dev._podman("inspect", "--format", "{{.Image}}", container, check=False)
        if running_id.stdout.strip() == state["image_id"]:
            utils.info(f"[dev] {service} was stopped, stop it again ...")
            dev._stop_service(service)
            raise
        _LEFT_RUNNING.add(service)
        raise ValueError(
            f"{str(error).splitlines()[0]}; left running on the new image, "
            f"'ligoj dev stop {service}' later"
        ) from error


def _update_pod(service, state, decision, args):
    pod, key, _database = PODS[service]
    original = state
    result = "up to date"
    notes = []
    # No target and no safe re-pull (unknown position in a ranged service): touch nothing.
    tags = decision.targets or ((state["tag"],) if decision.refresh else ())
    for tag in tags:
        image = f"{state['repository']}:{tag}"
        image_id = pull(image)
        if image_id == state["image_id"]:
            if tag != state["tag"]:
                # Same build under its explicit tag: pin it without restarting the pod.
                swap_image(service, image, replay=False)
                dev._dev_set(key, image)
                state = {**state, "image": image, "tag": tag}
                result = "pinned"
            continue
        if service == "postgresql" and versions.major(tag) != versions.major(state["tag"]):
            raise ValueError(
                "[dev] postgresql: a new major version needs the dump/restore of --force"
            )
        gate = HOP_GATES.get(service)
        if gate and tag != state["tag"]:
            blocked = gate(service, state, args, first=state is original)
            if blocked:
                notes.append(blocked)
                result = "held back" if result == "up to date" else result
                break
        swap_image(service, image)
        dev._dev_set(key, image)
        utils.info(f"[dev] {service}: [dev] {key} = {image}")
        result = "updated" if _is_newer(tag, original) else "refreshed"
        state = {**state, "image": image, "image_id": image_id, "tag": tag, "version": None}
    swapped = result in ("updated", "refreshed")
    healthy = False
    if swapped or original["running"]:
        step_notes, healthy = _after_update(service, args)
        notes.extend(step_notes)
    if not original["running"] and dev._pod_running(pod):
        if swapped and not healthy:
            # Stopping it now could interrupt the migrations it runs on boot.
            _LEFT_RUNNING.add(service)
            notes.append(f"left running, not confirmed healthy: 'ligoj dev stop {service}' later")
        else:
            utils.info(f"[dev] {service} was stopped, stop it again ...")
            dev._stop_service(service)
    if result == "up to date" and decision.held:
        if "--force" in decision.held:
            result = "held back"
        elif service not in versions.LEGACY and not tags:
            result = "skipped"
    if decision.held:
        notes.append(decision.held)
    return _row(
        service,
        _current_label(original),
        state["tag"] if state["tag"] != original["tag"] else "",
        decision.newest or "",
        result,
        "; ".join(notes),
    )


def _after_update(service, args):
    """Wait for health, then run the post-upgrade step: (notes for the summary, healthy)."""
    step = POST_STEPS.get(service)
    if args.get("wait") == 0 or not _await_healthy(service, args):
        if step:
            return [f"post-upgrade step pending, run 'ligoj dev update {service}' again"], False
        return ([] if args.get("wait") == 0 else ["not healthy yet"]), False
    note = step(service, args) if step else None
    return ([note] if note else []), True


def _await_healthy(service, args):
    start = time.time()
    healed = [False]

    def ready():
        healthy = dev._service_healthy(service, args)
        if not healthy and service == "artifactory":
            # Same self-heal as 'dev start': restart once on the JFrog router boot deadlock.
            dev._maybe_heal_artifactory(args, int(time.time() - start), healed)
        return (healthy, "")

    return dev._await(service, ready, dev._deadline(args.get("wait")))


# --------------------------------------------------------------------------- #
# Post-upgrade steps
# --------------------------------------------------------------------------- #
def sonar_post_upgrade(service, args):
    """Run the database migration a new SonarQube version asks for, then wait until it is UP."""
    endpoint = dev._service_url(service, args).rstrip("/")

    def status():
        try:
            return requests.get(f"{endpoint}/api/system/status", timeout=10).json().get("status")
        except (requests.RequestException, ValueError):
            return None

    settled = ("UP", "DB_MIGRATION_NEEDED", "DB_MIGRATION_RUNNING")
    last = [None]

    def ready():
        last[0] = status()
        return (last[0] in settled, last[0] or "")

    if not dev._await("SonarQube status", ready, dev._deadline(args.get("wait"))):
        return f"post-upgrade step pending, run 'ligoj dev update {service}' again"
    if last[0] != "DB_MIGRATION_NEEDED":
        dev._wait_sonar_up(endpoint, args.get("wait"))
        return None
    utils.info("[dev] SonarQube asks for a database migration, start it ...")
    response = requests.post(f"{endpoint}/api/system/migrate_db", timeout=60)
    if response.status_code in (401, 403):
        password = dev._dev_stored("sonar_admin_password")
        response = requests.post(
            f"{endpoint}/api/system/migrate_db", auth=("admin", password or ""), timeout=60
        )
    if response.status_code != 200:
        raise ValueError(
            f"[dev] SonarQube database migration refused (HTTP {response.status_code})"
        )
    dev._wait_sonar_up(endpoint, args.get("wait"))
    notes = ["database migrated"]
    plugins = dev._podman(
        "exec",
        dev._pod_container("sonarqube"),
        "ls",
        "/opt/sonarqube/extensions/plugins",
        check=False,
    ).stdout.split()
    if any(name.endswith(".jar") for name in plugins):
        notes.append("SonarQube plugins were not updated, check their compatibility")
    return "; ".join(notes)


# Updates every installed plugin having an update, then prints their short names.
_JENKINS_UPDATE_PLUGINS = """\
def j = jenkins.model.Jenkins.get()
j.updateCenter.updateAllSites().each { it.get() }
def updates = j.pluginManager.plugins.findAll { it.hasUpdate() }
updates.collect { it.getUpdateInfo().deploy(true) }.each { it.get() }
println updates.collect { it.shortName }.join(',')
"""


def jenkins_post_upgrade(service, args):
    """Update every installed Jenkins plugin, then restart Jenkins safely when any changed."""
    endpoint = dev._service_url(service, args).rstrip("/")
    password = dev._dev_stored("jenkins_admin_password")
    if not password:
        return "plugins not updated: no [dev] jenkins_admin_password"
    session = requests.Session()
    session.auth = (dev._dev_stored("jenkins_api_user") or "admin", password)
    crumb = session.get(f"{endpoint}/crumbIssuer/api/json", timeout=30)
    headers = {}
    if crumb.status_code == 200:
        headers = {crumb.json()["crumbRequestField"]: crumb.json()["crumb"]}
    utils.info("[dev] Update the Jenkins plugins ...")
    response = session.post(
        f"{endpoint}/scriptText",
        data={"script": _JENKINS_UPDATE_PLUGINS},
        headers=headers,
        timeout=1800,
    )
    lines = response.text.strip().splitlines()
    last = lines[-1] if lines else ""
    if response.status_code != 200 or not re.fullmatch(r"[\w.,-]*", last):
        raise ValueError(
            f"[dev] Jenkins plugin update failed (HTTP {response.status_code}): "
            f"{(lines or [''])[0][:200]}"
        )
    updated = [name for name in last.split(",") if name]
    if not updated:
        return "plugins up to date"
    utils.info(f"[dev] {len(updated)} Jenkins plugins updated, safe restart ...")
    session.post(f"{endpoint}/safeRestart", headers=headers, timeout=30)
    dev._await(
        "Jenkins restart",
        lambda: (not dev._service_healthy(service, args), ""),
        dev._deadline(120),
    )
    _await_healthy(service, args)
    return f"{len(updated)} plugins updated"


def gitlab_pending_migrations():
    """Count of the GitLab background migrations not finished yet."""
    output = dev._podman(
        "exec",
        dev._pod_container("gitlab"),
        "gitlab-rails",
        "runner",
        "-e",
        "production",
        # Queued (active, paused) and failed batched migrations: both block the next upgrade.
        "m = Gitlab::Database::BackgroundMigration::BatchedMigration; "
        "puts m.queued.count + m.with_status(:failed).count",
    ).stdout.strip()
    last = output.splitlines()[-1] if output else ""
    if not last.isdigit():
        raise ValueError(f"[dev] Unable to count the GitLab background migrations: {last[:200]}")
    return int(last)


def gitlab_gate(service, state, args, first):
    """Reason not to apply the next GitLab upgrade stop yet, or None.

    Before the first hop the pending migrations are only counted; between two hops (--force) they
    are awaited, since GitLab refuses an upgrade while those of the previous stop still run.
    """
    if not dev._pod_running(PODS[service][0]):
        dev._start_service(service)
    if args.get("wait") == 0 and not dev._service_healthy(service, args):
        return "GitLab is not ready (--wait 0), its background migrations cannot be checked"
    if not _await_healthy(service, args):
        return "GitLab did not become healthy, next upgrade stop not applied"
    if first:
        pending = gitlab_pending_migrations()
    else:
        pending = [gitlab_pending_migrations()]

        def drained():
            pending[0] = gitlab_pending_migrations()
            return (pending[0] == 0, f"{pending[0]} background migrations left")

        dev._await("GitLab background migrations", drained, dev._deadline(args.get("wait")))
        pending = pending[0]
    if pending:
        return f"background migrations still running ({pending}), run again later"
    return None


POST_STEPS = {"sonarqube": sonar_post_upgrade, "jenkins": jenkins_post_upgrade}
HOP_GATES = {"gitlab": gitlab_gate}


# --------------------------------------------------------------------------- #
# Helm releases on kind
# --------------------------------------------------------------------------- #
def _ensure_kind_node():
    """Start the kind node when it exists but is stopped; it is stopped again at the end."""
    if shutil.which("kind") is None:
        return
    if dev.KIND_CLUSTER not in dev._kind("get", "clusters", check=False).stdout.split():
        return
    if not dev._container_is_running(f"{dev.KIND_CLUSTER}-control-plane"):
        dev._kind_node_start()
        _STARTED.add("kind")


def _stop_started():
    """Stop again what this run started as a dependency, unless a service relying on it is left
    running (not confirmed healthy)."""
    if "kind" in _STARTED:
        if _LEFT_RUNNING & set(CHARTS):
            utils.warn("[dev] kind node left running: a release was not confirmed healthy")
        else:
            dev._stop_kind_node()
    if "postgresql" in _STARTED:
        if _LEFT_RUNNING & set(SHARED_DB_SERVICES):
            utils.warn("[dev] postgresql left running: a service using it was left running")
        else:
            dev._stop_service("postgresql")


def _scaled_down(namespace):
    """True when every deployment and statefulset of the namespace runs 0 replicas ('dev stop')."""
    replicas = dev._kubectl(
        "--namespace",
        namespace,
        "get",
        "deployment,statefulset",
        "--output",
        "jsonpath={.items[*].spec.replicas}",
        check=False,
    ).stdout.split()
    return bool(replicas) and all(count == "0" for count in replicas)


def update_chart(service, state, decision, args):
    release, namespace, chart, _repo, _url, key = CHARTS[service]
    if not decision.targets:
        if decision.held and "--force" in decision.held:
            result = "held back"
        else:
            result = "skipped" if decision.held else "up to date"
        return _row(service, state["tag"], "", decision.newest or "", result, decision.held or "")
    target = decision.targets[-1]
    stopped = _scaled_down(namespace)
    utils.info(f"[dev] helm upgrade {release} {state['tag']} -> {target} ...")
    dev._helm(
        "upgrade",
        release,
        chart,
        "--version",
        target,
        "--namespace",
        namespace,
        "--kube-context",
        f"kind-{dev.KIND_CLUSTER}",
        "--reset-then-reuse-values",  # new chart defaults (image tags), our overrides kept
        "--force-conflicts",
        *dev._helm_wait_flags(args.get("wait")),
        stream=True,
    )
    dev._dev_set(key, target)
    utils.info(f"[dev] {service}: [dev] {key} = {target}")
    notes = [decision.held] if decision.held else []
    if args.get("wait") == 0:
        # helm did not wait: scaling down now could interrupt the migrations of the new release.
        _LEFT_RUNNING.add(service)
        notes.insert(0, "left running, not confirmed healthy (--wait 0)")
    elif stopped:
        dev._stop_service(service)
    elif not _await_healthy(service, args):
        notes.insert(0, "not healthy yet")
    return _row(service, state["tag"], target, decision.newest or "", "updated", "; ".join(notes))


# --------------------------------------------------------------------------- #
# --force: snapshot and PostgreSQL major upgrade
# --------------------------------------------------------------------------- #
def _db_superuser():
    return (
        dev._container_env(dev._pod_container(dev.POSTGRES_CONTAINER), "POSTGRES_USER") or "ligoj"
    )


def _postgres_ready():
    """Ready over TCP inside the container: the entrypoint's temporary init server (first boot of a
    fresh volume) only listens on the unix socket, so it never counts as ready."""
    if not dev._pod_running(dev.POSTGRES_CONTAINER):
        return False
    container = dev._pod_container(dev.POSTGRES_CONTAINER)
    probe = ("exec", container, "pg_isready", "-h", "127.0.0.1", "-U", _db_superuser())
    return dev._podman(*probe, check=False).returncode == 0


def _await_postgres(seconds=600):
    if not dev._await("PostgreSQL", lambda: (_postgres_ready(), ""), dev._deadline(seconds)):
        raise ValueError(f"[dev] PostgreSQL not ready after {seconds}s")


def _ensure_postgres_running():
    if not dev._pod_running(dev.POSTGRES_CONTAINER):
        dev._start_service("postgresql")
        _STARTED.add("postgresql")
    _await_postgres()


def _psql(container, user, database, sql):
    result = dev._podman("exec", container, "psql", "-U", user, "-d", database, "-Atc", sql)
    return result.stdout.split()


def _inventory(container, user):
    """{database: table count} of a cluster, to compare before and after a dump/restore."""
    databases = _psql(
        container, user, "postgres", "SELECT datname FROM pg_database WHERE NOT datistemplate"
    )
    tables = (
        "SELECT count(*) FROM pg_catalog.pg_tables "
        "WHERE schemaname NOT IN ('pg_catalog', 'information_schema')"
    )
    return {name: int(_psql(container, user, name, tables)[0]) for name in databases}


def _exec_to_file(path, *command):
    """Run 'podman exec <command>' with its standard output written to a file (dumps can be big)."""
    utils.debug("[dev] $ podman exec " + " ".join(command) + f" > {path}")
    with open(path, "wb") as out:
        proc = subprocess.run(["podman", "exec", *command], stdout=out, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise ValueError(f"[dev] {command[1]} failed: {proc.stderr.decode(errors='replace')[:300]}")


def snapshot(service, state):
    """Save what a forced update could break: volumes, shared database, manifest and image."""
    pod, key, database = PODS[service]
    folder = os.path.join(SNAPSHOT_DIR, service, time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(folder, exist_ok=True)
    utils.info(f"[dev] Snapshot {service} into {folder} ...")
    manifest_copy = os.path.join(folder, f"{pod}.yaml")
    shutil.copyfile(dev._manifest_path(pod), manifest_copy)
    with open(os.path.join(folder, "image.txt"), "w", encoding="utf-8") as f:
        f.write(state["image"] + "\n")
    _require_manifest(service)
    restore = [f"podman pod rm -f {pod}"]
    if service != "postgresql":  # its data is dumped by postgres_major_upgrade, old volume kept
        with open(manifest_copy, encoding="utf-8") as f:
            volumes = yaml.safe_load(f)["spec"].get("volumes", [])
        claims = [
            v["persistentVolumeClaim"]["claimName"] for v in volumes if "persistentVolumeClaim" in v
        ]
        was_running = dev._pod_running(pod)
        try:
            if database:
                _ensure_postgres_running()
            if was_running:
                dev._podman("pod", "stop", pod, stream=True)  # consistent volumes and database
            for claim in claims:
                tar = os.path.join(folder, f"{claim}.tar")
                dev._podman("volume", "export", claim, "--output", tar)
                restore.append(
                    f"podman volume rm {claim} && podman volume create {claim} "
                    f"&& podman volume import {claim} {tar}"
                )
            if database:
                dump = os.path.join(folder, f"{database}.dump")
                user = _db_superuser()
                container = dev._pod_container(dev.POSTGRES_CONTAINER)
                _exec_to_file(dump, container, "pg_dump", "-U", user, "-Fc", database)
                # --create: drop and recreate the whole database, tables added since included.
                restore.append(
                    f"podman exec -i {container} pg_restore -U {user} --clean --if-exists "
                    f"--create -d postgres < {dump}"
                )
        except ValueError:
            if was_running:
                dev._start_service(service)
            raise
    restore.append(f"set [dev] {key} = {state['image']} in ~/.ligoj/credentials")
    restore.append(f"podman kube play --replace {manifest_copy}")
    with open(os.path.join(folder, "RESTORE.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(restore) + "\n")
    utils.info(f"[dev] To restore this snapshot ({folder}/RESTORE.txt):")
    for line in restore:
        utils.info(f"[dev]   {line}")
    return folder


def postgres_major_upgrade(state, image, folder, args):
    """Dump everything, start the new major on a new volume, restore, verify. The old volume is
    kept; when anything fails, the previous manifest (old image, old volume) is replayed."""
    pod = dev.POSTGRES_CONTAINER
    container = dev._pod_container(pod)
    major = versions.major(image.rpartition(":")[2])
    volume = f"{dev.POSTGRES_VOLUME}_{major}"
    if dev._podman("volume", "exists", volume, check=False).returncode == 0:
        raise ValueError(
            f"[dev] postgresql: volume '{volume}' already exists (a previous attempt?), "
            f"remove it first: podman volume rm {volume}"
        )
    pull(image)  # before anything is stopped
    _ensure_postgres_running()
    user = _db_superuser()
    path = _require_manifest("postgresql")
    previous = os.path.join(folder, f"{pod}.yaml")  # copied by snapshot()
    dependents = [s for s in SHARED_DB_SERVICES if dev._pod_running(PODS[s][0])]
    for service in dependents:
        dev._stop_service(service)
    switched = False
    try:
        before = _inventory(container, user)
        dump = os.path.join(folder, "dumpall.sql")
        utils.info(f"[dev] Dump every PostgreSQL database into {dump} ...")
        _exec_to_file(dump, container, "pg_dumpall", "-U", user)
        utils.info(f"[dev] Create volume '{volume}' for PostgreSQL {major} ...")
        dev._podman("volume", "create", volume)
        with open(path, encoding="utf-8") as f:
            manifest = yaml.safe_load(f)
        manifest["spec"]["containers"][0]["image"] = image
        manifest["spec"]["volumes"] = [
            {"name": "data", "persistentVolumeClaim": {"claimName": volume}}
            if v.get("name") == "data"
            else v
            for v in manifest["spec"].get("volumes", [])
        ]
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(manifest, f, sort_keys=False)
        utils.info(f"[dev] Replace pod '{pod}' with PostgreSQL {major} on volume '{volume}' ...")
        switched = True
        dev._podman("kube", "play", "--replace", path, stream=True)
        dev._dev_set("db_image", image)
        # The restore needs the final server ('--wait 0' does not apply here).
        _await_postgres()
        utils.info("[dev] Restore the dump (existing roles and databases are reported) ...")
        with open(dump, "rb") as source:
            restored = subprocess.run(
                ["podman", "exec", "-i", container, "psql", "-U", user, "-d", "postgres", "-q"],
                stdin=source,
                stdout=subprocess.DEVNULL,
            )
        if restored.returncode != 0:
            raise ValueError(f"[dev] psql restore exited with {restored.returncode}")
        after = _inventory(container, user)
        missing = [
            f"{name} ({after.get(name, 'absent')}/{count} tables)"
            for name, count in before.items()
            if after.get(name) != count
        ]
        if missing:
            raise ValueError(f"[dev] restore incomplete: {', '.join(missing)}")
    except (ValueError, OSError) as error:
        if switched:
            utils.warn(f"[dev] PostgreSQL {major} upgrade failed, back to {state['image']} ...")
            shutil.copyfile(previous, path)
            dev._podman("kube", "play", "--replace", path, stream=True, check=False)
            dev._dev_set("db_image", state["image"])
            _await_postgres()
        raise ValueError(
            f"[dev] PostgreSQL {major} upgrade failed ({str(error).splitlines()[0]}); still on "
            f"{state['image']} with its data untouched, volume '{volume}' kept for inspection"
        ) from error
    finally:
        for service in dependents:
            dev._start_service(service)
    utils.info(
        f"[dev] PostgreSQL {major} ready, {len(before)} databases verified; the previous data "
        "stays in its former volume"
    )
