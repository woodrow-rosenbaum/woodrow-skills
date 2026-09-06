# One worked deployment (dated — check before trusting)

Last verified: 2026-09-06, on a dual-RTX-4090 Windows rig. This is an *example* of the shape a
deployment takes, not a template to copy verbatim — your paths, model choice, and even which
dataset families are connected will differ. Endpoints, model IDs, and launcher paths are
configuration, not constants.

## Layout on that machine

```
<lab>/resource-raiser/         vendored upstream checkout (harness.py, app.py, planner.py, ...)
<lab>/local/env.local.ps1      env vars (OPENAI_BASE_URL etc.), dot-source before anything else
<lab>/local/Preflight.ps1      verifies model server(s) + embeddings endpoint + free ports
<lab>/local/Start-Stack.ps1    starts the discovery service (:8088) and the web app (:8099)
<lab>/local/Ask.ps1            "Ask.ps1 'question'" -- prints the answer, saves full JSON
```

## Serving the models

LM Studio, one process, both a chat model and an embedding model loaded simultaneously under
different identifiers:

```powershell
$lms = "$env:USERPROFILE\.lmstudio\bin\lms.exe"
& $lms server start --port 1234
& $lms load "<chat-model-id>" --identifier chat --gpu max --context-length 16384 -y
& $lms load "<embedding-model-id>" --identifier embed --gpu max --context-length 4096 -y
```

**Gotcha, confirmed on this machine:** a launcher script that does
`& $lms server start --port 1234 2>&1 | Write-Host` under `$ErrorActionPreference = "Stop"` will
abort immediately — LM Studio prints its own "Success! Server is now running..." message to
stderr, and PowerShell 5.1 wraps *any* redirected native-command stderr line as a terminating
`NativeCommandError`, regardless of the process's real exit code. The fix is to call the CLI
directly without the `2>&1 | Write-Host` wrapper, not to treat the reported "error" as real. This
generalizes beyond LM Studio: any Windows launcher script combining `2>&1` redirection of a
native exe with `-ErrorAction Stop`/`$ErrorActionPreference = "Stop"` is at risk of this.

Then bring up the discovery service and web app (both plain `uvicorn` processes in this case),
and confirm both respond before querying:

```powershell
. "<lab>/local/env.local.ps1"
& "<lab>/local/Preflight.ps1"
& "<lab>/local/Start-Stack.ps1"
```

## Asking

```powershell
& "<lab>/local/Ask.ps1" "Is the Sierra Club a 501(c)(3) nonprofit?"
```

or the raw HTTP call documented in `SKILL.md` step 4, against `http://127.0.0.1:8099/ask`.

## What was actually connected on this deployment

Nonprofit BMF (ProPublica + GivingTuesday mirrors), nonprofit 990 financials, Census, CDC PLACES,
Treasury, USASpending, NIH RePORTER, College Scorecard, FEMA. SEC EDGAR was parked (Windows
MAX_PATH issue generating ~8,100 leaves under a deeply-nested path) and the 13GB IRS grant graph
was not built. A different deployment may have a different subset — check the project's own
`GET /sources` or equivalent before assuming a family listed in `SKILL.md` is actually live.
