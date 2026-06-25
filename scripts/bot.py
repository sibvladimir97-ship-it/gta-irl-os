#!/usr/bin/env python3
"""GTA IRL OS Telegram inbox bot.

Runs with the Python standard library and Telegram Bot API only.
No AI API or paid service is required.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
INBOX_DIR = ROOT / "memory" / "inbox"
TARGET_FILE = ROOT / "modules" / "survival-economy" / "target.md"
BRANCHES_FILE = ROOT / "modules" / "survival-economy" / "branches.md"
MODE = "local fallback / no AI API"


def load_env(path=ENV_FILE):
    """Load simple KEY=VALUE entries without overwriting shell variables."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value.startswith(("'", '"')):
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def read_text(path):
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def table_value(text, *labels):
    for label in labels:
        match = re.search(
            rf"\|\s*{re.escape(label)}\s*\|\s*(.+?)\s*\|",
            text,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip()
    return None


def number_value(value):
    if not value:
        return 0
    match = re.search(r"\d+(?:[.,]\d+)?", value.replace(",", ""))
    return float(match.group()) if match else 0


def system_status():
    text = read_text(TARGET_FILE)
    goal = number_value(table_value(text, "Goal amount"))
    balance = number_value(table_value(text, "Current balance"))
    deadline = table_value(text, "Deadline") or "не задан"
    mode_match = re.search(r"\*\*Mode:\*\*\s*(\w+)", text, re.IGNORECASE)
    gta_mode = mode_match.group(1).upper() if mode_match else "UNKNOWN"
    return {
        "goal": goal,
        "balance": balance,
        "deficit": max(goal - balance, 0),
        "deadline": deadline,
        "gta_mode": gta_mode,
    }


def mission_of_the_day():
    """Use the active money branch as the personal local mission."""
    text = read_text(BRANCHES_FILE)
    for section in re.split(r"^###\s+", text, flags=re.MULTILINE)[1:]:
        if (table_value(section, "Статус", "Status") or "").strip().lower() != "active":
            continue
        action = table_value(section, "Следующий шаг", "Next action")
        if action:
            return action.rstrip(".") + "."

    return "Выбрать одно главное действие и завершить его до конца дня."


def display_name(user):
    parts = [user.get("first_name", ""), user.get("last_name", "")]
    name = " ".join(part for part in parts if part).strip()
    return name or user.get("username") or "Неизвестный пользователь"


def message_text(message):
    if message.get("text"):
        return message["text"]
    if message.get("caption"):
        return message["caption"]
    content_type = next(
        (
            key
            for key in (
                "photo",
                "video",
                "voice",
                "audio",
                "document",
                "sticker",
                "location",
                "contact",
            )
            if key in message
        ),
        "non-text",
    )
    return f"[{content_type}]"


def save_message(message, inbox_dir=INBOX_DIR):
    """Append one Telegram message to today's Markdown inbox."""
    timestamp = datetime.fromtimestamp(
        message.get("date", int(time.time()))
    ).astimezone()
    user = message.get("from", {})
    text = message_text(message).replace("\r\n", "\n").replace("\r", "\n")
    indented_text = text.replace("\n", "\n  ")

    inbox_dir.mkdir(parents=True, exist_ok=True)
    path = inbox_dir / f"{timestamp.date().isoformat()}.md"
    if not path.exists():
        path.write_text(
            f"# Telegram inbox — {timestamp.date().isoformat()}\n\n",
            encoding="utf-8",
        )

    entry = (
        f"- **{timestamp.strftime('%H:%M:%S %z')}** "
        f"— {display_name(user)}"
        f" (user_id: {user.get('id', 'unknown')}, "
        f"chat_id: {message.get('chat', {}).get('id', 'unknown')})\n"
        f"  {indented_text}\n\n"
    )
    with path.open("a", encoding="utf-8") as inbox:
        inbox.write(entry)
    return path


def normalize_text(text):
    return re.sub(r"[!.,?…]+$", "", text.strip().casefold())


def start_reply():
    return (
        "👋 GTA IRL OS подключён.\n\n"
        "Я сохраняю каждое сообщение в локальную память и работаю без AI API.\n\n"
        "Команды:\n"
        "/start — помощь\n"
        "/help — помощь\n"
        "/status — статус системы\n\n"
        "Напиши «Доброе утро», чтобы получить личную миссию дня."
    )


def status_reply():
    status = system_status()
    return (
        f"📍 GTA IRL OS: {status['gta_mode']}\n"
        f"💰 Баланс: {status['balance']:,.0f} THB\n"
        f"📉 Дефицит: {status['deficit']:,.0f} THB\n"
        f"⏰ Дедлайн: {status['deadline']}\n"
        f"⚙️ Режим бота: {MODE}"
    )


def morning_reply():
    return (
        "✅ Событие «Доброе утро» сохранено в память GTA IRL OS.\n\n"
        f"🎯 Личная миссия дня: {mission_of_the_day()}\n\n"
        f"⚙️ Текущий режим: {MODE}."
    )


def reply_for(message):
    text = message_text(message).strip()
    command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
    if command in ("/start", "/help"):
        return start_reply()
    if command == "/status":
        return status_reply()
    if normalize_text(text) == "доброе утро":
        return morning_reply()
    return (
        "✅ Сообщение сохранено в память GTA IRL OS.\n"
        "Напиши «Доброе утро» для миссии дня или используй /status."
    )


class TelegramAPI:
    def __init__(self, token, timeout=40):
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.timeout = timeout

    def call(self, method, **params):
        data = urlencode(params).encode("utf-8")
        request = Request(f"{self.base_url}/{method}", data=data)
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram API error in {method}")
        return payload["result"]

    def get_updates(self, offset=None):
        params = {"timeout": 30, "allowed_updates": json.dumps(["message"])}
        if offset is not None:
            params["offset"] = offset
        return self.call("getUpdates", **params)

    def send_message(self, chat_id, text):
        return self.call("sendMessage", chat_id=chat_id, text=text)


def process_update(api, update):
    message = update.get("message")
    if not message:
        return
    save_message(message)
    api.send_message(message["chat"]["id"], reply_for(message))


def run_bot(token):
    api = TelegramAPI(token)
    offset = None
    print(f"GTA IRL OS Telegram bot started — mode: {MODE}")
    print("Listening for messages. Press Ctrl+C to stop.")

    while True:
        try:
            for update in api.get_updates(offset):
                offset = update["update_id"] + 1
                try:
                    process_update(api, update)
                except (HTTPError, URLError, OSError, RuntimeError) as error:
                    print(
                        f"Could not process update {update.get('update_id')}: "
                        f"{type(error).__name__}",
                        file=sys.stderr,
                    )
        except KeyboardInterrupt:
            print("\nBot stopped.")
            return
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as error:
            print(
                f"Telegram connection error: {type(error).__name__}; retrying...",
                file=sys.stderr,
            )
            time.sleep(3)


def smoke_test():
    """Exercise persistence and replies without Telegram or real memory files."""
    sample = {
        "date": int(time.time()),
        "from": {"id": 1, "first_name": "Тест"},
        "chat": {"id": 2},
        "text": "Доброе утро",
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        path = save_message(sample, Path(temp_dir))
        saved = path.read_text(encoding="utf-8")
        reply = reply_for(sample)
        assert "Доброе утро" in saved
        assert "Личная миссия дня" in reply
        assert MODE in reply
        assert MODE in status_reply()
    print("Smoke test passed: inbox save, morning mission, /status, local mode.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="test local behavior without connecting to Telegram",
    )
    args = parser.parse_args()

    if args.smoke_test:
        smoke_test()
        return 0

    load_env()
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    if not token:
        print(
            "TELEGRAM_TOKEN is missing. Copy .env.example to .env and add the token.",
            file=sys.stderr,
        )
        return 1

    run_bot(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
