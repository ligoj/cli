#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Shared helpers for the per-plugin demo modules.
#
import os

from ligojcli.plugins import dev, ligoj, utils

# Repository root, two levels up from this package (ligojcli/dev_demo/).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def bundled_path(*parts):
    """Absolute path to a file bundled with the CLI source tree (e.g. docs/nodes/...)."""
    return os.path.join(_REPO_ROOT, *parts)


def dev_value(args, name, env, default=None):
    """Resolve a value from --args, the environment, the [dev] credentials section, then default."""
    return dev._dev_get(args, name, env, default)


def load_node(filename):
    """Load a bundled node sample (docs/nodes/<filename>) as a {parameter: value} mapping."""
    entries = utils.load_json_from_url_or_file_with_interpolation(
        bundled_path("docs", "nodes", filename), {}
    )
    return {entry["parameter"]: entry.get("text") for entry in entries if entry.get("parameter")}


def upsert_node(node_id, name, params, required=None, mode="LINK"):
    """Create/update a Ligoj node from a {parameter: value} mapping.

    Skips (with a warning) when a required value is missing, so the demo of one plugin never
    aborts the whole run because, say, the related dev service was not initialized yet. The default
    mode is LINK: the tool service nodes (build/scm/registry) are 'link' refined, so a child node
    must not exceed that (mode 'all' is rejected with invalid-mode).
    """
    keys = list(params) if required is None else required
    missing = [key for key in keys if not params.get(key)]
    if missing:
        utils.warn(
            f"[dev] {node_id}: missing value(s) for {', '.join(missing)}; "
            "skipping node (run the related 'dev init --only ...' first)"
        )
        return None
    parameters = [{"parameter": key, "text": str(value)} for key, value in params.items() if value]
    return ligoj.node_upsert(node_id, name, parameters, mode)
