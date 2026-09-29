---
name: "local-gpu-inference"
description: "Operate local GPU inference (LM Studio / llama-server / Ollama) across one or more GPUs in any project. Triggers whenever the user mentions local models, running Qwen/Llama/Mistral/DeepSeek locally, wanting to use their GPU(s), multi-GPU parallel jobs, or running AI inference without the cloud. Covers autonomous server startup, mandatory VRAM fit checks so no GPU is overrun, model parameter selection, parallel work assignment across GPUs and CPU, QA/validation passes, caching, and error handling — the methodology, not a project scaffold."
---

# Local GPU Inference — Operating Methodology

How to *operate* local GPU inference in a project. This is methodology, not a
scaffold — apply it to whatever the project needs.

---

## 0. Setup — fill this in before anything else

This skill assumes one or more GPUs of roughly equal VRAM, each running its own
inference server on its own port. Establish these values first, from the project
or by asking, and use them throughout:

```
ENDPOINTS    e.g. ["http://localhost:1234/v1", "http://localhost:1235/v1"]
             One per GPU. A single-GPU setup is one entry — everything below
             still applies except the parallel sections.
BACKEND      llama-server | LM Studio | Ollama
LAUNCHERS    path to the per-GPU start scripts (see reference/launchers.md)
MODEL_ID     as the backend reports it at /v1/models
MODEL_CARD   where the model's own sampling guidance lives — you will need it
VRAM_PER_GPU nominal size only. Sizing uses *measured free* VRAM (§1a), which
             is lower: a GPU driving a display typically loses 1–2 GB to it.
THERMALS     where to read GPU / coolant temps (nvidia-smi at minimum; a sensor
             MCP server if the machine has one)
```

Never hardcode ports, paths, or model names into scripts. Read them from config
so the same code runs on someone else's hardware.

---

## 1. Server startup — always autonomous

Never ask the human to start the servers. Check, start, and confirm them yourself.

```bash
for p in 1234 1235; do curl -s "http://localhost:$p/v1/models" >/dev/null \
  && echo ":$p up" || echo ":$p down"; done
```

Start whichever endpoints don't respond, using the project's launchers, then poll
until healthy before sending any inference request:

```python
import time, urllib.request

def wait_healthy(endpoints, tries=40, delay=5):
    for ep in endpoints:
        for _ in range(tries):
            try:
                urllib.request.urlopen(f"{ep}/models", timeout=3)
                print(f"{ep} OK"); break
            except Exception:
                time.sleep(delay)
        else:
            raise RuntimeError(f"{ep} never came up")
```

If no launcher scripts exist yet, ask where the model file is and write them.
See `reference/launchers.md`.

---

## 1a. Fit before you load — mandatory, every load

**Goal: no GPU is ever overrun.** A model must fit *comfortably* on the GPU it
is meant for, with headroom, before it is loaded. Overrun doesn't always fail
loudly: backends quietly split a model across cards, push layers to the CPU,
or (on Windows) the driver spills into shared system memory. Any of these
wrecks throughput and defeats per-GPU work assignment (§3). So check first,
then verify.

**1. Measure.** Free VRAM per GPU, right now. Don't assume the nominal size.
```bash
nvidia-smi --query-gpu=index,memory.used,memory.total,temperature.gpu --format=csv
```

**2. Budget.** Run `reference/fit_check.py MODEL.gguf --ctx N [--parallel P]`.
It reads the model's own GGUF metadata and adds up:
- weights (the file size)
- any vision projector (`mmproj-*.gguf` in the same folder)
- the KV cache: 2 × KV heads × head dim × context × bytes, summed over
  *attention* layers only. Hybrid models (e.g. Qwen3.5+ `qwen35`, full attention
  every 4th layer) need far less than dense ones. Sliding-window layers cap at
  the window. `--parallel` multiplies it.
- about 1 GB of overhead

The total must sit **at or under 85% of that one GPU's free VRAM**. That margin
is the "comfortably" part, and it is not optional.
Don't trust backend estimates alone: `lms load --estimate-only` has been seen
reporting the same figure at 8k and 32k context (i.e. ignoring the KV cache).

**3. If it doesn't fit**, in this order:
1. Shorter context (size it to the job, §2).
2. Quantized KV cache (q8_0 ≈ half of f16), where the backend supports it.
3. A smaller quant of the same model, or a smaller model.
4. **Deliberate** CPU offload: a chosen number of layers (or MoE experts,
   `reference/models.md`) in system RAM. Plan the speed cost: offloaded work
   runs at RAM bandwidth.
