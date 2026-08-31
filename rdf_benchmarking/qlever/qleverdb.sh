#!/bin/bash
echo "Starting services at $(date)"

export ENROOT_MOUNT_HOME=no
PORT=7020
DATA_DIR=data
CONTAINER_NAME=qlever

QLEVER_IMAGE="adfreiburg/qlever:commit-5799024b7b"
SQSH_PATH="adfreiburg+qlever+commit-5799024b7b.sqsh"

# Resource budget this run is tuned for - matched to postgresql/pgdb.sh's
# PG_TUNING and STXXL_MEMORY in qlever/data/Qleverfile, so PostgreSQL vs.
# QLever timings reflect the engines rather than unequal hardware. QLever
# has no live "SHOW ALL" equivalent to verify this against once running, so
# preflight_check.py::qlever_preflight() parses these two lines back out of
# this file to record what was actually declared for a given run.
MEM_BUDGET="128GB"
CPU_BUDGET=16

mkdir -p "${DATA_DIR}"
mkdir -p process_logs
echo "Created data directory: ${DATA_DIR}"

if [ ! -f "${SQSH_PATH}" ]; then
    echo "Image not found at ${SQSH_PATH}, importing docker://${QLEVER_IMAGE}..."
    enroot import -o "${SQSH_PATH}" "docker://${QLEVER_IMAGE}"
fi

if enroot create --name "${CONTAINER_NAME}" "${SQSH_PATH}" 2>/tmp/enroot_create_${SLURM_JOBID:-$$}.log; then
    echo "Created enroot container '${CONTAINER_NAME}' from ${SQSH_PATH}"
else
    if grep -qi "already exists" /tmp/enroot_create_${SLURM_JOBID:-$$}.log; then
        echo "enroot container '${CONTAINER_NAME}' already exists, reusing it"
    else
        echo "ERROR: enroot create failed for a reason other than 'already exists':"
        cat /tmp/enroot_create_${SLURM_JOBID:-$$}.log
        exit 1
    fi
fi
rm -f /tmp/enroot_create_${SLURM_JOBID:-$$}.log

do_cleanup() {
    echo ""
    echo "Shutting down services (manual termination)..."

    echo "Stopping QLever server"
    pkill -TERM -f "qlever-server" 2>/dev/null
    sleep 5
    pkill -KILL -f "qlever-server" 2>/dev/null

    screen -S qlever_server -X quit 2>/dev/null

    echo "Services stopped"
}

resubmit() {
  echo "$(date): job $SLURM_JOBID received SIGUSR1 at end of time limit"
  echo "Running cleanup before requeue"

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

echo "Starting QLever server"
SCREEN_LOG="/process_logs/qlever_screen_${SLURM_JOBID:-manual}.log"

RC_SCRIPT_FILE="process_logs/qlever_rc_${SLURM_JOBID:-manual}.sh"
cat > "${RC_SCRIPT_FILE}" <<EOF
#!/bin/bash
cd /data && exec /qlever/docker-entrypoint.sh -c 'qlever start --port ${PORT} --system native --kill-existing-with-same-port'
EOF
chmod +x "${RC_SCRIPT_FILE}"

screen -L -Logfile "${SCREEN_LOG}" -S qlever_server -d -m enroot start --root --rw \
  --mount "${DATA_DIR}:/data" \
  --rc "${RC_SCRIPT_FILE}" \
  "${CONTAINER_NAME}"

sleep 3
if ! screen -ls | grep -q qlever_server; then
    echo "ERROR: QLever server screen already exited - it crashed almost immediately."
    echo "Captured output (this is the actual error, read it before anything else):"
    cat "${SCREEN_LOG}" 2>/dev/null
    exit 1
fi

echo "QLever is up"
echo "SPARQL endpoint (verify exact shape with 'qlever query --show' inside the container): http://$(hostname):${PORT}/"
echo "Tunnel from your machine: ssh -L ${PORT}:$(hostname):${PORT} you@login-node"

# Keep job alive - wait will exit when SIGUSR1 is received
while true; do
  sleep 600 &
  wait $!
done