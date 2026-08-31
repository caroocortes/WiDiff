"""
Measures on-disk space for both engines, for the "space of the data
loaded" question. Run after loading (and again after adding
qualifiers/references, or after the schema-evolution benchmark, to see
how space grows) - each call snapshots current state under a label so
multiple runs don't overwrite each other's numbers in
results/space_stats.json.
"""

import json
import time
from pathlib import Path

import psycopg2

TABLES = ["revision", "rank_change", "value_change", "qualifier_change", "reference_change",
          "properties", "entities", "users", "file_paths"]

def postgres_space(db_config_path="config/postgresql_db_config.json"):
    with open(db_config_path) as f:
        db_config = json.load(f)

    conn = psycopg2.connect(
        dbname=db_config["DB_NAME"], user=db_config["DB_USER"], password=db_config["DB_PASS"],
        host=db_config["DB_HOST"], port=db_config["DB_PORT"], connect_timeout=30,
    )
    cursor = conn.cursor()

    per_table = {}
    for table in TABLES:
        cursor.execute("""
            SELECT
                pg_table_size(%s::regclass) AS table_bytes,
                pg_indexes_size(%s::regclass) AS index_bytes,
                pg_total_relation_size(%s::regclass) AS total_bytes
            WHERE to_regclass(%s) IS NOT NULL;
        """, (table, table, table, table))
        row = cursor.fetchone()
        if row is None:
            per_table[table] = None  # table doesn't exist
            continue
        table_bytes, index_bytes, total_bytes = row
        per_table[table] = {
            "table_bytes": table_bytes, "index_bytes": index_bytes, "total_bytes": total_bytes,
            "table_pretty": _pretty(table_bytes), "index_pretty": _pretty(index_bytes), "total_pretty": _pretty(total_bytes),
        }

    cursor.execute("SELECT pg_database_size(%s);", (db_config["DB_NAME"],)) # the total disk space used
    database_bytes = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    return {
        "database_bytes": database_bytes,
        "database_pretty": _pretty(database_bytes),
        "tables": per_table,
    }


def _pretty(num_bytes):
    if num_bytes is None:
        return None
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:.1f}{unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f}PB"


def qlever_space(qlever_config_path="config/qlever_db_config.json"):
    with open(qlever_config_path) as f:
        qlever_config = json.load(f)

    data_dir = Path(qlever_config["DATA_DIR"])

    index_files = sorted(data_dir.glob("*.index.*"))
    index_bytes = sum(f.stat().st_size for f in index_files if f.is_file())

    ttl_files = sorted(data_dir.glob("*.ttl"))
    ttl_bytes = sum(f.stat().st_size for f in ttl_files if f.is_file())

    vocab_files = sorted(f for f in data_dir.glob("*.vocabulary.*") if f.is_file())
    vocab_bytes = sum(f.stat().st_size for f in vocab_files)

    return {
        "index_bytes": index_bytes, "index_pretty": _pretty(index_bytes),
        "num_index_files": len(index_files),
        "vocabulary_bytes": vocab_bytes, "vocabulary_pretty": _pretty(vocab_bytes),
        "ttl_source_bytes": ttl_bytes, "ttl_source_pretty": _pretty(ttl_bytes),
        "num_ttl_files": len(ttl_files),
        "total_on_disk_bytes": index_bytes + vocab_bytes,
        "total_on_disk_pretty": _pretty(index_bytes + vocab_bytes),
    }


def run(label="snapshot", results_dir="results"):
    snapshot = {
        "label": label,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "postgresql": postgres_space(),
        "qlever": qlever_space(),
    }

    Path(results_dir).mkdir(parents=True, exist_ok=True)
    out_path = Path(results_dir) / "space_stats.json"
    if out_path.exists():
        with open(out_path) as f:
            all_snapshots = json.load(f)
    else:
        all_snapshots = {"snapshots": []}
    all_snapshots["snapshots"].append(snapshot)
    with open(out_path, "w") as f:
        json.dump(all_snapshots, f, indent=4)

    print(f"PostgreSQL database size: {snapshot['postgresql']['database_pretty']}")
    for table, stats in snapshot["postgresql"]["tables"].items():
        if stats:
            print(f"  {table}: {stats['total_pretty']} (table {stats['table_pretty']} + indexes {stats['index_pretty']})")
    print(f"QLever index on disk: {snapshot['qlever']['total_on_disk_pretty']} "
          f"(from {snapshot['qlever']['ttl_source_pretty']} of source Turtle)")
    print(f"\nWrote snapshot '{label}' to {out_path}")

    return snapshot


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Snapshot on-disk space usage for PostgreSQL and QLever.")
    parser.add_argument("--label", default="snapshot", help="Label for this snapshot, e.g. 'after_base_load', 'after_update'.")
    args = parser.parse_args()
    run(label=args.label)
