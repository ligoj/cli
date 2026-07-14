#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Local developer environment helpers, exposed under the `dev` service.
#
# `dev init` brings up the backing services a Ligoj developer needs and wires the
# resulting endpoints and credentials into the `[dev]` section of
# ~/.ligoj/credentials (reusable later with `--profile dev`).
#
# Runtime: Kubernetes manifests applied with `podman kube play` (no separate
# cluster) for every self-contained service, and a small `kind` cluster (podman
# provider) created on demand only for Harbor, which needs a real cluster:
#   * postgresql - 'ligoj-db' PostgreSQL (ligoj/ligoj), persistent; an existing
#                  data directory/volume and image are preserved on migration. Also
#                  hosts a dedicated database for Keycloak, SonarQube and Artifactory.
#   * openldap   - reads ldap_admin_password / LDAP_ADMIN_PASSWORD (generated when missing).
#   * keycloak   - backed by the shared PostgreSQL; 'ligoj' realm + LDAP federation +
#                  confidential 'ligoj' client; prints Spring Boot properties.
#   * jenkins    - admin password set from JENKINS_API_TOKEN when available.
#   * sonarqube  - backed by the shared PostgreSQL; changes the default admin
#                  password and creates an API token.
#   * gitlab     - GitLab CE omnibus (single container), persistent.
#   * harbor     - Helm chart on a kind cluster (podman), exposed via nodePort.
#   * nexus      - Sonatype Nexus Repository Manager; admin password reset from the
#                  generated initial password and stored in [dev].
#   * artifactory- JFrog Artifactory OSS backed by the shared PostgreSQL (Derby is
#                  refused by recent versions), persistent.
#   * argocd     - Helm chart on the shared kind cluster, with a 'ligoj' role.
#
import argparse
import base64
import concurrent.futures
import os
import re
import secrets
import shutil
import socket
import string
import subprocess
import sys
import time
from urllib.parse import urlparse

import requests
import yaml
from colorama import Fore, Style

from ligojcli.plugins import utils

PLUGIN_NAME = "dev"
DEV_SECTION = "dev"

SERVICES = [
    "postgresql",
    "openldap",
    "keycloak",
    "jenkins",
    "sonarqube",
    "gitlab",
    "harbor",
    "nexus",
    "artifactory",
    "argocd",
]
# Services that need the real (kind) cluster instead of `podman kube play`.
KIND_SERVICES = ("harbor", "argocd")

# Detailed help shown by `dev start -h`. Kept close to SERVICES so the two stay in sync.
_START_HELP = """\
Start local dev services that were created by `dev init` but are currently stopped.

With no argument every service is (re)started; otherwise only the space-separated
services you name are, e.g.:

  ligoj dev start                       # start all services
  ligoj dev start postgresql keycloak   # start just these two
  ligoj dev start sonarqube --wait 0    # start, do not wait for health

Behavior:
  * The podman machine is started first if it is not already running (a stopped
    machine otherwise makes every pod look absent), initializing it when missing,
    and the Podman Desktop GUI is launched (macOS, when installed).
  * Regular services are podman pods — each is resumed with `podman pod start`.
  * harbor and argocd run on the shared `kind` cluster: the kind node is started
    if it was stopped, then their workloads are scaled back up to 1 replica.
  * A service whose pod / kind cluster does not exist yet is skipped with a
    warning — run `dev init` (optionally `--only <service>`) to create it first.
  * `--wait/-w` controls the post-start health wait (live progress): omitted waits
    until healthy or Ctrl+C, `0` returns immediately, a positive N waits up to N
    seconds. Health is the same per-service probe shown by `dev status`.

Related: `dev up` also starts podman and its machine first; `dev stop` /
`dev restart` mirror this command; `dev status` shows what is running.

Services: """ + ", ".join(SERVICES)

# Detailed help shown by `dev stop -h`. Mirrors _START_HELP.
_STOP_HELP = """\
Stop running local dev services. Their data is preserved (named volumes and
persistent directories are kept), so `dev start` / `dev up` brings them back.

With no argument every service is stopped; otherwise only the space-separated
services you name are, e.g.:

  ligoj dev stop                        # stop everything
  ligoj dev stop gitlab sonarqube       # stop just these two
  ligoj dev stop nexus --wait 0         # stop, do not wait for it to go down

Behavior:
  * Regular services are podman pods — each is halted with `podman pod stop`.
  * harbor and argocd share the `kind` cluster: stopping BOTH pauses the whole
    kind node at once (preserving replica counts); stopping only one scales just
    that workload down to 0 replicas.
  * `--wait/-w` controls the wait for services to become unreachable (live
    progress): omitted waits until down or Ctrl+C, `0` returns immediately, a
    positive N waits up to N seconds.

Related: `dev down` stops the whole podman machine (everything at once); `dev
start` / `dev restart` mirror this command; `dev status` shows what is running.

Services: """ + ", ".join(SERVICES)

LDAP_DEFAULT_IMAGE = "docker.io/bitnamilegacy/openldap:latest"
JENKINS_DEFAULT_IMAGE = "jenkins/jenkins:2.570-slim-jdk25"
SONAR_DEFAULT_IMAGE = "sonarqube:26.6.0.123539-community"
POSTGRES_DEFAULT_IMAGE = "postgres:17"
KEYCLOAK_DEFAULT_IMAGE = "quay.io/keycloak/keycloak:26.6.1"
GITLAB_DEFAULT_IMAGE = "gitlab/gitlab-ce:latest"
NEXUS_DEFAULT_IMAGE = "docker.io/sonatype/nexus3:latest"
# Pinned (not ':latest') on purpose: from ~7.125 the OSS web UI (jffe) is stuck retrying a
# "first-time entitlement fetch" that 404s in OSS (the entitlements service is Pro/cloud only), which
# blocks/slows every /ui/api/v1/ui/* call and makes the UI unusable. 7.111.9 is the newest OSS tag
# whose UI works (login + data calls answer in ms, no entitlement retry loop). Override with
# ARTIFACTORY_IMAGE / [dev] artifactory_image if you need another version.
ARTIFACTORY_DEFAULT_IMAGE = "releases-docker.jfrog.io/jfrog/artifactory-oss:7.111.9"

POSTGRES_CONTAINER = "ligoj-db"
POSTGRES_VOLUME = "ligoj_db_data"
# Other service pods (SonarQube, Artifactory, ...) reuse this shared PostgreSQL, reaching its
# host-published port via the podman host gateway (same name Keycloak uses for LDAP federation).
SHARED_DB_HOST = "host.containers.internal"

KEYCLOAK_CONTAINER = "keycloak"
KEYCLOAK_VOLUME = "keycloak_data"
KEYCLOAK_REALM = "ligoj"
KEYCLOAK_CLIENT = "ligoj"
# Where the ligoj UI/API expect to receive the OIDC callbacks (see commands/README.md).
KEYCLOAK_REDIRECT_URIS = [
    "http://localhost:5173/ligoj/login/oauth2/code/keycloak",
    "http://localhost:8080/ligoj/login/oauth2/code/keycloak",
]
KEYCLOAK_ROOT_URL = "http://localhost:5173/ligoj/"

LDAP_DEFAULT_SCHEMA_DIR = (
    "~/git/ligoj-plugins/plugin-id-ldap-embedded/src/main/resources/export/schema"
)
SONAR_TOKEN_NAME = "ligoj-dev"
JENKINS_TOKEN_NAME = "ligoj-dev"
GITLAB_TOKEN_NAME = "ligoj-dev"

# Harbor and ArgoCD run on a shared kind cluster (the services that need a real cluster).
HARBOR_CHART = "harbor/harbor"
HARBOR_REPO_NAME = "harbor"
HARBOR_REPO_URL = "https://helm.goharbor.io"
HARBOR_RELEASE = "harbor"
HARBOR_NAMESPACE = "harbor"
KIND_CLUSTER = "ligoj-dev"
# goharbor/redis-photon ships amd64 only and segfaults under QEMU on Apple Silicon;
# swap the internal cache for a multi-arch redis so it runs natively on arm64.
HARBOR_REDIS_IMAGE = "docker.io/redis:7.4.1"

ARGOCD_CHART = "argo/argo-cd"
ARGOCD_REPO_NAME = "argo"
ARGOCD_REPO_URL = "https://argoproj.github.io/argo-helm"
ARGOCD_RELEASE = "argocd"
ARGOCD_NAMESPACE = "argocd"
ARGOCD_ACCOUNT = "ligoj"
ARGOCD_ROLE = "role:ligoj"
ARGOCD_TOKEN_NAME = "ligoj-dev"

# Host<->nodePort mappings baked into the kind cluster at creation (host_key, env, default, nodePort).
KIND_PORT_MAPPINGS = [
    ("harbor_port", "HARBOR_PORT", "8088", "harbor_node_port", "HARBOR_NODE_PORT", "30088"),
    ("argocd_port", "ARGOCD_PORT", "8083", "argocd_node_port", "ARGOCD_NODE_PORT", "30083"),
]

K8S_DIR = os.path.join(utils.user_home, ".ligoj", "dev", "k8s")


def _add_wait_argument(parser):
    parser.add_argument(
        "--wait",
        "-w",
        type=int,
        default=None,
        help="Seconds to wait for the operation with live progress: 0 = no wait, "
        "a positive number = up to that many seconds, omitted = until done or Ctrl+C",
    )


def _service_choice(value):
    """argparse per-token validator: like choices=SERVICES, but usable with nargs='*'.

    A plain choices=SERVICES on a nargs='*' positional rejects the no-argument case
    ('invalid choice: []'), so validate each token here instead (empty list = all).
    """
    if value not in SERVICES:
        raise argparse.ArgumentTypeError(
            f"invalid service '{value}' (choose from: {', '.join(SERVICES)})"
        )
    return value


def configure(subparser_service):
    subparser_action = subparser_service.add_parser(
        "dev", help="Local developer environment helpers"
    ).add_subparsers(title="action", help="Action", dest="action")
    parser_action = subparser_action.add_parser(
        "init", help="Bring up the local dev services on Kubernetes (podman kube play / kind)"
    )
    parser_action.add_argument(
        "--only",
        "-O",
        nargs="*",
        choices=SERVICES,
        help="Only initialize the given services (default: all)",
    )
    parser_action.add_argument(
        "--recreate",
        "-R",
        action="store_true",
        default=False,
        help="Delete and recreate the pods/cluster (named volumes are kept)",
    )
    parser_action.add_argument(
        "--skip-prereqs",
        action="store_true",
        default=False,
        help="Skip checking/installing prerequisites (podman, Java 21, Maven 3.9.6)",
    )
    parser_action.add_argument("--ldap-port", help="Host port for OpenLDAP (default 1389)")
    parser_action.add_argument("--jenkins-port", help="Host port for Jenkins HTTP (default 8085)")
    parser_action.add_argument("--sonar-port", help="Host port for SonarQube (default 9000)")
    parser_action.add_argument("--db-port", help="Host port for PostgreSQL (default 5432)")
    parser_action.add_argument("--keycloak-port", help="Host port for Keycloak (default 9083)")
    parser_action.add_argument("--gitlab-port", help="Host port for GitLab HTTP (default 8929)")
    parser_action.add_argument("--harbor-port", help="Host port for Harbor (default 8088)")
    parser_action.add_argument("--nexus-port", help="Host port for Nexus HTTP (default 8181)")
    parser_action.add_argument(
        "--nexus-docker-port",
        help="Host port for the Nexus Docker registry connector (default 8182)",
    )
    parser_action.add_argument(
        "--artifactory-port", help="Host port for Artifactory HTTP (default 8082)"
    )
    parser_action.add_argument("--argocd-port", help="Host port for ArgoCD (default 8083)")
    _add_wait_argument(parser_action)

    subparser_action.add_parser(
        "status", help="Show the status, host health check and access URL of each dev service"
    )

    parser_restart = subparser_action.add_parser(
        "restart", help="Restart all dev services (or a specific one)"
    )
    parser_restart.add_argument(
        "restart_service",
        metavar="service",
        nargs="?",
        choices=SERVICES,
        help="Service to restart (default: all)",
    )
    _add_wait_argument(parser_restart)

    parser_stop = subparser_action.add_parser(
        "stop",
        help="Stop running dev services (all, one, or a list)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Stop one or more running local dev services (their data is kept).",
        epilog=_STOP_HELP,
    )
    parser_stop.add_argument(
        "stop_service",
        metavar="service",
        nargs="*",
        type=_service_choice,
        help="Services to stop, space-separated (default: all). Choices: " + ", ".join(SERVICES),
    )
    _add_wait_argument(parser_stop)

    parser_start = subparser_action.add_parser(
        "start",
        help="Start stopped dev services (all, one, or a list)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Start one or more stopped local dev services.",
        epilog=_START_HELP,
    )
    parser_start.add_argument(
        "start_service",
        metavar="service",
        nargs="*",
        type=_service_choice,
        help="Services to start, space-separated (default: all). Choices: " + ", ".join(SERVICES),
    )
    _add_wait_argument(parser_start)

    parser_up = subparser_action.add_parser(
        "up", help="Start podman + its machine, then start every dev service"
    )
    _add_wait_argument(parser_up)

    subparser_action.add_parser(
        "down", help="Bring everything down by stopping the podman machine (not each service)"
    )

    parser_backup = subparser_action.add_parser(
        "backup",
        help="PG-dump a Ligoj service's DB rows into ~/.ligoj/backup (default: all supported)",
    )
    parser_backup.add_argument(
        "backup_service",
        metavar="service",
        nargs="?",
        help="Service to back up, e.g. 'service:prov' (default: every supported service)",
    )

    parser_restore = subparser_action.add_parser(
        "restore",
        help="Restore a service backup into the target DB (honours --profile, else [restore])",
    )
    parser_restore.add_argument(
        "restore_service",
        metavar="service",
        nargs="?",
        default="service:prov",
        help="Service to restore (default: service:prov)",
    )
    parser_restore.add_argument(
        "restore_backup_id",
        metavar="backup_id",
        nargs="?",
        help="Backup id to restore (omit to pick one from a keyboard-selectable list)",
    )

    parser_demo = subparser_action.add_parser(
        "demo",
        help="Configure installed Ligoj plugins (nodes, IAM, sample data) for local development",
    )
    parser_demo.add_argument(
        "--only",
        "-O",
        nargs="*",
        help="Only configure these plugin artifacts (e.g. plugin-id-ldap plugin-build-jenkins)",
    )
    parser_demo.add_argument(
        "--list",
        "-L",
        action="store_true",
        default=False,
        help="List installed plugins (with their demo availability) and exit, no changes",
    )
    _add_wait_argument(parser_demo)

    parser_debug = subparser_action.add_parser(
        "debug", help="Manage the IDE app stack (IntelliJ + Ligoj API/UI + Vite); macOS only"
    )
    debug_sub = parser_debug.add_subparsers(title="command", dest="operation")
    debug_sub.add_parser(
        "init",
        help="Compile the dedicated debug launcher app (grant it Accessibility, not the terminal)",
    )
    debug_start = debug_sub.add_parser(
        "start", help="Start IntelliJ and the Ligoj API/UI/Vite apps (only those stopped)"
    )
    _add_wait_argument(debug_start)
    debug_stop = debug_sub.add_parser(
        "stop", help="Stop the Ligoj API/UI/Vite apps (IntelliJ stays open)"
    )
    _add_wait_argument(debug_stop)
    debug_restart = debug_sub.add_parser("restart", help="Restart the Ligoj API/UI/Vite apps")
    _add_wait_argument(debug_restart)
    debug_sub.add_parser("status", help="Show the IDE app stack status")

    # 'test' takes free-form '-D...' JVM options grouped by '--api' / '--ui', which argparse cannot
    # model, so everything after 'test' is captured verbatim (REMAINDER) and parsed in dev_test.
    from ligojcli import dev_test

    subparser_action.add_parser(
        "test",
        help="Run the released Ligoj app containers (ligoj-api + ligoj-ui); 'dev test -h' for details",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Run the two released Ligoj application containers in the background.",
        epilog=dev_test.HELP,
    ).add_argument(
        "test_args",
        metavar="start|stop [options]",
        nargs=argparse.REMAINDER,
        help="'start' (run both, wait for health, open browser) or 'stop' (stop+remove both)",
    )

    # 'package' builds the two Ligoj app container images locally (with the JDBC drivers), natively via
    # podman/docker — no external release script. See dev_package.
    from ligojcli import dev_package

    parser_package = subparser_action.add_parser(
        "package",
        help="Build the Ligoj app container images locally; 'dev package -h' for details",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Build the ligoj-api + ligoj-ui container images locally (with the JDBC drivers).",
        epilog=dev_package.HELP,
    )
    parser_package.add_argument(
        "--project", help="Ligoj checkout to build from (default ~/git/ligoj)"
    )
    parser_package.add_argument(
        "--tag", help="Image tag (default: project version without -SNAPSHOT)"
    )
    parser_package.add_argument(
        "--only", choices=("api", "ui"), help="Build only one image (default: both)"
    )
    parser_package.add_argument(
        "--platform",
        help="Target arch: a single arch, a comma list, or 'all' for a multi-arch manifest; "
        "default: native",
    )
    parser_package.add_argument(
        "--runtime",
        choices=("docker", "podman"),
        help="Container runtime (default: docker if present, else podman)",
    )

    parser_config = subparser_action.add_parser(
        "config", help="Show key properties (URL, admin user/password, ...) of a service"
    )
    # dest is 'config_service' to avoid clobbering the top-level 'service' subparser dest.
    parser_config.add_argument(
        "config_service",
        metavar="service",
        nargs="?",
        choices=SERVICES,
        help="Service to describe (default: all services as a table)",
    )

    # 'dev plugin <command>' — scaffold, build frontends, and renovate Ligoj plugins.
    from ligojcli import dev_plugin

    parser_plugin = subparser_action.add_parser(
        "plugin", help="Ligoj plugin dev helpers ('create', 'build', 'renovate')"
    )
    plugin_sub = parser_plugin.add_subparsers(title="command", dest="operation")
    plugin_create = plugin_sub.add_parser(
        "create",
        help="Create a new Ligoj plugin (service or tool) in the current directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Scaffold a new Ligoj plugin (Java + Vue UI + tests + CI) from its artifact name.",
        epilog=dev_plugin.HELP,
    )
    plugin_create.add_argument(
        "plugin", help="Full plugin artifact, must start with 'plugin-' (e.g. plugin-km-confluence)"
    )
    plugin_create.add_argument("--name", help="Display name (pom <name>); prompted if omitted")
    plugin_create.add_argument("--description", help="One-line description; prompted if omitted")
    plugin_create.add_argument(
        "--dir", help="Parent directory to create the plugin in (default: cwd)"
    )

    plugin_build = plugin_sub.add_parser(
        "build", help="Run 'npm run build' for each live plugin's frontend (ui/)"
    )
    plugin_build.add_argument(
        "--only",
        "-O",
        nargs="*",
        help="Only build these plugin artifacts (e.g. plugin-ui plugin-id); skips the live lookup",
    )
    plugin_build.add_argument(
        "--jobs",
        "-j",
        type=int,
        default=None,
        help="Number of parallel builds (default: min(4, CPUs))",
    )

    plugin_renovate = plugin_sub.add_parser(
        "renovate",
        help="Update pom.xml plugin-parent + align npm deps with the host, regenerating the lockfile",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Update a plugin's pom.xml, package.json and package-lock.json (see release.sh).",
        epilog=dev_plugin.HELP_RENOVATE,
    )
    plugin_renovate.add_argument(
        "plugin",
        nargs="?",
        help="Plugin to renovate (artifact under LIGOJ_PLUGINS_DIR, or a path); default: current dir",
    )
    plugin_renovate.add_argument(
        "--all", action="store_true", help="Renovate every plugin under LIGOJ_PLUGINS_DIR"
    )
    plugin_renovate.add_argument(
        "--parent-version",
        dest="parent_version",
        help="plugin-parent target version (default: latest local org.ligoj.api:parent)",
    )
    plugin_renovate.add_argument(
        "--host-package-json",
        dest="host_package_json",
        help="Host UI package.json (default: LIGOJ_HOST_PACKAGE_JSON or the app-ui webapp one)",
    )
    plugin_renovate.add_argument(
        "--plugins-dir",
        dest="plugins_dir",
        help="Plugins root (default: ~/git/ligoj-plugins, LIGOJ_PLUGINS_DIR)",
    )


