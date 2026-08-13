#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# `dev test start` / `dev test stop` — run the two released Ligoj application containers (ligoj-api +
# ligoj-ui) in the background against the local dev stack, wait until both are healthy, then open the
# UI in the browser. This mirrors the plain `docker run` commands from the Ligoj DOC.md, but with the
# LIGOJ_HOME defaulting to the current user's `~/.ligoj`, configurable ports, and free-form `-D` JVM
# options grouped per container with `--api` / `--ui`.
#
import os
import re
import shlex
import shutil
import subprocess
import webbrowser

import requests

from ligojcli.plugins import dev, utils

# Released images (see app-api/Dockerfile, app-ui/Dockerfile). Tag is configurable (default 'latest').
_API_IMAGE = "ligoj/ligoj-api"
_UI_IMAGE = "ligoj/ligoj-ui"
_API_NAME = "ligoj-api"
_UI_NAME = "ligoj-ui"

# Container contexts (from the Dockerfiles): api serves /ligoj-api, ui serves /ligoj.
_API_CONTEXT = "/ligoj-api"
_UI_CONTEXT = "/ligoj"

# podman's built-in host gateway alias — how a bridged container reaches services on the machine host
# (the other container's published port, the dev PostgreSQL) in 'publish' network mode.
_PODMAN_HOST_GW = "host.containers.internal"

# Defaults matching the DOC.md sample commands (see "## `ligoj-api` / `ligoj-ui` Container").
_DEFAULT_API_PORT = "8088"
_DEFAULT_UI_PORT = "8089"
# API: enable-preview (also in the image JDK opts), a single-connection LDAP pool and relaxed SSL, and
# INFO logs. UI: 'Trusted' security (no password verification — a local test convenience) and INFO.
_DEFAULT_API_OPTS = [
    "--enable-preview",
    "-Dlog.level=INFO",
    "-Dcom.sun.jndi.ldap.connect.pool.initsize=1",
    "-Dcom.sun.jndi.ldap.connect.pool.maxsize=1",
    "-Dcom.sun.jndi.ldap.connect.pool.prefsize=1",
    "-Dcom.sun.jndi.ldap.connect.pool.debug=all",
    "-Dligoj.sslVerify=false",
]
_DEFAULT_UI_OPTS = ["-Dsecurity=Trusted", "-Dlog.level=info"]

# The app is a JVM with 'jpa.hbm2ddl=update' at boot, so first start is slow; wait up to 5 min.
_DEFAULT_WAIT = 300

# Recognised named flags: value-taking, and boolean. Everything else starting with '-' is a JVM option
# for the current --api / --ui group.
_VALUE_FLAGS = {
    "--port": "port",
    "--api-port": "api_port",
    "--home": "home",
    "--context": "context",
    "--tag": "tag",
    "--api-tag": "api_tag",
    "--ui-tag": "ui_tag",
    "--runtime": "runtime",
    "--net": "net",
    "--wait": "wait",
}
_BOOL_FLAGS = {"--no-browser": "no_browser", "--pull": "pull", "--no-wait": "no_wait"}


# --------------------------------------------------------------------------- #
# Argument parsing (free-form, because '-D...' tokens can't be modelled by argparse)
# --------------------------------------------------------------------------- #
def _parse(tokens):
    """Split the REMAINDER tokens into (operation, parsed dict).

    '--api' / '--ui' open a group; every following '-D...'/'-X...'/'--enable-preview' token is
    collected into that group's option list until the next '--api' / '--ui'. Named flags may appear
    anywhere and do not change the active group.
    """
    if not tokens:
        return None, {}
    if tokens[0] in ("-h", "--help", "help"):
        return "help", {}
    operation, rest = tokens[0], tokens[1:]
    parsed = {"api_opts": [], "ui_opts": [], "api_given": False, "ui_given": False}
    group = None  # None | 'api' | 'ui'
    i = 0
    while i < len(rest):
        token = rest[i]
        if token in ("-h", "--help"):
            return "help", {}
        if token == "--api":
            group, parsed["api_given"] = "api", True
        elif token == "--ui":
            group, parsed["ui_given"] = "ui", True
        elif token in _VALUE_FLAGS:
            i += 1
            if i >= len(rest):
                raise ValueError(f"[test] option '{token}' needs a value")
            parsed[_VALUE_FLAGS[token]] = rest[i]
        elif token in _BOOL_FLAGS:
            parsed[_BOOL_FLAGS[token]] = True
        elif token.startswith("-"):
            if group is None:
                raise ValueError(
                    f"[test] JVM option '{token}' must come after '--api' or '--ui' "
                    "(e.g. 'dev test start --api -Dlog.level=DEBUG')"
                )
            parsed[f"{group}_opts"].append(token)
        else:
            raise ValueError(f"[test] unexpected argument '{token}'")
        i += 1
    return operation, parsed


