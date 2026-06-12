#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# CLI actions for the Ligoj `plugin-build` service category, exposed under the
# `build:job` service. The build operations are implemented by provider
# sub-plugins (Jenkins, Travis, ...) under `service/build/<provider>/...`; the
# provider is taken from --provider, inferred from the --node identifier, or
# resolved from the subscription's node.
#
import urllib.parse

from ligojcli.plugins import ligoj, utils

SERVICE = "service/build"


def configure(subparser_service):
    sub = subparser_service.add_parser(
        "build:job", help="Build job operations (Jenkins, Travis, ...)"
    ).add_subparsers(title="action", help="Action", dest="action")

    p = sub.add_parser("trigger", help="Trigger the build configured for a subscription")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)
    p.add_argument(
        "--provider", "-p", help="Build provider, e.g. jenkins/travis (inferred if omitted)"
    )

    p = sub.add_parser("find", help="Search jobs matching a criteria on a node")
    p.add_argument(
        "--node", "-n", help="Node identifier, e.g. service:build:jenkins:dev", required=True
    )
    p.add_argument("--criteria", "-c", help="Search criteria (name/description)", required=True)
    p.add_argument("--provider", "-p", help="Build provider (inferred from the node if omitted)")

    p = sub.add_parser("templates", help="Search template jobs matching a criteria (Jenkins)")
    p.add_argument("--node", "-n", help="Node identifier", required=True)
    p.add_argument("--criteria", "-c", help="Search criteria", required=True)
    p.add_argument("--provider", "-p", help="Build provider (inferred from the node if omitted)")

    p = sub.add_parser("get", help="Return a job by identifier on a node")
    p.add_argument("--node", "-n", help="Node identifier", required=True)
    p.add_argument("--id", "-i", help="Job identifier/name", required=True)
    p.add_argument("--provider", "-p", help="Build provider (inferred from the node if omitted)")


def execute_action(service, action, _, args):
    if service != "build:job":
        return None

    if action == "trigger":
        sub = args["subscription"]
        provider = _resolve_provider(args, subscription=sub)
        utils.info(f"[ligoj] Trigger build for subscription '{sub}' on '{provider}' ...")
        return ligoj.call_api("POST", f"{SERVICE}/{provider}/build/{sub}")

    if action == "find":
        provider = _resolve_provider(args)
        node = args["node"]
        utils.info(f"[ligoj] Find '{provider}' jobs on '{node}' matching '{args['criteria']}' ...")
        return ligoj.call_api("GET", f"{SERVICE}/{provider}/{node}/{_enc(args['criteria'])}")

    if action == "templates":
        provider = _resolve_provider(args)
        node = args["node"]
        utils.info(
            f"[ligoj] Find '{provider}' template jobs on '{node}' matching '{args['criteria']}' ..."
        )
        return ligoj.call_api(
            "GET", f"{SERVICE}/{provider}/template/{node}/{_enc(args['criteria'])}"
        )

    if action == "get":
        provider = _resolve_provider(args)
        node = args["node"]
        utils.info(f"[ligoj] Get '{provider}' job '{args['id']}' on '{node}' ...")
        return ligoj.call_api("GET", f"{SERVICE}/{provider}/{node}/job/{_enc(args['id'])}")

    return None


def _enc(value):
    return urllib.parse.quote(str(value), safe="")


def _provider_from_node(node):
    parts = (node or "").split(":")
    if len(parts) >= 3 and parts[0] == "service" and parts[1] == "build":
        return parts[2]
    raise ValueError(f"[ligoj] Cannot infer the build provider from node '{node}'; pass --provider")


def _resolve_provider(args, *, subscription=None):
    if args.get("provider"):
        return args["provider"]
    if args.get("node"):
        return _provider_from_node(args["node"])
    if subscription is not None:
        details = ligoj.subscription_get_by_id(subscription, False)
        node = details.get("node") if isinstance(details, dict) else None
        if isinstance(node, dict):
            node = node.get("id")
        return _provider_from_node(node)
    raise ValueError("[ligoj] A --provider, --node or --subscription is required")
