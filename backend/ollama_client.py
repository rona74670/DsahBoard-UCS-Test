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

_BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"
_TIMEOUT  = (5, 240)  # (connect, read) seconds — local 32B models can take minutes on longer prompts

_cached_model: str = ""


def _auth():
    if OLLAMA_USER and OLLAMA_PASS_ENC:
        return HTTPBasicAuth(OLLAMA_USER, _decrypt_pw(OLLAMA_PASS_ENC))
    return None


def _resolve_model() -> str:
    """Use OLLAMA_MODEL if configured, otherwise auto-pick the first installed model."""
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
    _cached_model = models[0]["name"]
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
