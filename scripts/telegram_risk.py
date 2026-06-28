"""
GTA IRL OS — Telegram safety reporting.

Stores local Telegram send/error events without message text or secrets.
The goal is operational visibility: rate limits, FloodWait risk, and send errors.
"""

import json
import os
from datetime import date, datetime

from config import (
    TELEGRAM_DAILY_ERROR_LIMIT,
    TELEGRAM_DAILY_SEND_LIMIT,
    TELEGRAM_EVENTS_DIR,
)


def _events_path(day=None):
    if day is None:
        day = date.today().isoformat()
    if isinstance(day, date):
        day = day.isoformat()
    return os.path.join(TELEGRAM_EVENTS_DIR, f"{day}.jsonl")


def log_telegram_event(event_type, status="unknown", channel="unknown", meta=None):
    """Append a Telegram operational event without message content."""
    os.makedirs(TELEGRAM_EVENTS_DIR, exist_ok=True)
    record = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event_type,
        "status": status,
        "channel": channel,
        "meta": meta or {},
    }
    with open(_events_path(), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def classify_telegram_error(error):
    """Return safe metadata for Telegram/Telethon errors."""
    error_type = type(error).__name__
    meta = {"error_type": error_type}
    seconds = getattr(error, "seconds", None)
    if seconds is not None:
        meta["flood_wait_seconds"] = seconds
    code = getattr(error, "code", None)
    if code is not None:
        meta["code"] = code
    return meta


def load_telegram_events(day=None):
    path = _events_path(day)
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
                    "event_type": "corrupt_log_line",
                    "status": "error",
                    "channel": "unknown",
                    "meta": {},
                })
    return records


def telegram_risk_summary(day=None):
    records = load_telegram_events(day)
    summary = {
        "total": len(records),
        "sends": 0,
        "errors": 0,
        "flood_waits": 0,
        "rate_waits": 0,
        "by_status": {},
        "by_event_type": {},
        "by_error_type": {},
        "risk_level": "low",
        "warnings": [],
    }

    for record in records:
        event_type = record.get("event_type") or "unknown"
        status = record.get("status") or "unknown"
        meta = record.get("meta") or {}
        error_type = meta.get("error_type")

        summary["by_status"][status] = summary["by_status"].get(status, 0) + 1
        summary["by_event_type"][event_type] = summary["by_event_type"].get(event_type, 0) + 1
        if event_type in ["telethon_send", "bot_send"]:
            summary["sends"] += 1
        if status == "error":
            summary["errors"] += 1
        if event_type == "rate_wait":
            summary["rate_waits"] += 1
        if error_type:
            summary["by_error_type"][error_type] = summary["by_error_type"].get(error_type, 0) + 1
            if "FloodWait" in error_type or meta.get("flood_wait_seconds") is not None:
                summary["flood_waits"] += 1

    if summary["sends"] >= TELEGRAM_DAILY_SEND_LIMIT:
        summary["warnings"].append(f"исходящих отправок ≥ дневного лимита {TELEGRAM_DAILY_SEND_LIMIT}")
    if summary["errors"] >= TELEGRAM_DAILY_ERROR_LIMIT:
        summary["warnings"].append(f"ошибок ≥ дневного лимита {TELEGRAM_DAILY_ERROR_LIMIT}")
    if summary["flood_waits"]:
        summary["warnings"].append("обнаружен FloodWait/похожее ограничение")

    if summary["flood_waits"] or summary["errors"] >= TELEGRAM_DAILY_ERROR_LIMIT:
        summary["risk_level"] = "high"
    elif summary["warnings"] or summary["rate_waits"]:
        summary["risk_level"] = "medium"
    return summary


def format_telegram_risk_summary(day=None):
    report_day = day.isoformat() if isinstance(day, date) else (day or date.today().isoformat())
    summary = telegram_risk_summary(report_day)
    risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(summary["risk_level"], "⚪")
    lines = [
        f"🛡 *Telegram risk — {report_day}*",
        f"Риск: {risk_icon} `{summary['risk_level']}`",
        f"Событий: `{summary['total']}`",
        f"Отправок: `{summary['sends']}`",
        f"Ошибок: `{summary['errors']}`",
        f"FloodWait: `{summary['flood_waits']}`",
        f"Rate waits: `{summary['rate_waits']}`",
    ]

    if summary["warnings"]:
        lines.append("\n*Предупреждения:*")
        for warning in summary["warnings"]:
            lines.append(f"• {warning}")

    if summary["by_error_type"]:
        lines.append("\n*Ошибки:*")
        for error_type, count in sorted(summary["by_error_type"].items(), key=lambda item: item[1], reverse=True):
            lines.append(f"• {error_type}: `{count}`")

    if summary["by_event_type"]:
        lines.append("\n*Типы событий:*")
        for event_type, count in sorted(summary["by_event_type"].items()):
            lines.append(f"• {event_type}: `{count}`")

    if summary["total"] == 0:
        lines.append("\nTelegram-событий сегодня ещё нет.")
    return "\n".join(lines)