# --------------------------------------------------------------------------- #
# Configuration resolution: CLI flag -> env -> ~/.ligoj/config -> ~/.ligoj/credentials -> default
# --------------------------------------------------------------------------- #
def _resolve(value, env, config_key, default=None):
    if value not in (None, ""):
        return value
    env_value = os.environ.get(env)
    if env_value not in (None, ""):
        return env_value
    for store, section in (
        (utils.ini_config, utils.ini_profile),
        (utils.ini_credentials, dev.DEV_SECTION),
    ):
        if section and store.has_section(section):
            found = store.get(section, config_key, fallback=None)
            if found not in (None, ""):
                return utils.cleanup_ini_value(found)
    return default


def _opts(parsed, given_key, opts_key, env, config_key, default_opts):
    """Resolve a container's JVM option list: explicit '--api/--ui' group, else config, else default."""
    if parsed.get(given_key):
        return list(parsed.get(opts_key) or [])
    configured = _resolve(None, env, config_key)
    return shlex.split(configured) if configured else list(default_opts)


def _context_path(value):
    """Normalize a UI context path for the image's CONTEXT_URL (a Spring servlet context-path).

    Spring wants '/name' — leading slash, no trailing slash — so 'ligoj2' becomes '/ligoj2' and
    '/ligoj2/' is trimmed. '/' (or '') means the ROOT context and must be passed as '' (Spring
    rejects a bare '/').
    """
    path = (value or "").strip().rstrip("/")
    if path in ("", "/"):
        return ""
    return path if path.startswith("/") else f"/{path}"


def _resolve_config(parsed):
    home = _resolve(
        parsed.get("home"), "LIGOJ_HOME", "ligoj_home", os.path.join(utils.user_home, ".ligoj")
    )
    runtime = _runtime(_resolve(parsed.get("runtime"), "LIGOJ_TEST_RUNTIME", "ligoj_test_runtime"))
    tag = _resolve(parsed.get("tag"), "LIGOJ_TEST_TAG", "ligoj_test_tag")
    api_tag = _resolve(parsed.get("api_tag"), "LIGOJ_TEST_API_TAG", "ligoj_test_api_tag", tag)
    ui_tag = _resolve(parsed.get("ui_tag"), "LIGOJ_TEST_UI_TAG", "ligoj_test_ui_tag", tag)
    # podman-machine can't reach a host-networked container from the mac, so default it to published
    # ports; docker/Linux keeps host networking. In publish mode the containers reach the host (the
    # other service, the dev DB) through the podman gateway rather than 127.0.0.1.
    default_net = "publish" if os.path.basename(runtime) == "podman" else "host"
    network = _resolve(parsed.get("net"), "LIGOJ_TEST_NETWORK", "ligoj_test_network", default_net)
    gateway = _PODMAN_HOST_GW if network == "publish" else "127.0.0.1"
    db_host = _PODMAN_HOST_GW if network == "publish" else _cred("db_host", "localhost")
    return {
        "runtime": runtime,
        "network": network,
        "endpoint_host": gateway,
        "home": os.path.expanduser(home),
        "api_port": str(
            _resolve(parsed.get("api_port"), "LIGOJ_API_PORT", "ligoj_api_port", _DEFAULT_API_PORT)
        ),
        "ui_port": str(
            _resolve(parsed.get("port"), "LIGOJ_UI_PORT", "ligoj_ui_port", _DEFAULT_UI_PORT)
        ),
        "ui_context": _context_path(
            _resolve(parsed.get("context"), "LIGOJ_UI_CONTEXT", "ligoj_ui_context", _UI_CONTEXT)
        ),
        "api_image": _image_ref(runtime, _API_IMAGE, api_tag),
        "ui_image": _image_ref(runtime, _UI_IMAGE, ui_tag),
        "api_opts": _opts(
            parsed,
            "api_given",
            "api_opts",
            "LIGOJ_TEST_API_OPTS",
            "ligoj_test_api_opts",
            [*_DEFAULT_API_OPTS, *_dev_db_opts(db_host)],
        ),
        "ui_opts": _opts(
            parsed,
            "ui_given",
            "ui_opts",
            "LIGOJ_TEST_UI_OPTS",
            "ligoj_test_ui_opts",
            _DEFAULT_UI_OPTS,
        ),
        "pull": bool(parsed.get("pull")),
    }


