#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# Demo setup for plugin-id-ldap: register the local LDAP node, make it the primary IAM, restart the
# context, create the reference container scopes and technical groups, then seed 10K demo people
# (random unique names, mail, 9-char uppercase uid, optional custom attribute) and 100 demo groups
# (each person in 0/1/2 groups: 50/40/10 %) straight into LDAP. Fixed seeds keep re-runs identical.
#
# The structural OUs (ou=people, ou=groups, ou=tools, ...) are NOT created here: they are seeded in
# LDAP by `dev init` from ligojcli/data/ldap/dev.ldif. Creating them again via the company API would fail
# with HTTP 406 {'code':'internal'} — ligoj's company create issues an LDAP add of `ou=<name>,<dn>`
# that the server's company-existence pre-check (companies-dn only) can't see, so for an OU that
# already exists (e.g. ou=groups from bitnami, ou=tools from the LDIF) the add raises NameAlreadyBound.
#
import base64
import os
import random
import re
import string
import tempfile

from unidecode import unidecode

from ligojcli.dev_demo import _common, _names, _subscribe
from ligojcli.plugins import dev, ligoj, utils
from ligojcli.plugins import id as id_plugin

ARTIFACT = "plugin-id-ldap"
NODE = "service:id:ldap:local"
NODE_NAME = "TestLocalCLI"

# Demo people: count ([dev] demo_ldap_users / DEMO_LDAP_USERS, 0 disables), spread over these OUs
# under people-internal-dn (created when missing; plugin-id-ldap discovers them as companies).
DEMO_USERS_DEFAULT = "10000"
DEPARTMENTS = tuple(f"department{index}" for index in range(1, 6))
USER_PASSWORD = "ligoj-user"
UID_ALPHABET = string.ascii_uppercase + string.digits
UID_LENGTH = 9
# Fixed seeds: a re-run regenerates the SAME people and the SAME group memberships, so ldapadd -c
# reports them as existing (idempotent). Memberships use their own RNG so adding/changing the group
# layout can never alter the generated people.
RNG_SEED = "ligoj-demo-people"
GROUPS_SEED = "ligoj-demo-groups"
# 100 demo groups (10 domains x 10 teams) under the Project scope; membership per user: 0 (50 %),
# 1 (40 %) or 2 (10 %) groups.
GROUP_DOMAINS = (
    "billing",
    "catalog",
    "crm",
    "data",
    "devops",
    "finance",
    "hr",
    "legal",
    "marketing",
    "security",
)
GROUP_TEAMS = (
    "core",
    "api",
    "ui",
    "ops",
    "qa",
    "analytics",
    "mobile",
    "infra",
    "support",
    "research",
)
MEMBERSHIP_ODDS = ((0.5, 0), (0.9, 1), (1.0, 2))  # cumulative probability -> number of groups
# UI display of the people (plugin-id configurations): the visual identifier shown instead of the uid
# is the node's first custom attribute (Matricule = uidFonctionnel by default), full name as display.
VISUAL_ID_LABEL = "Matricule"
USER_DISPLAY = "${firstName} ${lastName}"
CONFIG_SYSTEM = True  # same level as the sibling 'feature:iam:node:primary' setting


def run(args):
    root = _common.dev_value(args, "ldap_root", "LDAP_ROOT", "dc=sample,dc=com")
    port = _common.dev_value(args, "ldap_port", "LDAP_PORT", "1389")
    admin_user = _common.dev_value(args, "ldap_admin_user", "LDAP_ADMIN_USERNAME", "Manager")
    password = _common.dev_value(args, "ldap_admin_password", "LDAP_ADMIN_PASSWORD", None)

    # Start from the bundled node definition, then reflect the actual running LDAP configuration.
    params = utils.load_json_from_url_or_file_with_interpolation(
        _common.bundled_path("nodes", "ldap.local.json"), {}
    )
    _set_param(params, "service:id:ldap:url", f"ldap://localhost:{port}")
    _set_param(params, "service:id:ldap:user-dn", f"cn={admin_user},{root}")
    if password:
        _set_param(params, "service:id:ldap:password", password)
    else:
        utils.warn("[dev] No LDAP admin password in [dev]; using the bundled placeholder")

    ligoj.node_upsert(NODE, NODE_NAME, params, "ALL")
    ligoj.node_get_by_id(NODE, return_secured_parameters=True)
    ligoj.configuration_set("feature:iam:node:primary", NODE, system=True)
    _configure_user_display()

    wait = args.get("wait")
    ligoj.plugin_restart_context(60 if wait is None else wait)

    # OUs come from the seed LDIF (see module docstring); only scopes and groups are created here.
    _create_company_scopes(root)
    _create_group_scopes(root)
    _create_technical_groups()
    _seed_users(args, root, port, admin_user, password)


