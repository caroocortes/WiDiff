#!/bin/bash
echo "Starting services at $(date)"

export ENROOT_MOUNT_HOME=no
MY_PORT=5434
PGADMIN_PORT=5051
SCRIPT_DIR="${SLURM_SUBMIT_DIR}"
BENCH_DIR="${SCRIPT_DIR}"
DATA_DIR=${BENCH_DIR}/data
PGADMIN_DATA_DIR=${BENCH_DIR}/pgadmin_data

PG_CONTAINER_NAME="pg16_bench"
PGADMIN_CONTAINER_NAME="pgadmin_bench"

SQSH_DIR=${SCRIPT_DIR}

PG_IMAGE="postgres:16.14"
PGADMIN_IMAGE="dpage/pgadmin4:9.16"

PG_SQSH_PATH="${SQSH_DIR}/postgres+16.14.sqsh"
PGADMIN_SQSH_PATH="${SQSH_DIR}/dpage+pgadmin4+9.16.sqsh"

MEM_BUDGET="128GB"
CPU_BUDGET=16

import_if_missing() {
    local sqsh_path="$1"
    local image="$2"

    if [ -f "${sqsh_path}" ]; then
        echo "Image already imported at ${sqsh_path}, skipping download."
        return
    fi

    echo "Importing docker://${image} -> ${sqsh_path}"
    enroot import -o "${sqsh_path}" "docker://${image}"
}

echo "Checking container images"
import_if_missing "${PG_SQSH_PATH}" "${PG_IMAGE}"
import_if_missing "${PGADMIN_SQSH_PATH}" "${PGADMIN_IMAGE}"
echo "Images ready."

echo "Creating /scratch directories"
mkdir -p ~/.local/share/enroot/${PG_CONTAINER_NAME}/scratch
mkdir -p ~/.local/share/enroot/${PGADMIN_CONTAINER_NAME}/scratch

create_container_if_missing() {
    local container_name="$1"
    local sqsh_path="$2"

    if [ ! -f "${sqsh_path}" ]; then
        echo "ERROR: expected image at ${sqsh_path} - not found."
        echo "Either fix the path above, or re-import it, e.g.:"
        echo "  enroot import -o ${sqsh_path} docker://<image>"
        exit 1
    fi

    if enroot create --name "${container_name}" "${sqsh_path}" 2>/tmp/enroot_create_${container_name}_${SLURM_JOBID:-$$}.log; then
        echo "Created enroot container '${container_name}' from ${sqsh_path}"
    else
        if grep -qi "already exists" /tmp/enroot_create_${container_name}_${SLURM_JOBID:-$$}.log; then
            echo "enroot container '${container_name}' already exists, reusing it"
        else
            echo "ERROR: enroot create failed for '${container_name}' for a reason other than 'already exists':"
            cat /tmp/enroot_create_${container_name}_${SLURM_JOBID:-$$}.log
            exit 1
        fi
    fi
    rm -f /tmp/enroot_create_${container_name}_${SLURM_JOBID:-$$}.log
}

create_container_if_missing "${PG_CONTAINER_NAME}" "${PG_SQSH_PATH}"
create_container_if_missing "${PGADMIN_CONTAINER_NAME}" "${PGADMIN_SQSH_PATH}"

PG_HBA_RULE="host all all 0.0.0.0/0 md5"

PG_SUPERUSER_PASSWORD="postgres"

# Tuning derived from the 128GB / 16-core budget above. Passed as -c
# flags directly on the postgres command line (NOT via a separate
# postgresql.conf that can silently stop being the one actually read -
# see wd_db's drifted postgresql_loading.conf for why that's a trap).
PG_TUNING=(
  -c "max_connections=50"
  -c "shared_buffers=32GB"              # 25% of 128GB
  -c "effective_cache_size=96GB"        # 75% of 128GB
  -c "work_mem=256MB"
  -c "maintenance_work_mem=4GB"
  -c "wal_buffers=16MB"
  -c "checkpoint_timeout=15min"
  -c "max_wal_size=16GB"
  -c "min_wal_size=4GB"
  -c "checkpoint_completion_target=0.9"
  -c "max_worker_processes=16"
  -c "max_parallel_workers_per_gather=4"
  -c "max_parallel_workers=16"
  -c "autovacuum=on"
  -c "autovacuum_max_workers=4"
  -c "autovacuum_naptime=10s"
  -c "log_min_duration_statement=5000"
  -c "log_checkpoints=on"
  -c "logging_collector=on"
  -c "log_directory=log"
  -c "log_filename=postgresql-%Y-%m-%d_%H%M%S.log"
)

do_cleanup() {
    echo ""
    echo "Shutting down services (manual termination)..."

    echo "Stopping PostgreSQL"
    enroot start --rw \
      --mount ${DATA_DIR}:/var/lib/postgresql/data \
      "${PG_CONTAINER_NAME}" bash -c "/usr/lib/postgresql/16/bin/pg_ctl stop -D /var/lib/postgresql/data -m smart -t 600" 2>/dev/null

    sleep 2

    screen -S postgres_bench_db -X quit 2>/dev/null
    screen -S pgadmin_bench -X quit 2>/dev/null

    echo "Services stopped"
}