def execute_action(service, action, _operation, args):
    if service != "dev":
        return None
    if action == "init":
        return dev_init(args)
    if action == "status":
        return dev_status(args)
    if action == "config":
        return dev_config(args)
    if action == "restart":
        return dev_restart(args)
    if action == "stop":
        return dev_stop(args)
    if action == "start":
        return dev_start(args)
    if action == "up":
        return dev_up(args)
    if action == "down":
        return dev_down(args)
    if action == "backup":
        from ligojcli import dev_backup

        return dev_backup.backup(args)
    if action == "restore":
        from ligojcli import dev_backup

        return dev_backup.restore(args)
    if action == "demo":
        # Lazy import: only needed for this action, and it talks to the Ligoj REST API.
        from ligojcli import dev_demo

        return dev_demo.demo(args)
    if action == "debug":
        # Lazy import: drives the local IDE app stack (IntelliJ + Ligoj API/UI + Vite).
        from ligojcli import dev_debug

        return dev_debug.execute(args)
    if action == "test":
        # Lazy import: runs the released Ligoj app containers (docker/podman) in the background.
        from ligojcli import dev_test

        return dev_test.execute(args)
    if action == "package":
        # Lazy import: builds the Ligoj app container images locally (podman/docker).
        from ligojcli import dev_package

        return dev_package.execute(args)
    if action == "plugin":
        # Lazy import: scaffolds/builds/renovates Ligoj plugin projects on disk.
        from ligojcli import dev_plugin

        return dev_plugin.execute(args)
    return None


def dev_build_plugin(args):
    """Run 'npm run build' in the ui/ frontend of each live plugin (in parallel)."""
    if shutil.which("npm") is None:
        raise ValueError("[dev] 'npm' not found; install Node.js first (needed to build frontends)")
    plugins_dir = os.path.expanduser(
        _dev_get(args, "ligoj_plugins_dir", "LIGOJ_PLUGINS_DIR", "~/git/ligoj-plugins")
    )
    targets = _plugin_ui_targets(args, plugins_dir)
    if not targets:
        utils.warn(
            f"[dev] plugin build: no plugin with a '<plugin>/ui/' frontend under {plugins_dir}"
        )
        return False

    workers = args.get("jobs") or min(4, os.cpu_count() or 4)
    utils.info(
        f"[dev] Building {len(targets)} plugin frontend(s) with 'npm run build' "
        f"({workers} parallel) ..."
    )
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(_npm_build_plugin, art, ui): art for art, ui in targets}
        for future in concurrent.futures.as_completed(pending):
            artifact = pending[future]
            ok, output = future.result()
            results[artifact] = ok
            if ok:
                utils.info(f"[dev] {artifact}: build OK")
            else:
                utils.warn(f"[dev] {artifact}: build FAILED\n{output}")

    done = sum(1 for ok in results.values() if ok)
    utils.info(f"[dev] Plugin build complete: {done}/{len(results)} succeeded")
    return results


def _plugin_ui_targets(args, plugins_dir):
    """Resolve the (artifact, ui_dir) pairs to build: the live plugins, or --only when given."""
    only = args.get("only")
    if only:
        artifacts = list(dict.fromkeys(only))  # explicit selection, no need for a running Ligoj
    else:
        # 'live' plugins = those installed in the running Ligoj.
        from ligojcli.plugins import ligoj

        try:
            plugins = ligoj.plugin_list() or []
        except Exception as error:  # noqa: BLE001 - turn any connection error into a clear hint
            raise ValueError(
                f"[dev] plugin build: cannot list live plugins (is Ligoj running? {error}); "
                "pass --only <artifact>... to build specific plugins without it"
            )
        artifacts = list(
            dict.fromkeys(
                (entry.get("plugin") or {}).get("artifact")
                for entry in plugins
                if (entry.get("plugin") or {}).get("artifact")
            )
        )
    targets = []
    for artifact in artifacts:
        ui_dir = os.path.join(plugins_dir, artifact, "ui")
        if os.path.isfile(os.path.join(ui_dir, "package.json")):
            targets.append((artifact, ui_dir))
        elif only:
            utils.warn(f"[dev] plugin build: no '{artifact}/ui/package.json' under {plugins_dir}")
    return targets


def _npm_build_plugin(artifact, ui_dir):
    """Install dependencies when missing, then 'npm run build'. Returns (ok, tail-of-output)."""
    if not os.path.isdir(os.path.join(ui_dir, "node_modules")):
        install = (
            ["npm", "ci"]
            if os.path.isfile(os.path.join(ui_dir, "package-lock.json"))
            else ["npm", "install"]
        )
        utils.info(f"[dev] {artifact}: {' '.join(install)} (first build) ...")
        installed = _run(install, cwd=ui_dir, check=False)
        if installed.returncode != 0:
            return False, _cmd_tail(installed)
    result = _run(["npm", "run", "build"], cwd=ui_dir, check=False)
    return result.returncode == 0, _cmd_tail(result)


def _cmd_tail(result, lines=15):
    text = ((result.stdout or "") + (result.stderr or "")).strip()
    return "\n".join(text.splitlines()[-lines:])


def dev_init(args):
    services = args.get("only") or SERVICES
    _check_preconditions(services, args)
    summary = {}
    if "postgresql" in services:
        summary["postgresql"] = _init_postgres(args)
    if "openldap" in services:
        summary["openldap"] = _init_openldap(args)
    if "keycloak" in services:
        summary["keycloak"] = _init_keycloak(args)
    if "jenkins" in services:
        summary["jenkins"] = _init_jenkins(args)
    if "sonarqube" in services:
        summary["sonarqube"] = _init_sonarqube(args)
    if "gitlab" in services:
        summary["gitlab"] = _init_gitlab(args)
    if "harbor" in services:
        summary["harbor"] = _init_harbor(args)
    if "nexus" in services:
        summary["nexus"] = _init_nexus(args)
    if "artifactory" in services:
        summary["artifactory"] = _init_artifactory(args)
    if "argocd" in services:
        summary["argocd"] = _init_argocd(args)
    utils.info("[dev] Developer environment ready")
    return summary


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
# svc, pod, (port option key, env, default), scheme, health path
_STATUS_SPECS = [
    ("postgresql", "ligoj-db", ("db_port", "DB_PORT", "5432"), "tcp", None),
    ("openldap", "openldap", ("ldap_port", "LDAP_PORT", "1389"), "tcp", None),
    ("keycloak", "keycloak", ("keycloak_port", "KEYCLOAK_PORT", "9083"), "http", "/realms/master"),
    ("jenkins", "jenkins", ("jenkins_port", "JENKINS_PORT", "8085"), "http", "/login"),
    ("sonarqube", "sonarqube", ("sonar_port", "SONAR_PORT", "9000"), "http", "/api/system/status"),
    ("gitlab", "gitlab", ("gitlab_port", "GITLAB_PORT", "8929"), "http", "/-/health"),
    ("harbor", "harbor", ("harbor_port", "HARBOR_PORT", "8088"), "http", "/api/v2.0/health"),
    ("nexus", "nexus", ("nexus_port", "NEXUS_PORT", "8181"), "http", "/service/rest/v1/status"),
    (
        "artifactory",
        "artifactory",
        ("artifactory_port", "ARTIFACTORY_PORT", "8082"),
        "http",
        "/api/system/ping",
    ),
    ("argocd", "argocd", ("argocd_port", "ARGOCD_PORT", "8083"), "http", "/healthz"),
]
_ENDPOINT_KEYS = {
    "postgresql": "db_url",
    "openldap": "ldap_url",
    "keycloak": "keycloak_endpoint",
    "jenkins": "jenkins_endpoint",
    "sonarqube": "sonar_endpoint",
    "gitlab": "gitlab_endpoint",
    "harbor": "harbor_endpoint",
    "nexus": "nexus_endpoint",
    "artifactory": "artifactory_endpoint",
    "argocd": "argocd_endpoint",
}
_PORT_SPECS = {spec[0]: spec[2] for spec in _STATUS_SPECS}
_PODS = {spec[0]: spec[1] for spec in _STATUS_SPECS}


def _service_port(svc, args):
    key, env, default = _PORT_SPECS[svc]
    return str(_dev_get(args, key, env, default))


def _service_url(svc, args):
    return _dev_stored(_ENDPOINT_KEYS[svc]) or _default_url(svc, _service_port(svc, args), args)


def dev_status(args):
    rows = [_service_status(spec, args) for spec in _STATUS_SPECS]
    _print_status_table(rows)
    return False


def dev_restart(args):
    wait = args.get("wait")
    svc = args.get("restart_service")
    services = [svc] if svc else SERVICES
    for service in services:
        _restart_service(service)
    if wait != 0:
        _await_services(services, args, True, wait)
    utils.info("[dev] Restart complete")
    return False


def _restart_service(svc):
    if svc in KIND_SERVICES:
        if (
            shutil.which("kind") is None
            or KIND_CLUSTER not in _kind("get", "clusters", check=False).stdout.split()
        ):
            utils.warn(f"[dev] {svc}: kind cluster absent, run 'dev init --only {svc}' first")
            return
        utils.info(f"[dev] Restart {svc} workloads (kind rollout) ...")
        _kind_node_start()
        _kubectl(
            "-n", svc, "rollout", "restart", "deployment,statefulset", check=False, stream=True
        )
        return
    pod = _PODS[svc]
    if not _pod_exists(pod):
        utils.warn(f"[dev] {svc}: pod '{pod}' does not exist, run 'dev init --only {svc}' first")
        return
    utils.info(f"[dev] Restart pod '{pod}' ...")
    _podman("pod", "restart", pod, stream=True)


def dev_stop(args):
    wait = args.get("wait")
    # 'stop_service' is a list (nargs='*'); empty or absent means every service.
    requested = args.get("stop_service")
    services = list(requested) if requested else SERVICES
    # Non-kind services are stopped as individual kube-play pods.
    for service in services:
        if service not in KIND_SERVICES:
            _stop_service(service)
    # Harbor + ArgoCD share the kind cluster: stopping ALL of them pauses the whole node at once
    # (preserving their replica counts); stopping only some scales just those to 0.
    kind_requested = [service for service in services if service in KIND_SERVICES]
    if set(kind_requested) == set(KIND_SERVICES):
        _stop_kind_node()
    else:
        for service in kind_requested:
            _stop_service(service)
    if wait != 0:
        _await_services(services, args, False, wait)
    utils.info("[dev] Stop complete (run 'dev init' to bring services back up)")
    return False


def _stop_service(svc):
    if svc in KIND_SERVICES:
        if (
            shutil.which("kind") is None
            or KIND_CLUSTER not in _kind("get", "clusters", check=False).stdout.split()
        ):
            utils.warn(f"[dev] {svc}: kind cluster absent, nothing to stop")
            return
        utils.info(f"[dev] Stop {svc} workloads (scale to 0) ...")
        _kubectl(
            "-n",
            svc,
            "scale",
            "deployment,statefulset",
            "--all",
            "--replicas=0",
            check=False,
            stream=True,
        )
        return
    pod = _PODS[svc]
    if not _pod_exists(pod):
        utils.warn(f"[dev] {svc}: pod '{pod}' does not exist")
        return
    utils.info(f"[dev] Stop pod '{pod}' ...")
    _podman("pod", "stop", pod, stream=True)


def _stop_kind_node():
    if (
        shutil.which("kind") is None
        or KIND_CLUSTER not in _kind("get", "clusters", check=False).stdout.split()
    ):
        return
    node = f"{KIND_CLUSTER}-control-plane"
    if _container_is_running(node):
        utils.info(f"[dev] Stop kind node '{node}' (Harbor + ArgoCD) ...")
        _podman("stop", node, check=False)