def _configure_user_display():
    """Set the plugin-id display configurations: full-name display and the custom-attribute visual id.

    'service:id:visual-id-name' points at the node's first custom attribute (customAttributes.<attr>),
    so the UI shows the Matricule (uidFonctionnel by default) instead of the technical uid; without a
    custom attribute on the node only the display format is set.
    """
    ligoj.configuration_set("service:id:user-display", USER_DISPLAY, system=CONFIG_SYSTEM)
    attributes, _ = _custom_attributes()
    if not attributes:
        utils.info(
            "[dev] ldap: no custom attribute on the node; visual id left to the default (uid)"
        )
        return
    ligoj.configuration_set(
        "service:id:visual-id-name", f"customAttributes.{attributes[0]}", system=CONFIG_SYSTEM
    )
    ligoj.configuration_set("service:id:visual-id-label", VISUAL_ID_LABEL, system=CONFIG_SYSTEM)


def subscribe(args, project):
    # The IAM subscription links a project to an existing LDAP group; create the group, then link it.
    _safe(f"group '{project}'", id_plugin.group_create, project, "Project")
    _subscribe.link(project, NODE, [{"parameter": "service:id:group", "text": project}])


def _safe(description, func, *args):
    # Best-effort step: keep configuring the rest of the demo if one item fails (already present,
    # a reserved name, or a server-side limitation). Idempotent re-runs.
    try:
        func(*args)
    except Exception as error:  # noqa: BLE001 - resilience is intended here
        utils.warn(f"[dev] {description}: {error}")


def _create_company_scopes(root):
    _safe(
        "company scope 'Unassigned'",
        id_plugin.container_scope_create,
        "Unassigned",
        "company",
        f"ou=people,{root}",
    )
    _safe(
        "company scope 'External'",
        id_plugin.container_scope_create,
        "External",
        "company",
        f"ou=external,ou=people,{root}",
    )
    _safe(
        "company scope 'Technical'",
        id_plugin.container_scope_create,
        "Technical",
        "company",
        f"ou=technical-users,ou=people,{root}",
    )


def _create_group_scopes(root):
    _safe(
        "group scope 'Unassigned'",
        id_plugin.container_scope_create,
        "Unassigned",
        "group",
        f"ou=groups,{root}",
    )
    _safe(
        "group scope 'Project'",
        id_plugin.container_scope_create,
        "Project",
        "group",
        f"ou=project,ou=groups,{root}",
    )
    _safe(
        "group scope 'Technical'",
        id_plugin.container_scope_create,
        "Technical",
        "group",
        f"ou=tools,ou=groups,{root}",
    )


def _create_technical_groups():
    _safe(
        "group 'jenkins-administrators'",
        id_plugin.group_create,
        "jenkins-administrators",
        "Technical",
    )
    _safe(
        "group 'nexus-administrators'", id_plugin.group_create, "nexus-administrators", "Technical"
    )
    _safe(
        "group 'nexus-administrators-paris'",
        id_plugin.group_create,
        "nexus-administrators-paris",
        "Technical",
        "nexus-administrators",
    )
    _safe(
        "group 'nexus-administrators-paris-8'",
        id_plugin.group_create,
        "nexus-administrators-paris-8",
        "Technical",
        "nexus-administrators-paris",
    )


def _set_param(params, key, value):
    for entry in params:
        if entry.get("parameter") == key:
            entry.pop("bool", None)
            entry["text"] = value
            return
    params.append({"parameter": key, "text": value})