5. Span both GPUs, but only as a conscious choice: it forfeits §3's
   one-job-per-GPU layout.

Never "load it and see". Never rely on silent spill.

**4. Place.** Put the model on the GPU the plan says. llama-server / Ollama:
`CUDA_VISIBLE_DEVICES`. LM Studio: its GPU split settings are **global**, and
its default strategy splits every model across all GPUs
(`reference/launchers.md`). Check the setting before assuming one-model-per-GPU.

**5. Verify after loading.** Re-run `nvidia-smi`. Confirm the memory landed on
the intended GPU(s), in about the amount budgeted, and that nothing spilled
(LM Studio: keep "strict VRAM cap" on). If it spread or spilled, unload and
fix the plan.

**6. Thermals.** Before a long or heavy run, check GPU temps (and coolant, if
available). During it, spot-check. Back off *before* thermal limits. A run
that pins the fans at maximum is itself a sign to lighten the load.

**CPU as a first-class worker.** Embeddings, rerankers, small classifiers and
pre- or post-processing can often run on the CPU and leave a GPU free for the
big model. Do it when it's expedient, meaning the CPU speed is acceptable for
the job.

---

## 2. Model parameters — decide them, don't look them up

Parameters are a judgment call for the task in front of you, made with the
model's own guidance in hand. What follows are calibration examples, not
presets — reason from them, don't copy them.

### Temperature

**Start from the model card, not from this file.** Sampling behaviour is
model-specific and the defaults that suit one family actively degrade another.
Some reasoning models want temperature near 1.0 and are made *worse*, not more
reliable, by being driven to 0.0 for "determinism". Check the card every time
you change models. See `reference/models.md` for current examples.

**Then adjust for what the task needs.** Roughly: the more a wrong token
cascades into a wrong artifact, the lower you want to sit within the range the
model supports — structured output and classification near the bottom, rewriting
in the middle, generation at the top. "Near the bottom" means the bottom of
*that model's* usable range, which may not be near zero.

**When it matters, measure.** For any job running over more than a few dozen
items, run 10 items at two or three settings and read the output before
committing. That takes minutes and beats any table.

**Reproducibility is separate from quality.** If you need identical reruns, fix
`seed` — don't crush temperature to get there.

### max_tokens

Fit the *expected output size*, not the maximum possible. Oversizing wastes KV
cache and can cause the model to pad or ramble.

- Short answers, classifications, yes/no + reason: 128 – 512
- Structured objects (JSON record, code function): 512 – 2048
- Multi-section documents, long summaries: 2048 – 4096
- Very long generation: raise `--ctx-size` at launch and match `max_tokens` to it

### Context window

The server's `--ctx-size` is a hard limit. If prompt + expected output might
exceed it, chunk the input — don't let the model silently truncate. Keep total
tokens under ~85% of `--ctx-size`. For long-context work, raise `--ctx-size` at
launch, and **re-run the fit check (§1a)**. A longer context grows the KV
cache, and "drop a few GPU layers" is an unplanned CPU offload, not a fix.

### Other parameters

- `top_p`: moves in the same direction as temperature — tighten for structured
  output, widen for creative. The right range is the model's, not a fixed one.
  Often redundant once temperature is set deliberately; changing both at once
  makes it hard to tell which did what.
- `repeat_penalty` (1.0–1.3): raise only if the model is looping.
- `seed`: fixed integer for reproducible runs.

The payload below shows the *shape* of the call. Fill each value from the model
card and the task, not from this snippet:

```python
payload = {
    "model": MODEL_ID,
    "messages": messages,
    "temperature": TEMPERATURE,   # from the model card, then task-adjusted
    "max_tokens": MAX_TOKENS,     # expected output size, not the ceiling
    "top_p": TOP_P,               # model's range; often leave at its default
    "repeat_penalty": 1.05,       # raise only if you see looping
    "seed": 42,                   # omit for non-reproducible runs
}
```

---

## 3. Work assignment — keep each GPU on a separate task

Separate servers exist so genuinely independent workloads run without sharing a
context window. Assign by job character, not round-robin:

| Job character | Endpoint | Why |
|---|---|---|
| Short, high-volume calls | A | Low per-call cost, fine to queue |
| Long-context / large-input jobs | B | Needs a clean, uncrowded KV cache |
| QA / validation pass | B | Runs simultaneously while A does other work |
| Any script you write | passed explicitly | Never round-robin a long-running job |

