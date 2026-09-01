# Launcher templates

One launcher per GPU. Each pins a single device and binds its own port. Adjust
model path, context size, and layer count to the hardware.

Ports here are `1234 + GPU index` by convention only — nothing depends on the
specific numbers, but keep them consistent with the project's `ENDPOINTS`.

---

## llama-server (Windows)

```bat
@echo off
:: start_server_gpu0.bat — GPU 0, port 1234
set CUDA_VISIBLE_DEVICES=0
set MODEL_PATH=C:\models\your-model.gguf
set PORT=1234
set CTX=8192
set GPU_LAYERS=99

llama-server.exe --model "%MODEL_PATH%" --port %PORT% ^
  --ctx-size %CTX% --n-gpu-layers %GPU_LAYERS% ^
  --threads 8 --log-disable
```

For GPU 1: `CUDA_VISIBLE_DEVICES=1`, `PORT=1235`.

## llama-server (Linux / macOS)

```bash
#!/usr/bin/env bash
# start_server_gpu0.sh — GPU 0, port 1234
set -euo pipefail
export CUDA_VISIBLE_DEVICES=0

llama-server \
  --model "${MODEL_PATH:?set MODEL_PATH}" \
  --port "${PORT:-1234}" \
  --ctx-size "${CTX:-8192}" \
  --n-gpu-layers "${GPU_LAYERS:-99}" \
  --threads "${THREADS:-8}"
```

## LM Studio

The model is loaded in the LM Studio UI or via `lms load`; the launcher only
starts the server:

```bash
lms server start --port 1234
```

LM Studio manages device placement itself — use its GPU controls to pin a model
to a specific card rather than `CUDA_VISIBLE_DEVICES`. Enable flash attention
and, for models that fit, limit offload to dedicated VRAM so nothing spills into
shared memory.

## Ollama

```bash
CUDA_VISIBLE_DEVICES=0 OLLAMA_HOST=127.0.0.1:1234 ollama serve
```

Ollama's OpenAI-compatible endpoint is at `/v1`, so `ENDPOINTS` entries look the
same as the others. Note that `MODEL_ID` must match the Ollama tag exactly.

---

## Flags worth knowing

| Flag | Use |
|---|---|
| `--ctx-size` | Hard context limit. Raise for long-input work; costs VRAM. |
| `--n-gpu-layers` | Layers on GPU. `99` means "all that fit". |
| `--n-cpu-moe N` | MoE only: keep experts for N layers in system RAM. |
| `--override-tensor` | Regex tensor placement, when layer-level control is too coarse. |
| `--tensor-split` | Ratio across GPUs when one model spans several cards. |
| `--flash-attn` | Usually a straight win; reduces KV cache footprint. |
| `--jinja` | Required by some newer chat templates. |

Verify flag names against the backend version in use — they change.
