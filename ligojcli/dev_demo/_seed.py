#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Data-seeding phase of `dev demo`: push real artifacts into the running tools so the demo project has
# something to show. All operations use the [dev] credentials and are best-effort (a failing tool
# never aborts the others). They are heavy (image pulls, Maven builds, a Sonar analysis, git mirrors),
# so the tools are seeded in parallel:
#   * Harbor          - pull 2 small public images, retag and push them into the demo project.
#   * Nexus (docker)  - push the same 2 images to the Nexus docker registry connector.
#   * Nexus/Artifactory (maven) + SonarQube - build plugin-ui and plugin-id, deploy the artifacts to
#                       both registries and run `sonar:sonar`.
#   * GitLab          - mirror the plugin-ui and plugin-id GitHub repositories.
#
import concurrent.futures
import os
import shutil
import subprocess
import tempfile
from urllib.parse import urlsplit

from ligojcli.dev_demo import _common
from ligojcli.plugins import utils

# 2 tiny public images, retagged into the demo registries.
IMAGES = [("docker.io/library/busybox", "1.36"), ("docker.io/library/alpine", "3.19")]
# The Ligoj plugins built, deployed and analysed. Source dirs live under LIGOJ_PLUGINS_DIR.
PLUGINS = [
    {"name": "plugin-ui", "key": "org.ligoj.plugin:plugin-ui", "label": "Ligoj - Plugin UI"},
    {"name": "plugin-id", "key": "org.ligoj.plugin:plugin-id", "label": "Ligoj - Plugin ID"},
]
GITHUB_BASE = "https://github.com/ligoj"
_TIMEOUT = 1800  # per external command (Maven builds are slow)


def seed(args, project):
    """Seed every tool with demo data, in parallel. Best-effort; never raises."""
    utils.info(f"[dev] === Seeding tools with demo data for '{project}' (this is slow) ===")
    seeders = [
        ("harbor", lambda: seed_harbor(args, project)),
        ("nexus-docker", lambda: seed_nexus_docker(args, project)),
        ("gitlab", lambda: seed_gitlab(args)),
        ("maven+sonar", lambda: seed_maven_sonar(args, project)),
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(seeders)) as pool:
        pending = {pool.submit(fn): name for name, fn in seeders}
        for future in concurrent.futures.as_completed(pending):
            name = pending[future]
            try:
                future.result()
            except Exception as error:  # noqa: BLE001 - one tool must not abort the others
                utils.warn(f"[dev] seed {name}: {error}")


# --------------------------------------------------------------------------- #
# Container images (Harbor, Nexus docker)
# --------------------------------------------------------------------------- #
def seed_harbor(args, project):
    if not _has("podman"):
        return
    endpoint = _common.dev_value(
        args, "harbor_endpoint", "HARBOR_ENDPOINT", "http://localhost:8088"
    )
    user = _common.dev_value(args, "harbor_admin_user", "HARBOR_ADMIN_USER", "admin")
    password = _common.dev_value(args, "harbor_admin_password", "HARBOR_ADMIN_PASSWORD", None)
    registry = _host(endpoint)
    _push_images(registry, user, password, f"{registry}/{project}", "Harbor")


def seed_nexus_docker(args, project):
    if not _has("podman"):
        return
    endpoint = _common.dev_value(args, "nexus_endpoint", "NEXUS_ENDPOINT", "http://localhost:8181")
    user = _common.dev_value(args, "nexus_admin_user", "NEXUS_ADMIN_USER", "admin")
    password = _common.dev_value(args, "nexus_admin_password", "NEXUS_ADMIN_PASSWORD", None)
    docker_port = _common.dev_value(args, "nexus_docker_port", "NEXUS_DOCKER_PORT", "8182")
    host = _host(endpoint).split(":")[0]
    registry = f"{host}:{docker_port}"  # the Nexus docker hosted repo connector
    _push_images(registry, user, password, registry, "Nexus")


