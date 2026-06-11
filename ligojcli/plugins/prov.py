#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# CLI actions for the Ligoj `plugin-prov` provisioning module, exposed under the
# `prov:<resource>` services (mirroring the `id:<resource>` actions of plugin-id).
# REST base path is `service/prov` (see ProvResource.SERVICE_URL).
#
import json

from ligojcli.plugins import ligoj, utils

SERVICE = "service/prov"


# ── argparse helpers ─────────────────────────────────────────────────────────
def _add_vm_args(parser, *, with_price=True):
    """Add the fields shared by every quoted VM resource (AbstractQuoteVmEditionVo)."""
    parser.add_argument("--id", "-i", help="Resource identifier (update only)", type=int)
    parser.add_argument("--subscription", "-s", help="Subscription identifier", type=int)
    parser.add_argument("--name", "-n", help="Resource name")
    parser.add_argument("--description", help="Description")
    if with_price:
        parser.add_argument("--price", "-P", help="Price identifier (from a lookup)", type=int)
    parser.add_argument("--cpu", help="Requested CPU", type=float)
    parser.add_argument("--cpu-max", help="Max used CPU", type=float)
    parser.add_argument("--gpu", help="Requested GPU", type=float)
    parser.add_argument("--ram", help="Requested RAM (MiB)", type=int)
    parser.add_argument("--ram-max", help="Max used RAM (MiB)", type=int)
    parser.add_argument("--min-quantity", "-m", help="Minimum quantity", type=int)
    parser.add_argument("--max-quantity", "-M", help="Maximum quantity", type=int)
    parser.add_argument(
        "--internet", choices=["PUBLIC", "PRIVATE", "PRIVATE_NAT"], help="Internet access"
    )
    parser.add_argument("--location", "-l", help="Location name")
    parser.add_argument("--usage", "-U", help="Usage name")
    parser.add_argument("--budget", "-b", help="Budget name")
    parser.add_argument("--optimizer", "-o", help="Optimizer name")
    parser.add_argument("--license", help="License model, e.g. BYOL")
    parser.add_argument("--type", "-t", help="Required type code")
    parser.add_argument("--processor", help="Required physical processor")
    parser.add_argument(
        "--physical", help="Require a physical host", action="store_true", default=None
    )
    parser.add_argument(
        "--ephemeral", help="Can be terminated by the provider", action="store_true", default=None
    )
    parser.add_argument(
        "--auto-scale", help="Auto-scaling requirement", action="store_true", default=None
    )
    parser.add_argument("--data", "-d", help="Raw JSON merged into the request body")


_VM_BODY = (
    ("id", "id"),
    ("subscription", "subscription"),
    ("name", "name"),
    ("description", "description"),
    ("price", "price"),
    ("cpu", "cpu"),
    ("cpu_max", "cpuMax"),
    ("gpu", "gpu"),
    ("ram", "ram"),
    ("ram_max", "ramMax"),
    ("min_quantity", "minQuantity"),
    ("max_quantity", "maxQuantity"),
    ("internet", "internet"),
    ("location", "location"),
    ("usage", "usage"),
    ("budget", "budget"),
    ("optimizer", "optimizer"),
    ("license", "license"),
    ("type", "type"),
    ("processor", "processor"),
    ("physical", "physical"),
    ("ephemeral", "ephemeral"),
    ("auto_scale", "autoScale"),
)


def _vm_lookup_args(parser, *, os=False, engine=False):
    parser.add_argument("--subscription", "-s", help="Subscription identifier", type=int)
    parser.add_argument("--cpu", help="Requested CPU", type=float)
    parser.add_argument("--ram", help="Requested RAM (MiB)", type=int)
    if os:
        parser.add_argument("--os", help="Operating system, e.g. LINUX")
    if engine:
        parser.add_argument("--engine", help="Database engine, e.g. MYSQL")
        parser.add_argument("--edition", help="Database edition")
    parser.add_argument("--type", "-t", help="Required type code")
    parser.add_argument("--location", "-l", help="Location name")
    parser.add_argument("--usage", "-U", help="Usage name")
    parser.add_argument("--budget", "-b", help="Budget name")
    parser.add_argument("--optimizer", "-o", help="Optimizer name")
    parser.add_argument("--license", help="License model")
    parser.add_argument("--processor", help="Required physical processor")