# --------------------------------------------------------------------------- #
# Demo people (10K users with random names, straight into LDAP)
# --------------------------------------------------------------------------- #
def _seed_users(args, root, port, admin_user, password):
    """Populate the LDAP with demo people: unique random names, a mail, a 9-char uppercase uid.

    Written directly with ldapadd inside the OpenLDAP container (10K entries in seconds; the REST
    API would take minutes), then Ligoj's LDAP cache is invalidated so they show up right away.
    When the node declares 'people-custom-attributes', each user also carries every such attribute
    set to its mail — with the 'people-class-create' auxiliary objectClass that allows them.
    """
    count = int(
        _common.dev_value(args, "demo_ldap_users", "DEMO_LDAP_USERS", DEMO_USERS_DEFAULT) or 0
    )
    if count <= 0:
        utils.info("[dev] ldap: demo people disabled (demo_ldap_users=0)")
        return
    if not password:
        utils.warn("[dev] ldap: no admin password in [dev]; skipping the demo people")
        return
    domain = _common.dev_value(args, "demo_mail_domain", "DEMO_MAIL_DOMAIN", _domain_of(root))
    attributes, custom_class = _custom_attributes()
    people_dn = _node_parameters().get("service:id:ldap:people-internal-dn") or (
        f"ou=internal,ou=people,{root}"
    )
    extra = f"; custom attribute(s) {', '.join(attributes)} = mail" if attributes else ""
    utils.info(
        f"[dev] ldap: generating {count} demo people under {people_dn} (@{domain}, "
        f"uid = {UID_LENGTH} uppercase alphanumerics{extra}) ..."
    )
    users = generate_users(count, domain)
    container = dev._pod_container("openldap")
    admin_dn = f"cn={admin_user},{root}"
    # Two passes so the counts are exact for people: the department OUs first, then the users.
    _ldap_add(container, port, admin_dn, password, build_ou_ldif(people_dn))
    code, added, existed, output = _ldap_add(
        container,
        port,
        admin_dn,
        password,
        build_users_ldif(users, people_dn, attributes, custom_class),
    )
    if code not in (0, 68):  # 68 = LDAP_ALREADY_EXISTS, what ldapadd -c returns on a re-run
        utils.warn(f"[dev] ldap: ldapadd returned {code}: {output.strip()[-300:]}")
        return
    utils.info(
        f"[dev] ldap: demo people ensured — {added} added, {existed} already present "
        f"(password '{USER_PASSWORD}' for all)"
    )
    _seed_groups(users, people_dn, root, container, port, admin_dn, password)
    _safe("cache 'id-ldap-data' invalidation", ligoj.cache_invalidate, "id-ldap-data")


def _seed_groups(users, people_dn, root, container, port, admin_dn, password):
    """Create the 100 demo groups with their (deterministic) members under the Project scope."""
    groups_dn = _node_parameters().get("service:id:ldap:groups-dn") or f"ou=groups,{root}"
    project_dn = f"ou=project,{groups_dn}"
    groups = assign_groups(users)
    members = sum(len(dns) for dns in groups.values())
    utils.info(
        f"[dev] ldap: ensuring {len(groups)} demo groups under {project_dn} "
        f"({members} memberships: 50 % of people in no group, 40 % in one, 10 % in two) ..."
    )
    code, added, existed, output = _ldap_add(
        container, port, admin_dn, password, build_groups_ldif(groups, project_dn, people_dn)
    )
    if code not in (0, 68):
        utils.warn(f"[dev] ldap: groups ldapadd returned {code}: {output.strip()[-300:]}")
        return
    utils.info(f"[dev] ldap: demo groups ensured — {added} added, {existed} already present")


def generate_users(count, domain, seed=RNG_SEED):
    """`count` demo people with distinct (first, last) names, distinct mails and distinct uids."""
    rng = random.Random(seed)
    pairs = [(first, last) for first in _names.FIRST_NAMES for last in _names.LAST_NAMES]
    if count > len(pairs):
        utils.warn(f"[dev] ldap: only {len(pairs)} distinct names available; capping {count}")
        count = len(pairs)
    rng.shuffle(pairs)
    users, mails, uids = [], set(), set()
    for first, last in pairs:
        mail = f"{_slug(first)}.{_slug(last)}@{domain}"
        if mail in mails:  # two spellings collapsing to one slug (e.g. Zoé / Zoe)
            continue
        while True:
            uid = "".join(rng.choices(UID_ALPHABET, k=UID_LENGTH))
            if uid not in uids:
                break
        mails.add(mail)
        uids.add(uid)
        users.append(
            {
                "uid": uid,
                "first": first,
                "last": last,
                "mail": mail,
                "department": DEPARTMENTS[len(users) % len(DEPARTMENTS)],
            }
        )
        if len(users) == count:
            break
    return users


def group_names():
    """The 100 demo group names, '<domain>-<team>'."""
    return [f"{domain}-{team}" for domain in GROUP_DOMAINS for team in GROUP_TEAMS]


def assign_groups(users, seed=GROUPS_SEED):
    """{group name: [users]} — each user in 0/1/2 groups (50/40/10 %), deterministic; no empty group.

    groupOfUniqueNames requires at least one uniqueMember, so a group left empty by the draw gets
    one deterministic member.
    """
    rng = random.Random(seed)
    names = group_names()
    groups = {name: [] for name in names}
    for user in users:
        draw = rng.random()
        count = next(count for threshold, count in MEMBERSHIP_ODDS if draw < threshold)
        for name in rng.sample(names, count):
            groups[name].append(user)
    for index, name in enumerate(names):
        if not groups[name]:
            groups[name].append(users[index % len(users)])
    return groups