def _push_images(registry, user, password, prefix, label):
    if not password:
        utils.warn(f"[dev] {label}: no admin password in [dev]; skipping image push")
        return
    login = _run(["podman", "login", "--tls-verify=false", "-u", user, "-p", password, registry])
    if login.returncode != 0:
        utils.warn(f"[dev] {label}: docker login failed: {_tail(login)}")
        return
    for image, tag in IMAGES:
        name = image.rsplit("/", 1)[-1]
        dest = f"{prefix}/{name}:{tag}"
        _run(["podman", "pull", f"{image}:{tag}"])
        _run(["podman", "tag", f"{image}:{tag}", dest])
        push = _run(["podman", "push", "--tls-verify=false", dest])
        if push.returncode == 0:
            utils.info(f"[dev] {label}: pushed {dest}")
        else:
            utils.warn(f"[dev] {label}: push {dest} failed: {_tail(push)}")


# --------------------------------------------------------------------------- #
# Maven artifacts (Nexus, Artifactory) + SonarQube analysis
# --------------------------------------------------------------------------- #
def seed_maven_sonar(args, project):
    if not _has("mvn"):
        utils.warn("[dev] maven: 'mvn' not found; skipping build/deploy/analysis")
        return
    plugins_dir = os.path.expanduser(
        _common.dev_value(args, "ligoj_plugins_dir", "LIGOJ_PLUGINS_DIR", "~/git/ligoj-plugins")
    )
    nexus_ep = _common.dev_value(args, "nexus_endpoint", "NEXUS_ENDPOINT", "http://localhost:8181")
    nexus_url = f"{nexus_ep.rstrip('/')}/repository/{project}-maven/"
    arti_ep = _common.dev_value(
        args, "artifactory_endpoint", "ARTIFACTORY_ENDPOINT", "http://localhost:8082/artifactory"
    )
    arti_url = f"{arti_ep.rstrip('/')}/example-repo-local/"
    sonar_url = _common.dev_value(args, "sonar_endpoint", "SONAR_ENDPOINT", "http://localhost:9000")
    sonar_token = _common.dev_value(args, "sonar_api_token", "SONAR_API_TOKEN", None)

    settings = _maven_settings(args)
    try:
        for plugin in PLUGINS:
            pom = os.path.join(plugins_dir, plugin["name"], "pom.xml")
            if not os.path.isfile(pom):
                utils.warn(f"[dev] maven: {pom} not found; skipping {plugin['name']}")
                continue
            _build_plugin(plugin, pom, settings, nexus_url, arti_url, sonar_url, sonar_token)
    finally:
        _remove(settings)


def _build_plugin(plugin, pom, settings, nexus_url, arti_url, sonar_url, sonar_token):
    name = plugin["name"]
    # One build: compile + test + Sonar analysis + deploy to Nexus.
    build = [
        "mvn",
        "-B",
        "-f",
        pom,
        "-s",
        settings,
        "clean",
        "verify",
        "deploy",
        "-Djarsigner.skip=true",
        f"-DaltDeploymentRepository=nexus-demo::default::{nexus_url}",
    ]
    if sonar_token:
        build += [
            "sonar:sonar",
            f"-Dsonar.host.url={sonar_url}",
            f"-Dsonar.token={sonar_token}",
            f"-Dsonar.projectKey={plugin['key']}",
            f"-Dsonar.projectName={plugin['label']}",
        ]
    utils.info(f"[dev] maven: building {name} (deploy to Nexus + Sonar analysis) ...")
    result = _run(build)
    if result.returncode != 0:
        utils.warn(f"[dev] maven: {name} build/deploy/sonar failed: {_tail(result)}")
        return
    utils.info(
        f"[dev] maven: {name} deployed to Nexus" + (" and analysed in Sonar" if sonar_token else "")
    )
    # Second, lighter deploy of the same artifacts to Artifactory.
    deploy = [
        "mvn",
        "-B",
        "-f",
        pom,
        "-s",
        settings,
        "deploy",
        "-DskipTests",
        "-Djarsigner.skip=true",
        f"-DaltDeploymentRepository=artifactory-demo::default::{arti_url}",
    ]
    utils.info(f"[dev] maven: deploying {name} to Artifactory ...")
    result = _run(deploy)
    if result.returncode == 0:
        utils.info(f"[dev] maven: {name} deployed to Artifactory")
    else:
        utils.warn(f"[dev] maven: {name} Artifactory deploy failed: {_tail(result)}")