_LOOKUP_PARAMS = (
    ("cpu", "cpu"),
    ("ram", "ram"),
    ("os", "os"),
    ("engine", "engine"),
    ("edition", "edition"),
    ("type", "type"),
    ("location", "location"),
    ("usage", "usage"),
    ("budget", "budget"),
    ("optimizer", "optimizer"),
    ("license", "license"),
    ("processor", "processor"),
)


def configure(subparser_service):
    # ── prov:quote ───────────────────────────────────────────────────────────
    sub = subparser_service.add_parser(
        "prov:quote", help="Provisioning quote (subscription) operations"
    ).add_subparsers(title="action", help="Action", dest="action")
    p = sub.add_parser("get", help="Return the full quote configuration")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)
    p = sub.add_parser("locations", help="List the available locations")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)
    p = sub.add_parser("refresh", help="Refresh all lookups and recompute the cost")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)
    p = sub.add_parser("refresh-cost", help="Recompute the total cost only")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)
    p = sub.add_parser("update", help="Update the quote settings")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)
    p.add_argument("--name", "-n", help="Quote name")
    p.add_argument("--description", help="Description")
    p.add_argument("--location", "-l", help="Default location name")
    p.add_argument("--usage", "-U", help="Default usage name")
    p.add_argument("--budget", "-b", help="Default budget name")
    p.add_argument("--optimizer", "-o", help="Default optimizer name")
    p.add_argument("--license", help="Default license model")
    p.add_argument("--processor", help="Default physical processor")
    p.add_argument("--ram-rate", help="RAM adjusted rate (1-200)", type=int)
    p.add_argument("--reservation-mode", choices=["RESERVED", "MAX"], help="Reservation mode")
    p.add_argument("--physical", help="Require physical hosts", action="store_true", default=None)
    p.add_argument("--data", "-d", help="Raw JSON merged into the request body")

    # ── prov:instance / container / database / function (quoted VMs) ──────────
    _configure_vm(subparser_service, "instance", "Compute instance", os=True, software=True)
    _configure_vm(subparser_service, "container", "Container", os=True)
    _configure_vm(subparser_service, "database", "Database", engine=True)
    _configure_function(subparser_service)

    # ── prov:storage ─────────────────────────────────────────────────────────
    sub = subparser_service.add_parser(
        "prov:storage", help="Provisioning storage operations"
    ).add_subparsers(title="action", help="Action", dest="action")
    p = sub.add_parser("lookup", help="Find storage types matching criteria")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)
    p.add_argument("--size", help="Requested size (GiB)", type=int)
    p.add_argument("--latency", help="Latency rate, e.g. BEST")
    p.add_argument("--optimized", help="Optimization, e.g. IOPS / THROUGHPUT / DURABILITY")
    p.add_argument("--location", "-l", help="Location name")
    p.add_argument("--instance", help="Attached quote instance id", type=int)
    p.add_argument("--database", help="Attached quote database id", type=int)
    p.add_argument("--container", help="Attached quote container id", type=int)
    p.add_argument("--function", help="Attached quote function id", type=int)
    for verb in ("create", "update"):
        p = sub.add_parser(verb, help=f"{verb.capitalize()} a storage")
        p.add_argument("--id", "-i", help="Storage identifier (update only)", type=int)
        p.add_argument("--subscription", "-s", help="Subscription identifier", type=int)
        p.add_argument("--name", "-n", help="Storage name")
        p.add_argument("--description", help="Description")
        p.add_argument("--type", "-t", help="Storage type code")
        p.add_argument("--size", help="Requested size (GiB)", type=int)
        p.add_argument("--size-max", help="Max used size (GiB)", type=int)
        p.add_argument("--quantity", "-q", help="Quantity", type=int)
        p.add_argument("--latency", help="Latency rate")
        p.add_argument("--optimized", help="Optimization requirement")
        p.add_argument("--location", "-l", help="Location name")
        p.add_argument("--instance", help="Attached quote instance id", type=int)
        p.add_argument("--database", help="Attached quote database id", type=int)
        p.add_argument("--container", help="Attached quote container id", type=int)
        p.add_argument("--function", help="Attached quote function id", type=int)
        p.add_argument("--data", "-d", help="Raw JSON merged into the request body")
    _add_delete(sub, "storage")

    # ── prov:support ─────────────────────────────────────────────────────────
    sub = subparser_service.add_parser(
        "prov:support", help="Provisioning support plan operations"
    ).add_subparsers(title="action", help="Action", dest="action")
    p = sub.add_parser("lookup", help="Find support plans matching requirements")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)
    p.add_argument("--seats", help="Number of seats", type=int)
    p.add_argument("--level", help="Consulting level rate")
    for opt in ("api", "email", "chat", "phone"):
        p.add_argument(f"--access-{opt}", help=f"{opt.capitalize()} access requirement")
    for verb in ("create", "update"):
        p = sub.add_parser(verb, help=f"{verb.capitalize()} a support plan")
        p.add_argument("--id", "-i", help="Support identifier (update only)", type=int)
        p.add_argument("--subscription", "-s", help="Subscription identifier", type=int)
        p.add_argument("--name", "-n", help="Support name")
        p.add_argument("--type", "-t", help="Support type name")
        p.add_argument("--seats", help="Number of seats", type=int)
        p.add_argument("--level", help="Consulting level rate")
        for opt in ("api", "email", "chat", "phone"):
            p.add_argument(f"--access-{opt}", help=f"{opt.capitalize()} access requirement")
        p.add_argument("--data", "-d", help="Raw JSON merged into the request body")
    _add_delete(sub, "support")

    # ── prov:usage / budget / optimizer (multi-scoped) ───────────────────────
    sub = subparser_service.add_parser(
        "prov:usage", help="Provisioning usage operations"
    ).add_subparsers(title="action", help="Action", dest="action")
    _add_scoped_list_delete(sub)
    for verb in ("create", "update"):
        p = sub.add_parser(verb, help=f"{verb.capitalize()} a usage")
        p.add_argument("--id", "-i", help="Usage identifier (update only)", type=int)
        p.add_argument(
            "--subscription", "-s", help="Subscription identifier", type=int, required=True
        )
        p.add_argument("--name", "-n", help="Usage name", required=True)
        p.add_argument("--rate", "-r", help="Usage rate (1-100)", type=int)
        p.add_argument("--duration", help="Duration in months (1-72)", type=int)
        p.add_argument("--start", help="Start month offset", type=int)
        p.add_argument("--data", "-d", help="Raw JSON merged into the request body")

    sub = subparser_service.add_parser(
        "prov:budget", help="Provisioning budget operations"
    ).add_subparsers(title="action", help="Action", dest="action")
    _add_scoped_list_delete(sub)
    for verb in ("create", "update"):
        p = sub.add_parser(verb, help=f"{verb.capitalize()} a budget")
        p.add_argument("--id", "-i", help="Budget identifier (update only)", type=int)
        p.add_argument(
            "--subscription", "-s", help="Subscription identifier", type=int, required=True
        )
        p.add_argument("--name", "-n", help="Budget name", required=True)
        p.add_argument("--initial-cost", help="Initial cost", type=float)
        p.add_argument("--data", "-d", help="Raw JSON merged into the request body")

    sub = subparser_service.add_parser(
        "prov:optimizer", help="Provisioning optimizer operations"
    ).add_subparsers(title="action", help="Action", dest="action")
    _add_scoped_list_delete(sub)
    for verb in ("create", "update"):
        p = sub.add_parser(verb, help=f"{verb.capitalize()} an optimizer")
        p.add_argument("--id", "-i", help="Optimizer identifier (update only)", type=int)
        p.add_argument(
            "--subscription", "-s", help="Subscription identifier", type=int, required=True
        )
        p.add_argument("--name", "-n", help="Optimizer name", required=True)
        p.add_argument("--mode", help="Optimizer mode, e.g. COST / CO2", required=True)
        p.add_argument("--data", "-d", help="Raw JSON merged into the request body")

    # ── prov:tag ─────────────────────────────────────────────────────────────
    sub = subparser_service.add_parser(
        "prov:tag", help="Provisioning resource tag operations"
    ).add_subparsers(title="action", help="Action", dest="action")
    for verb in ("create", "update"):
        p = sub.add_parser(verb, help=f"{verb.capitalize()} a tag on a resource")
        p.add_argument("--id", "-i", help="Tag identifier (update only)", type=int)
        p.add_argument(
            "--subscription", "-s", help="Subscription identifier", type=int, required=True
        )
        p.add_argument("--name", "-n", help="Tag name", required=True)
        p.add_argument("--value", help="Tag value")
        p.add_argument(
            "--type",
            "-t",
            help="Tagged resource type",
            required=True,
            choices=["INSTANCE", "DATABASE", "CONTAINER", "FUNCTION", "STORAGE", "SUPPORT"],
        )
        p.add_argument("--resource", "-R", help="Tagged resource id", type=int, required=True)
        p.add_argument("--data", "-d", help="Raw JSON merged into the request body")
    p = sub.add_parser("delete", help="Delete a tag by identifier")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)
    p.add_argument("--id", "-i", help="Tag identifier", type=int, required=True)

    # ── prov:catalog ─────────────────────────────────────────────────────────
    sub = subparser_service.add_parser(
        "prov:catalog", help="Provider price catalog operations"
    ).add_subparsers(title="action", help="Action", dest="action")
    sub.add_parser("list", help="List the catalog status of every provider")
    p = sub.add_parser("status", help="Get the catalog import status of a node")
    p.add_argument(
        "--node", "-N", help="Node identifier, e.g. service:prov:aws:test", required=True
    )
    p = sub.add_parser("update", help="Trigger a catalog import/update for a node")
    p.add_argument(
        "--node", "-N", help="Node identifier, e.g. service:prov:aws:test", required=True
    )
    p.add_argument("--force", "-F", help="Force a full update", action="store_true", default=False)
    p = sub.add_parser("cancel", help="Cancel a running catalog import")
    p.add_argument("--node", "-N", help="Node identifier", required=True)

    # ── prov:upload ──────────────────────────────────────────────────────────
    sub = subparser_service.add_parser(
        "prov:upload", help="Bulk CSV upload of resources"
    ).add_subparsers(title="action", help="Action", dest="action")
    p = sub.add_parser("resources", help="Upload a CSV of instances/databases/containers")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)
    p.add_argument("--from", "-f", help="CSV file path", required=True)
    p.add_argument("--headers", help="Semicolon-separated header names")
    p.add_argument(
        "--no-headers",
        help="The CSV first line is data, not headers",
        action="store_true",
        default=False,
    )
    p.add_argument("--separator", help="CSV separator", default=";")
    p.add_argument("--encoding", help="CSV encoding", default="UTF-8")
    p.add_argument(
        "--merge",
        help="Merge mode for existing resources",
        choices=["keep", "insert", "update"],
        default="keep",
    )
    p.add_argument("--usage", "-U", help="Default usage name")
    p.add_argument("--budget", "-b", help="Default budget name")
    p.add_argument("--optimizer", "-o", help="Default optimizer name")
    p.add_argument(
        "--continue-on-error", help="Do not stop on row errors", action="store_true", default=False
    )


