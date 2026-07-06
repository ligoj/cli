#
# Licensed under MIT (https://github.com/ligoj/ligoj/blob/master/LICENSE)
#
# `dev backup` / `dev restore` — snapshot and restore the database rows owned by a Ligoj service,
# using the PostgreSQL client tools (psql / pg_dump). Only `service:prov` is supported for now.
#
# What a `service:prov` backup captures:
#   * every `ligoj_prov_*` table (the whole catalog + quotes) — dumped in bulk with pg_dump, since the
#     price tables are huge (~1.8M rows) and their content is restored verbatim (no id patching);
#   * the cross-referenced core rows, so the quotes stay valid: the `ligoj_subscription` rows on prov
#     nodes (referenced by `ligoj_prov_quote.subscription`), the `ligoj_node` rows of those (and the
#     provider nodes the catalog points at), the `ligoj_parameter_value` rows of those nodes /
#     subscriptions, and the `ligoj_project` rows behind the subscriptions.
#
# Restore is an id-aware reload (a target ligoj DB already has its own projects / nodes / parameters):
#   * projects are matched by pkey or name and *reused* (their id is remapped), else inserted;
#   * nodes are inserted only when missing (string ids, no remap);
#   * a node's parameter values are dropped then re-inserted; subscriptions are inserted fresh (all
#     prior prov subscriptions were deleted first) with their project remapped;
#   * the `ligoj_prov_*` tables are emptied and bulk-reloaded verbatim, then sequences are bumped.
#
import gzip
import json
import os
import shutil
import subprocess
import time
from datetime import datetime

from ligojcli.plugins import utils

# --------------------------------------------------------------------------- #
# Supported services
# --------------------------------------------------------------------------- #
# Each spec drives the SQL predicates below. Adding a service = adding a spec (and, if its layout
# differs from prov, generalizing restore()).
_PROV = {
    "service": "service:prov",
    "short": "prov",
    # All bulk tables of the service (dumped/reloaded verbatim, ids preserved).
    "table_glob": "ligoj_prov%",
    "pg_dump_pattern": "ligoj_prov*",
    # Cross-referenced core rows.
    "subscription_where": "node LIKE 'service:prov:%'",
    "node_where": "id LIKE 'service:prov%'",
    "instance_node_where": "id LIKE 'service:prov:%:%'",
    "parameter_value_where": (
        "node LIKE 'service:prov:%:%' "
        "OR subscription IN (SELECT id FROM ligoj_subscription WHERE node LIKE 'service:prov:%')"
    ),
    # Status-event log rows on the prov subscriptions / instance nodes: transient (never backed up),
    # deleted on restore so the subscriptions / nodes they reference can be removed.
    "event_where": (
        "node LIKE 'service:prov:%:%' "
        "OR subscription IN (SELECT id FROM ligoj_subscription WHERE node LIKE 'service:prov:%')"
    ),
}
SUPPORTED = {_PROV["service"]: _PROV}

# Core tables reloaded with id remapping (order matters: projects/nodes -> subscriptions -> values).
_CORE_TABLES = ["ligoj_project", "ligoj_node", "ligoj_subscription", "ligoj_parameter_value"]


# --------------------------------------------------------------------------- #
# Service argument -> spec
# --------------------------------------------------------------------------- #
def _resolve_specs(service):
    """Return the list of specs to act on ('prov' / 'service:prov' -> the prov spec; None -> all)."""
    if not service:
        return list(SUPPORTED.values())
    key = service if service.startswith("service:") else f"service:{service}"
    spec = SUPPORTED.get(key)
    if spec is None:
        raise ValueError(
            f"[backup] Unsupported service '{service}'. Supported: {', '.join(SUPPORTED)}"
        )
    return [spec]


# --------------------------------------------------------------------------- #
# Database connection (from a credentials section: db_host/db_port/db_name/db_user/db_password)
# --------------------------------------------------------------------------- #
def _db(section):
    def get(key, default=None):
        return (
            utils.cleanup_ini_value(utils.ini_credentials.get(section, key, fallback=None))
            or default
        )

    if not utils.ini_credentials.has_section(section):
        raise ValueError(f"[backup] No '[{section}]' section in ~/.ligoj/credentials for the DB")
    db = {
        "host": get("db_host", "localhost"),
        "port": str(get("db_port", "5432")),
        "name": get("db_name", "ligoj"),
        "user": get("db_user", "ligoj"),
        "password": get("db_password", ""),
        "section": section,
    }
    return db


