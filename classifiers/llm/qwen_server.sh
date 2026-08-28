export TORCHINDUCTOR_AUTOTUNE_REMOTE_CACHE=0
export TRITON_CACHE_DIR=/sc/home/carolina.cortes/.triton/cache
export TORCHINDUCTOR_CACHE_DIR=/sc/home/carolina.cortes/.cache/torchinductor

mkdir -p "$TRITON_CACHE_DIR" "$TORCHINDUCTOR_CACHE_DIR"
rm -rf /sc/home/carolina.cortes/.cache/vllm/torch_compile_cache

export NCCL_P2P_DISABLE=1
export NCCL_IB_DISABLE=1
export NCCL_CUMEM_ENABLE=0

vllm serve Qwen/Qwen3.5-35B-A3B-FP8 \
    --port 8001 \
    --tensor-parallel-size 2 \
    --max-model-len 8192 \
    --reasoning-parser qwen3 \
    --language-model-only \
    --disable-custom-all-reduce \
    --enforce-eager 