def _configure_vm(subparser_service, kind, label, *, os=False, software=False, engine=False):
    sub = subparser_service.add_parser(
        f"prov:{kind}", help=f"Provisioning {label.lower()} operations"
    ).add_subparsers(title="action", help="Action", dest="action")
    p = sub.add_parser("lookup", help=f"Find the cheapest {label.lower()} matching criteria")
    _vm_lookup_args(p, os=os, engine=engine)
    if software:
        p.add_argument("--software", help="Built-in software")
    for verb in ("create", "update"):
        p = sub.add_parser(verb, help=f"{verb.capitalize()} a {label.lower()}")
        _add_vm_args(p)
        if os:
            p.add_argument("--os", help="Operating system, e.g. LINUX")
        if software:
            p.add_argument("--software", help="Built-in software")
        if engine:
            p.add_argument("--engine", help="Database engine, e.g. MYSQL")
            p.add_argument("--edition", help="Database edition")
    _add_delete(sub, kind)


def _configure_function(subparser_service):
    sub = subparser_service.add_parser(
        "prov:function", help="Provisioning function operations"
    ).add_subparsers(title="action", help="Action", dest="action")
    p = sub.add_parser("lookup", help="Find the cheapest function matching criteria")
    _vm_lookup_args(p)
    p.add_argument("--runtime", help="Runtime name, e.g. Python")
    p.add_argument("--duration", help="Average duration (ms)", type=int)
    p.add_argument("--nb-requests", help="Monthly millions of executions", type=float)
    p.add_argument("--concurrency", help="Average concurrency", type=float)
    for verb in ("create", "update"):
        p = sub.add_parser(verb, help=f"{verb.capitalize()} a function")
        _add_vm_args(p)
        p.add_argument("--runtime", help="Runtime name, e.g. Python")
        p.add_argument("--duration", help="Average duration (ms)", type=int)
        p.add_argument("--nb-requests", help="Monthly millions of executions", type=float)
        p.add_argument("--concurrency", help="Average concurrency", type=float)
    _add_delete(sub, "function")


