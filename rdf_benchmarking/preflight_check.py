"""
Records each engine's *actual effective* configuration before a benchmark
run, so every run is self-documenting instead of relying on remembering
what was tuned that day.

This exists because the production wd_db instance was found to have
drifted silently: the checked-in postgresql_loading.conf said work_mem =
64MB, but the live instance was actually running work_mem = 1GB (set at
some point via ALTER SYSTEM / command-line flags and never reconciled
with the file). `SHOW ALL` is the only way to know what's really in
effect - reading the conf file is not sufficient.

For QLever there's no live "SHOW ALL" equivalent over SPARQL, so we
record the *declared* config instead: STXXL_MEMORY parsed from the
Qleverfile, and MEM_BUDGET/CPU_BUDGET parsed from whichever startup
script (qleverdb.sh, or a Slurm variant of it) was actually run.
"""

import json
import re
import time
from pathlib import Path

import psycopg2

# The subset of postgresql.conf parameters that matter for this
# benchmark's fairness (memory budget, parallelism, autovacuum, logging
# thresholds) - not the full ~300-parameter SHOW ALL output.
PG_PARAMS_OF_INTEREST = [
    "max_connections", "shared_buffers", "effective_cache_size",
    "work_mem", "maintenance_work_mem", "wal_buffers",
    "checkpoint_timeout", "max_wal_size", "min_wal_size",
    "checkpoint_completion_target", "max_worker_processes",
    "max_parallel_workers_per_gather", "max_parallel_workers",
    "autovacuum", "autovacuum_max_workers", "autovacuum_naptime",
    "log_min_duration_statement",
]


def postgres_preflight(db_config_path="config/postgresql_db_config.json", db_name=None):
    """Connects to Postgres and returns live SHOW-ALL values for the
    params above, the target database's on-disk size, and a warning if
    other databases on the same cluster have active (non-idle)
    connections - a sign of contention from an unrelated workload."""

    with open(db_config_path) as f:
        db_config = json.load(f)

    conn = psycopg2.connect(
        dbname=db_config["DB_NAME"], user=db_config["DB_USER"], password=db_config["DB_PASS"],
        host=db_config["DB_HOST"], port=db_config["DB_PORT"], connect_timeout=30,
    )
    try:
        cursor = conn.cursor()

        settings = {}
        for param in PG_PARAMS_OF_INTEREST:
            cursor.execute("SHOW %s;" % param)  # param names come from a fixed whitelist above, not user input
            settings[param] = cursor.fetchone()[0]

        target_db = db_name or db_config["DB_NAME"]
        cursor.execute("SELECT pg_size_pretty(pg_database_size(%s));", (target_db,))
        db_size_pretty = cursor.fetchone()[0]

        # Other databases with active (non-idle) backends = a workload
        # other than this benchmark is currently hitting the same
        # instance, which would contaminate shared_buffers/OS cache/I-O.
        cursor.execute("""
            SELECT datname, count(*)
            FROM pg_stat_activity
            WHERE datname IS NOT NULL AND datname != %s AND state != 'idle'
            GROUP BY datname;
        """, (target_db,))
        contending = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.close()
    finally:
        conn.close()

    return {
        "host": db_config["DB_HOST"],
        "port": db_config["DB_PORT"],
        "database": target_db,
        "database_size_pretty": db_size_pretty,
        "settings": settings,
        "other_databases_with_active_connections": contending,
        "contention_warning": bool(contending),
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def qlever_preflight(
    qleverfile_path="qlever/data/Qleverfile",
    script_path="qlever/qleverdb.sh",
):
    """No live introspection endpoint exists for QLever's resource
    budget over SPARQL, so this parses the *declared* config straight
    out of the files actually used to start it - still catches the
    class of bug this whole module exists for (numbers declared in one
    place but not another).

    script_path defaults to the portable qleverdb.sh, but should be
    pointed at whichever script actually started the running instance
    (e.g. a private Slurm variant) if that's not it - MEM_BUDGET/
    CPU_BUDGET are declared the same way in both."""

    result = {
        "stxxl_memory": None,
        "mem_budget": None,
        "cpu_budget": None,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    qf = Path(qleverfile_path)
    if qf.exists():
        m = re.search(r"^\s*STXXL_MEMORY\s*=\s*(\S+)", qf.read_text(), re.MULTILINE)
        if m:
            result["stxxl_memory"] = m.group(1)

    sf = Path(script_path)
    if sf.exists():
        text = sf.read_text()
        m = re.search(r'^MEM_BUDGET=[\'"]?([^\'"\n]+)', text, re.MULTILINE)
        if m:
            result["mem_budget"] = m.group(1)
        m = re.search(r'^CPU_BUDGET=[\'"]?([^\'"\n]+)', text, re.MULTILINE)
        if m:
            result["cpu_budget"] = m.group(1)

    return result


def run_preflight(results_dir="results"):
    """Runs both preflight checks and writes them to a timestamped file
    under results_dir. Returns the combined dict so callers can also
    fold it into their own stats JSON."""

    combined = {
        "postgresql": None,
        "postgresql_error": None,
        "qlever": None,
    }

    try:
        combined["postgresql"] = postgres_preflight()
    except Exception as e:
        combined["postgresql_error"] = str(e)

    combined["qlever"] = qlever_preflight()

    Path(results_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(results_dir) / f"preflight_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(out_path, "w") as f:
        json.dump(combined, f, indent=4)

    return combined, out_path


if __name__ == "__main__":
    combined, out_path = run_preflight()
    print(json.dumps(combined, indent=4))
    print(f"\nWrote preflight report to {out_path}")
    if combined.get("postgresql", {}).get("contention_warning"):
        print("\nWARNING: other databases on this Postgres instance have active connections - "
              "benchmark timings may be contaminated by an unrelated workload.")
