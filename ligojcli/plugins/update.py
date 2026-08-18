#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# `ligoj update` — self-update of this CLI through `uv`.
#
# The recommended installation is `uv tool install ligoj-cli` (see README):
# `uv tool upgrade ligoj-cli` refreshes it to the latest published release,
# and `uv tool install --force 'ligoj-cli==X'` pins a specific one. This
# command wraps both. It never needs a Ligoj endpoint.
import shutil
import subprocess

from ligojcli.plugins import utils


def configure(subparser_service):
    parser = subparser_service.add_parser(
        "update", help="Update this CLI itself to the latest release with uv"
    )
    # No action subparsers: `ligoj update` alone is the whole command. The
    # implicit action keeps the `<service> <action>` grammar of main() happy.
    parser.set_defaults(action="self")
    parser.add_argument(
        "--target",
        help="Specific version to install instead of the latest release (e.g. 1.3.0)",
        default=None,
    )


def execute_action(service, action, operation, args):  # noqa: ARG001 - uniform plugin signature
    if service != "update":
        return False
    return _self_update(args)


def _current_version():
    try:
        from importlib.metadata import version

        return version("ligoj-cli")
    except Exception:  # noqa: BLE001 - purely informational
        return "unknown"


def _self_update(args):
    if shutil.which("uv") is None:
        utils.error(
            "[update] 'uv' is not available. Install it (https://docs.astral.sh/uv/) or update"
            " manually with your installer, e.g. 'pipx upgrade ligoj-cli' or"
            " 'pip install -U ligoj-cli'"
        )
        return True

    current = _current_version()
    target = args.get("target")
    if target:
        utils.info(f"[update] Updating ligoj-cli {current} -> {target} with uv ...")
        command = ["uv", "tool", "install", "--force", f"ligoj-cli=={target}"]
    else:
        utils.info(f"[update] Updating ligoj-cli {current} to the latest release with uv ...")
        command = ["uv", "tool", "upgrade", "ligoj-cli"]

    result = subprocess.run(command, check=False)  # noqa: S603 - fixed command, streamed output
    if result.returncode != 0:
        utils.error(
            f"[update] '{' '.join(command)}' failed ({result.returncode})."
            " If this CLI was not installed with 'uv tool install', update it with your"
            " installer instead ('pipx upgrade ligoj-cli' / 'pip install -U ligoj-cli')"
        )
        return True

    utils.info("[update] Done. Run 'ligoj --version' in a new command to verify the version")
    return True