def _add_delete(sub, kind):
    article = "an" if kind[0] in "aeiou" else "a"
    p = sub.add_parser("delete", help=f"Delete {article} {kind} by identifier")
    p.add_argument("--id", "-i", help=f"{kind.capitalize()} identifier", type=int, required=True)
    p = sub.add_parser("delete-all", help=f"Delete every {kind} of a subscription")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)


def _add_scoped_list_delete(sub):
    p = sub.add_parser("list", help="List entries of a subscription")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)
    p.add_argument("--criteria", help="Search criteria")
    p = sub.add_parser("delete", help="Delete an entry by identifier")
    p.add_argument("--subscription", "-s", help="Subscription identifier", type=int, required=True)
    p.add_argument("--id", "-i", help="Entry identifier", type=int, required=True)


# ── dispatch ─────────────────────────────────────────────────────────────────
def execute_action(service, action, _, args):
    if service is None or not service.startswith("prov:"):
        return None
    kind = service.split(":", 1)[1]

    if kind == "quote":
        return _quote_action(action, args)
    if kind in ("instance", "container", "database", "function"):
        return _vm_action(kind, action, args)
    if kind == "storage":
        return _storage_action(action, args)
    if kind == "support":
        return _support_action(action, args)
    if kind in ("usage", "budget", "optimizer"):
        return _scoped_action(kind, action, args)
    if kind == "tag":
        return _tag_action(action, args)
    if kind == "catalog":
        return _catalog_action(action, args)
    if kind == "upload":
        return _upload_action(action, args)
    return None