resubmit() {
  echo "$(date): job $SLURM_JOBID received SIGUSR1 at end of time limit"
  echo "Running cleanup before requeue so DB doesn't go into recovery mode"

  do_cleanup

  scontrol requeue $SLURM_JOBID
  exit 0
}

cleanup() {
    echo ""
    echo "Manual termination detected..."
    do_cleanup
    exit 0
}

trap resubmit SIGUSR1
trap cleanup SIGTERM SIGINT

mkdir -p ${DATA_DIR}
mkdir -p ${PGADMIN_DATA_DIR}
chmod 750 ${PGADMIN_DATA_DIR}
echo "Created data directory: ${DATA_DIR}"

echo "Starting PostgreSQL"
if [ ! -f ${DATA_DIR}/PG_VERSION ]; then
    enroot start --rw \
      --mount ${DATA_DIR}:/var/lib/postgresql/data \
      "${PG_CONTAINER_NAME}" bash -c "/usr/lib/postgresql/16/bin/initdb -D /var/lib/postgresql/data -U postgres"

    if [ $? -ne 0 ]; then
        echo "ERROR: initdb failed"
        exit 1
    fi
    echo "Database initialized successfully"

    echo "${PG_HBA_RULE}" >> ${DATA_DIR}/pg_hba.conf
    echo "Configured pg_hba.conf for cluster-internal access (${PG_HBA_RULE})"

    echo "Setting postgres superuser password"
    enroot start --rw \
      --mount ${DATA_DIR}:/var/lib/postgresql/data \
      "${PG_CONTAINER_NAME}" bash -c "
        mkdir -p /var/run/postgresql &&
        /usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/data -l /var/lib/postgresql/data/pg_setup.log -o '-p ${MY_PORT}' start &&
        sleep 3 &&
        /usr/lib/postgresql/16/bin/psql -p ${MY_PORT} -U postgres -c \"ALTER USER postgres WITH PASSWORD '${PG_SUPERUSER_PASSWORD}';\" &&
        /usr/lib/postgresql/16/bin/pg_ctl -D /var/lib/postgresql/data stop
      "
    if [ -f "${DATA_DIR}/pg_setup.log" ]; then
        echo "--- pg_setup.log ---"
        cat "${DATA_DIR}/pg_setup.log"
        echo "--------------------"
    fi
    if [ $? -ne 0 ]; then
        echo "ERROR: setting postgres superuser password failed"
        exit 1
    fi
    echo "Password set"
else
    echo "Database already initialized, skipping initdb"
    if ! grep -qF "${PG_HBA_RULE}" ${DATA_DIR}/pg_hba.conf 2>/dev/null; then
        echo "${PG_HBA_RULE}" >> ${DATA_DIR}/pg_hba.conf
        echo "Added missing cluster-internal access rule to existing pg_hba.conf (will apply once postgres (re)starts, which this script is about to do)"
    fi
fi

screen -S postgres_bench_db -d -m enroot start --rw \
  --mount ${DATA_DIR}:/var/lib/postgresql/data \
  --env POSTGRES_PASSWORD=${PG_SUPERUSER_PASSWORD} \
  "${PG_CONTAINER_NAME}" bash -c "mkdir -p /var/run/postgresql && /usr/lib/postgresql/16/bin/postgres -N 5000 -D /var/lib/postgresql/data -p $MY_PORT ${PG_TUNING[*]}"

if ! screen -ls | grep -q postgres_bench_db; then
    echo "ERROR: PostgreSQL screen failed to start"
    exit 1
fi

echo "Waiting for PostgreSQL to start"
sleep 15

if ! ps aux | grep "[p]ostgres.*${MY_PORT}" > /dev/null; then
    echo "ERROR: PostgreSQL process not found"
    screen -r postgres_bench_db
    exit 1
fi

echo "Starting pgAdmin"
screen -S pgadmin_bench -d -m enroot start --rw \
  --mount ${PGADMIN_DATA_DIR}:/var/lib/pgadmin \
  --env PGADMIN_LISTEN_PORT=${PGADMIN_PORT} \
  --env PGADMIN_SETUP_EMAIL=pgadmin@mail.com \
  --env PGADMIN_SETUP_PASSWORD=pgadminpass \
  --env PGADMIN_DEFAULT_EMAIL=pgadmin@mail.com \
  --env PGADMIN_DEFAULT_PASSWORD=pgadminpass \
  "${PGADMIN_CONTAINER_NAME}" bash -c "/entrypoint.sh"

if ! screen -ls | grep -q pgadmin_bench; then
    echo "WARNING: pgAdmin screen failed to start (PostgreSQL itself is still up)"
else
    echo "pgAdmin is up"
fi

echo ""
echo "Dedicated benchmark PostgreSQL is up on port ${MY_PORT}, host $(hostname)"
echo "This instance is ONLY for rdf_benchmarking - do not point production parser writes at it."
echo "Update rdf_benchmarking/config/postgresql_db_config.json DB_HOST to $(hostname -i) and DB_PORT to ${MY_PORT}."
echo ""
echo "pgAdmin: http://$(hostname):${PGADMIN_PORT}  (login: pgadmin@mail.com / pgadminpass)"
echo "In pgadmin create server with Hostname: localhost, Port: ${MY_PORT}, Username: postgres, Password: postgres"

while true; do
  sleep 600 &
  wait $!
done