"""
inference_wrapper.py — single entry point for local GPU inference.

Drop into a project and adapt. Everything else imports this; nothing calls the
HTTP API directly.

Configuration comes from the environment so the same code runs on other
people's hardware:

    LLM_ENDPOINTS   comma-separated, one per GPU
                    default "http://localhost:1234/v1,http://localhost:1235/v1"
    LLM_MODEL_ID    as the backend reports it at /v1/models
    LLM_API_KEY     most local backends ignore this
    LLM_CACHE_DIR   defaults to ./cache next to this file

Note there is deliberately no default temperature. Sampling is a decision for
the task and the model card, so callers must state it. See SKILL.md section 2.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional

ENDPOINTS: list[str] = [
    ep.strip()
    for ep in os.environ.get(
        "LLM_ENDPOINTS",
        "http://localhost:1234/v1,http://localhost:1235/v1",
    ).split(",")
    if ep.strip()
]
MODEL_ID = os.environ.get("LLM_MODEL_ID", "local-model")
API_KEY = os.environ.get("LLM_API_KEY", "not-needed")
CACHE_DIR = Path(os.environ.get("LLM_CACHE_DIR", Path(__file__).parent / "cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("inference_wrapper")

_rr_lock = threading.Lock()
_rr_idx = 0


# --- endpoint health -------------------------------------------------------

def _alive(ep: str) -> bool:
    try:
        req = urllib.request.Request(
            f"{ep}/models", headers={"Authorization": f"Bearer {API_KEY}"}
        )
        urllib.request.urlopen(req, timeout=3)
        return True
    except Exception:
        return False


def ensure_servers(endpoints: Optional[Iterable[str]] = None) -> list[str]:
    """Return reachable endpoints. Raise if none are. Warn if degraded."""
    eps = list(endpoints or ENDPOINTS)
    healthy = [ep for ep in eps if _alive(ep)]
    if not healthy:
        raise RuntimeError(f"No inference servers reachable. Expected: {eps}")
    if len(healthy) < len(eps):
        down = [ep for ep in eps if ep not in healthy]
        logger.warning("Degraded mode — unreachable: %s", down)
    return healthy


def _next_ep(healthy: list[str]) -> str:
    global _rr_idx
    with _rr_lock:
        ep = healthy[_rr_idx % len(healthy)]
        _rr_idx += 1
    return ep


# --- cache -----------------------------------------------------------------

def _cache_key(messages: Any, temperature: float) -> str:
    blob = json.dumps({"m": messages, "t": temperature}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"llm_{key}.json"


def _cache_load(key: str) -> Optional[dict]:
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        p.unlink(missing_ok=True)
        return None


def _cache_save(key: str, result: dict) -> None:
    _cache_path(key).write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )


# --- calls -----------------------------------------------------------------

def llm_call(
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    *,
    use_cache: bool = True,
    endpoint: Optional[str] = None,
    prefill: Optional[str] = None,
    timeout: int = 300,
    **extra: Any,
) -> dict:
    """
    One call to the local model.

    temperature and max_tokens are required — decide them per task from the
    model card rather than inheriting a default.

    prefill: optional assistant-turn pre-fill, e.g. an empty reasoning block to
    suppress chain-of-thought. Model-specific; see reference/models.md.
    extra: any further API params (top_p, repeat_penalty, seed, ...).

    Returns {content, usage, elapsed_s, cached, cache_key, endpoint_used}.
    """
    key = _cache_key(messages, temperature)
    if use_cache:
        hit = _cache_load(key)
        if hit:
            hit["cached"] = True
            return hit

    api = endpoint or _next_ep(ensure_servers())
    msgs = list(messages)
    if prefill:
        msgs.append({"role": "assistant", "content": prefill})

    payload = {
        "model": MODEL_ID,
        "messages": msgs,
        "temperature": temperature,
        "max_tokens": max_tokens,
        **extra,
    }
    req = urllib.request.Request(
        f"{api}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
        method="POST",
    )

    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = json.loads(r.read())

    content = raw["choices"][0]["message"]["content"]
    usage = raw.get("usage", {})
    result = {
        "content": content,
        "usage": usage,
        "elapsed_s": round(time.time() - t0, 2),
        "cached": False,
        "cache_key": key,
        "endpoint_used": api,
    }
    logger.info(
        "OK %.1fs in=%s out=%s ep=%s",
        result["elapsed_s"],
        usage.get("prompt_tokens", 0),
        usage.get("completion_tokens", 0),
        api,
    )
    if use_cache and content:
        _cache_save(key, result)
    return result


def llm_json(messages: list[dict], **kw: Any) -> Any:
    """
    llm_call, parsed as JSON. Strips reasoning blocks and markdown fences, and
    recovers from trailing data after a valid payload. Evicts the cache entry on
    parse failure so a retry gets a fresh response.
    """
    r = llm_call(messages, **kw)
    c = r["content"]

    if "</think>" in c:
        c = c.split("</think>")[-1]
    c = c.strip()

    if c.startswith("```"):
        lines = c.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        c = "\n".join(lines).strip()

    best = None
    for open_c, close_c in (("{", "}"), ("[", "]")):
        i = c.find(open_c)
        if i != -1:
            j = c.rfind(close_c)
            if j > i and (best is None or i < best[0]):
                best = (i, j)
    if best:
        c = c[best[0] : best[1] + 1]

    try:
        return json.loads(c)
    except json.JSONDecodeError as e:
        if "Extra data" in str(e):
            try:
                parsed, _ = json.JSONDecoder().raw_decode(c.strip())
                return parsed
            except Exception:
                pass
        _cache_path(r["cache_key"]).unlink(missing_ok=True)
        raise ValueError(f"Non-JSON response: {e}\n{c[:500]}") from e