def build_groups_ldif(groups, project_dn, people_dn):
    """The LDIF adding the demo groups (groupOfUniqueNames) with their members' DNs."""
    blocks = []
    for name, members in groups.items():
        lines = [f"dn: cn={name},{project_dn}", "objectClass: groupOfUniqueNames", f"cn: {name}"]
        lines += [
            f"uniqueMember: uid={user['uid']},ou={user['department']},{people_dn}"
            for user in members
        ]
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)


def build_ou_ldif(people_dn):
    """The LDIF adding the department OUs (each one idempotent under ldapadd -c)."""
    return "\n".join(
        f"dn: ou={department},{people_dn}\nobjectClass: organizationalUnit\nou: {department}\n"
        for department in DEPARTMENTS
    )


def build_users_ldif(users, people_dn, attributes=(), custom_class=None):
    """The LDIF adding every demo user (with the custom attribute(s) and their objectClass)."""
    blocks = []
    for user in users:
        lines = [
            f"dn: uid={user['uid']},ou={user['department']},{people_dn}",
            "objectClass: inetOrgPerson",
        ]
        if custom_class and attributes:
            lines.append(f"objectClass: {custom_class}")
        lines += [
            _ldif_attr("uid", user["uid"]),
            _ldif_attr("cn", f"{user['first']} {user['last']}"),
            _ldif_attr("sn", user["last"]),
            _ldif_attr("givenName", user["first"]),
            _ldif_attr("mail", user["mail"]),
            _ldif_attr("userPassword", USER_PASSWORD),
        ]
        lines += [_ldif_attr(attribute, user["mail"]) for attribute in attributes]
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)


def _ldif_attr(name, value):
    """An LDIF attribute line; non-ASCII (accented names) or unsafe-leading values go base64."""
    safe = value.isascii() and value == value.strip() and not value.startswith((":", "<"))
    if safe:
        return f"{name}: {value}"
    return f"{name}:: {base64.b64encode(value.encode('utf-8')).decode('ascii')}"


def _slug(text):
    """ASCII, lowercase, dash-separated e-mail local part piece: 'Nguyễn' -> 'nguyen'."""
    return re.sub(r"[^a-z0-9]+", "-", unidecode(text).lower()).strip("-")


def _domain_of(root):
    """'dc=sample,dc=com' -> 'sample.com' (the mail domain matching the LDAP suffix)."""
    parts = [
        piece.split("=", 1)[1]
        for piece in root.split(",")
        if piece.strip().lower().startswith("dc=")
    ]
    return ".".join(parts) if parts else "sample.com"


def _node_parameters():
    """{parameter id: value} of the demo LDAP node, live from Ligoj, else the bundled definition."""
    try:
        node = ligoj.node_get_by_id(NODE, "ALL", "map") or {}
        params = node.get("parameters") or {}
        if isinstance(params, list):  # tolerate the list shape too
            params = {p.get("parameter"): p.get("text") for p in params if p.get("parameter")}
        if params:
            return params
    except Exception as error:  # noqa: BLE001 - the bundled node is a faithful fallback
        utils.debug(
            f"[dev] ldap: live node parameters unavailable ({error}); using the bundled ones"
        )
    return _common.load_node("ldap.local.json")


def _custom_attributes():
    """(custom attribute names, objectClass carrying them) from the node, or ([], None)."""
    params = _node_parameters()
    raw = params.get("service:id:ldap:people-custom-attributes") or ""
    attributes = [attribute.strip() for attribute in raw.split(",") if attribute.strip()]
    custom_class = (params.get("service:id:ldap:people-class-create") or "").strip() or None
    if attributes and not custom_class:
        utils.warn(
            "[dev] ldap: 'people-custom-attributes' set but no 'people-class-create' objectClass; "
            "the custom attribute(s) cannot be written on the demo people — skipped"
        )
        return [], None
    return attributes, custom_class


def _ldap_add(container, port, admin_dn, password, ldif):
    """Bulk-add an LDIF text inside the OpenLDAP container (ldapadd -c).

    Returns (exit code, entries added, entries already existing, raw output).
    """
    with tempfile.NamedTemporaryFile("w", suffix=".ldif", delete=False, encoding="utf-8") as handle:
        handle.write(ldif)
        path = handle.name
    target = "/tmp/ligoj-demo.ldif"
    try:
        dev._podman("cp", path, f"{container}:{target}", check=False)
    finally:
        os.remove(path)
    result = dev._podman(
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
        target,
        check=False,
    )
    output = (result.stdout or "") + (result.stderr or "")
    attempted = len(re.findall(r"^adding new entry", output, re.MULTILINE))
    existed = output.count("Already exists")
    return result.returncode, max(0, attempted - existed), existed, output