def _quote_action(action, args):
    sub = args["subscription"]
    if action == "get":
        return ligoj.call_api("GET", f"{SERVICE}/{sub}")
    if action == "locations":
        return ligoj.call_api("GET", f"{SERVICE}/{sub}/location")
    if action == "refresh":
        utils.info(f"[ligoj] Refresh quote '{sub}' ...")
        return ligoj.call_api("PUT", f"{SERVICE}/{sub}/refresh")
    if action == "refresh-cost":
        utils.info(f"[ligoj] Refresh cost of quote '{sub}' ...")
        return ligoj.call_api("PUT", f"{SERVICE}/{sub}/refresh-cost")
    if action == "update":
        body = _body(
            args,
            ("name", "name"),
            ("description", "description"),
            ("location", "location"),
            ("usage", "usage"),
            ("budget", "budget"),
            ("optimizer", "optimizer"),
            ("license", "license"),
            ("processor", "processor"),
            ("physical", "physical"),
            ("ram_rate", "ramAdjustedRate"),
            ("reservation_mode", "reservationMode"),
        )
        utils.info(f"[ligoj] Update quote '{sub}' ...")
        return ligoj.call_api("PUT", f"{SERVICE}/{sub}", data=body)
    return None


def _vm_action(kind, action, args):
    if action == "lookup":
        sub = utils.not_none(args.get("subscription"), "subscription")
        params = _params(args, *_LOOKUP_PARAMS)
        if kind == "function":
            params |= _params(
                args,
                ("runtime", "runtime"),
                ("duration", "duration"),
                ("nb_requests", "nbRequests"),
                ("concurrency", "concurrency"),
            )
        if kind == "instance":
            params |= _params(args, ("software", "software"))
        utils.info(f"[ligoj] Lookup {kind} for subscription '{sub}' ...")
        return ligoj.call_api("GET", f"{SERVICE}/{sub}/{kind}-lookup", params=params)
    if action == "delete":
        utils.info(f"[ligoj] Delete {kind} '{args['id']}' ...")
        return ligoj.call_api("DELETE", f"{SERVICE}/{kind}/{args['id']}")
    if action == "delete-all":
        sub = args["subscription"]
        utils.info(f"[ligoj] Delete every {kind} of subscription '{sub}' ...")
        return ligoj.call_api("DELETE", f"{SERVICE}/{sub}/{kind}")
    if action in ("create", "update"):
        extra = (
            ("os", "os"),
            ("software", "software"),
            ("engine", "engine"),
            ("edition", "edition"),
            ("runtime", "runtime"),
            ("duration", "duration"),
            ("nb_requests", "nbRequests"),
            ("concurrency", "concurrency"),
        )
        body = _body(args, *_VM_BODY, *extra)
        if action == "create":
            utils.not_none(args.get("subscription"), "subscription")
            if body.get("price") is None:
                raise ValueError(
                    f"[ligoj] A price identifier (--price, from a lookup) is required to create a {kind}"
                )
        method = "POST" if action == "create" else "PUT"
        utils.info(f"[ligoj] {action.capitalize()} {kind} '{body.get('name', '')}' ...")
        return ligoj.call_api(method, f"{SERVICE}/{kind}", data=body)
    return None


