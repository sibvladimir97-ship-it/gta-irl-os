"""
GTA IRL OS — AI service adapter.

All paid/free external AI calls should go through this module.
The caller gets None on unavailable AI, rate limit, or provider error.
Every attempted call is logged locally without secrets.
"""

import json
import os
from datetime import datetime, date

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


def load_ai_usage(day=None):
    """Load local AI usage records for a day."""
    if day is None:
        day = date.today().isoformat()
    if isinstance(day, date):
        day = day.isoformat()

    path = os.path.join(AI_USAGE_DIR, f"{day}.jsonl")
    if not os.path.exists(path):
        return []

    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                records.append({
                    "timestamp": "",
                    "provider": "unknown",
                    "model": "unknown",
                    "purpose": "corrupt_log_line",
                    "status": "error",
                    "meta": {},
                })
    return records


def ai_usage_summary(day=None):
    """Return aggregate AI usage stats for reporting."""
    records = load_ai_usage(day)
    summary = {
        "total": len(records),
        "by_status": {},
        "by_purpose": {},
        "by_model": {},
        "estimated_prompt_chars": 0,
        "estimated_reply_chars": 0,
        "estimated_audio_bytes": 0,
    }
    for record in records:
        status = record.get("status") or "unknown"
        purpose = record.get("purpose") or "unknown"
        model = record.get("model") or "unknown"
        meta = record.get("meta") or {}

        summary["by_status"][status] = summary["by_status"].get(status, 0) + 1
        summary["by_purpose"][purpose] = summary["by_purpose"].get(purpose, 0) + 1
        summary["by_model"][model] = summary["by_model"].get(model, 0) + 1
        summary["estimated_prompt_chars"] += int(meta.get("user_chars") or 0)
        summary["estimated_reply_chars"] += int(meta.get("reply_chars") or 0)
        summary["estimated_audio_bytes"] += int(meta.get("audio_bytes") or 0)
    return summary


def format_ai_usage_summary(day=None):
    """Format AI usage summary for Telegram."""
    report_day = day.isoformat() if isinstance(day, date) else (day or date.today().isoformat())
    summary = ai_usage_summary(report_day)
    lines = [
        f"🤖 *AI usage — {report_day}*",
        f"Всего попыток: `{summary['total']}`",
    ]

    if summary["by_status"]:
        lines.append("\n*Статусы:*")
        for status, count in sorted(summary["by_status"].items()):
            lines.append(f"• {status}: `{count}`")

    if summary["by_purpose"]:
        lines.append("\n*Назначение:*")
        for purpose, count in sorted(summary["by_purpose"].items(), key=lambda item: item[1], reverse=True):
            lines.append(f"• {purpose}: `{count}`")

    if summary["by_model"]:
        lines.append("\n*Модели:*")
        for model, count in sorted(summary["by_model"].items()):
            lines.append(f"• {model}: `{count}`")

    lines.append(
        "\n*Оценка объёма:*"
        f"\nPrompt chars: `{summary['estimated_prompt_chars']}`"
        f"\nReply chars: `{summary['estimated_reply_chars']}`"
        f"\nAudio bytes: `{summary['estimated_audio_bytes']}`"
    )

    if summary["total"] == 0:
        lines.append("\nAI сегодня не использовался.")
    return "\n".join(lines)
