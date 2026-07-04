#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# `dev demo` orchestrator.
#
# Checks that the Ligoj instance is running (started as a container or from IntelliJ), lists the
# installed plugins (id, name, version), then runs the demo defined for each one. Each plugin
# demo lives in its own module under this package and is registered by Maven artifact id.
#
from ligojcli.dev_demo import (
    plugin_build_jenkins,
    plugin_id_ldap,
    plugin_registry_artifactory,
    plugin_registry_harbor,
    plugin_registry_nexus,
    plugin_scm_gitlab,
)
from ligojcli.plugins import ligoj, utils

# Maven artifact id -> demo module exposing run(args).
REGISTRY = {
    module.ARTIFACT: module
    for module in (
        plugin_id_ldap,
        plugin_build_jenkins,
        plugin_scm_gitlab,
        plugin_registry_harbor,
        plugin_registry_nexus,
        plugin_registry_artifactory,
    )
}


def demo(args):
    _check_ligoj_running()

    plugins = ligoj.plugin_list() or []
    _print_plugins(plugins)

    if args.get("list"):
        return False

    only = set(args.get("only") or [])
    results = {}
    for entry in plugins:
        artifact = (entry.get("plugin") or {}).get("artifact")
        module = REGISTRY.get(artifact)
        if module is None or (only and artifact not in only):
            continue
        utils.info(f"[dev] === Demo {artifact} ({entry.get('name')}) ===")
        try:
            module.run(args)
            results[artifact] = "ok"
        except Exception as error:  # noqa: BLE001 - one plugin must not abort the whole run
            utils.warn(f"[dev] {artifact}: demo failed: {error}")
            results[artifact] = f"failed: {error}"

    if not results:
        utils.warn("[dev] No installed plugin matched a known demo")
    else:
        done = sum(1 for state in results.values() if state == "ok")
        utils.info(f"[dev] Demo complete: {done}/{len(results)} plugin(s) configured")
    return results or False


def _check_ligoj_running():
    endpoint = utils.not_none(ligoj.ligoj_endpoint, "endpoint")
    utils.check_endpoint(endpoint, "ligoj")
    try:
        health = ligoj.info_status(0)
    except Exception as error:  # noqa: BLE001 - turn any connection error into a clear hint
        raise ValueError(
            f"[dev] Ligoj is not reachable at {endpoint}: start it (container or IntelliJ) first "
            f"({error})"
        )
    status = (
        health.json().get("status") if hasattr(health, "json") else (health or {}).get("status")
    )
    if status != "UP":
        raise ValueError(
            f"[dev] Ligoj at {endpoint} is not healthy (status={status}); start it first"
        )
    utils.info(f"[dev] Ligoj is running at {endpoint} (status {status})")


def _print_plugins(plugins):
    rows = []
    for entry in plugins:
        plugin = entry.get("plugin") or {}
        artifact = plugin.get("artifact", "")
        boot = "yes" if artifact in REGISTRY else "-"
        rows.append([entry.get("id", ""), entry.get("name", ""), plugin.get("version", ""), boot])
    cols = ["ID", "NAME", "VERSION", "DEMO"]
    widths = (
        [max(len(cols[i]), *(len(r[i]) for r in rows)) for i in range(len(cols))]
        if rows
        else [len(c) for c in cols]
    )
    utils.info(f"[dev] {len(plugins)} installed plugin(s):")
    print("  ".join(cols[i].ljust(widths[i]) for i in range(len(cols))))
    print("  ".join("-" * widths[i] for i in range(len(cols))))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(cols))))
