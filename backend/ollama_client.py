"""
Client for the internal Ollama LLM server used by the dashboard AI chatbot.
Server sits on the internal network (no public exposure). If it requires
HTTP Basic Auth, the username/password are read from backend/.env — the
password is stored Fernet-encrypted (see scripts/setup_ollama_credentials.ps1
and database._pw_fernet, which use the same DB_ENCRYPT_KEY).
"""
import os
import json
import requests
from requests.auth import HTTPBasicAuth

from database import _decrypt_pw

OLLAMA_HOST     = os.getenv("OLLAMA_HOST", "10.114.36.10").strip()
OLLAMA_PORT     = os.getenv("OLLAMA_PORT", "11434").strip()
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "").strip()
OLLAMA_USER     = os.getenv("OLLAMA_USER", "").strip()
OLLAMA_PASS_ENC = os.getenv("OLLAMA_PASS_ENC", "").strip()
# Used when OLLAMA_MODEL is not set and this model is installed (benchmark 2026-10-09: qwen2.5:14b was as fast as
# the 8B model but more faithful to the data; the 32B was ~10x slower with no better answers).
OLLAMA_PREFERRED_MODEL = os.getenv("OLLAMA_PREFERRED_MODEL", "qwen2.5:14b").strip()
# How long Ollama keeps the model loaded after a request (avoids ~1 min cold start on the first question).
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "60m").strip()

_BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
_TIMEOUT  = (5, 240)  # (connect, read) seconds — local 32B models can take minutes on longer prompts

_cached_model: str = ""


def _auth():
    if OLLAMA_USER and OLLAMA_PASS_ENC:
        return HTTPBasicAuth(OLLAMA_USER, _decrypt_pw(OLLAMA_PASS_ENC))
    return None


def _resolve_model() -> str:
    """OLLAMA_MODEL if configured; else OLLAMA_PREFERRED_MODEL when installed; else the first installed model."""
    global _cached_model
    if OLLAMA_MODEL:
        return OLLAMA_MODEL
    if _cached_model:
        return _cached_model
    resp = requests.get(f"{_BASE_URL}/api/tags", auth=_auth(), timeout=_TIMEOUT)
    resp.raise_for_status()
    models = resp.json().get("models") or []
    if not models:
        raise RuntimeError("No models are installed on the Ollama server")
    names = [m["name"] for m in models]
    _cached_model = OLLAMA_PREFERRED_MODEL if OLLAMA_PREFERRED_MODEL in names else names[0]
    return _cached_model


def chat(messages: list[dict]) -> str:
    """Send a chat completion request to Ollama and return the assistant's reply text.

    Uses stream=True against Ollama even though we return one final string: with the
    local 32B models this server runs, generation is slow (~2 tok/s), so a non-streamed
    request produces zero bytes on the wire until the whole reply is done, which blew
    past our read timeout. Streaming means tokens trickle in continuously, so the
    connection never sits idle long enough to hit the read timeout, however long the
    full reply takes. num_predict caps the reply length as a safety net either way.
    """
    payload = {
        "model":    _resolve_model(),
        "messages": messages,
        "stream":   True,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options":  {"num_predict": 600},
    }
    resp = requests.post(f"{_BASE_URL}/api/chat", json=payload, auth=_auth(), timeout=_TIMEOUT, stream=True)
    resp.raise_for_status()
    parts: list[str] = []
    for line in resp.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        if chunk.get("error"):
            raise RuntimeError(chunk["error"])
        content = (chunk.get("message") or {}).get("content", "")
        if content:
            parts.append(content)
        if chunk.get("done"):
            break
    return "".join(parts).strip()


def configured_model() -> str:
    """The model the dashboard uses (OLLAMA_MODEL, or the auto-picked first installed one)."""
    return _resolve_model()


def list_models() -> list:
    """Installed models with size/parameter count/quantization (from /api/tags)."""
    resp = requests.get(f"{_BASE_URL}/api/tags", auth=_auth(), timeout=_TIMEOUT)
    resp.raise_for_status()
    out = []
    for m in resp.json().get("models") or []:
        d = m.get("details") or {}
        out.append({
            "name": m.get("name"),
            "size_gb": round((m.get("size") or 0) / 1024 ** 3, 1),
            "parameters": d.get("parameter_size"),
            "quantization": d.get("quantization_level"),
            "family": d.get("family"),
            "modified": (m.get("modified_at") or "")[:10],
        })
    return out


def running_models() -> list:
    """Models currently loaded in memory (from /api/ps); size_vram_gb shows how much sits on the GPU."""
    resp = requests.get(f"{_BASE_URL}/api/ps", auth=_auth(), timeout=_TIMEOUT)
    resp.raise_for_status()
    return [{
        "name": m.get("name"),
        "size_gb": round((m.get("size") or 0) / 1024 ** 3, 1),
        "size_vram_gb": round((m.get("size_vram") or 0) / 1024 ** 3, 1),
        "expires_at": (m.get("expires_at") or "")[:19],
    } for m in (resp.json().get("models") or [])]


def chat_ex(messages: list, model: str = None, num_predict: int = 600, temperature: float = None, keep_alive: str = None) -> dict:
    """Like chat() but for a chosen model, returning timing: {text, seconds, tokens, tokens_per_s}."""
    import time
    options = {"num_predict": num_predict}
    if temperature is not None:
        options["temperature"] = temperature
    payload = {"model": model or _resolve_model(), "messages": messages, "stream": True, "options": options,
               "keep_alive": keep_alive or OLLAMA_KEEP_ALIVE}
    t0 = time.time()
    resp = requests.post(f"{_BASE_URL}/api/chat", json=payload, auth=_auth(), timeout=_TIMEOUT, stream=True)
    resp.raise_for_status()
    parts, last = [], {}
    for line in resp.iter_lines():
        if not line:
            continue
        chunk = json.loads(line)
        if chunk.get("error"):
            raise RuntimeError(chunk["error"])
        content = (chunk.get("message") or {}).get("content", "")
        if content:
            parts.append(content)
        if chunk.get("done"):
            last = chunk
            break
    tokens = last.get("eval_count") or 0
    ev_s = (last.get("eval_duration") or 0) / 1e9
    return {"text": "".join(parts).strip(), "seconds": round(time.time() - t0, 1), "tokens": tokens,
            "tokens_per_s": round(tokens / ev_s, 1) if ev_s else None}