def _cred(key, default):
    """A `[dev]`-credentials value (from `dev init`), or the default."""
    value = utils.ini_credentials.get(dev.DEV_SECTION, key, fallback=None)
    return utils.cleanup_ini_value(value) or default if value else default


def _dev_db_opts(db_host):
    """JVM options wiring the API to the dev-stack PostgreSQL from `[dev]` (host adjusted per network).

    Added to the API defaults so `dev test` targets the dev stack out of the box (the released image
    otherwise defaults to MySQL); an explicit `--api` group replaces these. NOTE: the API image must
    bundle the PostgreSQL JDBC driver for this to load. Empty when no `[dev]` DB is configured.
    """
    if not utils.ini_credentials.has_section(dev.DEV_SECTION) or not _cred("db_host", ""):
        return []
    return [
        "-Djdbc.vendor=postgresql",
        f"-Djdbc.host={db_host}",
        f"-Djdbc.port={_cred('db_port', '5432')}",
        f"-Djdbc.database={_cred('db_name', 'ligoj')}",
        f"-Djdbc.username={_cred('db_user', 'ligoj')}",
        f"-Djdbc.password={_cred('db_password', 'ligoj')}",
        "-Djdbc.driverClassName=org.postgresql.Driver",
        "-Djpa.dialect=org.ligoj.bootstrap.core.dao.PostgreSQL95NoSchemaDialect",
    ]


def _runtime(preference):
    if preference:
        if shutil.which(preference) is None:
            raise ValueError(f"[test] container runtime '{preference}' not found on PATH")
        return preference
    for candidate in ("docker", "podman"):
        if shutil.which(candidate):
            return candidate
    raise ValueError("[test] no container runtime found; install docker or podman")


# --------------------------------------------------------------------------- #
# Image resolution — prefer a locally-built image so podman does not try to pull
# --------------------------------------------------------------------------- #
def _local_images(runtime, suffix):
    """Local images whose repository is (or ends with) `suffix` (e.g. 'ligoj/ligoj-api'), newest first.

    podman tags a locally-built 'ligoj/ligoj-api' as 'localhost/ligoj/ligoj-api', which a bare
    'ligoj/ligoj-api:tag' reference would ignore in favour of a docker.io pull — so matching keeps the
    registry/`localhost/` prefix and returns the full 'repository:tag' verbatim.
    """
    result = _run(
        [runtime, "images", "--format", "{{.Repository}}:{{.Tag}}|{{.CreatedAt}}"], check=False
    )
    rows = []
    for line in result.stdout.splitlines():
        ref, _, created = line.partition("|")
        repo, _, tag = ref.rpartition(":")
        if not repo or tag in ("", "<none>"):
            continue
        if repo == suffix or repo.endswith("/" + suffix):
            rows.append((repo, tag, created))
    # CreatedAt is 'YYYY-MM-DD HH:MM:SS +0000 UTC', so a reverse string sort is newest-first.
    rows.sort(key=lambda row: row[2], reverse=True)
    return [(repo, tag) for repo, tag, _ in rows]


def _latest_tag(image):
    """Highest-versioned published tag of `image` on Docker Hub, or None (used only as a fallback)."""
    try:
        response = requests.get(
            f"https://hub.docker.com/v2/repositories/{image}/tags",
            params={"page_size": 100, "ordering": "last_updated"},
            timeout=10,
        )
        response.raise_for_status()
        names = [t["name"] for t in response.json().get("results", []) if t.get("name")]
    except (requests.RequestException, ValueError, KeyError):
        return None

    def version_key(name):
        return tuple(int(part) for part in re.findall(r"\d+", name)[:4])

    versioned = [name for name in names if version_key(name)]
    if versioned:
        return max(versioned, key=version_key)
    return names[0] if names else None


def _image_ref(runtime, suffix, tag):
    """Resolve the image reference to run for `suffix` (e.g. 'ligoj/ligoj-api')."""
    local = _local_images(runtime, suffix)
    if tag:
        # Explicit tag: use the local build with that tag if present, else let the runtime pull it.
        for repo, local_tag in local:
            if local_tag == tag:
                return f"{repo}:{tag}"
        return f"{suffix}:{tag}"
    if local:
        repo, local_tag = local[0]
        return f"{repo}:{local_tag}"
    published = _latest_tag(suffix)
    if published:
        utils.info(f"[test] No local '{suffix}' image; using latest published tag '{published}'")
        return f"{suffix}:{published}"
    raise ValueError(
        f"[test] no local '{suffix}' image found and none resolvable — build it "
        "('dev package' / docker build) or pass --tag"
    )


# --------------------------------------------------------------------------- #
# Command building (pure — kept separate from execution so it can be unit-tested)
# --------------------------------------------------------------------------- #
def _pull_flag(config, image):
    # A '--pull' request only applies to a registry image; a local 'localhost/…' build cannot be pulled.
    if config["pull"] and not image.startswith("localhost/"):
        return ["--pull", "always"]
    return []


def _user_flags(config):
    # The images run as ligoj:1001, but the host-mounted LIGOJ_HOME is owned by the host user, so uid
    # 1001 cannot write it. Under rootless podman, container-root maps to the host user, so '--user 0'
    # lets the app write the mount (and files stay host-user-owned). Docker Desktop maps this itself.
    if os.path.basename(config["runtime"]) == "podman":
        return ["--user", "0"]
    return []


def _net_flags(config, port):
    # 'host' networking (docker / Linux) binds the container port straight on the host, so localhost
    # reaches it. Under podman-machine that only binds inside the VM, unreachable from the mac — so the
    # port is published (-p) instead, and gvproxy forwards localhost:<port> to it.
    if config["network"] == "host":
        return ["--network=host"]
    return ["-p", f"{port}:{port}"]


