"""Pre-load VRAM fit check for a GGUF model on NVIDIA GPUs. Read-only: loads nothing, changes nothing.

Budget = weights (GGUF file size) + KV cache (from the model's own metadata) + runtime overhead,
compared against each GPU's *measured free* VRAM with a safety margin.

Usage:
  python fit_check.py MODEL.gguf --ctx 32768 [--parallel 1] [--kv-bytes 2] [--margin 0.85] [--overhead-gb 1.0]
  python fit_check.py MODEL.gguf --dump      # print the architecture metadata used for sizing

Exit code 0 = fits on at least one GPU on its own; 1 = does not fit on any single GPU.
"""
from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys

_SCALAR = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


def read_gguf_metadata(path: str) -> dict:
    """Parse the GGUF key/value header (tensor data is not read)."""
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError(f"{path} is not a GGUF file")
        version, = struct.unpack("<I", f.read(4))
        if version < 2:
            raise ValueError(f"GGUF v{version} not supported")
        _tensors, n_kv = struct.unpack("<QQ", f.read(16))

        def string() -> str:
            n, = struct.unpack("<Q", f.read(8))
            return f.read(n).decode("utf-8", "replace")

        def value(t: int):
            if t in _SCALAR:
                fmt = _SCALAR[t]
                return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]
            if t == 8:
                return string()
            if t == 9:
                sub, n = struct.unpack("<IQ", f.read(12))
                if sub in _SCALAR and n > 4096:  # skip big arrays (token tables) without keeping them
                    f.seek(n * struct.calcsize(_SCALAR[sub]), 1)
                    return f"<array of {n}>"
                items = [value(sub) for _ in range(n)]
                return items if n <= 4096 else f"<array of {n}>"
            raise ValueError(f"unknown GGUF value type {t}")

        meta = {}
        for _ in range(n_kv):
            key = string()
            t, = struct.unpack("<I", f.read(4))
            meta[key] = value(t)
        return meta


def kv_cache_bytes(meta: dict, ctx: int, parallel: int, kv_bytes: float) -> tuple[float, str]:
    """KV cache = sum over attention layers of 2 (K and V) x n_kv_heads x head_dim x ctx x bytes."""
    arch = meta.get("general.architecture", "")
    g = lambda k, d=None: meta.get(f"{arch}.{k}", d)  # noqa: E731
    n_layers = int(g("block_count", 0))
    n_head = g("attention.head_count", 0)
    n_kv = g("attention.head_count_kv", n_head)
    emb = int(g("embedding_length", 0))
    n_head_scalar = max(n_head) if isinstance(n_head, list) else n_head
    k_dim = int(g("attention.key_length", emb // n_head_scalar if n_head_scalar else 0))
    v_dim = int(g("attention.value_length", k_dim))

    per_layer_kv = n_kv if isinstance(n_kv, list) else [n_kv] * n_layers
    # Hybrid models (linear/recurrent layers + periodic full attention) only keep a KV cache on attention layers.
    interval = g("full_attention_interval")
    note = ""
    if interval:
        per_layer_kv = [h if (i + 1) % int(interval) == 0 else 0 for i, h in enumerate(per_layer_kv)]
        note = f"hybrid: full attention every {interval} layers"
    attn_layers = sum(1 for h in per_layer_kv if h)
    # Sliding-window layers cap their cache at the window size.
    window = g("attention.sliding_window")
    eff_ctx = ctx
    total = sum(2 * h * (k_dim + v_dim) / 2 * min(eff_ctx, window or eff_ctx) * kv_bytes for h in per_layer_kv)
    # Recurrent (SSM / linear-attention) layers hold a fixed-size f32 state per sequence instead of a KV cache.
    ssm_inner, ssm_state = g("ssm.inner_size"), g("ssm.state_size")
    if ssm_inner and ssm_state:
        total += (n_layers - attn_layers) * int(ssm_inner) * int(ssm_state) * 4
    total *= parallel
    desc =f"{attn_layers}/{n_layers} attention layers, kv_heads={n_kv if not isinstance(n_kv, list) else 'per-layer'}, " \
           f"k/v dim={k_dim}/{v_dim}" + (f", {note}" if note else "") + (f", sliding window {window}" if window else "")
    return total, desc


def gpu_free_mib() -> list[tuple[int, str, int, int]]:
    env = dict(os.environ)
    env.setdefault("ProgramFiles", r"C:\Program Files")  # NVML needs it; stripped by some launchers
    out = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.used",
                          "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=10, env=env)
    rows = []
    for line in out.stdout.strip().splitlines():
        i, name, total, used = [x.strip() for x in line.split(",")]
        rows.append((int(i), name, int(total), int(total) - int(used)))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gguf")
    ap.add_argument("--ctx", type=int, default=8192)
    ap.add_argument("--parallel", type=int, default=1, help="concurrent sequences (each gets its own KV cache)")
    ap.add_argument("--kv-bytes", type=float, default=2.0, help="2=f16, 1.0625=q8_0, 0.5625=q4_0")
    ap.add_argument("--margin", type=float, default=0.85, help="use at most this share of a GPU's free VRAM")
    ap.add_argument("--overhead-gb", type=float, default=1.0, help="compute buffers, CUDA context")
    ap.add_argument("--no-mmproj", action="store_true", help="don't count a vision projector found next to the model")
    ap.add_argument("--dump", action="store_true")
    a = ap.parse_args()

    meta = read_gguf_metadata(a.gguf)
    if a.dump:
        arch = meta.get("general.architecture", "")
        for k, v in meta.items():
            if k.startswith(arch + ".") or k in ("general.architecture", "general.name", "general.file_type"):
                print(f"{k} = {v}")
        return 0

    weights = os.path.getsize(a.gguf)
    # A vision projector next to the model (mmproj-*.gguf) is loaded with it by LM Studio.
    folder = os.path.dirname(os.path.abspath(a.gguf))
    mmproj = 0 if a.no_mmproj else sum(os.path.getsize(os.path.join(folder, n)) for n in os.listdir(folder)
                                       if n.lower().startswith("mmproj") and n.lower().endswith(".gguf"))
    kv, desc = kv_cache_bytes(meta, a.ctx, a.parallel, a.kv_bytes)
    need = weights + mmproj + kv + a.overhead_gb * 2**30
    gib = lambda b: b / 2**30  # noqa: E731
    print(f"model   {os.path.basename(a.gguf)}  ({meta.get('general.architecture')}; {desc})")
    print(f"budget  weights {gib(weights):.1f}" + (f" + vision {gib(mmproj):.1f}" if mmproj else "") +
          f" + KV/state {gib(kv):.1f} (ctx {a.ctx} x{a.parallel}) + overhead {a.overhead_gb:.1f} = {gib(need):.1f} GiB")
    fits_any = False
    for i, name, total, free in gpu_free_mib():
        limit = free * 2**20 * a.margin
        ok = need <= limit
        fits_any |= ok
        print(f"GPU {i}  {name}: free {free/1024:.1f} of {total/1024:.1f} GiB, usable at {a.margin:.0%} "
              f"= {gib(limit):.1f} GiB -> {'FITS' if ok else 'DOES NOT FIT'} "
              f"(headroom {gib(limit - need):+.1f} GiB)")
    if not fits_any:
        print("-> shorten context, quantize the KV cache (--kv-bytes 1.0625), pick a smaller quant, "
              "or plan a deliberate CPU offload. Do not rely on spill.")
    return 0 if fits_any else 1


if __name__ == "__main__":
    sys.exit(main())
