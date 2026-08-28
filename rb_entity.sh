#!/bin/bash
#SBATCH -A sci-naumann
#SBATCH -J rb_ent
#SBATCH --time=1-00:00:00
#SBATCH --mem=300GB
#SBATCH -c 2
#SBATCH --partition=cpu-batch
#SBATCH --mail-type=ALL 
#SBATCH --mail-user=slack:carolina.cortes
LOG_FILE="/sc/projects/sci-naumann/chair/carolina.cortes/wikidata-edit-history/rb_entity.log"
exec 3>&1 1>>${LOG_FILE} 2>&1
echo "Started rb classification for entity: $(date)"
echo "Starting environment setup"
source /sc/home/carolina.cortes/conda3/etc/profile.d/conda.sh
conda activate venv
echo "Environment setup complete"

python3 -m parser_scripts.compute_remaining_features --table_suffix rest