"""
GTA IRL OS — AI service adapter.

All paid/free external AI calls should go through this module.
The caller gets None on unavailable AI, rate limit, or provider error.
Every attempted call is logged locally without secrets.
"""

import json
import os
from datetime import datetime

import requests

from config import (
    AI_USAGE_DIR,
    GROQ_KEY,
    GROQ_MODEL,
    GROQ_TRANSCRIBE_MODEL,
    GROQ_TRANSCRIBE_URL,
    GROQ_URL,
)


def _usage_path(now=None):
    now = now or datetime.utcnow()
    return os.path.join(AI_USAGE_DIR, f"{now.date().isoformat()}.jsonl")


def log_ai_usage(purpose, provider="groq", model=None, status="unknown", meta=None):
    """Append local AI usage record. Never store API keys or full prompts."""
    os.makedirs(AI_USAGE_DIR, exist_ok=True)
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "provider": provider,
        "model": model,
        "purpose": purpose,
        "status": status,
        "meta": meta or {},
    }
    with open(_usage_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def ask_ai(system, user, max_tokens=200, purpose="chat", meta=None):
    """Run a chat completion through the configured AI provider."""
    model = GROQ_MODEL
    safe_meta = {
        **(meta or {}),
        "user_chars": len(user or ""),
        "system_chars": len(system or ""),
        "max_tokens": max_tokens,
    }

    if not GROQ_KEY:
        log_ai_usage(purpose, model=model, status="no_key", meta=safe_meta)
        return None

    try:
        response = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
            },
            timeout=15,
        )
        if response.status_code == 429:
            log_ai_usage(purpose, model=model, status="rate_limited", meta=safe_meta)
            return None
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        log_ai_usage(purpose, model=model, status="ok", meta={
            **safe_meta,
            "reply_chars": len(text or ""),
        })
        return text
    except Exception as error:
        log_ai_usage(purpose, model=model, status="error", meta={
            **safe_meta,
            "error_type": type(error).__name__,
        })
        return None


def transcribe_audio(audio_data, language="ru", purpose="voice_transcription", meta=None):
    """Transcribe audio bytes through the configured AI provider."""
    model = GROQ_TRANSCRIBE_MODEL
    safe_meta = {
        **(meta or {}),
        "audio_bytes": len(audio_data or b""),
        "language": language,
    }

    if not GROQ_KEY:
        log_ai_usage(purpose, model=model, status="no_key", meta=safe_meta)
        return None

    try:
        response = requests.post(
            GROQ_TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            files={"file": ("voice.ogg", audio_data, "audio/ogg")},
            data={"model": model, "language": language},
            timeout=30,
        )
        if response.status_code == 429:
            log_ai_usage(purpose, model=model, status="rate_limited", meta=safe_meta)
            return None
        response.raise_for_status()
        text = response.json().get("text", "").strip()
        log_ai_usage(purpose, model=model, status="ok", meta={
            **safe_meta,
            "reply_chars": len(text or ""),
        })
        return text
    except Exception as error:
        log_ai_usage(purpose, model=model, status="error", meta={
            **safe_meta,
            "error_type": type(error).__name__,
        })
        return None