def dev_start(args):
    # Bring the podman runtime up first: start (or init) the machine and launch the Podman Desktop
    # GUI. A stopped machine otherwise makes every pod look absent (podman can't connect), so
    # starting a service would just warn 'pod does not exist'.
    _ensure_podman()
    _start_podman_desktop()
    wait = args.get("wait")
    # 'start_service' is a list (nargs='*'); empty or absent (e.g. via 'dev up') means every service.
    requested = args.get("start_service")
    services = list(requested) if requested else SERVICES
    for service in services:
        _start_service(service)
    if wait != 0:
        _await_services(services, args, True, wait)
    utils.info("[dev] Start complete")
    return False


def dev_up(args):
    """Start podman + its machine and Podman Desktop, wait until ready, then start all services."""
    return dev_start(args)


def dev_down(args):
    """Hard-stop the whole environment: stop the podman machine, then quit Podman Desktop."""
    utils.info(
        "[dev] Hard stop: stopping the podman machine (all dev services go down with it) ..."
    )
    result = _podman("machine", "stop", check=False)
    if result.returncode != 0:
        error = (result.stderr or "").lower()
        if "already stopped" not in error and "not running" not in error:
            utils.warn(f"[dev] podman machine stop: {(result.stderr or '').strip()}")
    _stop_podman_desktop()
    utils.info("[dev] Environment down; run 'dev up' to bring it back")
    return False


# The Podman Desktop GUI (macOS) manages/holds the podman machine, so a full 'down' quits it too and
# 'up' launches it again.
_PODMAN_DESKTOP_APP = "Podman Desktop"


def _podman_desktop_installed():
    return sys.platform == "darwin" and os.path.isdir(f"/Applications/{_PODMAN_DESKTOP_APP}.app")


def _podman_desktop_running():
    running = _run(["pgrep", "-f", f"{_PODMAN_DESKTOP_APP}.app/Contents/MacOS/"], check=False)
    return running.returncode == 0


def _start_podman_desktop():
    if not _podman_desktop_installed():
        return
    utils.info(f"[dev] Start {_PODMAN_DESKTOP_APP} ...")
    _run(["open", "-a", _PODMAN_DESKTOP_APP], check=False)


def _stop_podman_desktop():
    if not _podman_desktop_installed() or not _podman_desktop_running():
        return
    utils.info(f"[dev] Quit {_PODMAN_DESKTOP_APP} ...")
    _run(["osascript", "-e", f'quit app "{_PODMAN_DESKTOP_APP}"'], check=False)
    # Hard stop: force-terminate anything that did not quit.
    _run(["pkill", "-f", f"{_PODMAN_DESKTOP_APP}.app/Contents/MacOS/"], check=False)


def _start_service(svc):
    if svc in KIND_SERVICES:
        if (
            shutil.which("kind") is None
            or KIND_CLUSTER not in _kind("get", "clusters", check=False).stdout.split()
        ):
            utils.warn(f"[dev] {svc}: kind cluster absent, run 'dev init --only {svc}' first")
            return
        _kind_node_start()  # start the node if it was stopped (whole-cluster stop)
        utils.info(f"[dev] Start {svc} workloads (scale to 1) ...")
        _kubectl(
            "-n",
            svc,
            "scale",
            "deployment,statefulset",
            "--all",
            "--replicas=1",
            check=False,
            stream=True,
        )
        return
    pod = _PODS[svc]
    if not _pod_exists(pod):
        utils.warn(f"[dev] {svc}: pod '{pod}' does not exist, run 'dev init --only {svc}' first")
        return
    utils.info(f"[dev] Start pod '{pod}' ...")
    _podman("pod", "start", pod, stream=True)


def _service_healthy(svc, args):
    # A host-side health probe: HTTP for web services, TCP connect for PostgreSQL/LDAP.
    spec = next(s for s in _STATUS_SPECS if s[0] == svc)
    scheme, path = spec[3], spec[4]
    url = _service_url(svc, args)
    if scheme == "tcp":
        parsed = urlparse(url)
        return _probe_tcp(
            parsed.hostname or "localhost", parsed.port or int(_service_port(svc, args))
        )
    return _probe_http(url.rstrip("/") + path)


def _service_status(spec, args):
    svc, pod, _ports, _scheme, _path = spec
    url = _service_url(svc, args)
    runtime = _runtime_status(svc, pod)
    healthy = _service_healthy(svc, args)
    return {
        "service": svc,
        "status": "running (kind)" if svc in KIND_SERVICES and runtime == "running" else runtime,
        "status_level": {"running": "ok", "stopped": "warn", "absent": "bad"}.get(runtime, "warn"),
        "health": "OK" if healthy else "DOWN",
        "health_level": "ok" if healthy else "bad",
        "url": url,
    }


def _default_url(svc, port, args):
    if svc == "postgresql":
        db = _dev_get(args, "db_name", "POSTGRES_DB", "ligoj")
        return f"postgresql://localhost:{port}/{db}"
    if svc == "openldap":
        return f"ldap://localhost:{port}"
    if svc == "artifactory":
        # The REST API (and the Ligoj node URL) live under the /artifactory context path.
        return f"http://localhost:{port}/artifactory"
    return f"http://localhost:{port}"


def _runtime_status(svc, pod):
    if svc in KIND_SERVICES:
        if shutil.which("kind") is None or shutil.which("kubectl") is None:
            return "unknown"
        clusters = _kind("get", "clusters", check=False).stdout.split()
        if KIND_CLUSTER not in clusters:
            return "absent"
        # Cluster is up; is this service's namespace actually running a pod?
        result = _kubectl(
            "-n",
            svc,
            "get",
            "pods",
            "--field-selector=status.phase=Running",
            "--no-headers",
            check=False,
        )
        return "running" if result.returncode == 0 and result.stdout.strip() else "absent"
    if shutil.which("podman") is None:
        return "unknown"
    if not _pod_exists(pod):
        return "absent"
    return "running" if _pod_running(pod) else "stopped"


def _probe_http(url):
    try:
        return requests.get(url, timeout=4, allow_redirects=False).status_code < 500
    except requests.RequestException:
        return False


def _probe_tcp(host, port):
    try:
        with socket.create_connection((host, int(port)), timeout=4):
            return True
    except OSError:
        return False


# Artifactory's JFrog microservice mesh occasionally deadlocks on boot: the internal services fail to
# join each other over localhost (they try the IPv6 ::1 loopback and get 'connection refused'), so the
# container stays up but its router never binds :8082 — the port `dev` and the Ligoj node probe. A
# healthy boot answers on :8082 within seconds (503 while starting), a hung one never does. When that
# signature persists past a grace period, restart the pod once; a fresh boot usually wins the race.
_ARTIFACTORY_HEAL_DEFAULT = 90


def _artifactory_heal_after(args):
    try:
        return int(
            _dev_get(
                args,
                "artifactory_heal_after",
                "ARTIFACTORY_HEAL_AFTER",
                str(_ARTIFACTORY_HEAL_DEFAULT),
            )
        )
    except (TypeError, ValueError):
        return _ARTIFACTORY_HEAL_DEFAULT


def _artifactory_router_down(args):
    # True only when :8082 refuses connections (the hung signature); a 503 while booting is 'up'.
    url = _service_url("artifactory", args).rstrip("/") + "/api/system/ping"
    try:
        requests.get(url, timeout=4, allow_redirects=False)
        return False
    except requests.RequestException:
        return True


def _maybe_heal_artifactory(args, elapsed, healed):
    # healed: single-element mutable flag so the pod is restarted at most once per wait.
    after = _artifactory_heal_after(args)
    if healed[0] or after <= 0 or elapsed < after:
        return
    if not _pod_exists("artifactory") or not _artifactory_router_down(args):
        return
    healed[0] = True
    utils.warn(
        f"[dev] Artifactory router still not listening after {elapsed}s (JFrog boot join "
        "deadlock); restarting the pod once"
    )
    _podman("pod", "restart", "artifactory", check=False)


def _color(text, level):
    palette = {"ok": Fore.GREEN, "warn": Fore.YELLOW, "bad": Fore.RED}
    if utils.no_color or level not in palette:
        return text
    return f"{palette[level]}{text}{Style.RESET_ALL}"


def _print_status_table(rows):
    cols = ["SERVICE", "STATUS", "HEALTH", "URL"]
    data = [[r["service"], r["status"], r["health"], r["url"]] for r in rows]
    widths = [max(len(cols[i]), *(len(row[i]) for row in data)) for i in range(len(cols))]
    print("  ".join(cols[i].ljust(widths[i]) for i in range(len(cols))))
    print("  ".join("-" * widths[i] for i in range(len(cols))))
    for r, row in zip(rows, data):
        print(
            "  ".join(
                [
                    row[0].ljust(widths[0]),
                    _color(row[1].ljust(widths[1]), r["status_level"]),
                    _color(row[2].ljust(widths[2]), r["health_level"]),
                    row[3].ljust(widths[3]),
                ]
            )
        )


def dev_config(args):
    svc = args.get("config_service")
    if not svc:
        _print_config_table(args)
        return False
    props = _service_config(svc, args)
    label_width = max((len(label) for label, _ in props), default=0)
    print(f"# {svc}")
    for label, value in props:
        print(f"{label.ljust(label_width)}  {value}")
    return False


def _config_row(svc, args):
    props = dict(_service_config(svc, args))
    return [
        svc,
        props.get("url", "-"),
        props.get("admin user") or props.get("user") or "-",
        props.get("admin password") or props.get("password") or "-",
        props.get("api token") or props.get("client secret") or "-",
    ]


def _print_config_table(args):
    cols = ["SERVICE", "URL", "USER", "PASSWORD", "TOKEN/SECRET"]
    rows = [_config_row(svc, args) for svc in SERVICES]
    widths = [max(len(cols[i]), *(len(r[i]) for r in rows)) for i in range(len(cols))]
    print("  ".join(cols[i].ljust(widths[i]) for i in range(len(cols))))
    print("  ".join("-" * widths[i] for i in range(len(cols))))
    for r in rows:
        print("  ".join(r[i].ljust(widths[i]) for i in range(len(cols))))


def _service_config(svc, args):
    url = _service_url(svc, args)
    port = _service_port(svc, args)
    if svc == "postgresql":
        return [
            ("url", url),
            ("host", "localhost"),
            ("port", port),
            ("database", _dev_get(args, "db_name", "POSTGRES_DB", "ligoj")),
            ("user", _dev_get(args, "db_user", "POSTGRES_USER", "ligoj")),
            ("password", _dev_get(args, "db_password", "POSTGRES_PASSWORD", "ligoj")),
        ]
    if svc == "openldap":
        admin = _dev_get(args, "ldap_admin_user", "LDAP_ADMIN_USERNAME", "Manager")
        root = _dev_get(args, "ldap_root", "LDAP_ROOT", "dc=sample,dc=com")
        return [
            ("url", url),
            ("admin user", admin),
            ("admin password", _dev_get(args, "ldap_admin_password", "LDAP_ADMIN_PASSWORD", "-")),
            ("bind DN", f"cn={admin},{root}"),
            ("base DN", root),
        ]
    if svc == "keycloak":
        return [
            ("url", url),
            (
                "admin user",
                _dev_get(args, "keycloak_admin_user", "KC_BOOTSTRAP_ADMIN_USERNAME", "admin"),
            ),
            (
                "admin password",
                _dev_get(args, "keycloak_admin_password", "KC_BOOTSTRAP_ADMIN_PASSWORD", "admin"),
            ),
            ("realm", _dev_stored("keycloak_realm") or KEYCLOAK_REALM),
            ("issuer URI", _dev_stored("keycloak_issuer_uri") or f"{url}/realms/{KEYCLOAK_REALM}"),
            ("client id", _dev_stored("keycloak_client_id") or KEYCLOAK_CLIENT),
            ("client secret", _dev_stored("keycloak_client_secret") or "-"),
        ]
    if svc == "jenkins":
        return [
            ("url", url),
            ("admin user", _dev_get(args, "jenkins_api_user", "JENKINS_API_USER", "admin")),
            ("admin password", _dev_stored("jenkins_admin_password") or "-"),
            ("api token", _dev_stored("jenkins_api_token") or "-"),
        ]
    if svc == "sonarqube":
        return [
            ("url", url),
            ("admin user", "admin"),
            ("admin password", _dev_stored("sonar_admin_password") or "-"),
            ("api token", _dev_stored("sonar_api_token") or "-"),
        ]
    if svc == "gitlab":
        ssh_port = _dev_get(args, "gitlab_ssh_port", "GITLAB_SSH_PORT", "2289")
        return [
            ("url", url),
            ("admin user", "root"),
            ("admin password", _dev_stored("gitlab_root_password") or "-"),
            ("ssh", f"ssh://git@localhost:{ssh_port}"),
        ]
    if svc == "harbor":
        return [
            ("url", url),
            ("registry", f"localhost:{port}"),
            ("admin user", _dev_stored("harbor_admin_user") or "admin"),
            ("admin password", _dev_stored("harbor_admin_password") or "-"),
        ]
    if svc == "nexus":
        return [
            ("url", url),
            ("admin user", _dev_stored("nexus_admin_user") or "admin"),
            ("admin password", _dev_stored("nexus_admin_password") or "-"),
        ]
    if svc == "artifactory":
        return [
            ("url", url),
            ("admin user", _dev_get(args, "artifactory_user", "ARTIFACTORY_USER", "admin")),
            (
                "admin password",
                _dev_stored("artifactory_password")
                or _dev_get(args, "artifactory_password", "ARTIFACTORY_PASSWORD", "-"),
            ),
        ]
    if svc == "argocd":
        return [
            ("url", url),
            ("admin user", "admin"),
            ("admin password", _dev_stored("argocd_admin_password") or "-"),
            ("account", _dev_stored("argocd_account") or ARGOCD_ACCOUNT),
            ("role", ARGOCD_ROLE),
            ("api token", _dev_stored("argocd_api_token") or "-"),
        ]
    return [("url", url)]


# --------------------------------------------------------------------------- #
# Pre-conditions
# --------------------------------------------------------------------------- #
JAVA_VERSION = "21"
MAVEN_VERSION = "3.9.6"


def _check_preconditions(services, args):
    # The init phase bootstraps its own tooling: missing CLIs are installed (Homebrew on
    # macOS/Linux, SDKMAN for the JVM) and the podman machine is initialized/started as needed.
    if args.get("skip_prereqs"):
        utils.info("[dev] --skip-prereqs: not checking podman / Java / Maven")
        return
    utils.info("[dev] Check pre-conditions ...")
    _ensure_podman(enforce_resources=True)
    # Java + Maven are only needed by 'dev demo' seeding, so they are best-effort (never fatal here).
    _ensure_java(JAVA_VERSION)
    _ensure_maven(MAVEN_VERSION)
    if set(KIND_SERVICES) & set(services):
        for tool in ("kind", "helm", "kubectl"):
            _ensure_tool(tool)
        utils.info("[dev] kind, helm and kubectl are available (for Harbor/ArgoCD)")


def _ensure_java(major):
    if _java_available(major):
        utils.info(f"[dev] Java {major} is available")
        return
    if sys.platform != "darwin":
        utils.warn(f"[dev] Java {major} not found; install a JDK {major} (needed by 'dev demo')")
        return
    try:
        if shutil.which("brew") is None:
            raise ValueError("Homebrew is not available")
        utils.info(f"[dev] Installing Temurin JDK {major} with Homebrew ...")
        _run(["brew", "install", "--cask", f"temurin@{major}"], stream=True)
    except Exception as error:  # noqa: BLE001 - best effort, only needed later by 'dev demo'
        utils.warn(f"[dev] Could not install Java {major}: {error}; install it manually")
        return
    utils.info(
        f"[dev] Java {major} " + ("installed" if _java_available(major) else "still missing")
    )