def _run_commands(config):
    """The two 'run' command argv lists for the api and ui containers, from a resolved config."""
    home = config["home"]
    api = [
        config["runtime"],
        "run",
        "--name",
        _API_NAME,
        *_net_flags(config, config["api_port"]),
        *_user_flags(config),
        "-v",
        f"{home}:/home/ligoj",
        "-v",
        f"{home}/hooks:/home/hooks",
        "-v",
        f"{home}/files:/home/files",
        "--detach",
        "--restart=always",
        "--log-opt",
        "max-size=5m",
        "--log-opt",
        "max-file=5",
        *_pull_flag(config, config["api_image"]),
        "-e",
        f"SERVER_PORT={config['api_port']}",
        "-e",
        f"CUSTOM_OPTS={' '.join(config['api_opts'])}",
        config["api_image"],
    ]
    ui = [
        config["runtime"],
        "run",
        "--name",
        _UI_NAME,
        *_net_flags(config, config["ui_port"]),
        *_user_flags(config),
        "--detach",
        "--restart=always",
        "-v",
        f"{home}:/home/ligoj",
        *_pull_flag(config, config["ui_image"]),
        "-e",
        f"CUSTOM_OPTS={' '.join(config['ui_opts'])}",
        "-e",
        f"ENDPOINT=http://{config['endpoint_host']}:{config['api_port']}/ligoj-api",
        "-e",
        f"SERVER_PORT={config['ui_port']}",
        "-e",
        f"CONTEXT_URL={config['ui_context']}",
        config["ui_image"],
    ]
    return api, ui


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #
def _run(cmd, check=True):
    utils.debug("[test] $ " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise ValueError(f"[test] command failed: {' '.join(cmd)}\n{(proc.stderr or '').strip()}")
    return proc


def _wait(config, wait, no_browser):
    api_health = f"http://localhost:{config['api_port']}{_API_CONTEXT}/manage/health"
    ui_health = f"http://localhost:{config['ui_port']}{config['ui_context']}/login.html"
    labels = {
        f"{_API_NAME} (:{config['api_port']})": api_health,
        f"{_UI_NAME} (:{config['ui_port']})": ui_health,
    }
    ready = set()

    def check(label):
        if dev._probe_http(labels[label]):
            ready.add(label)
            return True
        return False

    dev._await_many(list(labels), check, dev._deadline(wait), "up")
    ui_url = f"http://localhost:{config['ui_port']}{config['ui_context']}/"
    if len(ready) != len(labels):
        utils.warn(
            f"[test] not all containers became healthy; check logs: {config['runtime']} logs -f {_API_NAME}"
        )
        return False
    utils.info(f"[test] Ligoj UI ready at {ui_url}")
    if not no_browser:
        utils.info("[test] Opening the browser ...")
        webbrowser.open(ui_url)
    return False


def _start(parsed):
    config = _resolve_config(parsed)
    for sub in ("", "hooks", "files"):
        os.makedirs(os.path.join(config["home"], sub) if sub else config["home"], exist_ok=True)

    if any("org.postgresql.Driver" in opt for opt in config["api_opts"]):
        utils.warn(
            "[test] API auto-wired to the dev PostgreSQL ([dev]); the API image must bundle the "
            "PostgreSQL JDBC driver or it fails at boot — pass '--api …' to override the DB options"
        )

    api_cmd, ui_cmd = _run_commands(config)
    # A previous run leaves named containers behind; remove them so 'run --name' can recreate.
    _run([config["runtime"], "rm", "-f", _UI_NAME, _API_NAME], check=False)

    utils.info(
        f"[test] Start {_API_NAME} (:{config['api_port']}) from {config['api_image']} "
        f"with LIGOJ_HOME={config['home']} ..."
    )
    _run(api_cmd)
    utils.info(
        f"[test] Start {_UI_NAME} (:{config['ui_port']}) from {config['ui_image']} "
        f"-> endpoint :{config['api_port']} ..."
    )
    _run(ui_cmd)

    wait = _wait_seconds(parsed)
    if wait == 0:
        utils.info(f"[test] Containers started in the background ({config['runtime']} ps to check)")
        return False
    return _wait(config, wait, bool(parsed.get("no_browser")))


def _stop(parsed):
    runtime = _runtime(_resolve(parsed.get("runtime"), "LIGOJ_TEST_RUNTIME", "ligoj_test_runtime"))
    utils.info(f"[test] Stop {_UI_NAME}, {_API_NAME} ...")
    _run([runtime, "stop", _UI_NAME, _API_NAME], check=False)
    _run([runtime, "rm", _UI_NAME, _API_NAME], check=False)
    utils.info("[test] Stopped")
    return False


def _wait_seconds(parsed):
    if parsed.get("no_wait"):
        return 0
    given = parsed.get("wait")
    if given in (None, ""):
        return _DEFAULT_WAIT
    try:
        return max(0, int(given))
    except (TypeError, ValueError):
        raise ValueError(f"[test] --wait expects a number of seconds, got '{given}'")


def execute(args):
    operation, parsed = _parse(args.get("test_args") or [])
    if operation in (None, "help"):
        print(HELP)
        return False
    if operation == "start":
        return _start(parsed)
    if operation == "stop":
        return _stop(parsed)
    raise ValueError(f"[test] unknown command '{operation}' (expected 'start' or 'stop')")


# --------------------------------------------------------------------------- #
# Help / notes (surfaced on 'dev test' and 'dev test -h'); mirrors ligoj/DOC.md
# --------------------------------------------------------------------------- #
HELP = """\
dev test start|stop — run the released Ligoj app containers (ligoj-api + ligoj-ui) in the background.

  start   Run both containers detached, wait until both are healthy, then open the UI in the browser.
  stop    Stop and remove both containers.

Options (start):
  --port N            UI container port and browser port          (default 8089, LIGOJ_UI_PORT / ligoj_ui_port)
  --api-port N        API port: the UI ENDPOINT and API exposed   (default 8088, LIGOJ_API_PORT / ligoj_api_port)
  --home DIR          LIGOJ_HOME mounted at /home/ligoj           (default ~/.ligoj, LIGOJ_HOME / ligoj_home)
  --context PATH      UI context path (the image's CONTEXT_URL)   (default /ligoj, LIGOJ_UI_CONTEXT /
                      e.g. --context /ligoj2; '/' = root context   ligoj_ui_context)
  --tag T             Image tag for both images   (default: newest LOCAL build, else latest published;
                                                   LIGOJ_TEST_TAG / ligoj_test_tag)
  --api-tag / --ui-tag T   Per-image tag override
  --runtime docker|podman  Container runtime                       (default: docker if present, else podman)
  --net host|publish  Networking. 'host' = --network=host (docker/Linux); 'publish' = -p ports +
                      host.containers.internal (podman-machine, reachable from the mac). Default per
                      runtime (podman -> publish, docker -> host). LIGOJ_TEST_NETWORK / ligoj_test_network
  --pull              Pull the images before running
  --no-browser        Do not open the browser once healthy
  --wait N            Health-wait timeout in seconds               (default 300; 0 or --no-wait: don't wait)
  --api  -D... [-D...] JVM options for the API container (replaces the defaults)
  --ui   -D... [-D...] JVM options for the UI container (replaces the defaults)

Example:
  ligoj dev test start --port 8089 --api-port 8088 \\
    --api -Dlog.level=INFO -Dligoj.sslVerify=false \\
    --ui  -Dsecurity=Trusted -Dlog.level=info

Default API JVM options: --enable-preview -Dlog.level=INFO <single-connection LDAP pool> -Dligoj.sslVerify=false
Default UI  JVM options: -Dsecurity=Trusted -Dlog.level=info

Well-known -D values (see ligoj/DOC.md, "Application level properties"):
  UI   -Dsecurity=Trusted|Rest|OAuth2Bff   Session provider. Trusted = no password check (RBAC still
                                           enforced), Rest = default, OAuth2Bff = Keycloak/OIDC.
  both -Dlog.level=trace|debug|info|warn|error         Global log verbosity.
       -Dlogging.level.root=<level>                    Same as above (Spring property).
       -Dlogging.level.<category>=<level>              Per-category verbosity (see log4j2.json).
  API  -Djdbc.vendor=mysql|postgresql|mariadb          Database type (default mysql).
       -Djpa.hbm2ddl=update|none|validate              Schema handling (update = slow first start).
       -Dligoj.plugin.repository=central|nexus         Plugin repository.
       -Dligoj.sslVerify=true|false                    Disable SSL verification (dev only).
       -Dligoj.plugin.install=p1,p2                    Plugins to auto-install at start.
  UI   -Dsecurity.pre-auth-principal / -Dsecurity.pre-auth-credentials   Header-based pre-auth.
       -Dligoj.security.login-by-api-key=true|false    Enable the API-key login bypass.

Notes:
  * By DEFAULT the API is wired to the dev-stack PostgreSQL from [dev] (host/port/db/user/password),
    so it targets the dev DB out of the box. The API image must bundle the PostgreSQL JDBC driver, or
    it fails at boot with ClassNotFoundException. Pass '--api …' to take full control of the DB opts.
  * Networking: podman-machine publishes ports (-p) and reaches the machine host (other container, dev
    DB) via host.containers.internal; docker/Linux uses --network=host. Override with --net.
  * LIGOJ_HOME (default ~/.ligoj) is mounted at /home/ligoj, with hooks/ and files/ subdirectories.
    Under podman the containers run as --user 0 so they can write that host-owned mount.
  * -Dsecurity=Trusted (the UI default here) runs Ligoj without password verification — for local
    testing only; never expose it publicly.
"""
