"""Minimal Ollama chat client (works with Ollama Cloud and a self-hosted Ollama server).

Settings (from .env):
  OLLAMA_BASE_URL  https://ollama.com (Ollama Cloud) or http://localhost:11434 (self-hosted)
  OLLAMA_API_KEY   API key from ollama.com/settings/keys (Ollama Cloud only; leave blank for self-hosted)
  OLLAMA_MODEL     model name, e.g. gpt-oss:120b on Ollama Cloud or llama3.1:8b locally
"""
import json
import logging
import re

import requests
from django.conf import settings

log = logging.getLogger(__name__)


class LlmError(Exception):
    pass


def is_configured():
    return bool(settings.OLLAMA_BASE_URL and settings.OLLAMA_MODEL)


def chat(messages, json_mode=False, temperature=0.2):
    """Send a chat to Ollama and return the reply text. `json_mode` asks the model for a JSON object."""
    if not is_configured():
        raise LlmError("The AI assistant is not configured (OLLAMA_BASE_URL / OLLAMA_MODEL in .env).")
    headers = {"Content-Type": "application/json"}
    if settings.OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OLLAMA_API_KEY}"
    body = {"model": settings.OLLAMA_MODEL, "messages": messages, "stream": False,
            "options": {"temperature": temperature, "num_ctx": settings.OLLAMA_NUM_CTX}}
    if json_mode:
        body["format"] = "json"
    url = settings.OLLAMA_BASE_URL.rstrip("/") + "/api/chat"
    try:
        r = requests.post(url, json=body, headers=headers, timeout=settings.OLLAMA_TIMEOUT)
    except requests.RequestException as exc:
        log.warning("Ollama request failed: %s", exc)
        raise LlmError("Could not reach the AI service. Please try again in a moment.") from exc
    if r.status_code == 401:
        raise LlmError("The AI service rejected the API key (check OLLAMA_API_KEY).")
    if r.status_code == 402:
        log.warning("Ollama 402 (billing): %s", r.text[:300])
        raise LlmError("The AI account has no usage credits left. An admin needs to add credits or a plan at "
                       "ollama.com/plans (or point OLLAMA_BASE_URL at a self-hosted Ollama).")
    if r.status_code == 429:
        raise LlmError("The AI service is rate-limiting requests right now. Please try again in a minute.")
    if r.status_code == 404:
        raise LlmError(f"The AI model '{settings.OLLAMA_MODEL}' was not found (check OLLAMA_MODEL).")
    if r.status_code >= 400:
        log.warning("Ollama error %s: %s", r.status_code, r.text[:500])
        raise LlmError(f"The AI service returned an error ({r.status_code}).")
    try:
        return r.json()["message"]["content"]
    except (ValueError, KeyError) as exc:
        raise LlmError("Unexpected reply from the AI service.") from exc


def parse_json(text):
    """Parse a JSON object from a model reply (tolerates ```json fences and leading prose)."""
    if not text:
        return {}
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except ValueError:
                pass
    return {}