def _storage_action(action, args):
    if action == "lookup":
        sub = utils.not_none(args.get("subscription"), "subscription")
        params = _params(
            args,
            ("size", "size"),
            ("latency", "latency"),
            ("optimized", "optimized"),
            ("location", "location"),
            ("instance", "instance"),
            ("database", "database"),
            ("container", "container"),
            ("function", "function"),
        )
        utils.info(f"[ligoj] Lookup storage for subscription '{sub}' ...")
        return ligoj.call_api("GET", f"{SERVICE}/{sub}/storage-lookup", params=params)
    if action == "delete":
        utils.info(f"[ligoj] Delete storage '{args['id']}' ...")
        return ligoj.call_api("DELETE", f"{SERVICE}/storage/{args['id']}")
    if action == "delete-all":
        sub = args["subscription"]
        utils.info(f"[ligoj] Delete every storage of subscription '{sub}' ...")
        return ligoj.call_api("DELETE", f"{SERVICE}/{sub}/storage")
    if action in ("create", "update"):
        body = _body(
            args,
            ("id", "id"),
            ("subscription", "subscription"),
            ("name", "name"),
            ("description", "description"),
            ("type", "type"),
            ("size", "size"),
            ("size_max", "sizeMax"),
            ("quantity", "quantity"),
            ("latency", "latency"),
            ("optimized", "optimized"),
            ("location", "location"),
            ("instance", "instance"),
            ("database", "database"),
            ("container", "container"),
            ("function", "function"),
        )
        if action == "create":
            utils.not_none(args.get("subscription"), "subscription")
        method = "POST" if action == "create" else "PUT"
        utils.info(f"[ligoj] {action.capitalize()} storage '{body.get('name', '')}' ...")
        return ligoj.call_api(method, f"{SERVICE}/storage", data=body)
    return None


def _support_action(action, args):
    if action == "lookup":
        sub = utils.not_none(args.get("subscription"), "subscription")
        params = _params(
            args,
            ("seats", "seats"),
            ("level", "level"),
            ("access_api", "access-api"),
            ("access_email", "access-email"),
            ("access_chat", "access-chat"),
            ("access_phone", "access-phone"),
        )
        utils.info(f"[ligoj] Lookup support for subscription '{sub}' ...")
        return ligoj.call_api("GET", f"{SERVICE}/{sub}/support-lookup", params=params)
    if action == "delete":
        utils.info(f"[ligoj] Delete support '{args['id']}' ...")
        return ligoj.call_api("DELETE", f"{SERVICE}/support/{args['id']}")
    if action == "delete-all":
        sub = args["subscription"]
        utils.info(f"[ligoj] Delete every support of subscription '{sub}' ...")
        return ligoj.call_api("DELETE", f"{SERVICE}/{sub}/support")
    if action in ("create", "update"):
        body = _body(
            args,
            ("id", "id"),
            ("subscription", "subscription"),
            ("name", "name"),
            ("type", "type"),
            ("seats", "seats"),
            ("level", "level"),
            ("access_api", "accessApi"),
            ("access_email", "accessEmail"),
            ("access_chat", "accessChat"),
            ("access_phone", "accessPhone"),
        )
        if action == "create":
            utils.not_none(args.get("subscription"), "subscription")
        method = "POST" if action == "create" else "PUT"
        utils.info(f"[ligoj] {action.capitalize()} support '{body.get('name', '')}' ...")
        return ligoj.call_api(method, f"{SERVICE}/support", data=body)
    return None


def _scoped_action(kind, action, args):
    sub = args["subscription"]
    if action == "list":
        params = {}
        if args.get("criteria"):
            params["search[value]"] = args["criteria"]
        return ligoj.call_api("GET", f"{SERVICE}/{sub}/{kind}", params=params)
    if action == "delete":
        utils.info(f"[ligoj] Delete {kind} '{args['id']}' ...")
        return ligoj.call_api("DELETE", f"{SERVICE}/{sub}/{kind}/{args['id']}")
    if action in ("create", "update"):
        body = _body(
            args,
            ("id", "id"),
            ("name", "name"),
            ("rate", "rate"),
            ("duration", "duration"),
            ("start", "start"),
            ("initial_cost", "initialCost"),
            ("mode", "mode"),
        )
        method = "POST" if action == "create" else "PUT"
        utils.info(f"[ligoj] {action.capitalize()} {kind} '{body.get('name', '')}' ...")
        return ligoj.call_api(method, f"{SERVICE}/{sub}/{kind}", data=body)
    return None


def _tag_action(action, args):
    sub = args["subscription"]
    if action == "delete":
        utils.info(f"[ligoj] Delete tag '{args['id']}' ...")
        return ligoj.call_api("DELETE", f"{SERVICE}/{sub}/tag/{args['id']}")
    if action in ("create", "update"):
        body = _body(
            args,
            ("id", "id"),
            ("name", "name"),
            ("value", "value"),
            ("type", "type"),
            ("resource", "resource"),
        )
        method = "POST" if action == "create" else "PUT"
        utils.info(f"[ligoj] {action.capitalize()} tag '{body.get('name', '')}' ...")
        return ligoj.call_api(method, f"{SERVICE}/{sub}/tag", data=body)
    return None


def _catalog_action(action, args):
    if action == "list":
        return ligoj.call_api("GET", f"{SERVICE}/catalog")
    node = args.get("node")
    if action == "status":
        return ligoj.call_api("GET", f"{SERVICE}/catalog/{node}")
    if action == "update":
        utils.info(f"[ligoj] Trigger catalog import for node '{node}' ...")
        return ligoj.call_api(
            "POST", f"{SERVICE}/catalog/{node}", params={"force": args.get("force", False)}
        )
    if action == "cancel":
        utils.info(f"[ligoj] Cancel catalog import for node '{node}' ...")
        return ligoj.call_api("DELETE", f"{SERVICE}/catalog/{node}")
    return None


def _upload_action(action, args):
    if action != "resources":
        return None
    sub = args["subscription"]
    path = utils.not_none(args.get("from"), "Import file")
    with open(path, encoding=args.get("encoding", "UTF-8")) as f:
        csv_content = f.read()
    fields = {
        "csv-file": csv_content,
        "headers-included": "false" if args.get("no_headers") else "true",
        "separator": args.get("separator", ";"),
        "encoding": args.get("encoding", "UTF-8"),
        "mergeUpload": (args.get("merge") or "keep").upper(),
        "errorContinue": "true" if args.get("continue_on_error") else "false",
    }
    for arg_key, form_key in (
        ("headers", "headers"),
        ("usage", "usage"),
        ("budget", "budget"),
        ("optimizer", "optimizer"),
    ):
        if args.get(arg_key) is not None:
            fields[form_key] = args[arg_key]
    files = {key: (None, value) for key, value in fields.items()}
    utils.info(f"[ligoj] Upload '{path}' to subscription '{sub}' ...")
    return ligoj.call_api("POST", f"{SERVICE}/{sub}/upload", files=files)


# ── body / param builders ────────────────────────────────────────────────────
def _body(args, *mapping):
    body = {}
    for arg_key, json_key in mapping:
        value = args.get(arg_key)
        if value is not None:
            body[json_key] = value
    raw = args.get("data")
    if raw:
        body.update(json.loads(raw))
    return body


def _params(args, *mapping):
    params = {}
    for arg_key, query_key in mapping:
        value = args.get(arg_key)
        if value is not None:
            params[query_key] = value
    return params
