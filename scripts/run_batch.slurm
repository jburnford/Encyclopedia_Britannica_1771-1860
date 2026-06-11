#!/bin/bash
#SBATCH --account=def-jic823
#SBATCH --job-name=eb-chandra
#SBATCH --gres=gpu:h100:1
#SBATCH --cpus-per-task=12
#SBATCH --mem=128G
#SBATCH --time=06:00:00
#SBATCH --output=/project/def-jic823/britannica_chandra2/logs/chunk-%a-job-%j.out

# OCR a chunk of NLS Britannica volumes with Chandra 2 (headers/footers kept).
# Usage: sbatch --array=0-64%4 run_batch.slurm

set -uo pipefail
BASE=/project/def-jic823/britannica_chandra2
CHANDRA=/project/def-jic823/chandra2

export HF_HOME=/scratch/jic823/hf_cache
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export XDG_CACHE_HOME=/scratch/jic823/.cache
export VLLM_CACHE_ROOT=/scratch/jic823/.cache/vllm
export FLASHINFER_WORKSPACE_BASE=/scratch/jic823/.cache/flashinfer
mkdir -p "$XDG_CACHE_HOME" "$VLLM_CACHE_ROOT" "$FLASHINFER_WORKSPACE_BASE" "$BASE/logs"

module load python/3.11 gcc opencv/4.13.0 cuda/12.9
source "$CHANDRA/venv/bin/activate"

CHUNK_FILE="$BASE/chunks/chunk_${SLURM_ARRAY_TASK_ID}.txt"
[ -f "$CHUNK_FILE" ] || { echo "missing $CHUNK_FILE"; exit 1; }
echo "[job] node=$(hostname) chunk=$CHUNK_FILE"; nvidia-smi -L

SLOG="$BASE/logs/vllm-${SLURM_JOB_ID}.log"
PORT=$(python -c "import socket;s=socket.socket();s.bind((\"127.0.0.1\",0));print(s.getsockname()[1]);s.close()")
export VLLM_API_BASE="http://127.0.0.1:${PORT}/v1"

echo "[job] starting vLLM server on port $PORT -> $SLOG"
vllm serve datalab-to/chandra-ocr-2 \
  --host 127.0.0.1 --port "$PORT" \
  --served-model-name chandra \
  --dtype bfloat16 \
  --max-model-len 18000 \
  --max-num-seqs 64 \
  --max-num-batched-tokens 8192 \
  --gpu-memory-utilization 0.85 \
  --enable-prefix-caching \
  --trust-remote-code \
  --mm-processor-kwargs "{\"min_pixels\":3136,\"max_pixels\":6291456}" \
  > "$SLOG" 2>&1 &
VLLM_PID=$!

READY=0
for i in $(seq 1 120); do
  curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1 && { READY=1; echo "[job] server ready after ${i}0s"; break; }
  kill -0 $VLLM_PID 2>/dev/null || { echo "[job] SERVER DIED during startup"; tail -60 "$SLOG"; exit 1; }
  sleep 10
done
[ $READY -eq 1 ] || { echo "[job] server not ready in time"; tail -60 "$SLOG"; kill $VLLM_PID; exit 1; }

OVERALL=0
while read -r ID; do
  [ -z "$ID" ] && continue
  echo "[job] === volume $ID $(date) ==="
  python "$BASE/scripts/chandra_volume.py" \
    --identifier "$ID" \
    --manifest "$BASE/manifest/volumes.jsonl" \
    --out-root "$BASE/output"
  RC=$?
  [ $RC -ne 0 ] && { echo "[job] volume $ID exited rc=$RC"; OVERALL=1; }
done < "$CHUNK_FILE"

echo "[job] chunk done rc=$OVERALL; stopping server"
kill $VLLM_PID 2>/dev/null
sleep 3
exit $OVERALL
