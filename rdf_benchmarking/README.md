# RDF Benchmarking - Loading & Space Usage (PostgreSQL vs. QLever)

This benchmark loads the data from 10 files of the June 2025 Edit History dump into PostgreSQL and QLever and compares
loading/indexing time and on-disk space. 

The experiments were run in an HPC cluster with the following resources for both DBs:

- PostgreSQL DB instance and QLever index creation:
```bash
  #SBATCH --mem=128GB
  #SBATCH --ntasks=1
  #SBATCH -c 16
  #SBATCH --constraint=ARCH:X86
```

## Prerequisites

- Install all dependencies from the requirements.txt in the root repo.
- Download data from [Wikidata changes for RDF vs RDB benchmark](https://doi.org/10.5281/zenodo.22207667) and put *data/* directory inside *wikidata-edit-history/rdf_benchmarking/*

## 1. Configure connection settings

- `config/postgresql_db_config.json` - `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS`..
- `config/qlever_db_config.json` - `DATA_DIR` (QLever's data directory, default `qlever/data`), `PORT`, `SPARQL_ENDPOINT`, `ACCESS_TOKEN`.

We provide .sh files with the configuration used for both database engines
(`postgresql/pgdb.sh`, `qlever/qleverdb.sh`). Each imports its pinned
container image (PostgreSQL 16.14, pgAdmin 9.16, QLever `commit-5799024b7b`
- QLever has no stable version tags, so it's pinned to an immutable
per-commit build instead) automatically on first run if it isn't already
present locally - no separate download step needed.

## Resource budget

Both engines are tuned for a 128GB RAM / 16-core host, declared as
`MEM_BUDGET`/`CPU_BUDGET` near the top of `postgresql/pgdb.sh` and
`qlever/qleverdb.sh`. PostgreSQL's `PG_TUNING` array and QLever's
`STXXL_MEMORY` (in `qlever/data/Qleverfile`) are both derived from that same
budget, so timing/space comparisons reflect the engines rather than unequal
hardware - running on different hardware means re-tuning both files to
match. `preflight_check.py` (called automatically by `load_data.py` before
loading) records what was actually declared for a given run - PostgreSQL's
live `SHOW ALL` settings, and QLever's `MEM_BUDGET`/`CPU_BUDGET`/
`STXXL_MEMORY` parsed from whichever script started it - to
`results/preflight_<timestamp>.json`.

## 2. Start PostgreSQL (+ pgAdmin)

```bash
cd postgresql
bash pgdb.sh
```

**NOTE:** Must create a server and the corresponding database where the data will be stored. Update **wikidata-edit-history/rdf_benchmarking/config/postgresql_db_config.json** accordingly

## 3. Load into PostgreSQL

```bash
python3 load_data.py --db_type postgresql
```

Connects using `config/postgresql_db_config.json`, creates the schema, bulk loads every CSV via `psql \copy`, then adds primary/foreign keys and indexes and runs `ANALYZE`. Timing and row counts are written to `results/loading_creation_stats.json` under the `"postgresql"` key.

## 4. Load into QLever

```bash
python3 load_data.py --db_type qlever
```

This has two phases:

1. Serializes every CSV to Turtle triples and saves them into `data/triples_ttl.ttl` (skipped if that file already exists - delete it first to force a rebuild). Serialization stats go under the `"triples_creation"` key in `results/loading_creation_stats.json`.
2. Copies the `.ttl` file into QLever's `DATA_DIR` and builds the QLever index (`qlever-index`) with `STXXL_MEMORY` matched to the PostgreSQL job's resource budget for a fair comparison. If `sbatch` is available on `PATH` this runs as a Slurm job (`sbatch --wait qlever/qlever_index.slurm`); otherwise `qlever/qlever_index.sh` is run directly as a local process - no Slurm required either way. The index build time is written to `results/loading_creation_stats.json` under `"qlever" -> "loading_index_creation_time_sec"`.

## 5. Measure on-disk space usage

```bash
python3 measure_space_usage.py
```

Reports PostgreSQL table/index sizes (`pg_table_size` / `pg_indexes_size` / `pg_total_relation_size` per table, plus total database size) and QLever's on-disk footprint (index files, vocabulary files, and the size of the source `.ttl`, read from `DATA_DIR` in `config/qlever_db_config.json`). Each run appends a labeled snapshot to `results/space_stats.json` rather than overwriting previous ones.

## 6. View the results

```bash
cd results
jupyter notebook results_summary.ipynb
```

Run it from inside `results/` - the notebook reads `loading_creation_stats.json`
and `space_stats.json` via relative paths. 

Run the first two cells:

- **LOADING AND INDEX CREATION STATS** - total loading + index creation time and row/triple counts for PostgreSQL and QLever.
- **SPACE USAGE STATS** - PostgreSQL database size vs. QLever index + vocabulary size vs. the source `.ttl` size.