def _java_available(major):
    home = _run(["/usr/libexec/java_home", "-v", str(major)], check=False)
    if home.returncode == 0:
        return True
    if shutil.which("java") is None:
        return False
    out = _run(["java", "-version"], check=False)
    match = re.search(r'version "(\d+)', (out.stderr or "") + (out.stdout or ""))
    return match is not None and match.group(1) == str(major)


def _ensure_maven(version):
    current = _maven_version()
    if current and _version_ge(current, version):
        utils.info(f"[dev] Maven {current} is available")
        return
    if sys.platform != "darwin":
        utils.warn(f"[dev] Maven {version} not found; install it (needed by 'dev demo')")
        return
    try:
        utils.info(f"[dev] Installing Maven {version} with SDKMAN ...")
        _ensure_sdkman()
        _sdk(f"install maven {version}")
        _sdk(f"default maven {version}")
    except Exception as error:  # noqa: BLE001 - best effort, only needed later by 'dev demo'
        utils.warn(f"[dev] Could not install Maven {version}: {error}; install it manually")
        return
    utils.info(f"[dev] Maven {version} installed via SDKMAN (open a new shell to use it)")


def _maven_version():
    mvn = shutil.which("mvn") or os.path.expanduser("~/.sdkman/candidates/maven/current/bin/mvn")
    if not os.path.exists(mvn):
        return None
    out = _run([mvn, "-version"], check=False)
    match = re.search(r"Apache Maven (\d+\.\d+\.\d+)", (out.stdout or "") + (out.stderr or ""))
    return match.group(1) if match else None


def _version_ge(actual, minimum):
    def parts(value):
        return tuple(int(piece) for piece in value.split("."))

    return parts(actual) >= parts(minimum)


def _sdk(command):
    script = (
        f'source "$HOME/.sdkman/bin/sdkman-init.sh"; export sdkman_auto_answer=true; sdk {command}'
    )
    _run(["bash", "-c", script], stream=True)


def _ensure_sdkman():
    init = os.path.expanduser("~/.sdkman/bin/sdkman-init.sh")
    if os.path.exists(init):
        return
    utils.info("[dev] Installing SDKMAN ...")
    _run(["bash", "-c", 'curl -s "https://get.sdkman.io" | bash'], stream=True)
    if not os.path.exists(init):
        raise ValueError("SDKMAN installation did not complete")


def _brew_install(package):
    if shutil.which("brew") is None:
        raise ValueError(
            f"[dev] '{package}' is missing and Homebrew is not available to install it. "
            f"Install Homebrew (https://brew.sh) then 'brew install {package}', or add it to PATH."
        )
    utils.info(f"[dev] Installing '{package}' with Homebrew ...")
    _run(["brew", "install", package], stream=True)


def _ensure_tool(tool, package=None):
    if shutil.which(tool) is not None:
        return
    _brew_install(package or tool)
    if shutil.which(tool) is None:
        raise ValueError(f"[dev] '{tool}' is still not on PATH after installation")


# Minimum resources for the podman machine backing the full dev stack (GitLab + SonarQube + Nexus +
# Artifactory + kind all run at once). 'dev init' resizes the machine up to this when it is below.
_PODMAN_MIN_CPUS = 6
_PODMAN_MIN_MEMORY_MIB = 23 * 1024  # 23 GiB


def _ensure_podman(enforce_resources=False):
    """Ensure podman is installed and reachable, its machine sized (when requested) and started."""
    _ensure_tool("podman")
    _ensure_podman_machine(enforce_resources)
    result = _podman("info", "--format", "{{.Host.Arch}}", check=False)
    if result.returncode != 0:
        raise ValueError(
            f"[dev] podman is still not ready after machine start: {(result.stderr or '').strip()}"
        )
    utils.info("[dev] podman is available")


def _ensure_podman_machine(enforce_resources):
    """Init the machine if missing, resize it to the CPU/RAM minimum when requested, and start it.

    On native Linux podman there is no VM (the 'machine' subsystem is unavailable), so this is a
    no-op there.
    """
    listed = _podman("machine", "list", "--format", "{{.Name}}", check=False)
    if listed.returncode != 0:
        return  # native podman: no machine to manage
    if not listed.stdout.split():
        utils.info(
            f"[dev] Initialize podman machine ({_PODMAN_MIN_CPUS} vCPU, "
            f"{_PODMAN_MIN_MEMORY_MIB // 1024} GB RAM) ..."
        )
        _podman(
            "machine",
            "init",
            "--cpus",
            str(_PODMAN_MIN_CPUS),
            "--memory",
            str(_PODMAN_MIN_MEMORY_MIB),
            stream=True,
        )
    elif enforce_resources:
        _ensure_podman_resources()
    # Start it if it is not already running/reachable (blocks until the machine is up).
    if _podman("info", "--format", "{{.Host.Arch}}", check=False).returncode != 0:
        utils.info("[dev] Start podman machine (waiting until it is ready) ...")
        _podman("machine", "start", check=False, stream=True)


def _ensure_podman_resources():
    """Bring the podman machine up to the required CPU/RAM minimum: stop, resize, then it is
    restarted by the caller. Only bumps upward — never shrinks a machine that already exceeds it."""
    cpus, memory = _podman_machine_resources()
    if cpus is None:
        return
    if cpus >= _PODMAN_MIN_CPUS and memory >= _PODMAN_MIN_MEMORY_MIB:
        utils.info(f"[dev] podman machine: {cpus} vCPU / {memory // 1024} GB RAM (meets minimum)")
        return
    new_cpus = max(cpus, _PODMAN_MIN_CPUS)
    new_memory = max(memory, _PODMAN_MIN_MEMORY_MIB)
    utils.info(
        f"[dev] podman machine under-provisioned ({cpus} vCPU / {memory} MiB); resizing to "
        f"{new_cpus} vCPU / {new_memory} MiB ({new_memory // 1024} GB) — stop, set, start ..."
    )
    _podman("machine", "stop", check=False, stream=True)
    resized = _podman(
        "machine",
        "set",
        "--cpus",
        str(new_cpus),
        "--memory",
        str(new_memory),
        check=False,
        stream=True,
    )
    if resized.returncode != 0:
        utils.warn("[dev] Could not resize the podman machine; keeping its current resources")


def _podman_machine_resources():
    """(CPUs, Memory in MiB) of the default podman machine, or (None, None) if undeterminable."""
    result = _podman(
        "machine", "inspect", "--format", "{{.Resources.CPUs}} {{.Resources.Memory}}", check=False
    )
    parts = result.stdout.split() if result.returncode == 0 else []
    if len(parts) < 2:
        return None, None
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None


# --------------------------------------------------------------------------- #
# PostgreSQL (ligoj-db)
# --------------------------------------------------------------------------- #
def _init_postgres(args):
    utils.info("[dev] === PostgreSQL (ligoj-db) ===")
    recreate = args.get("recreate", False)
    image_override = _dev_get(args, "db_image", "DB_IMAGE", None)
    port = int(_dev_get(args, "db_port", "DB_PORT", "5432"))
    # Defaults match what ligoj-api expects (jdbc.username/password=ligoj, see ligoj/DOC.md).
    db_user = _dev_get(args, "db_user", "POSTGRES_USER", "ligoj")
    db_password = _dev_get(args, "db_password", "POSTGRES_PASSWORD", "ligoj")
    db_name = _dev_get(args, "db_name", "POSTGRES_DB", "ligoj")

    # Keep data under a sub-dir so the volume/bind root stays writable by postgres.
    pgdata = "/var/lib/postgresql/data/pgdata"
    data_source = None
    recovered_image = None
    if _container_exists(POSTGRES_CONTAINER):
        # Recover settings the existing (raw) container was created with, so the
        # migration keeps the same database, image (major version) and data location.
        db_user = _container_env(POSTGRES_CONTAINER, "POSTGRES_USER") or db_user
        db_password = _container_env(POSTGRES_CONTAINER, "POSTGRES_PASSWORD") or db_password
        db_name = _container_env(POSTGRES_CONTAINER, "POSTGRES_DB") or db_name
        pgdata = _container_env(POSTGRES_CONTAINER, "PGDATA") or pgdata
        recovered_image = _container_image(POSTGRES_CONTAINER)
        mount = _container_mounts(POSTGRES_CONTAINER).get("/var/lib/postgresql/data")
        if mount and (mount[0] or mount[1]):
            data_source = mount[0] or mount[1]
            kind = "volume" if mount[0] else "directory"
            utils.info(f"[dev] Reusing existing persistent {kind} '{data_source}'")
    if data_source is None:
        data_source = POSTGRES_VOLUME
    image = image_override or recovered_image or POSTGRES_DEFAULT_IMAGE

    volume, named = _data_volume(data_source)
    env = {
        "POSTGRES_USER": db_user,
        "POSTGRES_PASSWORD": db_password,
        "POSTGRES_DB": db_name,
        "PGDATA": pgdata,
    }
    manifest = _pod_manifest(
        POSTGRES_CONTAINER,
        image,
        [(5432, port)],
        env=env,
        volumes=[volume],
        mounts=[{"name": volume["name"], "mountPath": "/var/lib/postgresql/data"}],
    )
    if _pod_will_create(POSTGRES_CONTAINER, recreate):
        _ensure_image(image)
    _kube_apply(POSTGRES_CONTAINER, manifest, recreate, named)

    for name, value in (
        ("db_host", "localhost"),
        ("db_port", port),
        ("db_name", db_name),
        ("db_user", db_user),
        ("db_password", db_password),
        ("db_url", f"postgresql://{db_user}@localhost:{port}/{db_name}"),
    ):
        _dev_set(name, value)

    wait = args.get("wait")
    if wait != 0:
        _wait_postgres(POSTGRES_CONTAINER, db_user, db_name, wait)
    utils.info(
        f"[dev] PostgreSQL available on localhost:{port}, database '{db_name}' (user '{db_user}')"
    )
    return {
        "endpoint": f"postgresql://localhost:{port}/{db_name}",
        "database": db_name,
        "user": db_user,
        "data": data_source,
    }


# --------------------------------------------------------------------------- #
# Shared PostgreSQL provisioning (for SonarQube, Artifactory, ...)
# --------------------------------------------------------------------------- #
def _shared_db_provision(args, db_name, key_prefix, wait=None):
    """Ensure a dedicated role + database for another service in the shared 'ligoj-db' PostgreSQL.

    Returns a connection dict ``{host, port, name, user, password}`` the service can consume, or
    ``None`` when the shared PostgreSQL is absent/unreachable (the caller decides how to degrade).
    The service reaches the server at ``host.containers.internal:<db_port>`` (its own pod cannot use
    localhost). The role password is generated once and kept in ``[dev] <key_prefix>_password``.
    """
    if not _pod_exists(POSTGRES_CONTAINER):
        utils.warn(
            f"[dev] Shared PostgreSQL '{POSTGRES_CONTAINER}' not found; run "
            f"'dev init --only postgresql' first to back {db_name} with it (skipping DB setup)"
        )
        return None
    superuser = _dev_get(args, "db_user", "POSTGRES_USER", "ligoj")
    port = str(_dev_get(args, "db_port", "DB_PORT", "5432"))
    container = _pod_container(POSTGRES_CONTAINER)
    if not _wait_shared_pg(container, superuser, wait):
        utils.warn(f"[dev] Shared PostgreSQL not ready; skipping {db_name} database setup")
        return None
    user = db_name
    password = (
        _dev_get(args, f"{key_prefix}_password", f"{key_prefix.upper()}_PASSWORD", None)
        or _generate_secret()
    )
    if not _ensure_database(container, superuser, db_name, user, password):
        return None
    _dev_set(f"{key_prefix}_password", password)
    utils.info(f"[dev] Shared PostgreSQL database '{db_name}' ready (user '{user}')")
    return {
        "host": SHARED_DB_HOST,
        "port": port,
        "name": db_name,
        "user": user,
        "password": password,
    }


def _wait_shared_pg(container, superuser, wait):
    def ready():
        result = _podman("exec", container, "pg_isready", "-U", superuser, check=False)
        return (result.returncode == 0, "")

    # The shared server is normally already up (initialized earlier in the same 'dev init').
    return _await("PostgreSQL (shared)", ready, _deadline(0 if wait == 0 else 120))


def _ensure_database(container, superuser, db, user, password):
    # Idempotent: create the login role (or refresh its password), then the database it owns.
    # Generated secrets never contain a single quote (see SECRET_SPECIALS), so literal-quoting is safe.
    role_sql = (
        "DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{user}') THEN "
        f"CREATE ROLE \"{user}\" LOGIN PASSWORD '{password}'; "
        f"ELSE ALTER ROLE \"{user}\" WITH LOGIN PASSWORD '{password}'; "
        "END IF; END $$;"
    )
    role = _podman(
        "exec",
        container,
        "psql",
        "-U",
        superuser,
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        role_sql,
        check=False,
    )
    if role.returncode != 0:
        utils.warn(f"[dev] Could not ensure DB role '{user}': {(role.stderr or '').strip()[:200]}")
        return False
    create = _podman(
        "exec",
        container,
        "psql",
        "-U",
        superuser,
        "-d",
        "postgres",
        "-c",
        f'CREATE DATABASE "{db}" OWNER "{user}"',
        check=False,
    )
    if create.returncode == 0 or "already exists" in (create.stderr or "").lower():
        return True
    utils.warn(f"[dev] Could not create database '{db}': {(create.stderr or '').strip()[:200]}")
    return False


# --------------------------------------------------------------------------- #
# OpenLDAP
# --------------------------------------------------------------------------- #
def _init_openldap(args):
    utils.info("[dev] === OpenLDAP ===")
    recreate = args.get("recreate", False)
    image = _dev_get(args, "ldap_image", "LDAP_IMAGE", LDAP_DEFAULT_IMAGE)
    port = int(_dev_get(args, "ldap_port", "LDAP_PORT", "1389"))
    admin_user = _dev_get(args, "ldap_admin_user", "LDAP_ADMIN_USERNAME", "Manager")
    root = _dev_get(args, "ldap_root", "LDAP_ROOT", "dc=sample,dc=com")

    password = _dev_get(args, "ldap_admin_password", "LDAP_ADMIN_PASSWORD", None)
    if not password and _container_exists("openldap"):
        password = _container_env("openldap", "LDAP_ADMIN_PASSWORD")
        admin_user = _container_env("openldap", "LDAP_ADMIN_USERNAME") or admin_user
        root = _container_env("openldap", "LDAP_ROOT") or root
    if not password:
        password = _generate_secret()
        utils.info("[dev] No LDAP admin password found, generated one in [dev]")
    _dev_set("ldap_admin_password", password)

    env = {
        "LDAP_ADMIN_USERNAME": admin_user,
        "LDAP_ADMIN_PASSWORD": password,
        "LDAP_ROOT": root,
        "LDAP_USERS": "customuser",
        "LDAP_PASSWORDS": "custompassword",
    }
    volumes = [{"name": "data", "persistentVolumeClaim": {"claimName": "openldap_data"}}]
    mounts = [{"name": "data", "mountPath": "/bitnami/openldap"}]
    named = ["openldap_data"]
    schema_dir = os.path.expanduser(
        _dev_get(args, "ldap_schema_dir", "LDAP_SCHEMA_DIR", LDAP_DEFAULT_SCHEMA_DIR)
    )
    if os.path.isdir(schema_dir):
        utils.info(f"[dev] Mount LDAP custom schema from {schema_dir}")
        volumes.append({"name": "schema", "hostPath": {"path": schema_dir}})
        mounts.append({"name": "schema", "mountPath": "/schema"})

    manifest = _pod_manifest(
        "openldap", image, [(1389, port)], env=env, volumes=volumes, mounts=mounts
    )
    if _pod_will_create("openldap", recreate):
        _ensure_image(image)
    _kube_apply("openldap", manifest, recreate, named)

    endpoint = f"ldap://localhost:{port}"
    _dev_set("ldap_url", endpoint)
    _dev_set("ldap_port", port)
    _dev_set("ldap_admin_user", admin_user)
    _dev_set("ldap_root", root)

    # Seed the base DIT (OUs + sample users) so the structure referenced by the LDAP node and the
    # `dev demo` commands exists. bitnami only imports /ldifs on a first, empty-volume boot, so apply
    # it ourselves (idempotently) on every init to also heal an already-populated volume.
    wait = args.get("wait")
    ldif = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "ldap", "dev.ldif")
    if wait != 0 and os.path.isfile(ldif):
        container = _pod_container("openldap")
        if _wait_ldap(container, port, wait):
            _ldap_import(container, port, f"cn={admin_user},{root}", password, ldif)

    utils.info(f"[dev] OpenLDAP available on {endpoint} (bind cn={admin_user},{root})")
    return {"endpoint": endpoint, "admin_user": f"cn={admin_user},{root}", "root": root}


