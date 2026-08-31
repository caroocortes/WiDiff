#!/bin/bash
echo "Starting indexing at $(date)"

export ENROOT_MOUNT_HOME=no
DATA_DIR=qlever/data
CONTAINER_NAME=qlever

# Pinned image - keep in sync with qlever/qleverdb.sh (see the comment
# there for why this is a commit-<sha> tag rather than a version number).
QLEVER_IMAGE="adfreiburg/qlever:commit-5799024b7b"
SQSH_PATH="qlever/adfreiburg+qlever+commit-5799024b7b.sqsh"

mkdir -p "${DATA_DIR}"
mkdir -p qlever/process_logs/

if [ ! -f "${DATA_DIR}/Qleverfile" ]; then
    echo "ERROR: ${DATA_DIR}/Qleverfile not found - copy qlever/Qleverfile there first."
    exit 1
fi

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

# Same --rc-file fix as the server script: enroot always runs the image's
# baked-in /etc/rc (docker-entrypoint.sh) and only ever passes a trailing
# command to it as arguments, never as a cwd-setting replacement - and
# --rc itself wants a file path, not inline script text.
RC_SCRIPT_FILE="./qlever/process_logs/qlever_index_rc_${SLURM_JOBID:-manual}.sh"
cat > "${RC_SCRIPT_FILE}" <<EOF
#!/bin/bash
cd /data && \
ulimit -Sn 65535 && \
echo '{}' > wikidata_diffs.settings.json && \
cat *.ttl | qlever-index -i wikidata_diffs -s wikidata_diffs.settings.json \
  --vocabulary-type on-disk-compressed -F ttl -f - --stxxl-memory 96G \
  2>&1 | tee wikidata_diffs.index-log.txt
EOF
chmod +x "${RC_SCRIPT_FILE}"

echo "Running qlever index"
SECONDS=0
enroot start --root --rw \
  --mount "${DATA_DIR}:/data" \
  --rc "${RC_SCRIPT_FILE}" \
  "${CONTAINER_NAME}" \
  2>&1 | tee "./qlever/process_logs/index_output_${SLURM_JOBID:-manual}.log"
duration=$SECONDS

PATH_TO_STATS="$(pwd)/results/loading_creation_stats.json"
echo PATH_TO_STATS: $PATH_TO_STATS
python3 -c "
import json
p = '${PATH_TO_STATS}'
d = json.load(open(p))
d.setdefault('qlever', {})['loading_index_creation_time_sec'] = ${duration}
json.dump(d, open(p, 'w'), indent=4)
"

INDEX_EXIT=${PIPESTATUS[0]}
if [ "$INDEX_EXIT" -ne 0 ]; then
    echo "ERROR: qlever index exited with status ${INDEX_EXIT}"
    exit 1
fi

echo "Indexing finished at $(date)"
echo "Index files should now be in ${DATA_DIR} - the persistent server job can be submitted."