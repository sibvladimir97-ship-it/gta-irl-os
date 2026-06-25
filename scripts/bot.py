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
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.daily_cycle import run_morning_cycle


ENV_FILE = ROOT / ".env"
INBOX_DIR = ROOT / "memory" / "inbox"
TARGET_FILE = ROOT / "modules" / "survival-economy" / "target.md"
MODE = "local fallback / no AI API"
MORNING_ACK = "Принял. Записал в память GTA IRL OS. Считаю миссию…"


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


def message_command(message):
    text = message_text(message).strip()
    return text.split(maxsplit=1)[0].split("@", 1)[0].lower()


def is_morning_message(message):
    return (
        message_command(message) == "/morning"
        or normalize_text(message_text(message)) == "доброе утро"
    )


def log_timing(event, started_at):
    elapsed_ms = (time.monotonic() - started_at) * 1000
    now = datetime.now().astimezone().strftime("%H:%M:%S")
    print(f"[{now}] {event} (+{elapsed_ms:.0f} мс)", flush=True)


def start_reply():
    return (
        "👋 GTA IRL OS подключён.\n\n"
        "Я сохраняю каждое сообщение в локальную память и работаю без AI API.\n\n"
        "Команды:\n"
        "/start — помощь\n"
        "/help — помощь\n"
        "/morning — запустить Daily Cycle\n"
        "/ping — проверить соединение\n"
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


def morning_result_reply(cycle_runner=None):
    cycle_runner = cycle_runner or run_morning_cycle
    try:
        cycle_result = cycle_runner()
    except Exception as error:
        print(
            f"Daily Cycle error: {type(error).__name__}",
            file=sys.stderr,
        )
        return (
            "⚠️ Не удалось запустить Daily Cycle. "
            "Проверь файлы target.md и branches.md, затем повтори /morning.\n\n"
            f"⚙️ Текущий режим: {MODE}."
        )

    return (
        f"{cycle_result}\n\n"
        f"⚙️ Текущий режим: {MODE}."
    )


def reply_for(message):
    command = message_command(message)
    if command in ("/start", "/help"):
        return start_reply()
    if command == "/ping":
        return "GTA IRL OS онлайн."
    if command == "/status":
        return status_reply()
    if is_morning_message(message):
        return MORNING_ACK
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


def send_morning_result(api, chat_id, cycle_runner, started_at):
    log_timing("Daily Cycle запущен", started_at)
    reply = morning_result_reply(cycle_runner)
    try:
        api.send_message(chat_id, reply)
        log_timing("Результат Daily Cycle отправлен", started_at)
    except (HTTPError, URLError, OSError, RuntimeError) as error:
        print(
            f"Не удалось отправить результат Daily Cycle: {type(error).__name__}",
            file=sys.stderr,
            flush=True,
        )


def process_update(api, update, cycle_runner=None, inbox_dir=INBOX_DIR):
    message = update.get("message")
    if not message:
        return None

    started_at = time.monotonic()
    log_timing("Сообщение получено", started_at)
    save_message(message, inbox_dir)
    log_timing("Сообщение сохранено в память", started_at)

    chat_id = message["chat"]["id"]
    if is_morning_message(message):
        api.send_message(chat_id, MORNING_ACK)
        log_timing("Быстрый ответ отправлен", started_at)
        worker = threading.Thread(
            target=send_morning_result,
            args=(api, chat_id, cycle_runner or run_morning_cycle, started_at),
            daemon=True,
            name=f"daily-cycle-{update.get('update_id', 'message')}",
        )
        worker.start()
        return worker

    api.send_message(chat_id, reply_for(message))
    log_timing("Ответ отправлен", started_at)
    return None


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
    class FakeAPI:
        def __init__(self):
            self.messages = []

        def send_message(self, chat_id, text):
            self.messages.append((chat_id, text, time.monotonic()))

    def sample_message(text):
        return {
            "date": int(time.time()),
            "from": {"id": 1, "first_name": "Тест"},
            "chat": {"id": 2},
            "text": text,
        }

    with tempfile.TemporaryDirectory() as temp_dir:
        inbox_dir = Path(temp_dir) / "inbox"
        cycle_dir = Path(temp_dir) / "daily"
        api = FakeAPI()

        def slow_cycle():
            assert api.messages[0][1] == MORNING_ACK
            time.sleep(0.1)
            return run_morning_cycle(daily_dir=cycle_dir)

        start = time.monotonic()
        worker = process_update(
            api,
            {"update_id": 1, "message": sample_message("Доброе утро")},
            cycle_runner=slow_cycle,
            inbox_dir=inbox_dir,
        )
        ack_elapsed = api.messages[0][2] - start
        assert ack_elapsed < 0.1
        assert worker is not None
        worker.join(timeout=2)
        assert not worker.is_alive()
        saved = next(inbox_dir.glob("*.md")).read_text(encoding="utf-8")
        assert "Доброе утро" in saved
        assert len(api.messages) == 2
        assert "Миссия дня" in api.messages[1][1]
        assert list(cycle_dir.glob("*.md"))
        assert MODE in api.messages[1][1]
        assert MODE in status_reply()
        error_reply = morning_result_reply(
            lambda: (_ for _ in ()).throw(RuntimeError("test failure"))
        )
        assert "Не удалось запустить Daily Cycle" in error_reply

        ordinary_api = FakeAPI()
        ordinary_start = time.monotonic()
        process_update(
            ordinary_api,
            {"update_id": 2, "message": sample_message("Обычное сообщение")},
            inbox_dir=inbox_dir,
        )
        assert time.monotonic() - ordinary_start < 0.1
        assert "сохранено" in ordinary_api.messages[0][1]
        assert reply_for(sample_message("/ping")) == "GTA IRL OS онлайн."
    print(
        "Smoke test passed: fast save, instant ack, background Daily Cycle, /ping."
    )


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