def _wait_ldap(container, port, wait):
    def ready():
        result = _podman(
            "exec",
            container,
            "ldapsearch",
            "-x",
            "-H",
            f"ldap://localhost:{port}",
            "-b",
            "",
            "-s",
            "base",
            "namingContexts",
            check=False,
        )
        return (result.returncode == 0, "")

    if _await("OpenLDAP", ready, _deadline(wait)):
        return True
    utils.warn("[dev] OpenLDAP not ready in time; skipping base DIT import")
    return False


def _ldap_import(container, port, admin_dn, password, ldif_host_path):
    utils.info("[dev] Import base DIT into LDAP (OUs + sample users) ...")
    _podman("cp", ldif_host_path, f"{container}:/tmp/ligoj-base.ldif", check=False)
    result = _podman(
        "exec",
        container,
        "ldapadd",
        "-c",
        "-x",
        "-H",
        f"ldap://localhost:{port}",
        "-D",
        admin_dn,
        "-w",
        password,
        "-f",
        "/tmp/ligoj-base.ldif",
        check=False,
    )
    # ldapadd -c exits 68 (LDAP_ALREADY_EXISTS) when entries already exist: idempotent, not an error.
    if result.returncode in (0, 68):
        utils.info("[dev] LDAP base DIT ensured")
    else:
        detail = (result.stderr or result.stdout or "").strip()
        utils.warn(f"[dev] LDAP base DIT import returned {result.returncode}: {detail[:300]}")


# --------------------------------------------------------------------------- #
# Keycloak
# --------------------------------------------------------------------------- #
def _init_keycloak(args):
    utils.info("[dev] === Keycloak ===")
    recreate = args.get("recreate", False)
    image = _dev_get(args, "keycloak_image", "KEYCLOAK_IMAGE", KEYCLOAK_DEFAULT_IMAGE)
    port = int(_dev_get(args, "keycloak_port", "KEYCLOAK_PORT", "9083"))
    admin_user = _dev_get(args, "keycloak_admin_user", "KC_BOOTSTRAP_ADMIN_USERNAME", "admin")
    admin_password = _dev_get(
        args, "keycloak_admin_password", "KC_BOOTSTRAP_ADMIN_PASSWORD", "admin"
    )
    wait = args.get("wait")
    if _container_exists(KEYCLOAK_CONTAINER):
        admin_user = _container_env(KEYCLOAK_CONTAINER, "KC_BOOTSTRAP_ADMIN_USERNAME") or admin_user
        admin_password = (
            _container_env(KEYCLOAK_CONTAINER, "KC_BOOTSTRAP_ADMIN_PASSWORD") or admin_password
        )

    env = {
        "KC_BOOTSTRAP_ADMIN_USERNAME": admin_user,
        "KC_BOOTSTRAP_ADMIN_PASSWORD": admin_password,
    }
    # Back Keycloak with the shared 'ligoj-db' PostgreSQL instead of the (dev-only) embedded H2.
    db = _shared_db_provision(args, "keycloak", "keycloak_db", wait)
    if db:
        env.update(
            {
                "KC_DB": "postgres",
                "KC_DB_URL": f"jdbc:postgresql://{db['host']}:{db['port']}/{db['name']}",
                "KC_DB_USERNAME": db["user"],
                "KC_DB_PASSWORD": db["password"],
            }
        )
    else:
        utils.warn("[dev] Keycloak falls back to the embedded H2 database (dev only)")

    manifest = _pod_manifest(
        KEYCLOAK_CONTAINER,
        image,
        [(8080, port)],
        env=env,
        args=["start-dev"],
        volumes=[{"name": "data", "persistentVolumeClaim": {"claimName": KEYCLOAK_VOLUME}}],
        mounts=[{"name": "data", "mountPath": "/opt/keycloak/data"}],
    )
    if _pod_will_create(KEYCLOAK_CONTAINER, recreate):
        _ensure_image(image)
    _kube_apply(KEYCLOAK_CONTAINER, manifest, recreate, [KEYCLOAK_VOLUME])

    base = f"http://localhost:{port}"
    _dev_set("keycloak_endpoint", base)
    _dev_set("keycloak_admin_user", admin_user)
    _dev_set("keycloak_admin_password", admin_password)

    if wait == 0:
        utils.warn("[dev] --wait 0, skipping Keycloak realm/client configuration")
        return {"endpoint": base}

    _wait_http(f"{base}/realms/master", "Keycloak", wait)
    token = _kc_admin_token(base, admin_user, admin_password)
    _kc_ensure_realm(base, token, KEYCLOAK_REALM)
    _kc_ensure_ldap_federation(base, token, args)
    secret = _kc_ensure_client(base, token)

    issuer = f"{base}/realms/{KEYCLOAK_REALM}"
    _dev_set("keycloak_realm", KEYCLOAK_REALM)
    _dev_set("keycloak_client_id", KEYCLOAK_CLIENT)
    _dev_set("keycloak_client_secret", secret)
    _dev_set("keycloak_issuer_uri", issuer)

    properties = _kc_spring_properties(issuer, secret)
    utils.info("[dev] Keycloak configured. Sample Spring Boot properties:")
    print(f"\n{properties}\n")
    return {
        "endpoint": base,
        "realm": KEYCLOAK_REALM,
        "client_id": KEYCLOAK_CLIENT,
        "issuer_uri": issuer,
    }


def _kc_headers(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": utils.MIME_JSON}


def _kc_admin_token(base, user, password):
    response = requests.post(
        f"{base}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": user,
            "password": password,
        },
        timeout=30,
    )
    if response.status_code != 200:
        raise ValueError(
            f"[dev] Keycloak admin login failed (HTTP {response.status_code}): {response.text}"
        )
    return response.json()["access_token"]


def _kc_ensure_realm(base, token, realm):
    existing = requests.get(f"{base}/admin/realms/{realm}", headers=_kc_headers(token), timeout=30)
    if existing.status_code == 200:
        utils.info(f"[dev] Keycloak realm '{realm}' already exists")
        return
    utils.info(f"[dev] Create Keycloak realm '{realm}' ...")
    response = requests.post(
        f"{base}/admin/realms",
        headers=_kc_headers(token),
        json={"realm": realm, "enabled": True},
        timeout=30,
    )
    if response.status_code not in (201, 409):
        raise ValueError(
            f"[dev] Unable to create realm '{realm}' (HTTP {response.status_code}): {response.text}"
        )


def _kc_ensure_ldap_federation(base, token, args):
    realm = KEYCLOAK_REALM
    ldap_user = _dev_get(args, "ldap_admin_user", "LDAP_ADMIN_USERNAME", "Manager")
    ldap_root = _dev_get(args, "ldap_root", "LDAP_ROOT", "dc=sample,dc=com")
    ldap_port = str(_dev_get(args, "ldap_port", "LDAP_PORT", "1389"))
    ldap_password = _dev_get(args, "ldap_admin_password", "LDAP_ADMIN_PASSWORD", None) or (
        _container_env("openldap", "LDAP_ADMIN_PASSWORD") or ""
    )
    # Keycloak runs in a pod, so it reaches the published LDAP port via the host gateway.
    ldap_url = _dev_get(
        args,
        "keycloak_ldap_url",
        "KEYCLOAK_LDAP_URL",
        f"ldap://host.containers.internal:{ldap_port}",
    )
    bind_dn = f"cn={ldap_user},{ldap_root}"
    if not ldap_password:
        utils.warn("[dev] No LDAP admin password available; federation bind credential is empty")

    components = requests.get(
        f"{base}/admin/realms/{realm}/components",
        headers=_kc_headers(token),
        params={"type": "org.keycloak.storage.UserStorageProvider"},
        timeout=30,
    ).json()
    if any(c.get("name") == "ldap" for c in components):
        utils.info("[dev] Keycloak LDAP federation 'ldap' already exists")
        return

    realm_info = requests.get(
        f"{base}/admin/realms/{realm}", headers=_kc_headers(token), timeout=30
    ).json()
    component = {
        "name": "ldap",
        "providerId": "ldap",
        "providerType": "org.keycloak.storage.UserStorageProvider",
        "parentId": realm_info.get("id", realm),
        "config": {
            "enabled": ["true"],
            "vendor": ["other"],
            "connectionUrl": [ldap_url],
            "bindDn": [bind_dn],
            "bindCredential": [ldap_password],
            "editMode": ["READ_ONLY"],
            "usersDn": [ldap_root],
            "userObjectClasses": ["inetOrgPerson"],
            "searchScope": ["2"],
            "usernameLDAPAttribute": ["uid"],
            "rdnLDAPAttribute": ["uid"],
            "uuidLDAPAttribute": ["entryUUID"],
            "importEnabled": ["true"],
            "syncRegistrations": ["false"],
            "pagination": ["true"],
        },
    }
    utils.info(f"[dev] Create Keycloak LDAP federation -> {ldap_url} (bind {bind_dn}) ...")
    response = requests.post(
        f"{base}/admin/realms/{realm}/components",
        headers=_kc_headers(token),
        json=component,
        timeout=30,
    )
    if response.status_code != 201:
        raise ValueError(
            f"[dev] Unable to create LDAP federation (HTTP {response.status_code}): {response.text}"
        )


def _kc_ensure_client(base, token):
    realm = KEYCLOAK_REALM
    representation = {
        "clientId": KEYCLOAK_CLIENT,
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": False,  # 'Client authentication' ON -> confidential
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": True,
        "serviceAccountsEnabled": False,
        "rootUrl": KEYCLOAK_ROOT_URL,
        "baseUrl": KEYCLOAK_ROOT_URL,
        "redirectUris": KEYCLOAK_REDIRECT_URIS,
        "webOrigins": ["+"],
        "attributes": {"post.logout.redirect.uris": "+"},
    }
    found = requests.get(
        f"{base}/admin/realms/{realm}/clients",
        headers=_kc_headers(token),
        params={"clientId": KEYCLOAK_CLIENT},
        timeout=30,
    ).json()
    if found:
        uid = found[0]["id"]
        utils.info(f"[dev] Keycloak client '{KEYCLOAK_CLIENT}' already exists, update ...")
        requests.put(
            f"{base}/admin/realms/{realm}/clients/{uid}",
            headers=_kc_headers(token),
            json={**found[0], **representation},
            timeout=30,
        )
    else:
        utils.info(f"[dev] Create Keycloak client '{KEYCLOAK_CLIENT}' ...")
        response = requests.post(
            f"{base}/admin/realms/{realm}/clients",
            headers=_kc_headers(token),
            json=representation,
            timeout=30,
        )
        if response.status_code != 201:
            raise ValueError(
                f"[dev] Unable to create client (HTTP {response.status_code}): {response.text}"
            )
        found = requests.get(
            f"{base}/admin/realms/{realm}/clients",
            headers=_kc_headers(token),
            params={"clientId": KEYCLOAK_CLIENT},
            timeout=30,
        ).json()
        uid = found[0]["id"]

    secret = (
        requests.get(
            f"{base}/admin/realms/{realm}/clients/{uid}/client-secret",
            headers=_kc_headers(token),
            timeout=30,
        )
        .json()
        .get("value")
    )
    if not secret:
        secret = (
            requests.post(
                f"{base}/admin/realms/{realm}/clients/{uid}/client-secret",
                headers=_kc_headers(token),
                timeout=30,
            )
            .json()
            .get("value")
        )
    return secret


def _kc_spring_properties(issuer, secret):
    prefix = "spring.security.oauth2.client"
    return "\n".join(
        [
            "security=OAuth2Bff",
            "ligoj.security.oauth2.username-attribute = email",
            "ligoj.security.login.url = /oauth2/authorization/keycloak",
            f"{prefix}.provider.keycloak.issuer-uri={issuer}",
            f"{prefix}.registration.keycloak.provider=keycloak",
            f"{prefix}.registration.keycloak.authorization-grant-type=authorization_code",
            f"{prefix}.registration.keycloak.client-id={KEYCLOAK_CLIENT}",
            f"{prefix}.registration.keycloak.client-secret={secret}",
            f"{prefix}.registration.keycloak.scope=openid",
        ]
    )


# --------------------------------------------------------------------------- #
# Jenkins
# --------------------------------------------------------------------------- #
def _init_jenkins(args):
    utils.info("[dev] === Jenkins ===")
    image = _dev_get(args, "jenkins_image", "JENKINS_IMAGE", JENKINS_DEFAULT_IMAGE)
    port = int(_dev_get(args, "jenkins_port", "JENKINS_PORT", "8085"))
    agent_port = int(_dev_get(args, "jenkins_agent_port", "JENKINS_AGENT_PORT", "50000"))
    recreate = args.get("recreate", False)
    will_create = _pod_will_create("jenkins", recreate)
    admin_user = _dev_get(args, "jenkins_api_user", "JENKINS_API_USER", None) or "admin"
    # A provided JENKINS_API_TOKEN doubles as the admin password (back-compat); otherwise a
    # password is generated. The admin is always provisioned so the setup wizard never blocks.
    provided_token = _dev_get(args, "jenkins_api_token", "JENKINS_API_TOKEN", None)
    admin_password = (
        _dev_get(args, "jenkins_admin_password", "JENKINS_ADMIN_PASSWORD", None)
        or provided_token
        or _generate_secret()
    )
    if not will_create and not _dev_stored("jenkins_admin_password"):
        utils.warn(
            "[dev] Jenkins pod already exists but was not provisioned; run with --recreate to "
            "set the admin user and generate an API token"
        )

    init_dir = _write_jenkins_init_groovy()
    env = {
        "JAVA_OPTS": "-Djenkins.install.runSetupWizard=false",
        "JENKINS_DEV_ADMIN_USER": admin_user,
        "JENKINS_DEV_ADMIN_TOKEN": admin_password,
    }
    volumes = [
        {"name": "data", "persistentVolumeClaim": {"claimName": "jenkins_home"}},
        {"name": "init", "hostPath": {"path": init_dir}},
    ]
    mounts = [
        {"name": "data", "mountPath": "/var/jenkins_home"},
        {"name": "init", "mountPath": "/usr/share/jenkins/ref/init.groovy.d", "readOnly": True},
    ]
    manifest = _pod_manifest(
        "jenkins",
        image,
        [(8080, port), (50000, agent_port)],
        env=env,
        volumes=volumes,
        mounts=mounts,
    )
    if will_create:
        _ensure_image(image)
    _kube_apply("jenkins", manifest, recreate, ["jenkins_home"])

    endpoint = f"http://localhost:{port}"
    _dev_set("jenkins_endpoint", endpoint)
    _dev_set("jenkins_api_user", admin_user)
    _dev_set("jenkins_admin_password", admin_password)
    utils.info(f"[dev] Jenkins admin '{admin_user}' provisioned")

    wait = args.get("wait")
    if wait != 0:
        _wait_http(f"{endpoint}/login", "Jenkins", wait)

    # Generate an API token as needed (none provided/stored yet).
    token = provided_token or _dev_stored("jenkins_api_token")
    if wait != 0 and not token:
        token = _jenkins_create_token(endpoint, admin_user, admin_password, JENKINS_TOKEN_NAME)
        if token:
            utils.info("[dev] Generated Jenkins API token in [dev] jenkins_api_token")
    if token:
        _dev_set("jenkins_api_token", token)
    return {"endpoint": endpoint, "admin_user": admin_user, "api_token": bool(token)}