**This whole section assumes each GPU holds its own copy of a model**, and
that §1a confirmed it fits on one card with margin. A model
too large to fit twice — most large mixture-of-experts models, anything relying
on expert offload to system RAM — collapses to a single instance spanning all
GPUs. Parallelism then comes from continuous batching within that one server,
not from splitting work across endpoints. Check which regime you're in before
planning around this section.

**Different models on different GPUs is a first-class use.** Speech-to-text on
one card and a cleanup model on the other, one pass each, running at the same
time, is often the highest-value shape this pattern takes.

---

## 4. True parallel execution

Two processes, simplest:

```bash
python script_a.py --endpoint http://localhost:1234/v1   # terminal 1
python script_b.py --endpoint http://localhost:1235/v1   # terminal 2
```

Threads within one script:

```python
import threading

def run_batch(items, endpoint, results, lock):
    for item in items:
        r = llm_json(build_prompt(item), endpoint=endpoint)
        with lock:
            results[item["id"]] = r

lock, results = threading.Lock(), {}
chunks = [items[i::len(ENDPOINTS)] for i in range(len(ENDPOINTS))]
threads = [threading.Thread(target=run_batch, args=(c, ep, results, lock))
           for c, ep in zip(chunks, ENDPOINTS)]
for t in threads: t.start()
for t in threads: t.join()
```

Pass `endpoint=` explicitly in both cases. At high call rates, round-robin can
send both threads to the same GPU.

---

## 5. QA / validation pattern

Where output quality matters, run a second pass that independently checks the
first. Put it on another GPU so both run simultaneously.

```python
messages = [
    {"role": "system", "content": (
        "You are an independent quality reviewer. Given the original input and "
        "the produced output, identify errors, omissions, or anything that "
        "doesn't match the input. Return JSON: {\"ok\": bool, \"issues\": [...]}"
    )},
    {"role": "user", "content": f"INPUT:\n{original}\n\nOUTPUT:\n{produced}"}
]
verdict = llm_json(
    messages,
    temperature=REVIEW_TEMPERATURE,   # decide it; see §2
    max_tokens=512,
    endpoint=ENDPOINTS[1],
    use_cache=False,   # always fresh — cached verdicts defeat the purpose
)
if not verdict["ok"]:
    flag_for_rework(item_id, verdict["issues"])
```

Iterate: re-run flagged items on A, re-validate on B, until the flag rate is
acceptable.

**A different model makes a better reviewer.** A second architecture and
training lineage has different failure modes, so it catches errors a model
judging its own output will not. An older large model kept on disk earns its
keep here even after it stops being the workhorse.

---

## 6. Error handling conventions

- On failure for any item: write a sentinel (`00123_item.error.json`) with the
  error and continue. Never crash the whole run.
- On re-run: skip items with good output already written; retry `.error.json`.
- If a server dies mid-run: catch, write the sentinel, check whether it recovers
  before the next item. Don't auto-restart servers from script code.
- After >5 consecutive errors: stop and report. Don't burn hours against a dead
  server.
- Never delete output files to "force retry" — move or rename them.

---

## 7. The inference wrapper

Every project using local inference should have one wrapper module. Everything
else imports it; nothing calls the HTTP API directly. It handles endpoint health
and graceful degradation, a prompt-hash cache, a raw `llm_call()`, and a
`llm_json()` that strips reasoning blocks and markdown fences and recovers from
trailing-data parse errors.

Drop-in implementation: `reference/wrapper.py`.

---

## 8. Reasoning-model output suppression

Reasoning models emit a thinking block that consumes the `max_tokens` budget
before the answer appears. Where chain-of-thought isn't needed, suppress it —
but *how* is model- and backend-specific and changes between releases. Check
`reference/models.md`, then the model card, before assuming a method works.
Verify by inspecting one response, not by trusting the flag.

When thinking *is* useful, leave it on and raise `max_tokens` substantially to
give the model room to finish.

---

## 9. Cache behaviour

- Key: SHA-256 of `{messages, temperature}` — same inputs, same result.
- Directory: local to the project, gitignored. Losing it loses nothing.
- `use_cache=False` when re-running items that produced wrong output, so you
  don't replay the stale result.
- On JSON parse failure: evict the entry so the next call is fresh.
