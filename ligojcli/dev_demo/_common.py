#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Shared helpers for the per-plugin demo modules.
#
import os
from urllib.parse import urlparse

from ligojcli.plugins import dev, ligoj, utils

# Repository root, two levels up from this package (ligojcli/dev_demo/).
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def bundled_path(*parts):
    """Absolute path to a file bundled with the CLI source tree (e.g. docs/nodes/...)."""
    return os.path.join(_REPO_ROOT, *parts)


def dev_value(args, name, env, default=None):
    """Resolve a value from --args, the environment, the [dev] credentials section, then default."""
    return dev._dev_get(args, name, env, default)


def host_of(url):
    """`http://localhost:8088` -> `localhost:8088` (the docker registry host)."""
    return urlparse(url).netloc or url


def upsert_node(node_id, name, params, required=None):
    """Create/update a Ligoj node from a {parameter: value} mapping.

    Skips (with a warning) when a required value is missing, so the demo of one plugin never
    aborts the whole run because, say, the related dev service was not initialized yet.
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
    return ligoj.node_upsert(node_id, name, parameters, "ALL")