def _write_jenkins_init_groovy():
    init_dir = os.path.join(utils.user_home, ".ligoj", "dev", "jenkins", "init.groovy.d")
    os.makedirs(init_dir, exist_ok=True)
    groovy = """import jenkins.model.Jenkins
import hudson.security.HudsonPrivateSecurityRealm
import hudson.security.FullControlOnceLoggedInAuthorizationStrategy
import jenkins.install.InstallState

def token = System.getenv('JENKINS_DEV_ADMIN_TOKEN')
if (token != null && token.length() > 0) {
    def user = System.getenv('JENKINS_DEV_ADMIN_USER')
    if (user == null || user.length() == 0) { user = 'admin' }
    def jenkins = Jenkins.get()
    def realm = new HudsonPrivateSecurityRealm(false)
    realm.createAccount(user, token)
    jenkins.setSecurityRealm(realm)
    def strategy = new FullControlOnceLoggedInAuthorizationStrategy()
    strategy.setAllowAnonymousRead(false)
    jenkins.setAuthorizationStrategy(strategy)
    if (!jenkins.getInstallState().isSetupComplete()) {
        InstallState.INITIAL_SETUP_COMPLETED.initializeState()
    }
    jenkins.save()
    println '[dev] Admin user ' + user + ' configured from JENKINS_DEV_ADMIN_TOKEN'
}
"""
    with open(os.path.join(init_dir, "dev-security.groovy"), "w", encoding="utf-8") as f:
        f.write(groovy)
    return init_dir


def _jenkins_create_token(endpoint, user, password, name):
    # Reuse the jenkins plugin's crumb + generateNewToken flow.
    from ligojcli.plugins import jenkins as jenkins_plugin

    jenkins_plugin.jenkins_endpoint = endpoint
    jenkins_plugin.jenkins_crumb = "auto"
    try:
        return jenkins_plugin.jenkins_create_api_token(name, user, password)
    except Exception as error:  # noqa: BLE001 - token generation is best-effort
        utils.warn(f"[dev] Could not generate a Jenkins API token: {error}")
        return None


# --------------------------------------------------------------------------- #
# SonarQube
# --------------------------------------------------------------------------- #
def _init_sonarqube(args):
    utils.info("[dev] === SonarQube ===")
    image = _dev_get(args, "sonar_image", "SONAR_IMAGE", SONAR_DEFAULT_IMAGE)
    port = int(_dev_get(args, "sonar_port", "SONAR_PORT", "9000"))
    recreate = args.get("recreate", False)
    wait = args.get("wait")

    # Back SonarQube with the shared 'ligoj-db' PostgreSQL instead of the (eval-only) embedded H2.
    db = _shared_db_provision(args, "sonarqube", "sonar_db", wait)
    env = {}
    if db:
        env = {
            "SONAR_JDBC_URL": f"jdbc:postgresql://{db['host']}:{db['port']}/{db['name']}",
            "SONAR_JDBC_USERNAME": db["user"],
            "SONAR_JDBC_PASSWORD": db["password"],
        }
    else:
        utils.warn("[dev] SonarQube falls back to the embedded H2 database (not recommended)")

    volumes = [
        {"name": "data", "persistentVolumeClaim": {"claimName": "sonarqube_data"}},
        {"name": "extensions", "persistentVolumeClaim": {"claimName": "sonarqube_extensions"}},
        {"name": "logs", "persistentVolumeClaim": {"claimName": "sonarqube_logs"}},
    ]
    mounts = [
        {"name": "data", "mountPath": "/opt/sonarqube/data"},
        {"name": "extensions", "mountPath": "/opt/sonarqube/extensions"},
        {"name": "logs", "mountPath": "/opt/sonarqube/logs"},
    ]
    named = ["sonarqube_data", "sonarqube_extensions", "sonarqube_logs"]
    manifest = _pod_manifest(
        "sonarqube", image, [(9000, port)], env=env, volumes=volumes, mounts=mounts
    )
    if _pod_will_create("sonarqube", recreate):
        _ensure_image(image)
    _kube_apply("sonarqube", manifest, recreate, named)

    endpoint = f"http://localhost:{port}"
    _dev_set("sonar_endpoint", endpoint)

    if wait == 0:
        utils.warn("[dev] --wait 0, skipping SonarQube readiness and token creation")
        return {"endpoint": endpoint}

    _wait_sonar_up(endpoint, wait)
    preferred = (
        _dev_get(args, "sonar_admin_password", "SONAR_ADMIN_PASSWORD", None) or _generate_secret()
    )
    # Persist only once the password is known to work, so a rejected candidate never poisons [dev].
    admin_password = _sonar_ensure_admin_password(endpoint, preferred)
    _dev_set("sonar_admin_password", admin_password)
    token = _sonar_create_token(endpoint, admin_password, SONAR_TOKEN_NAME)
    _dev_set("sonar_api_token", token)
    utils.info("[dev] SonarQube API token stored in [dev] sonar_api_token")
    return {"endpoint": endpoint, "admin_user": "admin", "token_name": SONAR_TOKEN_NAME}


def _sonar_valid(endpoint, user, password):
    try:
        response = requests.get(
            f"{endpoint}/api/authentication/validate", auth=(user, password), timeout=30
        )
        return response.status_code == 200 and response.json().get("valid") is True
    except requests.RequestException:
        return False


def _sonar_ensure_admin_password(endpoint, preferred):
    # Idempotent: the preferred password is already in place.
    if _sonar_valid(endpoint, "admin", preferred):
        utils.info("[dev] SonarQube admin password already set, reuse it")
        return preferred
    # Change from the default admin/admin. If the preferred password is rejected by the
    # password policy (e.g. missing special character), fall back to a generated compliant one.
    last = None
    for candidate in (preferred, _generate_secret(), _generate_secret()):
        response = requests.post(
            f"{endpoint}/api/users/change_password",
            params={"login": "admin", "previousPassword": "admin", "password": candidate},
            auth=("admin", "admin"),
            timeout=30,
        )
        if response.status_code in (200, 204):
            utils.info("[dev] Changed SonarQube default admin password")
            return candidate
        if response.status_code == 401:
            raise ValueError(
                "[dev] SonarQube 'admin/admin' is no longer valid and the configured password "
                "does not match. Set [dev] sonar_admin_password to the current one, or run "
                "'dev init --only sonarqube --recreate'"
            )
        last = f"HTTP {response.status_code}: {response.text}"
        utils.warn(f"[dev] SonarQube rejected the admin password ({last}), retrying ...")
    raise ValueError(f"[dev] Unable to set SonarQube admin password ({last})")


def _sonar_create_token(endpoint, admin_password, name):
    utils.info(f"[dev] Create SonarQube API token '{name}' ...")
    # Tokens are write-once; revoke any previous one so generation is idempotent.
    requests.post(
        f"{endpoint}/api/user_tokens/revoke",
        params={"name": name},
        auth=("admin", admin_password),
        timeout=30,
    )
    response = requests.post(
        f"{endpoint}/api/user_tokens/generate",
        params={"name": name},
        auth=("admin", admin_password),
        timeout=30,
    )
    if response.status_code not in (200, 201):
        raise ValueError(
            f"[dev] Unable to create SonarQube token (HTTP {response.status_code}): {response.text}"
        )
    return response.json()["token"]


# --------------------------------------------------------------------------- #
# GitLab CE
# --------------------------------------------------------------------------- #
def _init_gitlab(args):
    utils.info("[dev] === GitLab CE ===")
    recreate = args.get("recreate", False)
    image = _dev_get(args, "gitlab_image", "GITLAB_IMAGE", GITLAB_DEFAULT_IMAGE)
    port = int(_dev_get(args, "gitlab_port", "GITLAB_PORT", "8929"))
    ssh_port = int(_dev_get(args, "gitlab_ssh_port", "GITLAB_SSH_PORT", "2289"))
    root_password = _dev_get(args, "gitlab_root_password", "GITLAB_ROOT_PASSWORD", None)
    if not root_password:
        root_password = _generate_secret()
        utils.info("[dev] Generated GitLab root password in [dev] gitlab_root_password")
    _dev_set("gitlab_root_password", root_password)

    external_url = f"http://localhost:{port}"
    # Trim the omnibus footprint: single puma worker, no Prometheus, reduced sidekiq.
    omnibus = "; ".join(
        [
            f"external_url '{external_url}'",
            f"gitlab_rails['gitlab_shell_ssh_port'] = {ssh_port}",
            f"gitlab_rails['initial_root_password'] = '{root_password}'",
            "puma['worker_processes'] = 0",
            "sidekiq['max_concurrency'] = 5",
            "prometheus_monitoring['enable'] = false",
        ]
    )
    env = {"GITLAB_OMNIBUS_CONFIG": omnibus}
    volumes = [
        {"name": "config", "persistentVolumeClaim": {"claimName": "gitlab_config"}},
        {"name": "data", "persistentVolumeClaim": {"claimName": "gitlab_data"}},
        {"name": "logs", "persistentVolumeClaim": {"claimName": "gitlab_logs"}},
    ]
    mounts = [
        {"name": "config", "mountPath": "/etc/gitlab"},
        {"name": "data", "mountPath": "/var/opt/gitlab"},
        {"name": "logs", "mountPath": "/var/log/gitlab"},
    ]
    named = ["gitlab_config", "gitlab_data", "gitlab_logs"]
    manifest = _pod_manifest(
        "gitlab", image, [(port, port), (22, ssh_port)], env=env, volumes=volumes, mounts=mounts
    )
    if _pod_will_create("gitlab", recreate):
        _ensure_image(image)
    _kube_apply("gitlab", manifest, recreate, named)

    _dev_set("gitlab_endpoint", external_url)
    _dev_set("gitlab_ssh_port", ssh_port)

    wait = args.get("wait")
    if wait != 0:
        # GitLab's first boot is slow (several minutes); don't fail the whole init on a timeout.
        _wait_http(f"{external_url}/users/sign_in", "GitLab", wait, fatal=False)

    # Provision a personal access token for 'root' (GitLab has no username/password API to mint one,
    # so we use the Rails runner) and store it in [dev] gitlab_token for the CLI / 'dev demo'. Only
    # (re)generate when the stored token is missing, expired or revoked; reuse it otherwise.
    token = _dev_get(args, "gitlab_token", "GITLAB_TOKEN", None)
    if wait != 0:
        if token and _gitlab_token_valid(external_url, token):
            utils.debug("[dev] Existing GitLab token still valid, reusing it")
        else:
            if token:
                utils.info("[dev] Stored GitLab token is missing or expired, generating a new one")
            token = _gitlab_create_token(_pod_container("gitlab"), GITLAB_TOKEN_NAME)
            if token:
                utils.info("[dev] Generated GitLab personal access token in [dev] gitlab_token")
    if token:
        _dev_set("gitlab_token", token)

    utils.info(f"[dev] GitLab available on {external_url} (root / [dev] gitlab_root_password)")
    return {
        "endpoint": external_url,
        "admin_user": "root",
        "ssh_port": ssh_port,
        "token": bool(token),
    }


def _gitlab_token_valid(url, token):
    # A live, non-expired, non-revoked PAT authenticates; an expired/revoked/unknown one returns 401.
    try:
        response = requests.get(
            f"{url}/api/v4/personal_access_tokens/self",
            headers={"PRIVATE-TOKEN": token},
            timeout=10,
        )
    except requests.RequestException:
        return False
    if response.status_code == 401:
        return False
    if response.status_code == 200:
        data = response.json()
        return bool(data.get("active", True)) and not data.get("revoked", False)
    # Authenticated but, e.g., lacking scope for this endpoint: the token still exists and is valid.
    return True


def _gitlab_create_token(container, name):
    # Create (idempotently) a non-expiring-as-possible PAT for 'root' via the Rails console. Old
    # tokens of the same name are removed first so re-runs do not pile up duplicates.
    utils.info(f"[dev] Generate GitLab personal access token '{name}' ...")
    script = (
        "user = User.find_by_username('root'); "
        f"user.personal_access_tokens.where(name: '{name}').delete_all; "
        "token = user.personal_access_tokens.create!("
        f"name: '{name}', scopes: ['api', 'read_api', 'read_repository', 'write_repository'], "
        "expires_at: 365.days.from_now); "
        "puts token.token"
    )
    result = _podman("exec", container, "gitlab-rails", "runner", script, check=False)
    if result.returncode != 0:
        utils.warn(f"[dev] Could not generate GitLab token: {(result.stderr or '').strip()}")
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    for candidate in reversed(lines):
        if candidate.startswith("glpat-"):
            return candidate
    # Older GitLab versions emit a bare 20+ char token without the 'glpat-' prefix.
    if lines and " " not in lines[-1] and len(lines[-1]) >= 20:
        return lines[-1]
    utils.warn("[dev] GitLab token generation produced no recognizable token output")
    return None


# --------------------------------------------------------------------------- #
# Nexus (Sonatype Repository Manager)
# --------------------------------------------------------------------------- #
def _init_nexus(args):
    utils.info("[dev] === Nexus (Repository Manager) ===")
    recreate = args.get("recreate", False)
    image = _dev_get(args, "nexus_image", "NEXUS_IMAGE", NEXUS_DEFAULT_IMAGE)
    # Host port 8181 (not Nexus's own 8081) to leave 8081 free for the Ligoj API dev app.
    port = int(_dev_get(args, "nexus_port", "NEXUS_PORT", "8181"))

    # A second port exposes a Docker registry connector (Nexus serves a docker hosted repo on its own
    # port); the demo creates the repo with this httpPort so images can be pushed to it.
    docker_port = int(_dev_get(args, "nexus_docker_port", "NEXUS_DOCKER_PORT", "8182"))

    volumes = [{"name": "data", "persistentVolumeClaim": {"claimName": "nexus_data"}}]
    mounts = [{"name": "data", "mountPath": "/nexus-data"}]
    manifest = _pod_manifest(
        "nexus", image, [(8081, port), (docker_port, docker_port)], volumes=volumes, mounts=mounts
    )
    if _pod_will_create("nexus", recreate):
        _ensure_image(image)
    _kube_apply("nexus", manifest, recreate, ["nexus_data"])

    endpoint = f"http://localhost:{port}"
    _dev_set("nexus_endpoint", endpoint)
    _dev_set("nexus_admin_user", "admin")
    _dev_set("nexus_docker_port", str(docker_port))

    wait = args.get("wait")
    if wait == 0:
        utils.warn("[dev] --wait 0, skipping Nexus readiness and admin password setup")
        return {"endpoint": endpoint}

    _wait_http(f"{endpoint}/service/rest/v1/status", "Nexus", wait, fatal=False)
    # Reuse the stored/configured password if it already works, else reset the generated initial one.
    preferred = (
        _dev_get(args, "nexus_admin_password", "NEXUS_ADMIN_PASSWORD", None)
        or _dev_stored("nexus_admin_password")
        or _generate_secret()
    )
    admin_password = _nexus_ensure_admin_password(endpoint, _pod_container("nexus"), preferred)
    _dev_set("nexus_admin_password", admin_password)
    _nexus_accept_eula(endpoint, "admin", admin_password)
    utils.info(f"[dev] Nexus available on {endpoint} (admin / [dev] nexus_admin_password)")
    return {"endpoint": endpoint, "admin_user": "admin"}


def _nexus_accept_eula(endpoint, user, password):
    # Nexus Community Edition refuses writes (repo create, docker push) until its EULA is accepted.
    try:
        current = requests.get(
            f"{endpoint}/service/rest/v1/system/eula", auth=(user, password), timeout=15
        )
        if current.status_code != 200:
            return
        data = current.json()
        if data.get("accepted"):
            return
        data["accepted"] = True
        resp = requests.post(
            f"{endpoint}/service/rest/v1/system/eula", auth=(user, password), json=data, timeout=15
        )
        if resp.status_code in (200, 204):
            utils.info("[dev] Accepted the Nexus Community Edition EULA")
    except requests.RequestException as error:
        utils.warn(f"[dev] Could not accept the Nexus EULA: {error}")


