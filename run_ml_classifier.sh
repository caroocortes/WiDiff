#!/bin/bash
#SBATCH -A sci-naumann
#SBATCH -J class_ml
#SBATCH --time=15:00:00
#SBATCH --mem=100GB
#SBATCH -c 2
#SBATCH --partition=cpu-batch
#SBATCH --mail-type=ALL 
#SBATCH --mail-user=slack:carolina.cortes

echo "Started: $(date) on $(hostname)"

echo "Starting environment setup"
source /sc/home/carolina.cortes/conda3/etc/profile.d/conda.sh
conda activate venv
echo "Environment setup complete"

RUN_DATE=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="ml_classifier_output_${RUN_DATE}.log"

echo "Starting ML classification at $(date)" >> "$LOG_FILE"
echo "PID: $$" >> "$LOG_FILE"

python3 classify_remaining_changes.py >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
  echo "classify_remaining_changes.py crashed with exit code $EXIT_CODE at $(date)" >> "$LOG_FILE"
  exit $EXIT_CODE
fi

echo "Finished ML classification at $(date)" >> "$LOG_FILE"

echo "=========================================="
echo "Finished: $(date)"
echo "Exit code: $EXIT_CODE"
echo "=========================================="

exit $EXIT_CODE
