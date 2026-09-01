# woodrow-skills

A small Claude Code marketplace. Currently one plugin: **local-inference**.

## local-gpu-inference

Most guidance on running local models stops at "here's how to load a GGUF."
This skill covers what happens after that: how to drive one or more GPUs from a
project without babysitting them.

It teaches Claude to start the inference servers itself and wait until they're
healthy, choose sampling parameters from the model's own card rather than a
lookup table, split genuinely independent work across GPUs so both cards run at
once, validate output with a second pass on a second card, cache by prompt hash,
and fail one item at a time instead of losing a long run.

It's methodology, not a project scaffold — it applies to whatever you're
building rather than generating one.

### Install

```
/plugin marketplace add woodrow-rosenbaum/woodrow-skills
/plugin install local-inference@woodrow-skills
```

Restart Claude Code. The skill loads on its own when a project touches local
inference; you don't need to invoke it.

### Assumptions

- One or more GPUs of roughly equal VRAM, each running its own server on its own
  port. Single-GPU works — the parallel sections just don't apply.
- An OpenAI-compatible endpoint: llama-server, LM Studio, or Ollama.
- Enough VRAM per card to hold the model you intend to run on it. Models too
  large to load twice change the picture; the skill says where and why.

Endpoints, model IDs, and launcher paths are configuration, not constants.
Nothing here is pinned to a particular machine.

### Worked example

Transcribing a recording, using both cards at once:

```python
# GPU 0: speech-to-text
segments = whisper_transcribe("recording.mp4", device="cuda:0")

# GPU 1: cleanup pass, simultaneously
cleaned = llm_call(
    build_cleanup_prompt(segments),
    temperature=0.2,      # decided for this task; see SKILL.md §2
    max_tokens=4096,
    endpoint=ENDPOINTS[1],
)
```

Two different models, one pass each, no queue. That shape — different models on
different cards rather than the same model twice — is often where this pattern
pays off most.

### Layout

```
.claude-plugin/marketplace.json
plugins/local-inference/
├── .claude-plugin/plugin.json
└── skills/local-gpu-inference/
    ├── SKILL.md              methodology — the durable part
    └── reference/
        ├── models.md         model-specific facts; dated, expected to go stale
        ├── launchers.md      per-backend launcher templates
        └── wrapper.py        drop-in inference wrapper
```

The split is deliberate. `SKILL.md` holds what stays true; `reference/models.md`
holds what doesn't, carries a review date, and says so at the top.

### Contributing

Corrections to `reference/models.md` are especially welcome — that file ages
fastest. Issues and PRs both fine.

## License

MIT