def _db_section(default):
    """The active --profile section when it carries DB params, else the command default."""
    profile = utils.ini_profile
    if (
        profile
        and utils.ini_credentials.has_section(profile)
        and utils.ini_credentials.get(profile, "db_host", fallback=None)
    ):
        return profile
    return default


def _env(db):
    return dict(os.environ, PGPASSWORD=db["password"] or "")


def _conn_args(db):
    return ["-h", db["host"], "-p", db["port"], "-U", db["user"], "-d", db["name"]]


def _tool(name):
    path = shutil.which(name)
    if path is None:
        raise ValueError(
            f"[backup] '{name}' not found on PATH — install the PostgreSQL client tools "
            "(e.g. 'brew install libpq' and add its bin to PATH)"
        )
    return path


def _psql_query(db, sql):
    """Run a single query, return stdout stripped ('-At': unaligned, tuples-only)."""
    result = subprocess.run(
        [_tool("psql"), *_conn_args(db), "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
        env=_env(db),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError(f"[backup] psql query failed: {(result.stderr or '').strip()[:400]}")
    return result.stdout.strip()


def _psql_script(db, path, single_transaction=False, progress_prefix=None):
    cmd = [_tool("psql"), *_conn_args(db), "-v", "ON_ERROR_STOP=1"]
    if single_transaction:
        cmd.append("--single-transaction")
    cmd += ["-f", path]
    if progress_prefix is None:
        rc = subprocess.run(cmd, env=_env(db), text=True).returncode
    else:
        # Stream but forward only the phase-progress lines (prefixed with progress_prefix); the noisy
        # per-statement tags on stdout are dropped, while psql errors on the inherited stderr show.
        proc = subprocess.Popen(cmd, env=_env(db), text=True, stdout=subprocess.PIPE)
        for line in proc.stdout:
            if progress_prefix in line:
                print(line.rstrip())
        proc.stdout.close()
        rc = proc.wait()
    if rc != 0:
        raise ValueError("[backup] psql script failed")


# --------------------------------------------------------------------------- #
# Backup layout
# --------------------------------------------------------------------------- #
def _backup_root():
    return os.path.join(utils.user_home, ".ligoj", "backup")


def _prov_tables(db, spec):
    rows = _psql_query(
        db,
        f"SELECT tablename FROM pg_tables WHERE tablename LIKE '{spec['table_glob']}' "
        "ORDER BY tablename",
    )
    return [t for t in rows.splitlines() if t]


def _count(db, table, where=None):
    sql = f"SELECT count(*) FROM {table}" + (f" WHERE {where}" if where else "")
    try:
        return int(_psql_query(db, sql) or 0)
    except ValueError:
        return 0


# --------------------------------------------------------------------------- #
# Backup
# --------------------------------------------------------------------------- #
def backup(args):
    db = _db(_db_section("dev"))
    specs = _resolve_specs(args.get("backup_service"))
    results = {}
    for spec in specs:
        results[spec["service"]] = _backup_one(db, spec)
    return results or False


def _backup_one(db, spec):
    started = time.time()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_id = f"{spec['short']}-{stamp}"
    out_dir = os.path.join(_backup_root(), backup_id)
    core_dir = os.path.join(out_dir, "core")
    os.makedirs(core_dir, exist_ok=True)
    utils.info(f"[backup] === {spec['service']} -> {backup_id} ===")

    stats = {}

    # 1. Core rows (small) -> CSV, kept for id-aware restore.
    core_where = {
        "ligoj_project": (
            "id IN (SELECT project FROM ligoj_subscription WHERE "
            + spec["subscription_where"]
            + ")"
        ),
        "ligoj_node": spec["node_where"],
        "ligoj_subscription": spec["subscription_where"],
        "ligoj_parameter_value": spec["parameter_value_where"],
    }
    for table in _CORE_TABLES:
        where = core_where[table]
        csv_path = os.path.join(core_dir, f"{table}.csv")
        step = time.time()
        _psql_query(
            db,
            f"\\copy (SELECT * FROM {table} WHERE {where}) TO '{csv_path}' CSV HEADER",
        )
        stats[table] = _count(db, table, where)
        utils.info(f"[backup]   {table}: {stats[table]} row(s) ({_dur(step)})")

    # 2. Bulk prov tables -> a single gzipped pg_dump (data only, verbatim on restore).
    prov_tables = _prov_tables(db, spec)
    for table in prov_tables:
        stats[table] = _count(db, table)
    total_prov = sum(stats[t] for t in prov_tables)
    dump_path = os.path.join(out_dir, "prov-data.sql.gz")
    utils.info(
        f"[backup]   {len(prov_tables)} prov table(s), {total_prov} row(s) -> pg_dump (bulk) ..."
    )
    step = time.time()
    _pg_dump(db, spec, dump_path)
    size = os.path.getsize(dump_path)
    utils.info(f"[backup]   prov-data.sql.gz: {_human_size(size)} ({_dur(step)})")

    duration = time.time() - started
    meta = {
        "id": backup_id,
        "service": spec["service"],
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_db": f"{db['user']}@{db['host']}:{db['port']}/{db['name']}",
        "core_tables": {t: stats[t] for t in _CORE_TABLES},
        "prov_tables": {t: stats[t] for t in prov_tables},
        "prov_rows_total": total_prov,
        "prov_dump_bytes": size,
        "duration_seconds": round(duration, 2),
    }
    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)

    _print_backup_summary(meta, out_dir)
    return meta


def _pg_dump(db, spec, gz_path):
    cmd = [
        _tool("pg_dump"),
        *_conn_args(db),
        "--data-only",
        "--no-owner",
        "--no-privileges",
        "--format=plain",
        "-t",
        spec["pg_dump_pattern"],
    ]
    with gzip.open(gz_path, "wb") as gz:
        proc = subprocess.Popen(cmd, env=_env(db), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        shutil.copyfileobj(proc.stdout, gz)
        proc.stdout.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        if proc.wait() != 0:
            raise ValueError(f"[backup] pg_dump failed: {err.strip()[:400]}")


def _print_backup_summary(meta, out_dir):
    print()
    utils.info(f"[backup] Backup '{meta['id']}' complete in {_human_dur(meta['duration_seconds'])}")
    core = meta["core_tables"]
    utils.info(
        "[backup]   core: " + ", ".join(f"{t.replace('ligoj_', '')}={n}" for t, n in core.items())
    )
    utils.info(
        f"[backup]   prov: {len(meta['prov_tables'])} table(s), {meta['prov_rows_total']} row(s), "
        f"dump {_human_size(meta['prov_dump_bytes'])}"
    )
    utils.info(f"[backup]   stored in {out_dir}")
    utils.info(f"[backup]   restore with: ligoj dev restore {meta['service']} {meta['id']}")


# --------------------------------------------------------------------------- #
# Restore
# --------------------------------------------------------------------------- #
def restore(args):
    db = _db(_db_section("restore"))
    specs = _resolve_specs(args.get("restore_service"))
    if len(specs) != 1:
        # Restore is one service + one backup at a time (a backup id designates a single service).
        raise ValueError("[restore] Specify a single service to restore, e.g. 'service:prov'")
    spec = specs[0]

    backup_id = args.get("restore_backup_id") or _choose_backup(spec)
    if not backup_id:
        return False
    out_dir = os.path.join(_backup_root(), backup_id)
    meta_path = os.path.join(out_dir, "metadata.json")
    if not os.path.isfile(meta_path):
        raise ValueError(f"[restore] Unknown backup id '{backup_id}' (no {meta_path})")
    with open(meta_path, encoding="utf-8") as handle:
        meta = json.load(handle)
    if meta.get("service") != spec["service"]:
        raise ValueError(
            f"[restore] Backup '{backup_id}' is for {meta.get('service')}, not {spec['service']}"
        )

    utils.info(
        f"[restore] === {spec['service']} <- {backup_id} into "
        f"{db['user']}@{db['host']}:{db['port']}/{db['name']} ==="
    )
    _preflight(db, spec)
    before = {t: _count(db, t, w) for t, w in _restore_scope(spec).items()}

    started = time.time()
    sql_path = _build_restore_sql(db, spec, out_dir)
    utils.info(
        "[restore] Applying (delete prov data, reload core with id remap, bulk-load prov) ..."
    )
    try:
        _psql_script(db, sql_path, single_transaction=True, progress_prefix=">>")
    finally:
        # The bulk prov dump is gunzipped next to the archive for '\i'; it can be ~5x the .gz, so
        # drop the scratch files (the compressed dump stays for the next restore).
        for scratch in ("prov-data.sql", "restore.generated.sql"):
            path = os.path.join(out_dir, scratch)
            if os.path.exists(path):
                os.remove(path)

    after = {t: _count(db, t, w) for t, w in _restore_scope(spec).items()}
    _print_restore_summary(meta, before, after, time.time() - started)
    return meta


def _restore_scope(spec):
    """Row scopes shown before/after restore (prov-owned rows in the core tables + prov quotes)."""
    return {
        "ligoj_subscription": spec["subscription_where"],
        "ligoj_node": spec["instance_node_where"],
        "ligoj_prov_quote": None,
    }


def _preflight(db, spec):
    """Fail early with a clear message if the target is not a ligoj DB with the prov plugin."""
    has_tables = _psql_query(
        db,
        "SELECT count(*) FROM information_schema.tables "
        f"WHERE table_name LIKE '{spec['table_glob']}'",
    )
    if has_tables == "0":
        raise ValueError(
            f"[restore] Target DB has no '{spec['table_glob']}' tables — it is not a ligoj database "
            "with the provisioning plugin installed. Point --profile/[section] at a real ligoj DB."
        )


def _timed_phase(n, title, statements):
    """Announce + time one restore phase as a whole (not each statement).

    Emits a start line, captures clock_timestamp() around the statements, and emits a done line with
    the elapsed seconds. Both progress lines are prefixed '>>' so _psql_script forwards only them,
    hiding the per-statement ALTER/DELETE/COPY tags.
    """
    var = f"_p{n}"
    return [
        f"\\echo '>> [{n}/5] {title} ...'",
        f"SELECT extract(epoch FROM clock_timestamp()) AS {var} \\gset",
        *statements,
        f"SELECT '>> [{n}/5] done (' || "
        f"to_char((extract(epoch FROM clock_timestamp()) - :{var})::numeric, 'FM999990.0') || 's)' "
        f"AS _d{n} \\gset",
        f"\\echo :_d{n}",
    ]


def _csv_header_cols(path):
    """The column names of a core CSV (its header row); identifiers only, so a plain split is safe."""
    with open(path, encoding="utf-8") as handle:
        return [c.strip() for c in handle.readline().strip().split(",")]


def _core_copy(db, tmp, table, csv_path):
    r"""A '\copy' that maps CSV columns to the temp table *by name*, not by position.

    The backup may come from a different Postgres/Ligoj version whose table has the same columns in a
    different order (or a superset/subset). Naming the columns explicitly — intersected with the
    target table so an obsolete backup column is skipped rather than erroring — keeps each value in
    its own column, instead of the positional load shifting e.g. a username into a timestamp column.
    """
    target = set(_columns(db, table))
    cols = [c for c in _csv_header_cols(csv_path) if c in target]
    return f"\\copy {tmp} ({', '.join(cols)}) FROM '{csv_path}' CSV HEADER"


def _prov_table_columns(db):
    """{prov table name -> set of its column names} in the target, for schema-adapting the bulk load."""
    rows = _psql_query(
        db,
        "SELECT table_name || E'\\t' || column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name LIKE 'ligoj_prov%' "
        "ORDER BY table_name, ordinal_position",
    )
    cols = {}
    for line in rows.splitlines():
        if "\t" in line:
            table, col = line.split("\t", 1)
            cols.setdefault(table, set()).add(col)
    return cols


def _parse_copy(line):
    r"""Split a pg_dump 'COPY public.<t> (<cols>) FROM stdin;' into (qualified name, table, [cols])."""
    body = line.strip()
    lparen, rparen = body.index("("), body.rindex(")")
    qualified = body[len("COPY ") : lparen].strip()
    cols = [c.strip().strip('"') for c in body[lparen + 1 : rparen].split(",")]
    return qualified, qualified.split(".")[-1].strip('"'), cols


def _extract_prov_sql(db, gz_path, prov_sql):
    r"""Gunzip the bulk dump for '\i', adapting it to the target schema; return a list of adaptations.

    Two mismatches are handled so an older / differently-versioned target still loads:
      * pg_dump's header SETs — the newer client adds `SET transaction_timeout`, unknown to an older
        server and (under ON_ERROR_STOP) fatal — are dropped from the preamble;
      * each `COPY t (cols)` block is aligned to the target's actual columns: a column the target
        lacks (e.g. a field a newer prov plugin added) is removed from the header *and* every data
        row, and a whole table the target doesn't have is skipped. Columns the target has but the
        backup lacks simply keep their default. Non-matching blocks stream through untouched.
    """
    target = _prov_table_columns(db)
    notes = []
    seen_copy = False
    drop_idx = None  # indices to strip from each data row while inside an adapted COPY block
    skipping = False  # inside a COPY block for a table the target does not have
    with (
        gzip.open(gz_path, "rt", encoding="utf-8", errors="surrogateescape") as src,
        open(prov_sql, "w", encoding="utf-8", errors="surrogateescape") as dst,
    ):
        for line in src:
            if drop_idx is not None:
                if line.rstrip("\r\n") == "\\.":
                    drop_idx = None
                    dst.write(line)
                else:
                    fields = line.rstrip("\n").split("\t")
                    dst.write(
                        "\t".join(f for i, f in enumerate(fields) if i not in drop_idx) + "\n"
                    )
                continue
            if skipping:
                skipping = line.rstrip("\r\n") != "\\."
                continue
            if line.startswith("COPY "):
                seen_copy = True
                qualified, table, cols = _parse_copy(line)
                tcols = target.get(table)
                if tcols is None:
                    skipping = True
                    notes.append(f"skipped table {table} (absent in target)")
                    continue
                extra = [c for c in cols if c not in tcols]
                if extra:
                    drop_idx = {i for i, c in enumerate(cols) if c not in tcols}
                    # Re-quote every kept column: _parse_copy stripped pg_dump's quoting, and a kept
                    # name may be a reserved word (e.g. "end", "limit") that is invalid unquoted.
                    keep = [f'"{c}"' for c in cols if c in tcols]
                    notes.append(
                        f"{table}: dropped column(s) {', '.join(extra)} (absent in target)"
                    )
                    dst.write(f"COPY {qualified} ({', '.join(keep)}) FROM stdin;\n")
                    continue
                dst.write(line)
                continue
            if not seen_copy and line.startswith("SET ") and "timeout" in line:
                continue
            dst.write(line)
    return notes


def _build_restore_sql(db, spec, out_dir):
    core_dir = os.path.join(out_dir, "core")
    # Uncompress the bulk prov dump next to it for '\i' (psql cannot include a .gz directly).
    gz_path = os.path.join(out_dir, "prov-data.sql.gz")
    prov_sql = os.path.join(out_dir, "prov-data.sql")
    for note in _extract_prov_sql(db, gz_path, prov_sql):
        utils.warn(f"[restore] schema-adapt: {note} — its data is dropped from this restore")

    prov_tables = _prov_tables(db, spec)
    truncate = ", ".join(prov_tables)
    project_cols = _columns(db, "ligoj_project")
    non_id = [c for c in project_cols if c != "id"]
    proj_select = ", ".join(f"t.{c}" for c in non_id)
    proj_insert_cols = ", ".join([*non_id, "id"])
    seq_fix = _sequence_fixups(db, spec, prov_tables)

    # The prov tables have foreign keys among themselves that form a cycle (quote <-> optimizer), so
    # no single COPY order satisfies them and — without superuser to disable triggers — the bulk load
    # would fail. Drop every prov FK before the load and re-add it NOT VALID afterwards: instant (no
    # rescan of the ~1.8M-row tables) and safe, since the backup data is already internally consistent.
    fks = _prov_fk_constraints(db)
    drop_fks = [f"ALTER TABLE {t} DROP CONSTRAINT IF EXISTS {n};" for t, n, _ in fks]
    add_fks = [f"ALTER TABLE {t} ADD CONSTRAINT {n} {d} NOT VALID;" for t, n, d in fks]

    lines = [
        "\\set ON_ERROR_STOP on",
        "\\set QUIET on",
        *_timed_phase(
            1,
            f"Delete current {spec['service']} data (drop FKs)",
            [
                *drop_fks,
                f"TRUNCATE {truncate} RESTART IDENTITY;",
                "DELETE FROM ligoj_event WHERE " + spec["event_where"] + ";",
                "DELETE FROM ligoj_parameter_value WHERE " + spec["parameter_value_where"] + ";",
                "DELETE FROM ligoj_subscription WHERE " + spec["subscription_where"] + ";",
                "DELETE FROM ligoj_node WHERE " + spec["instance_node_where"] + ";",
            ],
        ),
        *_timed_phase(
            2,
            "Stage backup core rows",
            [
                "CREATE TEMP TABLE tmp_project (LIKE ligoj_project);",
                _core_copy(db, "tmp_project", "ligoj_project", f"{core_dir}/ligoj_project.csv"),
                "CREATE TEMP TABLE tmp_node (LIKE ligoj_node);",
                _core_copy(db, "tmp_node", "ligoj_node", f"{core_dir}/ligoj_node.csv"),
                "CREATE TEMP TABLE tmp_subscription (LIKE ligoj_subscription);",
                _core_copy(
                    db,
                    "tmp_subscription",
                    "ligoj_subscription",
                    f"{core_dir}/ligoj_subscription.csv",
                ),
                "CREATE TEMP TABLE tmp_pv (LIKE ligoj_parameter_value);",
                _core_copy(
                    db, "tmp_pv", "ligoj_parameter_value", f"{core_dir}/ligoj_parameter_value.csv"
                ),
            ],
        ),
        *_timed_phase(
            3,
            "Reload projects (reuse by pkey/name) + nodes",
            [
                "CREATE TEMP TABLE map_project (old_id int, new_id int, is_new boolean);",
                # Reuse an existing project matched by pkey (preferred) or name.
                "INSERT INTO map_project SELECT t.id, e.id, false FROM tmp_project t "
                "JOIN LATERAL (SELECT id FROM ligoj_project e WHERE e.pkey = t.pkey OR e.name = t.name "
                "ORDER BY (e.pkey = t.pkey) DESC, e.id LIMIT 1) e ON true;",
                # The rest are new -> allocate ids from the sequence.
                "INSERT INTO map_project SELECT id, nextval('ligoj_project_seq'), true FROM tmp_project "
                "WHERE id NOT IN (SELECT old_id FROM map_project);",
                f"INSERT INTO ligoj_project ({proj_insert_cols}) SELECT {proj_select}, m.new_id "
                "FROM tmp_project t JOIN map_project m ON m.old_id = t.id WHERE m.is_new;",
                # Nodes: string ids, insert only the missing ones (parents first via id length).
                "INSERT INTO ligoj_node SELECT * FROM tmp_node t "
                "WHERE NOT EXISTS (SELECT 1 FROM ligoj_node n WHERE n.id = t.id) "
                "ORDER BY char_length(t.id);",
            ],
        ),
        *_timed_phase(
            4,
            "Reload subscriptions (fresh ids) + parameter values",
            [
                # Give every restored subscription a fresh id from the sequence: the backup's ids may
                # already belong to unrelated (non-prov) subscriptions in the target. Referrers are
                # remapped too — parameter values here, prov quotes after the bulk load.
                "CREATE TEMP TABLE map_subscription (old_id int, new_id int);",
                "INSERT INTO map_subscription "
                "SELECT id, nextval('ligoj_subscription_seq') FROM tmp_subscription;",
                "UPDATE tmp_subscription t SET project = m.new_id FROM map_project m "
                "WHERE m.old_id = t.project;",
                "UPDATE tmp_subscription t SET id = m.new_id FROM map_subscription m "
                "WHERE m.old_id = t.id;",
                "INSERT INTO ligoj_subscription SELECT * FROM tmp_subscription;",
                # Parameter values: point subscription-scoped rows at the remapped subscription, drop
                # the node-scoped values we replace, then insert everything with fresh ids.
                "UPDATE tmp_pv t SET subscription = m.new_id FROM map_subscription m "
                "WHERE m.old_id = t.subscription;",
                "DELETE FROM ligoj_parameter_value pv USING tmp_pv t "
                "WHERE pv.node = t.node AND pv.parameter = t.parameter AND t.node IS NOT NULL;",
                "UPDATE tmp_pv SET id = nextval('ligoj_parameter_value_seq');",
                "INSERT INTO ligoj_parameter_value SELECT * FROM tmp_pv;",
            ],
        ),
        *_timed_phase(
            5,
            "Bulk-load prov tables + re-add FKs + sequences",
            [
                f"\\i {prov_sql}",
                "RESET search_path;",
                # The bulk load carries the backup's original subscription ids; repoint the quotes at
                # the remapped subscriptions before the FK is re-added.
                "UPDATE ligoj_prov_quote q SET subscription = m.new_id "
                "FROM map_subscription m WHERE q.subscription = m.old_id;",
                *add_fks,
                *seq_fix,
            ],
        ),
    ]
    sql_path = os.path.join(out_dir, "restore.generated.sql")
    with open(sql_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return sql_path


def _columns(db, table):
    rows = _psql_query(
        db,
        "SELECT column_name FROM information_schema.columns "
        f"WHERE table_name = '{table}' ORDER BY ordinal_position",
    )
    return [c for c in rows.splitlines() if c]


def _prov_fk_constraints(db):
    """Every foreign key declared ON a prov table, as (table, constraint_name, definition)."""
    rows = _psql_query(
        db,
        "SELECT conrelid::regclass::text || '\t' || conname || '\t' || pg_get_constraintdef(oid) "
        "FROM pg_constraint WHERE contype = 'f' "
        "AND conrelid::regclass::text LIKE 'ligoj_prov%' "
        "ORDER BY conrelid::regclass::text, conname",
    )
    out = []
    for line in rows.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            out.append((parts[0], parts[1], "\t".join(parts[2:])))
    return out


def _sequence_fixups(db, spec, prov_tables):
    """Advance each touched id-sequence safely past its table's max(id).

    Ligoj's ids come from a Hibernate pooled optimizer, so the sequence increments by the allocation
    size (e.g. 50) and a single nextval reserves a whole block of ids around the returned value.
    Setting the sequence to max(id) + increment (is_called=false) makes the next reserved block start
    strictly above the current rows for either pooled variant (hi/lo); with increment 1 it is just
    the plain max(id)+1.
    """
    fixes = []
    core = ["ligoj_project", "ligoj_subscription", "ligoj_parameter_value"]
    for table in core + prov_tables:
        seq = f"{table}_seq"
        increment = _psql_query(
            db, f"SELECT increment_by FROM pg_sequences WHERE sequencename = '{seq}'"
        )
        if not increment or "id" not in _columns(db, table):
            continue
        fixes.append(
            f"SELECT setval('{seq}', "
            f"(SELECT COALESCE(MAX(id), 0) FROM {table}) + {int(increment)}, false);"
        )
    return fixes


def _print_restore_summary(meta, before, after, duration):
    print()
    utils.info(f"[restore] Restore of '{meta['id']}' complete in {_human_dur(duration)}")
    for table in before:
        name = table.replace("ligoj_", "")
        utils.info(f"[restore]   {name}: {before[table]} -> {after[table]} row(s)")


# --------------------------------------------------------------------------- #
# Backup listing / selection
# --------------------------------------------------------------------------- #
def _list_backups(spec):
    root = _backup_root()
    items = []
    if not os.path.isdir(root):
        return items
    for name in sorted(os.listdir(root)):
        meta_path = os.path.join(root, name, "metadata.json")
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, encoding="utf-8") as handle:
                meta = json.load(handle)
        except (OSError, ValueError):
            continue
        if spec is None or meta.get("service") == spec["service"]:
            items.append(meta)
    items.sort(key=lambda m: m.get("created", ""), reverse=True)
    return items


def _choose_backup(spec):
    items = _list_backups(spec)
    if not items:
        utils.warn(
            f"[restore] No backups for {spec['service']} in {_backup_root()} "
            f"(run 'ligoj dev backup {spec['service']}' first)"
        )
        return None
    utils.info(f"[restore] Available {spec['service']} backups:")
    for index, meta in enumerate(items, 1):
        prov = meta.get("prov_rows_total", "?")
        subs = meta.get("core_tables", {}).get("ligoj_subscription", "?")
        print(
            f"  [{index}] {meta['id']:26} {meta.get('created', ''):25} "
            f"subs={subs}  prov_rows={prov}  ({_human_size(meta.get('prov_dump_bytes', 0))})"
        )
    try:
        raw = input(f"Select a backup to restore [1-{len(items)}] (Enter to cancel): ").strip()
    except EOFError:
        raw = ""
    if not raw:
        utils.info("[restore] Cancelled")
        return None
    if not raw.isdigit() or not (1 <= int(raw) <= len(items)):
        utils.warn(f"[restore] Invalid selection '{raw}'")
        return None
    return items[int(raw) - 1]["id"]


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def _dur(since):
    return _human_dur(time.time() - since)


def _human_dur(seconds):
    seconds = float(seconds)
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"


def _human_size(num):
    size = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"
