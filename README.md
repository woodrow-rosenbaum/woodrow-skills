# woodrow-skills

A small Claude Code marketplace. Currently two plugins: **local-inference** and
**resource-raiser**.

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

## resource-raiser

Routes natural-language questions about US nonprofits and public data (501(c)(3)
status, IRS Form 990 financials, Census demographics, CDC PLACES health stats,
Treasury figures, USASpending awards, NIH grants, College Scorecard, FEMA
declarations) to a local [TechSoup/resource-raiser](https://github.com/TechSoup/resource-raiser)
deployment instead of a web search or a training-data guess — grounded, cited,
and typically free to run.

It only activates if it can actually find a deployment in the current project;
otherwise it steps out of the way. It also knows to distrust certain answer
shapes: a documented, reproducible bug (a rolling multi-year IRS total getting
reported as if it were a single year's figure, with nothing downstream catching
the mislabel) is recorded in `reference/known-issues.md` so the skill flags it
instead of repeating it with false confidence.

### Install

```
/plugin marketplace add woodrow-rosenbaum/woodrow-skills
/plugin install resource-raiser@woodrow-skills
```

### Assumptions

- A resource-raiser deployment already exists somewhere the project documents
  (its own CLAUDE.md/README, or a `resource-raiser/` checkout plus launcher
  scripts). This skill doesn't stand one up from nothing.
- The deployment exposes the standard `/health` and `/ask` endpoints.

### Layout

```
plugins/resource-raiser/
├── .claude-plugin/plugin.json
└── skills/resource-raiser-query/
    ├── SKILL.md              methodology — the durable part
    └── reference/
        ├── deployment.md     one worked example; dated, expected to go stale
        └── known-issues.md   trust-calibration caveats; dated
```

### Contributing

If you find a resource-raiser answer that looked right but wasn't, corrections
to `reference/known-issues.md` are especially welcome.

## License

MIT