def _maven_settings(args):
    npw = _common.dev_value(args, "nexus_admin_password", "NEXUS_ADMIN_PASSWORD", "") or ""
    apw = _common.dev_value(args, "artifactory_password", "ARTIFACTORY_PASSWORD", "password")
    nuser = _common.dev_value(args, "nexus_admin_user", "NEXUS_ADMIN_USER", "admin")
    auser = _common.dev_value(args, "artifactory_user", "ARTIFACTORY_USER", "admin")
    content = (
        "<settings><servers>"
        f"<server><id>nexus-demo</id><username>{nuser}</username><password>{npw}</password></server>"
        f"<server><id>artifactory-demo</id><username>{auser}</username>"
        f"<password>{apw}</password></server>"
        "</servers></settings>"
    )
    handle = tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-8")
    handle.write(content)
    handle.close()
    return handle.name


# --------------------------------------------------------------------------- #
# GitLab (mirror the GitHub repositories)
# --------------------------------------------------------------------------- #
def seed_gitlab(args):
    if not _has("git"):
        return
    endpoint = _common.dev_value(
        args, "gitlab_endpoint", "GITLAB_ENDPOINT", "http://localhost:8929"
    )
    user = _common.dev_value(args, "gitlab_user", "GITLAB_USER", "root")
    token = _common.dev_value(args, "gitlab_token", "GITLAB_TOKEN", None) or _common.dev_value(
        args, "gitlab_root_password", "GITLAB_ROOT_PASSWORD", None
    )
    if not token:
        utils.warn("[dev] gitlab: no token in [dev]; skipping mirror")
        return
    scheme, host = urlsplit(endpoint)[:2]
    for plugin in PLUGINS:
        name = plugin["name"]
        _gitlab_create_project(endpoint, token, name)
        push_url = f"{scheme}://{user}:{token}@{host}/{user}/{name}.git"
        _mirror_repo(f"{GITHUB_BASE}/{name}.git", push_url, name)


def _gitlab_create_project(endpoint, token, path):
    import requests

    try:
        requests.post(
            f"{endpoint}/api/v4/projects",
            headers={"PRIVATE-TOKEN": token},
            json={"name": path, "path": path, "visibility": "private"},
            timeout=30,
        )
    except requests.RequestException as error:
        utils.warn(f"[dev] gitlab: create project {path}: {error}")


def _mirror_repo(github_url, push_url, name):
    workdir = tempfile.mkdtemp(prefix=f"ligoj-mirror-{name}-")
    bare = os.path.join(workdir, f"{name}.git")
    try:
        clone = _run(["git", "clone", "--mirror", github_url, bare])
        if clone.returncode != 0:
            utils.warn(f"[dev] gitlab: clone {github_url} failed: {_tail(clone)}")
            return
        push = _run(["git", "-C", bare, "push", "--mirror", push_url])
        if push.returncode == 0:
            utils.info(f"[dev] gitlab: mirrored {name} from GitHub")
        else:
            utils.warn(f"[dev] gitlab: mirror push {name} failed: {_tail(push)}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _has(tool):
    if shutil.which(tool) is None:
        utils.warn(f"[dev] seed: '{tool}' not found; skipping the steps that need it")
        return False
    return True


def _host(endpoint):
    return urlsplit(endpoint).netloc


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT)


def _tail(result, lines=12):
    text = (result.stderr or "") + (result.stdout or "")
    return "\n".join(text.strip().splitlines()[-lines:])


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass
