#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# `dev debug` (macOS) — manage the local Ligoj *application* stack you debug from the IDE:
#   * IntelliJ IDEA          - opened on the ligoj project
#   * ligoj-api  (Java app)  - org.ligoj.boot.api.Application, http://localhost:8081/ligoj-api
#   * ligoj-ui   (Java app)  - org.ligoj.boot.web.Application,  http://localhost:8080/ligoj
#   * Vite dev server        - `npm run dev` in app-ui/src/main/webapp, http://localhost:5173/ligoj/
#
# IntelliJ has no headless "run this configuration" command; automating its UI needs the broad macOS
# Accessibility permission. Rather than grant that to the whole terminal, `dev debug init` compiles a
# tiny dedicated launcher app (default ~/Applications/Ligoj Debug.app) — you grant Accessibility to
# THAT app only. `dev debug start` opens the launcher (which starts ligoj-api / ligoj-ui in Debug
# mode, skipping any already running) plus the Vite dev server. Detection (status) and stopping are
# done from the OS (process match / TCP port), needing no permission. `stop`/`restart` never quit the
# IDE (to preserve unsaved work). All commands accept the same `--wait` as the other `dev` commands.
#
import os
import shutil
import signal
import subprocess
import time

from ligojcli.plugins import dev, utils

IDEA_BUNDLE_ID = "com.jetbrains.intellij"
APP_BUNDLE_ID = "org.ligoj.dev.debug"
# Bumped whenever the compiled launcher's AppleScript changes, so `dev debug start` can tell the user
# to re-run `dev debug init` when the installed app predates the change (v2: wait for IntelliJ ready).
_LAUNCHER_VERSION = "2"


# --------------------------------------------------------------------------- #
# Configuration / component model
# --------------------------------------------------------------------------- #
def _idea_app(args):
    return dev._dev_get(args, "idea_app", "IDEA_APP", "IntelliJ IDEA")


def _project_dir(args):
    return os.path.expanduser(
        dev._dev_get(args, "ligoj_project_dir", "LIGOJ_PROJECT_DIR", "~/git/ligoj")
    )


def _debug_app_path(args):
    return os.path.expanduser(
        dev._dev_get(args, "ligoj_debug_app", "LIGOJ_DEBUG_APP", "~/Applications/Ligoj Debug.app")
    )


def _components(args):
    project = _project_dir(args)
    webapp = os.path.join(project, "app-ui", "src", "main", "webapp")
    return [
        {"key": "intellij", "label": "IntelliJ IDEA", "kind": "ide", "url": project},
        {
            "key": "api",
            "label": "Ligoj API",
            "kind": "java",
            "config": "ligoj-api",
            "main": "org.ligoj.boot.api.Application",
            "port": 8081,
            "url": "http://localhost:8081/ligoj-api",
        },
        {
            "key": "ui",
            "label": "Ligoj UI",
            "kind": "java",
            "config": "ligoj-ui",
            "main": "org.ligoj.boot.web.Application",
            "port": 8080,
            "url": "http://localhost:8080/ligoj",
        },
        {
            "key": "vite",
            "label": "Vite (app-ui)",
            "kind": "vite",
            "webapp": webapp,
            "port": 5173,
            "url": "http://localhost:5173/ligoj/",
        },
    ]


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def execute(args):
    op = args.get("operation")
    if op == "init":
        return _init(args)
    if op == "start":
        return _start(args)
    if op == "stop":
        return _stop(args)
    if op == "restart":
        return _restart(args)
    if op in (None, "status"):
        return _render_status(args)
    utils.warn(f"[debug] Unknown command '{op}'; use init | start | stop | restart | status")
    return False


# --------------------------------------------------------------------------- #
# init — compile the dedicated debug launcher app
# --------------------------------------------------------------------------- #
def _init(args):
    app_path = _debug_app_path(args)
    if shutil.which("osacompile") is None:
        utils.warn("[debug] 'osacompile' not found; the debug launcher is macOS only")
        return False

    os.makedirs(_state_dir(), exist_ok=True)
    src = os.path.join(_state_dir(), "ligoj-debug.applescript")
    with open(src, "w", encoding="utf-8") as handle:
        handle.write(_build_applescript(args))

    os.makedirs(os.path.dirname(app_path), exist_ok=True)
    if os.path.exists(app_path):
        utils.info(f"[debug] Replacing existing launcher app {app_path}")
        shutil.rmtree(app_path, ignore_errors=True)
    result = subprocess.run(["osacompile", "-o", app_path, src], capture_output=True, text=True)
    if result.returncode != 0 or not os.path.isdir(app_path):
        utils.warn(f"[debug] osacompile failed: {(result.stderr or '').strip()[:300]}")
        return False

    name = os.path.splitext(os.path.basename(app_path))[0]
    _apply_app_identity(app_path, name)
    utils.info(f"[debug] Compiled the debug launcher app: {app_path} ('{name}')")
    _print_init_instructions(app_path, args)
    return False


def _apply_app_identity(app_path, name):
    # Give the osacompile'd applet a friendly name + a stable bundle id (so the Accessibility list
    # shows '<name>' rather than 'applet'), then swap in the bundled Ligoj icon.
    plist = os.path.join(app_path, "Contents", "Info.plist")
    _plist_set(plist, "CFBundleName", name)
    _plist_set(plist, "CFBundleDisplayName", name)
    _plist_set(plist, "CFBundleIdentifier", APP_BUNDLE_ID)
    _install_icon(app_path)
    # Stamp the launcher version inside the bundle (before signing, so it is sealed in) — read back by
    # 'dev debug start' to detect an outdated launcher.
    with open(_launcher_version_file(app_path), "w", encoding="utf-8") as handle:
        handle.write(_LAUNCHER_VERSION)
    # Re-sign ad-hoc as the LAST step (after the plist/icon edits): on Apple Silicon an unsigned or
    # tampered bundle "can't be opened", and the Accessibility list keys on the signing *identifier*
    # (osacompile's default is 'applet'), so pin it to our bundle id — the app then lists as its
    # display name 'Ligoj Debug' with the Ligoj icon.
    result = subprocess.run(
        ["codesign", "--force", "--sign", "-", "--identifier", APP_BUNDLE_ID, app_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        utils.warn(f"[debug] codesign failed: {(result.stderr or '').strip()[:200]}")


def _install_icon(app_path):
    png = os.path.join(os.path.dirname(__file__), "assets", "logo.png")
    if not os.path.isfile(png) or shutil.which("iconutil") is None:
        utils.warn("[debug] Bundled icon or iconutil unavailable; keeping the default app icon")
        return
    resources = os.path.join(app_path, "Contents", "Resources")
    iconset = os.path.join(_state_dir(), "ligoj.iconset")
    shutil.rmtree(iconset, ignore_errors=True)
    os.makedirs(iconset)
    for size in (16, 32, 128, 256, 512):
        _sips_resize(png, size, os.path.join(iconset, f"icon_{size}x{size}.png"))
        _sips_resize(png, size * 2, os.path.join(iconset, f"icon_{size}x{size}@2x.png"))
    icns = os.path.join(resources, "applet.icns")
    result = subprocess.run(
        ["iconutil", "-c", "icns", iconset, "-o", icns], capture_output=True, text=True
    )
    if result.returncode != 0:
        utils.warn(f"[debug] iconutil failed: {(result.stderr or '').strip()[:200]}; kept default")
        return
    # Prefer the classic .icns: remove the compiled asset-catalog icon that would otherwise win.
    car = os.path.join(resources, "Assets.car")
    if os.path.exists(car):
        os.remove(car)
    subprocess.run(
        ["/usr/libexec/PlistBuddy", "-c", "Delete :CFBundleIconName", plist_of(app_path)],
        capture_output=True,
        text=True,
    )
    _plist_set(plist_of(app_path), "CFBundleIconFile", "applet")


def plist_of(app_path):
    return os.path.join(app_path, "Contents", "Info.plist")


def _launcher_version_file(app_path):
    return os.path.join(app_path, "Contents", "Resources", "ligoj-launcher.version")


def _installed_launcher_version(app_path):
    try:
        with open(_launcher_version_file(app_path), encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return None


def _sips_resize(png, size, out):
    subprocess.run(
        ["sips", "-z", str(size), str(size), png, "--out", out], capture_output=True, text=True
    )


def _plist_set(plist, key, value):
    result = subprocess.run(
        ["/usr/libexec/PlistBuddy", "-c", f"Set :{key} {value}", plist],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        subprocess.run(
            ["/usr/libexec/PlistBuddy", "-c", f"Add :{key} string {value}", plist],
            capture_output=True,
            text=True,
        )


def _build_applescript(args):
    # A self-contained applet: for each run configuration, skip it when its main class is already
    # running, else drive IntelliJ's "Run > Debug…" chooser (speed-search + Enter) to start it in
    # Debug mode. The chooser item is matched by enumerating the Run menu (its label uses a real
    # ellipsis "…", and localizations vary), so we click the "Debug…" entry without hardcoding it.
    # UI scripting via System Events is what needs the app's own Accessibility grant.
    pairs = ", ".join(
        '{"%s", "%s"}' % (comp["config"], comp["main"])
        for comp in _components(args)
        if comp["kind"] == "java"
    )
    return (
        "on run\n"
        f"\tset configs to {{{pairs}}}\n"
        "\tmy waitForIdeReady()\n"
        "\trepeat with cfg in configs\n"
        "\t\tmy startConfig(item 1 of cfg, item 2 of cfg)\n"
        "\tend repeat\n"
        "end run\n"
        "\n"
        "on waitForIdeReady()\n"
        "\t-- Block until IntelliJ is UI-scriptable, not merely launched: its process must exist\n"
        "\t-- AND the Run menu must be populated (the project frame is up). Keystrokes sent before\n"
        "\t-- that -- e.g. right after 'dev debug start' launched a cold IDE -- are simply lost.\n"
        "\tset deadline to (current date) + 180\n"
        "\trepeat\n"
        "\t\ttry\n"
        '\t\t\ttell application "System Events"\n'
        f'\t\t\t\tset proc to first process whose bundle identifier is "{IDEA_BUNDLE_ID}"\n'
        '\t\t\t\tset runMenu to menu 1 of menu bar item "Run" of menu bar 1 of proc\n'
        "\t\t\t\tif (count of menu items of runMenu) > 0 then\n"
        "\t\t\t\t\tset frontmost of proc to true\n"
        "\t\t\t\t\tdelay 0.5\n"
        "\t\t\t\t\treturn\n"
        "\t\t\t\tend if\n"
        "\t\t\tend tell\n"
        "\t\tend try\n"
        "\t\tif (current date) > deadline then\n"
        '\t\t\terror "IntelliJ IDEA not ready (no Run menu) after 180s"\n'
        "\t\tend if\n"
        "\t\tdelay 1\n"
        "\tend repeat\n"
        "end waitForIdeReady\n"
        "\n"
        "on startConfig(configName, mainClass)\n"
        '\tset AppleScript\'s text item delimiters to ", "\n'
        "\tset isRunning to false\n"
        "\ttry\n"
        '\t\tdo shell script "pgrep -f " & quoted form of mainClass & " >/dev/null 2>&1"\n'
        "\t\tset isRunning to true\n"
        "\tend try\n"
        "\tif isRunning then return\n"
        '\ttell application "System Events"\n'
        f'\t\tset proc to first process whose bundle identifier is "{IDEA_BUNDLE_ID}"\n'
        "\t\tset frontmost of proc to true\n"
        "\t\tdelay 0.4\n"
        "\t\ttell proc\n"
        '\t\t\tset runMenu to menu 1 of menu bar item "Run" of menu bar 1\n'
        "\t\t\tset target to missing value\n"
        "\t\t\tset seen to {}\n"
        "\t\t\trepeat with mi in menu items of runMenu\n"
        "\t\t\t\tset nm to name of mi\n"
        "\t\t\t\tif nm is not missing value then\n"
        "\t\t\t\t\tset end of seen to nm\n"
        '\t\t\t\t\tif target is missing value and nm starts with "Debug" '
        'and nm does not contain "\'" then\n'
        "\t\t\t\t\t\tset target to mi\n"
        "\t\t\t\t\tend if\n"
        "\t\t\t\tend if\n"
        "\t\t\tend repeat\n"
        "\t\t\tif target is missing value then\n"
        "\t\t\t\terror \"No 'Debug…' entry in the Run menu. Found: \" & (seen as string)\n"
        "\t\t\tend if\n"
        "\t\t\tclick target\n"
        "\t\t\tdelay 1\n"
        "\t\t\tkeystroke configName\n"
        "\t\t\tdelay 0.5\n"
        "\t\t\tkey code 36\n"
        "\t\tend tell\n"
        "\tend tell\n"
        "\tdelay 2\n"
        "end startConfig\n"
    )


def _print_init_instructions(app_path, args):
    configs = " and ".join(
        f"'{comp['config']}'" for comp in _components(args) if comp["kind"] == "java"
    )
    print()
    utils.info("[debug] One-time setup for the dedicated debug launcher:")
    print(f"  1. Run 'ligoj dev debug start' (or open {app_path}).")
    print(
        "     macOS will ask to let 'Ligoj Debug' control your computer (Accessibility) — approve."
    )
    print("     Only THIS app gets the permission; you can then revoke your Terminal's grant.")
    print(
        "     (Remove any stale 'applet' entry in that list; macOS may re-prompt after a re-init.)"
    )
    print(f"  2. The app starts {configs} in Debug mode (skipping any already running), so you can")
    print(
        "     set breakpoints in IntelliJ. Re-run 'dev debug init' after you rename a run config."
    )
    print()


# --------------------------------------------------------------------------- #
# start / stop / restart
# --------------------------------------------------------------------------- #
# Backing services the IDE stack depends on: ligoj-api needs the dev PostgreSQL ('ligoj-db' pod)
# to boot at all, and OpenLDAP ('openldap' pod) for the plugin-id-ldap identity backend.
_BACKING_SERVICES = ("postgresql", "openldap")


def _ensure_backing_services(args, wait):
    """Bring the backing pods (dev PostgreSQL + OpenLDAP) up before the apps.

    A service already answering on its port is skipped. For the rest the podman machine is started
    first (a stopped machine makes every pod look absent), then each pod; a never-created pod only
    warns (pointing at 'dev init'), so the IDE apps still launch and their own logs show the error.
    """
    pending = []
    for svc in _BACKING_SERVICES:
        if dev._service_healthy(svc, args):
            utils.info(f"[debug] {svc} ({dev._PODS[svc]}) already up")
        else:
            pending.append(svc)
    if not pending:
        return
    dev._ensure_podman()
    started = []
    for svc in pending:
        if not dev._pod_exists(dev._PODS[svc]):
            utils.warn(
                f"[debug] {svc}: pod '{dev._PODS[svc]}' does not exist — run "
                f"'ligoj dev init --only {svc}' first; ligoj-api needs it"
            )
            continue
        dev._start_service(svc)
        started.append(svc)
    if started and wait != 0:
        # Bounded even when --wait is unset (unset means 'no limit' elsewhere): a healthy pod
        # answers within seconds, so a broken one should not hold the IDE startup hostage.
        dev._await_services(started, args, True, wait if wait is not None else 90)


def _stop_backing_services():
    """Stop the backing pods ('dev debug stop' owns them symmetrically with start).

    When the podman machine itself is down every pod is already stopped — skip quietly instead of
    letting the per-pod probes misreport 'does not exist' on a dead connection.
    """
    if dev._podman("info", "--format", "{{.Host.Arch}}", check=False).returncode != 0:
        utils.info("[debug] podman not running — backing pods already down")
        return
    for svc in _BACKING_SERVICES:
        dev._stop_service(svc)


def _start(args):
    app = _idea_app(args)
    project = _project_dir(args)
    wait = args.get("wait")
    comps = _components(args)
    expect_up = []

    # 0. Backing services: ligoj-api depends on the [dev] PostgreSQL and OpenLDAP, so start their
    #    pods first (they warm up while IntelliJ loads).
    _ensure_backing_services(args, wait)

    # 1. IntelliJ IDEA (start + open the project, or just focus it if already running).
    ide_was_running = _ide_running(app)
    if ide_was_running:
        utils.info(f"[debug] {app} already running")
        _open_project(app, project)
    else:
        _open_project(app, project)
        if wait != 0:
            _wait_ide(app, wait)

    # 2. ligoj-api / ligoj-ui via the dedicated launcher app (Debug mode; needs no terminal grant).
    java = [c for c in comps if c["kind"] == "java"]
    for comp in java:
        if _running_pids(comp, args):
            utils.info(f"[debug] {comp['label']} already running")
            expect_up.append(comp)
    stopped = [c for c in java if not _running_pids(c, args)]
    launched = _launch_debug_app(args, stopped) if stopped else []
    expect_up.extend(launched)

    # 3. Vite dev server (managed directly as a detached process).
    vite = next(c for c in comps if c["kind"] == "vite")
    if _running_pids(vite, args) or dev._probe_tcp("localhost", vite["port"]):
        utils.info("[debug] Vite already running")
        expect_up.append(vite)
    elif _start_vite(vite, args):
        expect_up.append(vite)

    # 4. Wait for the started apps, then show status. Cap an otherwise-unbounded wait when the debug
    #    app was just launched, so a not-yet-granted Accessibility prompt cannot hang forever. A
    #    cold IntelliJ must first finish loading (the launcher waits for its Run menu) before the
    #    apps can even start, so allow more time in that case.
    if wait is None and launched:
        eff_wait = 240 if not ide_was_running else 120
    else:
        eff_wait = wait
    if wait != 0 and expect_up:
        _await_components(expect_up, True, eff_wait, args)
    _render_status(args)
    return False


def _launch_debug_app(args, stopped):
    app_path = _debug_app_path(args)
    configs = ", ".join(comp["config"] for comp in stopped)
    if not os.path.isdir(app_path):
        utils.warn(
            f"[debug] Debug launcher app not found ({app_path}). Run 'ligoj dev debug init' to "
            f"create it, then re-run start (or launch {configs} from IntelliJ's Run menu)."
        )
        return []
    installed = _installed_launcher_version(app_path)
    if installed != _LAUNCHER_VERSION:
        utils.warn(
            f"[debug] Launcher app is outdated (v{installed or '1'}, expected v{_LAUNCHER_VERSION}); "
            "re-run 'ligoj dev debug init' so it waits for IntelliJ to be ready before driving it — "
            "otherwise starting a cold IDE may fail."
        )
    utils.info(f"[debug] Start {configs} in Debug mode via {os.path.basename(app_path)} ...")
    result = subprocess.run(["open", app_path], capture_output=True, text=True)
    if result.returncode != 0:
        utils.warn(f"[debug] Could not launch {app_path}: {(result.stderr or '').strip()[:200]}")
        return []
    return stopped


def _stop(args):
    _stop_apps(args, args.get("wait"))
    # Symmetric with start: also stop the backing pods. NOT done on restart (_restart calls
    # _stop_apps directly), which only bounces the apps and leaves the pods running.
    _stop_backing_services()
    utils.info("[debug] IntelliJ left running (quit it manually to preserve unsaved work)")
    _render_status(args)
    return False


def _restart(args):
    wait = args.get("wait")
    # Ensure a clean shutdown (bounded, so restart never hangs) before starting again — otherwise
    # the re-launched app cannot bind its still-busy port.
    _stop_apps(args, 30 if wait is None else wait)
    return _start(args)


def _stop_apps(args, wait):
    comps = _components(args)
    for comp in comps:
        if comp["kind"] == "java":
            pids = _running_pids(comp, args)
            if pids:
                _terminate(pids, comp["label"])
            else:
                utils.info(f"[debug] {comp['label']} not running")
        elif comp["kind"] == "vite":
            _stop_vite(comp, args)
    if wait != 0:
        _await_components([c for c in comps if c["kind"] != "ide"], False, wait, args)


# --------------------------------------------------------------------------- #
# IntelliJ IDEA
# --------------------------------------------------------------------------- #
def _ide_running(app):
    result = subprocess.run(
        ["osascript", "-e", f'application "{app}" is running'], capture_output=True, text=True
    )
    return result.stdout.strip() == "true"


def _open_project(app, project):
    if not os.path.isdir(project):
        utils.warn(f"[debug] Project directory not found: {project}")
        return
    result = subprocess.run(["open", "-a", app, project], capture_output=True, text=True)
    if result.returncode != 0:
        utils.warn(f"[debug] Could not open {app}: {(result.stderr or '').strip()[:200]}")
    else:
        utils.info(f"[debug] Opened {project} in {app}")


def _wait_ide(app, wait):
    utils.info(f"[debug] Launching {app} ...")
    deadline = dev._deadline(60 if wait is None else wait)
    while not _ide_running(app):
        if deadline is not None and time.time() >= deadline:
            utils.warn(f"[debug] {app} did not report running in time")
            return False
        time.sleep(1)
    utils.info(f"[debug] {app} is up")
    return True


# --------------------------------------------------------------------------- #
# Vite dev server
# --------------------------------------------------------------------------- #
def _vite_pattern(webapp):
    # The node process running vite carries the project webapp path in its command line.
    return f"{webapp}.*vite"


def _start_vite(comp, args):
    webapp = comp["webapp"]
    if not os.path.isdir(webapp):
        utils.warn(f"[debug] Vite directory not found: {webapp}; skipping")
        return False
    if shutil.which("npm") is None:
        utils.warn("[debug] npm is not on PATH; cannot start Vite")
        return False
    os.makedirs(_state_dir(), exist_ok=True)
    log_path = os.path.join(_state_dir(), "vite.log")
    utils.info(f"[debug] Start Vite (npm run dev) in {webapp} ...")
    with open(log_path, "ab") as log:
        proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=webapp,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # detach into its own session so it survives the CLI
        )
    _write_pid(proc.pid)
    utils.debug(f"[debug] Vite started (pid {proc.pid}), logs at {log_path}")
    return True


def _stop_vite(comp, args):
    pids = set(_running_pids(comp, args))
    tracked = _read_pid()
    if not pids and not (tracked and _alive(tracked)):
        utils.info("[debug] Vite not running")
        _clear_pid()
        return
    utils.info("[debug] Stop Vite ...")
    if tracked and _alive(tracked):
        _killpg(tracked, signal.SIGTERM)  # our own detached session: kill npm + node children
    for pid in pids:
        _signal(pid, signal.SIGTERM)
    deadline = time.time() + 10
    while time.time() < deadline and dev._probe_tcp("localhost", comp["port"]):
        time.sleep(0.5)
    if tracked and _alive(tracked):
        _killpg(tracked, signal.SIGKILL)
    for pid in pids:
        if _alive(pid):
            _signal(pid, signal.SIGKILL)
    _clear_pid()


# --------------------------------------------------------------------------- #
# Process detection / signalling
# --------------------------------------------------------------------------- #
def _running_pids(comp, args):
    if comp["kind"] == "java":
        return _pgrep(comp["main"])
    if comp["kind"] == "vite":
        return _pgrep(_vite_pattern(comp["webapp"]))
    return []


def _pgrep(pattern):
    result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return [int(pid) for pid in result.stdout.split()] if result.returncode == 0 else []


def _terminate(pids, label):
    # SIGTERM each pid individually (never the process group: an IDE-launched JVM shares the IDE's
    # session, so killpg would take IntelliJ down too), then SIGKILL any survivor.
    utils.info(f"[debug] Stop {label} (pid {', '.join(map(str, pids))}) ...")
    for pid in pids:
        _signal(pid, signal.SIGTERM)
    deadline = time.time() + 10
    while time.time() < deadline and any(_alive(pid) for pid in pids):
        time.sleep(0.5)
    for pid in pids:
        if _alive(pid):
            utils.warn(f"[debug] {label} pid {pid} still alive, sending SIGKILL")
            _signal(pid, signal.SIGKILL)


def _alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _signal(pid, sig):
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        utils.warn(f"[debug] Not permitted to signal pid {pid}")


def _killpg(pid, sig):
    try:
        os.killpg(os.getpgid(pid), sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        utils.warn(f"[debug] Not permitted to signal the process group of pid {pid}")


# --------------------------------------------------------------------------- #
# Waiting (reuses the shared live-progress renderer)
# --------------------------------------------------------------------------- #
def _await_components(comps, want_up, wait, args):
    comps = [c for c in comps if c["kind"] != "ide"]
    if not comps:
        return
    by_label = {c["label"]: c for c in comps}

    def check(label):
        return _reached(by_label[label], want_up, args)

    dev._await_many(list(by_label), check, dev._deadline(wait), "up" if want_up else "down")


def _reached(comp, want_up, args):
    up = dev._probe_tcp("localhost", comp["port"])
    if want_up:
        return up
    # 'down' means the port is free and no matching process remains.
    return not up and not _running_pids(comp, args)


# --------------------------------------------------------------------------- #
# Status
# --------------------------------------------------------------------------- #
def _render_status(args):
    app = _idea_app(args)
    rows = []
    for comp in _components(args):
        if comp["kind"] == "ide":
            running = _ide_running(app)
            rows.append(
                {
                    "component": comp["label"],
                    "status": "running" if running else "stopped",
                    "status_level": "ok" if running else "warn",
                    "port": "-",
                    "port_level": "",
                    "info": comp["url"],
                }
            )
        else:
            running = bool(_running_pids(comp, args))
            up = dev._probe_tcp("localhost", comp["port"])
            rows.append(
                {
                    "component": comp["label"],
                    "status": "running" if running else "stopped",
                    "status_level": "ok" if running else "warn",
                    "port": f":{comp['port']} {'up' if up else 'down'}",
                    "port_level": "ok" if up else "bad",
                    "info": comp["url"],
                }
            )
    _print_table(rows)
    return False


def _print_table(rows):
    cols = ["COMPONENT", "STATUS", "PORT", "URL / PATH"]
    data = [[r["component"], r["status"], r["port"], r["info"]] for r in rows]
    widths = [max(len(cols[i]), *(len(row[i]) for row in data)) for i in range(len(cols))]
    print("  ".join(cols[i].ljust(widths[i]) for i in range(len(cols))))
    print("  ".join("-" * widths[i] for i in range(len(cols))))
    for r, row in zip(rows, data):
        print(
            "  ".join(
                [
                    row[0].ljust(widths[0]),
                    dev._color(row[1].ljust(widths[1]), r["status_level"]),
                    dev._color(row[2].ljust(widths[2]), r["port_level"]),
                    row[3].ljust(widths[3]),
                ]
            )
        )


# --------------------------------------------------------------------------- #
# Vite pid state
# --------------------------------------------------------------------------- #
def _state_dir():
    return os.path.join(utils.user_home, ".ligoj", "dev", "debug")


def _pid_file():
    return os.path.join(_state_dir(), "vite.pid")


def _write_pid(pid):
    os.makedirs(_state_dir(), exist_ok=True)
    with open(_pid_file(), "w", encoding="utf-8") as handle:
        handle.write(str(pid))


def _read_pid():
    try:
        with open(_pid_file(), encoding="utf-8") as handle:
            return int(handle.read().strip())
    except (OSError, ValueError):
        return None


def _clear_pid():
    try:
        os.remove(_pid_file())
    except OSError:
        pass
