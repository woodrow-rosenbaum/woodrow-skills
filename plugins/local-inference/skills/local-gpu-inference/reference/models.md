# Model-specific notes

**This file goes stale. The methodology in SKILL.md does not.**

Everything here is a snapshot of particular model families at a particular time.
Treat it as worked examples of *how* to read a model card, not as current fact.
Always check the actual card for the model you are loading.

Last reviewed: 2026-09.

---

## Sampling guidance is per-family, and the differences are large

| Family | Card guidance | Note |
|---|---|---|
| Qwen3.8 (thinking) | temp 1.0, top_p 0.95, top_k 20 | Driving toward 0.0 degrades it |
| Qwen3.8 (instruct) | temp 0.7, top_p 0.80, presence_penalty 1.5 | |
| DeepSeek-R1 family | temp 0.5–0.7 (0.6 typical) | Below this it loops or degrades |

The pattern worth internalising: reasoning-tuned models generally want *higher*
temperature than intuition suggests, because their reliability comes from the
reasoning pass rather than from greedy decoding. A near-zero temperature that
improves a non-reasoning model can make a reasoning model measurably worse.

---

## Reasoning-block suppression

Methods, roughly in order of reliability, all of which need verifying against
the actual backend build:

1. **Assistant pre-fill** — append `{"role": "assistant", "content":
   "<think>\n\n</think>\n"}`. Works where the model uses literal `<think>` tags.
   Fails on models whose template uses different markers.
2. **Template kwargs** — `chat_template_kwargs: {"enable_thinking": false}`.
   Correct where supported, but some builds route the reasoning to
   `reasoning_content` while still spending the token budget, leaving `content`
   empty. Verify one response before trusting it across a batch.
3. **Effort levels** — newer models expose named levels rather than a boolean.

Whichever you use, confirm by inspecting a single full response: check that
`content` is non-empty and that `usage.completion_tokens` is in the range you
expect for the answer alone.

---

## Sizing a model to available VRAM

Dense models: total parameters × bits-per-weight ÷ 8 ≈ weight size in GB, plus
KV cache. At Q4_K_M, roughly 0.55–0.6 GB per billion parameters. Leave several
GB of headroom per GPU for the KV cache — more for long contexts.

Mixture-of-experts models need different arithmetic, and it is easy to get
wrong in a way that costs real throughput:

- **All weights must be resident**, in VRAM or system RAM. MoE does not stream
  from disk on demand. Size by *total* parameters.
- **Speed comes from active parameters**, which is why a large MoE can decode at
  the rate of a small dense model.
- **The expert FFNs are nearly all the weights.** The attention/dense trunk is
  frequently a small single-digit share of the total. That trunk belongs on GPU;
  the experts are what you offload.
- **Backends split by layer, not by tensor class, unless told otherwise.**
  Getting trunk-on-GPU / experts-in-RAM requires an explicit flag
  (`--n-cpu-moe N`, or an `--override-tensor` regex matching the expert
  tensors). It is not what automatic offload does.
- **Put as many experts in VRAM as fit.** Routing re-selects experts every
  token, so there is no stable working set to cache. The share of experts
  resident in VRAM is roughly the share of fetches running at VRAM bandwidth
  rather than system-RAM bandwidth. That share is the throughput dial.
- **Two copies need twice the RAM.** A model near the size of system memory can
  only run as one instance, which forfeits the per-GPU work assignment in §3.

Check that the backend actually supports the architecture before planning
around it. Support for a new architecture lands in llama.cpp — and therefore in
LM Studio and Ollama — some weeks after weights are published, and quantisations
released before then may be untested.