def _nexus_valid(endpoint, user, password):
    try:
        response = requests.get(
            f"{endpoint}/service/rest/v1/security/users",
            params={"userId": "admin"},
            auth=(user, password),
            timeout=15,
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def _nexus_ensure_admin_password(endpoint, container, preferred):
    # Idempotent: the preferred password already authenticates.
    if _nexus_valid(endpoint, "admin", preferred):
        utils.info("[dev] Nexus admin password already set, reuse it")
        return preferred
    # First boot: Nexus writes a random admin password to /nexus-data/admin.password and removes it
    # after the first change. Read it, then swap it for our known/generated one.
    result = _podman("exec", container, "cat", "/nexus-data/admin.password", check=False)
    initial = result.stdout.strip() if result.returncode == 0 else ""
    if not initial:
        utils.warn(
            "[dev] Nexus initial admin password not found (already changed?); "
            "set [dev] nexus_admin_password to the current one or run --recreate"
        )
        return preferred
    response = requests.put(
        f"{endpoint}/service/rest/v1/security/users/admin/change-password",
        auth=("admin", initial),
        headers={"Content-Type": "text/plain"},
        data=preferred,
        timeout=30,
    )
    if response.status_code in (200, 204):
        utils.info("[dev] Changed Nexus default admin password")
        return preferred
    utils.warn(
        f"[dev] Could not change Nexus admin password (HTTP {response.status_code}); "
        "keeping the initial one in [dev] nexus_admin_password"
    )
    return initial


# --------------------------------------------------------------------------- #
# Artifactory (JFrog OSS)
# --------------------------------------------------------------------------- #
def _init_artifactory(args):
    utils.info("[dev] === Artifactory (OSS) ===")
    recreate = args.get("recreate", False)
    image = _dev_get(args, "artifactory_image", "ARTIFACTORY_IMAGE", ARTIFACTORY_DEFAULT_IMAGE)
    port = int(_dev_get(args, "artifactory_port", "ARTIFACTORY_PORT", "8082"))
    admin_user = _dev_get(args, "artifactory_user", "ARTIFACTORY_USER", "admin")
    # Artifactory OSS ships with a well-known admin/password that stays valid for the REST API.
    admin_password = _dev_get(args, "artifactory_password", "ARTIFACTORY_PASSWORD", "password")
    wait = args.get("wait")

    # Recent Artifactory refuses the embedded Derby DB, so it must use the shared PostgreSQL.
    db = _shared_db_provision(args, "artifactory", "artifactory_db", wait)
    if db is None:
        utils.warn(
            "[dev] Skipping Artifactory: it requires the shared PostgreSQL. Run "
            "'dev init --only postgresql' first, then 'dev init --only artifactory'"
        )
        return {"skipped": "shared PostgreSQL unavailable"}

    env = {
        "JF_SHARED_DATABASE_TYPE": "postgresql",
        "JF_SHARED_DATABASE_DRIVER": "org.postgresql.Driver",
        "JF_SHARED_DATABASE_URL": f"jdbc:postgresql://{db['host']}:{db['port']}/{db['name']}",
        "JF_SHARED_DATABASE_USERNAME": db["user"],
        "JF_SHARED_DATABASE_PASSWORD": db["password"],
        # Force IPv4 for the JVM services so they don't try the ::1 loopback when the microservices
        # join over localhost (a frequent cause of the boot deadlock). The Go router isn't covered by
        # this, so the wait also self-heals a stuck boot by restarting the pod once.
        "EXTRA_JAVA_OPTIONS": "-Djava.net.preferIPv4Stack=true",
    }
    volumes = [{"name": "data", "persistentVolumeClaim": {"claimName": "artifactory_data"}}]
    mounts = [{"name": "data", "mountPath": "/var/opt/jfrog/artifactory"}]
    # The unified JFrog router (and the UI) listen on 8082 and route /artifactory to the service.
    manifest = _pod_manifest(
        "artifactory", image, [(8082, port)], env=env, volumes=volumes, mounts=mounts
    )
    if _pod_will_create("artifactory", recreate):
        _ensure_image(image)
    _kube_apply("artifactory", manifest, recreate, ["artifactory_data"])

    endpoint = f"http://localhost:{port}/artifactory"
    _dev_set("artifactory_endpoint", endpoint)
    _dev_set("artifactory_user", admin_user)
    _dev_set("artifactory_password", admin_password)

    if wait != 0:
        # Artifactory's first boot is slow (DB migration + access bootstrap); never fatal, and it
        # self-heals a hung JFrog mesh by restarting the pod once (see _maybe_heal_artifactory).
        _wait_artifactory(args, wait)
    utils.info(
        f"[dev] Artifactory available on {endpoint} ({admin_user} / [dev] artifactory_password)"
    )
    return {"endpoint": endpoint, "admin_user": admin_user}


# --------------------------------------------------------------------------- #
# Harbor (kind + Helm)
# --------------------------------------------------------------------------- #
def _init_harbor(args):
    utils.info("[dev] === Harbor (kind + Helm) ===")
    recreate = args.get("recreate", False)
    port = int(_dev_get(args, "harbor_port", "HARBOR_PORT", "8088"))
    node_port = int(_dev_get(args, "harbor_node_port", "HARBOR_NODE_PORT", "30088"))
    admin_password = _dev_get(args, "harbor_admin_password", "HARBOR_ADMIN_PASSWORD", None)
    if not admin_password:
        admin_password = _generate_secret()
        utils.info("[dev] Generated Harbor admin password in [dev] harbor_admin_password")
    _dev_set("harbor_admin_password", admin_password)
    external_url = f"http://localhost:{port}"

    redis_image = _dev_get(args, "harbor_redis_image", "HARBOR_REDIS_IMAGE", HARBOR_REDIS_IMAGE)
    _ensure_kind_cluster(args, recreate)
    _helm_repo(HARBOR_REPO_NAME, HARBOR_REPO_URL)
    _harbor_helm_install(admin_password, node_port, external_url, args.get("wait"), redis_image)

    _dev_set("harbor_endpoint", external_url)
    _dev_set("harbor_admin_user", "admin")

    wait = args.get("wait")
    if wait != 0:
        _wait_http(f"{external_url}/api/v2.0/systeminfo", "Harbor", wait, fatal=False)
    utils.info(f"[dev] Harbor available on {external_url} (admin / [dev] harbor_admin_password)")
    return {"endpoint": external_url, "admin_user": "admin", "cluster": f"kind-{KIND_CLUSTER}"}


# --------------------------------------------------------------------------- #
# ArgoCD (kind + Helm) - with a 'ligoj' role and LDAP federation
# --------------------------------------------------------------------------- #
def _init_argocd(args):
    utils.info("[dev] === ArgoCD (kind + Helm) ===")
    recreate = args.get("recreate", False)
    port = int(_dev_get(args, "argocd_port", "ARGOCD_PORT", "8083"))
    node_port = int(_dev_get(args, "argocd_node_port", "ARGOCD_NODE_PORT", "30083"))
    external_url = f"http://localhost:{port}"

    _ensure_kind_cluster(args, recreate)
    _helm_repo(ARGOCD_REPO_NAME, ARGOCD_REPO_URL)
    # Dex (inside kind) reaches the published OpenLDAP via the podman host IP.
    ldap = {
        "host": (_kind_host_ip() or "host.containers.internal"),
        "port": str(_dev_get(args, "ldap_port", "LDAP_PORT", "1389")),
        "user": _dev_get(args, "ldap_admin_user", "LDAP_ADMIN_USERNAME", "Manager"),
        "root": _dev_get(args, "ldap_root", "LDAP_ROOT", "dc=sample,dc=com"),
        "password": _dev_get(args, "ldap_admin_password", "LDAP_ADMIN_PASSWORD", None) or "",
    }
    _argocd_helm_install(external_url, node_port, ldap, args.get("wait"))

    _dev_set("argocd_endpoint", external_url)
    _dev_set("argocd_admin_user", "admin")
    _dev_set("argocd_account", ARGOCD_ACCOUNT)

    wait = args.get("wait")
    if wait == 0:
        utils.warn("[dev] --wait 0, skipping ArgoCD token creation")
        return {"endpoint": external_url}

    _wait_http(f"{external_url}/healthz", "ArgoCD", wait, fatal=False)
    admin_password = _argocd_admin_password()
    if admin_password:
        _dev_set("argocd_admin_password", admin_password)
    token = _dev_stored("argocd_api_token")
    if not token and admin_password:
        token = _argocd_create_token(external_url, "admin", admin_password, ARGOCD_ACCOUNT)
        if token:
            utils.info("[dev] Generated ArgoCD API token for 'ligoj' in [dev] argocd_api_token")
    if token:
        _dev_set("argocd_api_token", token)
    utils.info(
        f"[dev] ArgoCD available on {external_url} (admin / [dev] argocd_admin_password; "
        f"account '{ARGOCD_ACCOUNT}' bound to '{ARGOCD_ROLE}', LDAP federation via Dex)"
    )
    return {
        "endpoint": external_url,
        "admin_user": "admin",
        "account": ARGOCD_ACCOUNT,
        "role": ARGOCD_ROLE,
    }


def _argocd_helm_install(external_url, node_port, ldap, wait):
    dex_config = (
        "connectors:\n"
        "- type: ldap\n"
        "  id: ldap\n"
        "  name: LDAP\n"
        "  config:\n"
        f"    host: {ldap['host']}:{ldap['port']}\n"
        "    insecureNoSSL: true\n"
        f"    bindDN: cn={ldap['user']},{ldap['root']}\n"
        f"    bindPW: {ldap['password']}\n"
        "    userSearch:\n"
        f"      baseDN: {ldap['root']}\n"
        '      filter: "(objectClass=inetOrgPerson)"\n'
        "      username: uid\n"
        "      idAttr: uid\n"
        "      emailAttr: mail\n"
        "      nameAttr: cn\n"
        "    groupSearch:\n"
        f"      baseDN: {ldap['root']}\n"
        '      filter: "(objectClass=groupOfNames)"\n'
        "      userMatchers:\n"
        "      - userAttr: DN\n"
        "        groupAttr: member\n"
        "      nameAttr: cn\n"
    )
    # A 'ligoj' role with broad permissions, bound to the 'ligoj' account/LDAP group.
    policy_csv = (
        "p, role:ligoj, applications, *, */*, allow\n"
        "p, role:ligoj, projects, get, *, allow\n"
        "p, role:ligoj, clusters, get, *, allow\n"
        "p, role:ligoj, repositories, *, *, allow\n"
        "g, ligoj, role:ligoj\n"
    )
    values = {
        "configs": {
            "cm": {
                "url": external_url,
                "accounts.ligoj": "apiKey, login",
                "dex.config": dex_config,
            },
            "params": {"server.insecure": "true"},
            "rbac": {"policy.default": "role:readonly", "policy.csv": policy_csv},
        },
        "server": {"service": {"type": "NodePort", "nodePortHttp": node_port}},
        # Trim the footprint: optional components off.
        "applicationSet": {"enabled": False},
        "notifications": {"enabled": False},
    }
    os.makedirs(K8S_DIR, exist_ok=True)
    values_path = os.path.join(K8S_DIR, "argocd-values.yaml")
    with open(values_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(values, f, sort_keys=False)
    utils.info("[dev] helm upgrade --install argocd ...")
    _helm(
        "upgrade",
        "--install",
        ARGOCD_RELEASE,
        ARGOCD_CHART,
        "--namespace",
        ARGOCD_NAMESPACE,
        "--create-namespace",
        "--kube-context",
        f"kind-{KIND_CLUSTER}",
        "--values",
        values_path,
        "--force-conflicts",  # argocd-server co-owns argocd-cm fields; force SSA on re-runs
        *_helm_wait_flags(wait),
        stream=True,
    )


def _argocd_admin_password():
    result = _kubectl(
        "-n",
        ARGOCD_NAMESPACE,
        "get",
        "secret",
        "argocd-initial-admin-secret",
        "-o",
        "jsonpath={.data.password}",
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return base64.b64decode(result.stdout.strip()).decode()
    return None


def _argocd_create_token(url, admin_user, admin_password, account):
    try:
        session = requests.post(
            f"{url}/api/v1/session",
            json={"username": admin_user, "password": admin_password},
            timeout=15,
        )
        if session.status_code != 200:
            utils.warn(f"[dev] ArgoCD admin login failed (HTTP {session.status_code})")
            return None
        admin_token = session.json()["token"]
        response = requests.post(
            f"{url}/api/v1/account/{account}/token",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": ARGOCD_TOKEN_NAME},
            timeout=15,
        )
        if response.status_code != 200:
            utils.warn(
                f"[dev] Could not create ArgoCD token (HTTP {response.status_code}): {response.text}"
            )
            return None
        return response.json()["token"]
    except requests.RequestException as error:
        utils.warn(f"[dev] Could not create ArgoCD token: {error}")
        return None


def _ensure_kind_cluster(args, recreate):
    clusters = _kind("get", "clusters").stdout.split()
    if KIND_CLUSTER in clusters and recreate:
        utils.info(f"[dev] Delete kind cluster '{KIND_CLUSTER}' ...")
        _kind("delete", "cluster", "--name", KIND_CLUSTER, stream=True)
        clusters = []
    if KIND_CLUSTER in clusters:
        utils.info(f"[dev] Reusing kind cluster '{KIND_CLUSTER}'")
        _kind_node_start()
        return
    # Bake every kind-service host<->nodePort mapping in at creation (they are immutable after).
    mappings = [
        {
            "containerPort": int(_dev_get(args, nk, ne, nd)),
            "hostPort": int(_dev_get(args, hk, he, hd)),
            "protocol": "TCP",
        }
        for hk, he, hd, nk, ne, nd in KIND_PORT_MAPPINGS
    ]
    config = {
        "kind": "Cluster",
        "apiVersion": "kind.x-k8s.io/v1alpha4",
        "nodes": [{"role": "control-plane", "extraPortMappings": mappings}],
    }
    os.makedirs(K8S_DIR, exist_ok=True)
    config_path = os.path.join(K8S_DIR, "kind-config.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False)
    utils.info(f"[dev] Create kind cluster '{KIND_CLUSTER}' (podman provider) ...")
    _kind("create", "cluster", "--name", KIND_CLUSTER, "--config", config_path, stream=True)


def _helm_repo(name, url):
    utils.info(f"[dev] Add/refresh Helm repo '{name}' ...")
    _helm("repo", "add", name, url, check=False)
    _helm("repo", "update", name, stream=True)


def _kubectl(*cmd, check=True, stream=False):
    return _run(["kubectl", "--context", f"kind-{KIND_CLUSTER}", *cmd], check=check, stream=stream)


def _kind_host_ip():
    # Address of the podman host as reachable from inside the kind cluster (for LDAP, etc.).
    node = f"{KIND_CLUSTER}-control-plane"
    result = _podman("exec", node, "getent", "ahostsv4", "host.containers.internal", check=False)
    if result.returncode == 0 and result.stdout.split():
        return result.stdout.split()[0]
    return None


def _container_is_running(name):
    result = _podman("inspect", "--format", "{{.State.Running}}", name, check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _kind_node_start():
    # After a podman machine restart the kind node is stopped and its kubeconfig is stale; start
    # the node, refresh the kubeconfig (the API port may change) and wait for the API to answer.
    node = f"{KIND_CLUSTER}-control-plane"
    if _container_exists(node) and not _container_is_running(node):
        utils.info(f"[dev] Start stopped kind node '{node}' ...")
        _podman("start", node, check=False)
    start = time.time()
    while time.time() - start < 90:
        _kind("export", "kubeconfig", "--name", KIND_CLUSTER, check=False)
        if _kubectl("get", "--raw=/readyz", check=False).returncode == 0:
            return
        time.sleep(3)
    utils.warn("[dev] kind API server is not ready yet; cluster operations may fail")


def _harbor_helm_install(admin_password, node_port, external_url, wait, redis_image):
    repo, sep, tag = redis_image.rpartition(":")
    if not sep:  # no tag in the reference
        repo, tag = redis_image, "latest"
    values = {
        "expose": {
            "type": "nodePort",
            "tls": {"enabled": False},
            "nodePort": {"ports": {"http": {"nodePort": node_port}}},
        },
        "externalURL": external_url,
        "harborAdminPassword": admin_password,
        # Minimal install: optional scanner/metrics off; arm64-native redis (see above).
        "trivy": {"enabled": False},
        "metrics": {"enabled": False},
        "redis": {"internal": {"image": {"repository": repo, "tag": tag}}},
    }
    os.makedirs(K8S_DIR, exist_ok=True)
    values_path = os.path.join(K8S_DIR, "harbor-values.yaml")
    with open(values_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(values, f, sort_keys=False)
    utils.info("[dev] helm upgrade --install harbor ...")
    _helm(
        "upgrade",
        "--install",
        HARBOR_RELEASE,
        HARBOR_CHART,
        "--namespace",
        HARBOR_NAMESPACE,
        "--create-namespace",
        "--kube-context",
        f"kind-{KIND_CLUSTER}",
        "--values",
        values_path,
        "--force-conflicts",  # take over server-side-apply field ownership on re-runs
        *_helm_wait_flags(wait),
        stream=True,
    )


# --------------------------------------------------------------------------- #
# podman / kube-play / kind / helm helpers
# --------------------------------------------------------------------------- #
def _run(cmd, check=True, stream=False, env=None, cwd=None) -> subprocess.CompletedProcess:
    utils.debug("[dev] $ " + " ".join(cmd))
    run_env = {**os.environ, **env} if env else None
    if stream:
        proc = subprocess.run(cmd, env=run_env, cwd=cwd)
        if check and proc.returncode != 0:
            raise ValueError(f"[dev] Command failed: {' '.join(cmd)}")
        return proc
    proc = subprocess.run(cmd, capture_output=True, text=True, env=run_env, cwd=cwd)
    if check and proc.returncode != 0:
        raise ValueError(f"[dev] Command failed: {' '.join(cmd)}\n{(proc.stderr or '').strip()}")
    return proc


def _podman(*cmd, check=True, stream=False) -> subprocess.CompletedProcess:
    return _run(["podman", *cmd], check=check, stream=stream)


def _kind(*cmd, check=True, stream=False) -> subprocess.CompletedProcess:
    # kind drives podman as its node provider.
    return _run(
        ["kind", *cmd], check=check, stream=stream, env={"KIND_EXPERIMENTAL_PROVIDER": "podman"}
    )


def _helm(*cmd, check=True, stream=False) -> subprocess.CompletedProcess:
    return _run(["helm", *cmd], check=check, stream=stream)


def _ensure_image(image):
    if _podman("image", "exists", image, check=False).returncode == 0:
        utils.info(f"[dev] Image '{image}' already present")
        return
    utils.info(f"[dev] Pull image '{image}' ...")
    _podman("pull", image, stream=True)


def _ensure_volume(name):
    if _podman("volume", "exists", name, check=False).returncode != 0:
        utils.info(f"[dev] Create volume '{name}' ...")
        _podman("volume", "create", name)


def _container_exists(name):
    return _podman("container", "exists", name, check=False).returncode == 0


def _pod_exists(name):
    return _podman("pod", "exists", name, check=False).returncode == 0


def _pod_running(name):
    status = _podman(
        "pod", "ps", "--filter", f"name=^{name}$", "--format", "{{.Status}}"
    ).stdout.strip()
    return status.lower().startswith(("running", "degraded"))


def _pod_will_create(name, recreate):
    return recreate or not _pod_exists(name)


def _pod_container(pod):
    # podman kube play names a Pod's container '<pod>-<container>'; we use container name == pod.
    return f"{pod}-{pod}"


def _container_env(name, key):
    result = _podman(
        "inspect", "--format", "{{range .Config.Env}}{{println .}}{{end}}", name, check=False
    )
    if result.returncode == 0:
        prefix = f"{key}="
        for line in result.stdout.splitlines():
            if line.startswith(prefix):
                return line[len(prefix) :]
    return None


def _container_image(name):
    result = _podman("inspect", "--format", "{{.ImageName}}", name, check=False)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def _container_mounts(name):
    # Map each mount destination -> (named volume or "", host source).
    result = _podman(
        "inspect",
        "--format",
        "{{range .Mounts}}{{.Destination}}|{{.Name}}|{{.Source}}{{println}}{{end}}",
        name,
        check=False,
    )
    mounts = {}
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            parts = line.split("|")
            if len(parts) == 3 and parts[0]:
                mounts[parts[0]] = (parts[1], parts[2])
    return mounts


def _data_volume(data_source):
    # Build a single data volume entry; returns (volume_dict, named_volumes_to_ensure).
    if "/" in data_source:  # host path (named volumes cannot contain '/')
        return {"name": "data", "hostPath": {"path": data_source}}, []
    return {"name": "data", "persistentVolumeClaim": {"claimName": data_source}}, [data_source]


def _pod_manifest(name, image, ports, env=None, args=None, volumes=None, mounts=None):
    container = {"name": name, "image": image}
    if args:
        container["args"] = list(args)
    if ports:
        container["ports"] = [{"containerPort": int(cp), "hostPort": int(hp)} for cp, hp in ports]
    if env:
        container["env"] = [{"name": k, "value": str(v)} for k, v in env.items()]
    if mounts:
        container["volumeMounts"] = mounts
    spec = {"restartPolicy": "Always", "containers": [container]}
    if volumes:
        spec["volumes"] = volumes
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "labels": {"app": name, "app.kubernetes.io/managed-by": "ligoj-dev"},
        },
        "spec": spec,
    }


def _manifest_path(name):
    os.makedirs(K8S_DIR, exist_ok=True)
    return os.path.join(K8S_DIR, f"{name}.yaml")


def _kube_apply(name, manifest, recreate, named_volumes=()):
    path = _manifest_path(name)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    # PVC claimNames map to podman volumes; pre-create them so existing data is reused.
    for vol in named_volumes:
        _ensure_volume(vol)
    # Migrate away from a legacy standalone container of the same name (raw-container era).
    if _container_exists(name) and not _pod_exists(name):
        utils.info(f"[dev] Removing legacy container '{name}' (migrating to a pod) ...")
        _podman("rm", "-f", name)
    if _pod_exists(name):
        if recreate:
            utils.info(f"[dev] Replace pod '{name}' ...")
            _podman("kube", "play", "--replace", path, stream=True)
            return True
        if _pod_running(name):
            utils.info(f"[dev] Pod '{name}' already running, reuse (use --recreate to rebuild)")
            return False
        utils.info(f"[dev] Start existing pod '{name}' ...")
        _podman("pod", "start", name)
        return False
    utils.info(f"[dev] Apply pod '{name}' ...")
    _podman("kube", "play", path, stream=True)
    return True


# --------------------------------------------------------------------------- #
# [dev] credentials helpers
# --------------------------------------------------------------------------- #
def _dev_get(args, name, env_variable_name, default):
    value = args.get(name)
    if value is None or value == "":
        value = os.environ.get(env_variable_name)
    if value is None or value == "":
        value = utils.ini_credentials.get(DEV_SECTION, name, fallback=None)
    if value is None or value == "":
        return default
    return utils.cleanup_ini_value(value)


def _dev_set(name, value):
    if not utils.ini_credentials.has_section(DEV_SECTION):
        utils.ini_credentials.add_section(DEV_SECTION)
    utils.ini_credentials.set(DEV_SECTION, name, str(value))
    utils.ini_credentials_write()


def _dev_stored(name):
    # Value already written to the [dev] section by a previous init (no env/default).
    return utils.cleanup_ini_value(utils.ini_credentials.get(DEV_SECTION, name, fallback=None))


# Special characters kept shell/LDAP friendly and free of '%' (ConfigParser interpolation).
SECRET_SPECIALS = "-_.@#+=!?*"


def _generate_secret(length=24):
    alphabet = string.ascii_letters + string.digits + SECRET_SPECIALS
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        # Guarantee complexity (SonarQube requires at least one special character).
        if (
            any(c.islower() for c in candidate)
            and any(c.isupper() for c in candidate)
            and any(c.isdigit() for c in candidate)
            and any(c in SECRET_SPECIALS for c in candidate)
        ):
            return candidate


# --------------------------------------------------------------------------- #
# waiting / live progress
#
# A wait value of None means "until done or Ctrl+C" (infinite), 0 means "no wait", and a positive
# integer means "up to that many seconds". Waits stream live progress and handle Ctrl+C cleanly.
# --------------------------------------------------------------------------- #
_POLL = 2.0
# Heartbeat cadence for non-interactive output (logs/CI), where we cannot refresh a line in place.
_HEARTBEAT = 15


def _deadline(wait):
    # wait: None (infinite) or a positive number of seconds (callers handle wait == 0 themselves).
    return None if wait is None else time.time() + wait


def _live():
    # Live, in-place rendering only makes sense on an interactive terminal.
    return sys.stdout.isatty()


def _live_write(text):
    # Overwrite the current line in place (carriage return + clear to end of line).
    sys.stdout.write("\r\033[K" + text)
    sys.stdout.flush()


def _live_clear(tty):
    if tty:
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()


def _await(label, ready, deadline, poll=_POLL):
    start = time.time()
    tty = _live()
    bound = "no limit" if deadline is None else f"{max(0, int(deadline - start))}s max"
    if not tty:
        utils.info(f"[dev] Waiting for {label} ({bound}) ...")
    heartbeat = 0
    try:
        while True:
            ok, detail = ready()
            now = time.time()
            elapsed = int(now - start)
            suffix = f" - {detail}" if detail else ""
            if ok:
                _live_clear(tty)
                utils.info(f"[dev] {label} ready after {elapsed}s{suffix}")
                return True
            if deadline is not None and now >= deadline:
                _live_clear(tty)
                utils.warn(f"[dev] {label} not ready after {elapsed}s{suffix}")
                return False
            left = "" if deadline is None else f", {max(0, int(deadline - now))}s left"
            if tty:
                _live_write(_color(f"[dev] {label} … waiting {elapsed}s{left}{suffix}", "warn"))
            elif elapsed - heartbeat >= _HEARTBEAT:
                heartbeat = elapsed
                utils.info(f"[dev] {label} ... still waiting {elapsed}s{left}{suffix}")
            time.sleep(poll)
    except KeyboardInterrupt:
        _live_clear(tty)
        utils.warn(f"[dev] {label}: interrupted (the operation keeps running in the background)")
        raise SystemExit(130)


def _helm_wait_flags(wait):
    if wait == 0:
        return []  # return as soon as the chart is applied, without waiting for readiness
    seconds = 86400 if wait is None else max(wait, 600)
    return ["--wait", "--timeout", f"{seconds}s"]


def _service_down(svc):
    # 'down' is decided by the pod/cluster runtime, not a host probe: a lingering rootless
    # port-forwarder (or a foreign service bound to the same port) can keep a host probe
    # reporting 'up' forever, so a probe-based wait would never finish.
    return _runtime_status(svc, _PODS[svc]) != "running"


def _await_services(services, args, want_healthy, wait):
    # Poll every service together and render one live, in-place status block (instead of a line
    # per attempt). 'up' is checked with a host health probe; 'down' with the runtime state.
    target = "up" if want_healthy else "down"
    if want_healthy:
        start = time.time()
        healed = [False]

        def check(svc):
            if _service_healthy(svc, args):
                return True
            if svc == "artifactory":
                _maybe_heal_artifactory(args, int(time.time() - start), healed)
            return False
    else:

        def check(svc):
            return _service_down(svc)

    _await_many(services, check, _deadline(wait), target)


def _await_many(services, check, deadline, target):
    start = time.time()
    tty = _live()
    status = {svc: "pending" for svc in services}
    done = {}
    bound = "no limit" if deadline is None else f"{max(0, int(deadline - start))}s max"
    utils.info(f"[dev] Waiting for {len(services)} service(s) to be {target} ({bound}) ...")
    height = 0
    try:
        while True:
            elapsed = int(time.time() - start)
            for svc in services:
                if status[svc] == "pending" and check(svc):
                    status[svc] = "ready"
                    done[svc] = elapsed
                    if not tty:
                        utils.info(f"[dev]   {svc}: {target} after {elapsed}s")
            if deadline is not None and time.time() >= deadline:
                for svc in services:
                    if status[svc] == "pending":
                        status[svc] = "timeout"
                        done[svc] = elapsed
                        if not tty:
                            utils.warn(f"[dev]   {svc}: still not {target} after {elapsed}s")
            if tty:
                height = _render_status_block(
                    services, status, done, elapsed, deadline, target, height
                )
            if all(state != "pending" for state in status.values()):
                break
            time.sleep(_POLL)
    except KeyboardInterrupt:
        if tty:
            sys.stdout.write("\n")
            sys.stdout.flush()
        pending = [s for s in services if status[s] == "pending"]
        utils.warn(
            f"[dev] interrupted while waiting for {', '.join(pending)} to be {target} "
            "(the operation keeps running in the background)"
        )
        raise SystemExit(130)

    ready = [s for s in services if status[s] == "ready"]
    if len(ready) == len(services):
        utils.info(f"[dev] All {len(ready)} service(s) {target}")
    else:
        failed = [s for s in services if status[s] != "ready"]
        utils.warn(
            f"[dev] {len(ready)}/{len(services)} service(s) {target}; "
            f"still not {target}: {', '.join(failed)}"
        )


def _render_status_block(services, status, done, elapsed, deadline, target, prev_height):
    name_w = max((len(svc) for svc in services), default=0)
    left = "" if deadline is None else f", {max(0, int(deadline - time.time()))}s left"
    lines = []
    for svc in services:
        state = status[svc]
        if state == "ready":
            cell = _color(f"✓ {target} ({done[svc]}s)", "ok")
        elif state == "timeout":
            cell = _color(f"✗ still not {target} ({done[svc]}s)", "bad")
        else:
            cell = _color(f"… waiting {elapsed}s{left}", "warn")
        lines.append(f"  {svc.ljust(name_w)}  {cell}")
    if prev_height:
        sys.stdout.write(f"\033[{prev_height}A")
    for line in lines:
        sys.stdout.write("\r\033[K" + line + "\n")
    sys.stdout.flush()
    return len(lines)


def _wait_http(url, name, wait, fatal=True):
    def ready():
        try:
            response = requests.get(url, timeout=5, allow_redirects=False)
            return (response.status_code < 500, f"HTTP {response.status_code}")
        except requests.RequestException:
            return (False, "unreachable")

    if _await(name, ready, _deadline(wait)):
        return
    if fatal:
        raise ValueError(f"[dev] {name} did not become ready in time")


def _wait_artifactory(args, wait):
    # Like _wait_http, but restarts the pod once if the JFrog router never comes up (boot deadlock).
    start = time.time()
    healed = [False]
    url = _service_url("artifactory", args).rstrip("/") + "/api/system/ping"

    def ready():
        try:
            code = requests.get(url, timeout=5, allow_redirects=False).status_code
            return (code < 500, f"HTTP {code}")
        except requests.RequestException:
            _maybe_heal_artifactory(args, int(time.time() - start), healed)
            return (False, "unreachable")

    _await("Artifactory", ready, _deadline(wait))


def _wait_sonar_up(endpoint, wait):
    def ready():
        try:
            response = requests.get(f"{endpoint}/api/system/status", timeout=5)
            if response.status_code == 200:
                status = response.json().get("status")
                return (status == "UP", status or "")
            return (False, f"HTTP {response.status_code}")
        except requests.RequestException:
            return (False, "unreachable")

    if not _await("SonarQube", ready, _deadline(wait)):
        raise ValueError("[dev] SonarQube did not become ready in time")


def _wait_postgres(pod, user, database, wait):
    container = _pod_container(pod)

    def ready():
        result = _podman("exec", container, "pg_isready", "-U", user, "-d", database, check=False)
        return (result.returncode == 0, "")

    if not _await("PostgreSQL", ready, _deadline(wait)):
        raise ValueError("[dev] PostgreSQL did not become ready in time")
