#!/usr/bin/env python3
"""
GTA IRL OS — Telegram Assistant Bot
Groq AI (llama-3.3-70b) + Whisper (голосовые) + файлы OS
В группах: отвечает только на @упоминания и реплаи на свои сообщения
"""

import os
import json
import re
import requests
import subprocess
import telebot
from datetime import date, datetime

# Импортируем воронку
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from offer_store import get_offer, update_offer
from negotiator import (
    create_deal, draft_first_message, update_stage, add_message,
    format_deal_card, get_deal, save_deal, list_deals, list_closed_deals, prepare_proposal,
    record_prepayment, plan_execution, start_execution, mark_delivered,
    record_final_payment, pipeline_summary, money_summary,
    prepare_followup, mark_followup_sent, list_followup_candidates,
    format_deal_timeline, close_deal, loss_summary,
)
from deal_pipeline import is_terminal_stage, stage_label

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL     = "llama-3.3-70b-versatile"
GROQ_URL       = "https://api.groq.com/openai/v1/chat/completions"
WHISPER_URL    = "https://api.groq.com/openai/v1/audio/transcriptions"
BOT_USERNAME   = "gta_irl_assistant_bot"

ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURVIVAL = os.path.join(ROOT, "modules", "survival-economy")
TARGET_FILE   = os.path.join(SURVIVAL, "target.md")
BRANCHES_FILE = os.path.join(SURVIVAL, "branches.md")
DAILY_DIR     = os.path.join(SURVIVAL, "daily")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
chat_history = {}


DEAL_ACTIONS = {
    "WAITING_REPLY": [
        ("✍️ Follow-up", "prepare_followup"),
        ("👻 Клиент пропал", "CLIENT_GHOSTED"),
        ("🪦 Lost: клиент пропал", "close_lost_client_ghosted"),
    ],
    "CLIENT_REPLIED": [
        ("🔍 Собирать ТЗ", "BRIEF_COLLECTING"),
        ("✅ ТЗ собрано", "BRIEF_READY"),
        ("❌ Отказаться", "REJECTED"),
    ],
    "BRIEF_COLLECTING": [
        ("✍️ Follow-up", "prepare_followup"),
        ("✅ ТЗ собрано", "BRIEF_READY"),
        ("👻 Клиент пропал", "CLIENT_GHOSTED"),
        ("❌ Не подходит", "close_rejected_not_fit"),
    ],
    "BRIEF_READY": [
        ("📋 Подготовить КП", "prepare_proposal"),
        ("📤 Делегировать", "DELEGATED"),
        ("❌ Нет бюджета/не подходит", "close_rejected_no_budget"),
    ],
    "PROPOSAL_DRAFTED": [
        ("📨 Отправить КП", "send_proposal"),
        ("📤 КП отправлено вручную", "PROPOSAL_SENT"),
        ("❌ Отказаться", "close_rejected_manual"),
    ],
    "PROPOSAL_SENT": [
        ("💳 Ждём предоплату", "PREPAYMENT_WAITING"),
        ("💰 Предоплата получена", "record_prepayment"),
        ("👻 Клиент пропал", "CLIENT_GHOSTED"),
    ],
    "PREPAYMENT_WAITING": [
        ("✍️ Follow-up", "prepare_followup"),
        ("💰 Предоплата получена", "record_prepayment"),
        ("👻 Клиент пропал", "CLIENT_GHOSTED"),
        ("🪦 Lost: клиент пропал", "close_lost_client_ghosted"),
    ],
    "PREPAYMENT_RECEIVED": [
        ("🧭 План исполнения", "plan_execution"),
        ("📤 Делегировать", "DELEGATED"),
        ("❌ Отказаться", "close_rejected_manual"),
    ],
    "EXECUTION_PLANNING": [
        ("⚙️ В работу", "start_execution"),
        ("📤 Делегировать", "DELEGATED"),
    ],
    "IN_PROGRESS": [
        ("📦 Сдано", "mark_delivered"),
        ("📤 Делегировать", "DELEGATED"),
    ],
    "DELIVERED": [
        ("🧾 Ждём доплату", "FINAL_PAYMENT_WAITING"),
        ("🏁 Закрыть успешно", "record_final_payment"),
    ],
    "FINAL_PAYMENT_WAITING": [
        ("✍️ Follow-up", "prepare_followup"),
        ("💰 Доплата получена", "record_final_payment"),
        ("🪦 Lost: не оплатил", "close_lost_no_budget"),
    ],
    "DELEGATED": [
        ("⚙️ В работе", "IN_PROGRESS"),
        ("📦 Сдано", "DELIVERED"),
        ("🏁 Закрыть успешно", "record_final_payment"),
        ("🪦 Lost: делегирование", "close_lost_delegated"),
    ],
    "CLIENT_GHOSTED": [
        ("✍️ Follow-up", "prepare_followup"),
        ("⏳ Вернуть в ожидание", "WAITING_REPLY"),
        ("🪦 Lost: клиент пропал", "close_lost_client_ghosted"),
    ],
}


def deal_keyboard(deal: dict):
    stage = deal.get("stage")
    if is_terminal_stage(stage):
        return None

    rows = []
    for label, next_stage in DEAL_ACTIONS.get(stage, []):
        rows.append([{"text": label, "callback_data": f"deal:{next_stage}:{deal['deal_id']}"}])

    rows.append([
        {"text": "🧾 Timeline", "callback_data": f"deal:timeline:{deal['deal_id']}"},
        {"text": "🔄 Обновить", "callback_data": f"deal:refresh:{deal['deal_id']}"},
    ])
    return {"inline_keyboard": rows}


def send_deal_card(chat_id, deal: dict, message_id=None):
    text = format_deal_card(deal)
    keyboard = deal_keyboard(deal)
    if message_id:
        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            parse_mode="Markdown",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    else:
        bot.send_message(
            chat_id,
            text,
            parse_mode="Markdown",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )


def send_client_message(deal: dict, text: str):
    """Send a confirmed outgoing message to the deal contact via Telethon."""
    username = deal.get("contact", {}).get("username")
    user_id = deal.get("contact", {}).get("user_id")
    target = username if username else int(user_id or 0)

    script = """
import asyncio
import json
import os
import sys
from telethon import TelegramClient

async def send():
    target = json.loads(sys.argv[1])
    text = sys.argv[2]
    client = TelegramClient(
        'scripts/parser_session',
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'),
    )
    await client.start()
    await client.send_message(target, text)
    await client.disconnect()

asyncio.run(send())
"""
    return subprocess.run(
        ["python3", "-c", script, json.dumps(target), text],
        capture_output=True,
        text=True,
        timeout=20,
        env={
            **os.environ,
            "TELEGRAM_API_ID": os.getenv("TELEGRAM_API_ID", ""),
            "TELEGRAM_API_HASH": os.getenv("TELEGRAM_API_HASH", ""),
        },
    )


# ── Проверка: нужно ли отвечать ──────────────────────────────────────────────

def should_respond(msg):
    """В личке — всегда. В группе — только @упоминание или реплай на бота."""
    # Личка
    if msg.chat.type == "private":
        return True, msg.text or ""

    # Группа — реплай на сообщение бота
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if msg.reply_to_message.from_user.username == BOT_USERNAME:
            text = msg.text or ""
            return True, text

    # Группа — упоминание @username
    mention = f"@{BOT_USERNAME}"
    text = msg.text or msg.caption or ""
    if mention.lower() in text.lower():
        clean = text.replace(mention, "").strip()
        return True, clean

    return False, ""


def should_respond_voice(msg):
    """Голосовые в группе — только реплай на бота."""
    if msg.chat.type == "private":
        return True
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if msg.reply_to_message.from_user.username == BOT_USERNAME:
            return True
    return False


# ── Файлы системы ─────────────────────────────────────────────────────────────

def read_file(path):
    return open(path).read() if os.path.exists(path) else ""

def read_today():
    path = os.path.join(DAILY_DIR, f"{date.today().isoformat()}.md")
    return read_file(path)

def build_system_context():
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""Ты — персональный ассистент GTA IRL OS, операционной системы жизни Владимира.
Текущее время: {now}

Отвечай на русском языке. Будь конкретным и честным.
Если пользователь говорит голосом — отвечай естественно, как в разговоре.

═══ ФИНАНСОВАЯ ЦЕЛЬ ═══
{read_file(TARGET_FILE)}

═══ ДЕНЕЖНЫЕ ВЕТКИ ═══
{read_file(BRANCHES_FILE)}

═══ ДНЕВНОЙ ФОКУС ═══
{read_today() or "Файл за сегодня ещё не создан."}

═══ СИСТЕМА ═══
Цикл: Collect → Classify → Update → Analyze → Prioritize → Collapse → Decide → Execute → Learn
Crisis Mode: дефицит >80% и <3 дней → только 1 активная ветка. Decide всегда принимает человек.
"""


# ── Парсеры ───────────────────────────────────────────────────────────────────

def parse_table_value(text, *fields):
    for field in fields:
        m = re.search(rf"\|\s*{re.escape(field)}\s*\|\s*(.+?)\s*\|", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None

def parse_number(s):
    if not s:
        return 0
    s = s.replace(",", "").replace("~", "").replace("THB", "").strip()
    m = re.search(r"[\d]+(?:\.\d+)?", s)
    return float(m.group()) if m else 0

def parse_target():
    text = read_file(TARGET_FILE)
    if not text:
        return None
    goal    = parse_number(parse_table_value(text, "Goal amount"))
    balance = parse_number(parse_table_value(text, "Current balance"))
    deadline = parse_table_value(text, "Deadline")
    mode_m  = re.search(r"\*\*Mode:\*\*\s*(\w+)", text)
    mode    = mode_m.group(1).upper() if mode_m else "NORMAL"
    deficit = goal - balance if goal else 0
    days_remaining = None
    if deadline:
        clean = re.sub(r"\s*\(.*?\)", "", deadline).strip()
        try:
            days_remaining = (date.fromisoformat(clean) - date.today()).days
        except ValueError:
            pass
    obligations = []
    for row in re.finditer(
        r"\|\s*([^|]+?)\s*\|\s*([\d,~]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(yes|no)\s*\|",
        text, re.IGNORECASE
    ):
        name, amount, due, dtype, layer, paid = [g.strip() for g in row.groups()]
        if paid.lower() == "no":
            obligations.append({"name": name, "amount": parse_number(amount), "due": due, "type": dtype})
    return {"goal": goal, "balance": balance, "deficit": deficit,
            "deadline": deadline, "days_remaining": days_remaining,
            "mode": mode, "obligations": obligations}

def parse_branches():
    text = read_file(BRANCHES_FILE)
    if not text:
        return []
    branches = []
    for section in re.split(r"^### ", text, flags=re.MULTILINE)[1:]:
        lines = section.strip().split("\n")
        body  = "\n".join(lines[1:])
        status = re.sub(r"\*+", "", parse_table_value(body, "Статус", "Status") or "unknown").strip()
        branches.append({
            "id":            lines[0].strip(),
            "name":          parse_table_value(body, "Название", "Name") or lines[0].strip(),
            "status":        status,
            "earliest_income": parse_table_value(body, "Ближайший доход", "Earliest income") or "—",
            "blocking":      parse_table_value(body, "Блокеры", "Blocking factors") or "—",
            "next_action":   parse_table_value(body, "Следующий шаг", "Next action") or "—",
            "frozen_reason": parse_table_value(body, "Причина заморозки", "Frozen reason") or None,
        })
    return branches


# ── Форматирование ────────────────────────────────────────────────────────────

def fmt_status(t):
    if not t:
        return "❌ target.md не найден"
    mode_text = "КРИЗИС 🚨" if t["mode"] == "CRISIS" else "НОРМАЛЬНЫЙ 🟡"
    lines = [f"*Режим: {mode_text}*", "",
             f"💰 Баланс:    `{t['balance']:,.0f} THB`",
             f"🎯 Цель:      `{t['goal']:,.0f} THB`",
             f"📉 Дефицит:   `{t['deficit']:,.0f} THB`"]
    if t["days_remaining"] is not None:
        dr = t["days_remaining"]
        icon = "🔴" if dr <= 2 else "🟡" if dr <= 7 else "🟢"
        lines.append(f"⏰ Дедлайн:   {t['deadline']}  {icon} {dr} дн.")
        if dr > 0 and t["deficit"] > 0:
            lines.append(f"📊 Нужно/день: `{t['deficit']/dr:,.0f} THB`")
    if t["obligations"]:
        lines += ["", "*Неоплачено:*"]
        for ob in t["obligations"]:
            icon = "🔴" if "hard" in ob["type"].lower() else "🟡"
            lines.append(f"{icon} {ob['name']}: `{ob['amount']:,.0f} THB`  до {ob['due']}")
    return "\n".join(lines)

def fmt_branches(branches):
    active = [b for b in branches if b["status"].lower() == "active"]
    frozen = [b for b in branches if b["status"].lower() == "frozen"]
    lines = []
    if active:
        lines.append("*🟢 АКТИВНЫЕ*")
        for b in active:
            lines += ["", f"● *{b['name']}*",
                      f"  Шаг: {b['next_action']}",
                      f"  Доход: {b['earliest_income']}"]
            if b["blocking"] != "—":
                lines.append(f"  ⚠️ {b['blocking']}")
    if frozen:
        lines += ["", "*⚫ ЗАМОРОЖЕНЫ*"]
        for b in frozen:
            lines.append(f"○ {b['name']} — _{b['frozen_reason'] or '—'}_")
    return "\n".join(lines) or "Ветки не найдены"

def fmt_collapse(t, branches):
    today = date.today().isoformat()
    now   = datetime.now().strftime("%H:%M")
    active = [b for b in branches if b["status"].lower() == "active"]
    dr = t.get("days_remaining", 99) if t else 99
    deficit = t.get("deficit", 0) if t else 0
    if t and dr is not None and dr <= 2 and deficit > 0:
        insight = f"💡 *Инсайт:* 48 часов. Нужно `{deficit/max(dr,1):,.0f} THB/день`."
    elif not active:
        insight = "💡 *Инсайт:* Нет активных веток."
    else:
        insight = "💡 *Инсайт:* Система в норме. Выполняй и обновляй вечером."
    return "\n".join([f"*🧠 GTA IRL OS — Контекст*", f"_{today}  {now}_", "",
                      fmt_status(t), "", "─────────────────────", "",
                      fmt_branches(branches), "", "─────────────────────", "", insight])


# ── Whisper ───────────────────────────────────────────────────────────────────

def transcribe_voice(file_id):
    file_info = bot.get_file(file_id)
    file_url  = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"
    audio_data = requests.get(file_url).content
    r = requests.post(
        WHISPER_URL,
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        files={"file": ("voice.ogg", audio_data, "audio/ogg")},
        data={"model": "whisper-large-v3-turbo", "language": "ru"},
        timeout=30
    )
    r.raise_for_status()
    return r.json().get("text", "").strip()


# ── Groq AI ───────────────────────────────────────────────────────────────────

def ask_groq(user_id, user_message):
    if user_id not in chat_history:
        chat_history[user_id] = []
    chat_history[user_id].append({"role": "user", "content": user_message})
    history = chat_history[user_id][-20:]
    try:
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": GROQ_MODEL,
                  "messages": [{"role": "system", "content": build_system_context()}] + history,
                  "max_tokens": 1024},
            timeout=30)
        if r.status_code == 429:
            return "⏳ Слишком много запросов, подожди 10 секунд и повтори."
        r.raise_for_status()
        reply = r.json()["choices"][0]["message"]["content"]
        chat_history[user_id].append({"role": "assistant", "content": reply})
        return reply
    except Exception as e:
        return f"❌ Ошибка AI: {e}"


# ── Хендлеры ─────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "help"])
def cmd_start(msg):
    bot.send_message(msg.chat.id,
        "👋 *GTA IRL OS — Ассистент*\n\n"
        "В группе: упомяни меня `@gta_irl_assistant_bot` или ответь на моё сообщение.\n"
        "Понимаю текст и голосовые 🎤\n\n"
        "/collapse — полный контекст\n"
        "/status — баланс и дефицит\n"
        "/branches — ветки\n"
        "/today — дневной фокус\n"
        "/deals — активные сделки\n"
        "/deal ID — карточка сделки\n"
        "/timeline ID — история сделки\n"
        "/pipeline — дашборд воронки\n"
        "/money — деньги по сделкам\n"
        "/followups — кого пора пнуть\n"
        "/losses — причины потерь\n"
        "/closed — архив закрытых сделок\n"
        "/reset — сбросить историю",
        parse_mode="Markdown")

@bot.message_handler(commands=["reset"])
def cmd_reset(msg):
    chat_history.pop(msg.from_user.id, None)
    bot.send_message(msg.chat.id, "✅ История сброшена.")

@bot.message_handler(commands=["стоп", "stop"])
def cmd_stop_parser(msg):
    stop_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", ".parser_stop")
    try:
        open(stop_file, 'w').close()
        bot.send_message(msg.chat.id, "⏹ Команда отправлена. Парсер остановится через несколько секунд.")
    except Exception as e:
        bot.send_message(msg.chat.id, f"❌ Ошибка: {e}")

@bot.message_handler(commands=["status"])
def cmd_status(msg):
    bot.send_message(msg.chat.id, fmt_status(parse_target()), parse_mode="Markdown")

@bot.message_handler(commands=["branches"])
def cmd_branches(msg):
    bot.send_message(msg.chat.id, fmt_branches(parse_branches()), parse_mode="Markdown")

@bot.message_handler(commands=["collapse"])
def cmd_collapse(msg):
    bot.send_message(msg.chat.id, fmt_collapse(parse_target(), parse_branches()), parse_mode="Markdown")

@bot.message_handler(commands=["today"])
def cmd_today(msg):
    content = read_today()
    if not content:
        bot.send_message(msg.chat.id,
            f"Файл за {date.today().isoformat()} не создан.\n"
            "`python3 scripts/daily_cycle.py`", parse_mode="Markdown")
        return
    if len(content) > 4000:
        content = content[:4000] + "\n_...обрезано_"
    bot.send_message(msg.chat.id, f"```\n{content}\n```", parse_mode="Markdown")


@bot.message_handler(commands=["deals"])
def cmd_deals(msg):
    deals = [d for d in list_deals() if not is_terminal_stage(d.get("stage"))]
    if not deals:
        bot.send_message(msg.chat.id, "Активных сделок нет.")
        return

    lines = ["📋 *Активные сделки*"]
    for deal in deals[:10]:
        contact = deal.get("contact", {})
        name = contact.get("name") or contact.get("username") or "клиент"
        lines.append(
            f"`{deal['deal_id']}` — {stage_label(deal.get('stage'))} — {name}"
        )
    lines.append("\nОткрыть карточку: `/deal ID`")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["deal"])
def cmd_deal(msg):
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "Напиши так: `/deal ID`", parse_mode="Markdown")
        return

    deal_id = parts[1].strip()
    deal = get_deal(deal_id)
    if not deal:
        bot.send_message(msg.chat.id, f"❌ Сделка `{deal_id}` не найдена.", parse_mode="Markdown")
        return

    send_deal_card(msg.chat.id, deal)


@bot.message_handler(commands=["timeline"])
def cmd_timeline(msg):
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "Напиши так: `/timeline ID`", parse_mode="Markdown")
        return

    deal_id = parts[1].strip()
    deal = get_deal(deal_id)
    if not deal:
        bot.send_message(msg.chat.id, f"❌ Сделка `{deal_id}` не найдена.", parse_mode="Markdown")
        return

    bot.send_message(msg.chat.id, format_deal_timeline(deal), parse_mode="Markdown")


@bot.message_handler(commands=["pipeline"])
def cmd_pipeline(msg):
    summary = pipeline_summary()
    if summary["total"] == 0:
        bot.send_message(msg.chat.id, "Воронка пуста: сделок пока нет.")
        return

    stage_order = [
        "FIRST_MESSAGE_DRAFTED",
        "WAITING_REPLY",
        "BRIEF_COLLECTING",
        "BRIEF_READY",
        "PROPOSAL_DRAFTED",
        "PROPOSAL_SENT",
        "PREPAYMENT_WAITING",
        "PREPAYMENT_RECEIVED",
        "EXECUTION_PLANNING",
        "IN_PROGRESS",
        "DELIVERED",
        "FINAL_PAYMENT_WAITING",
        "CLOSED_WON",
        "CLOSED_LOST",
        "SCAM",
        "REJECTED",
        "DELEGATED",
        "CLIENT_GHOSTED",
    ]

    lines = [
        "📊 *GTA IRL OS — Pipeline*",
        f"Всего сделок: `{summary['total']}`",
        f"Активных: `{len(summary['active'])}`",
        "",
    ]
    for stage in stage_order:
        count = summary["by_stage"].get(stage, 0)
        if count:
            lines.append(f"{stage_label(stage)}: `{count}`")

    if summary["stuck"]:
        lines.append("\n⚠️ *Требуют внимания:*")
        for deal in summary["stuck"][:5]:
            contact = deal.get("contact", {})
            name = contact.get("name") or contact.get("username") or "клиент"
            lines.append(f"`{deal['deal_id']}` — {stage_label(deal['stage'])} — {name}")

    lines.append("\nОткрыть сделку: `/deal ID`")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["money"])
def cmd_money(msg):
    totals = money_summary()
    lines = [
        "💰 *GTA IRL OS — Деньги по сделкам*",
        f"КП / потенциально: `{totals['proposed']:,.0f}`",
        f"Предоплата получена: `{totals['prepayment_received']:,.0f}`",
        f"Финальная оплата получена: `{totals['final_received']:,.0f}`",
        f"Всего получено: `{totals['received_total']:,.0f}`",
        "",
        f"Закрыто успешно: `{totals['won_deals']}`",
        f"Ждём предоплату: `{totals['waiting_prepayment']}`",
        f"Ждём доплату: `{totals['waiting_final']}`",
    ]
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["followups"])
def cmd_followups(msg):
    deals = list_followup_candidates()
    if not deals:
        bot.send_message(msg.chat.id, "Follow-up кандидатов нет. Никого пинать не надо.")
        return

    lines = ["✉️ *Follow-up кандидаты*"]
    for deal in deals[:10]:
        contact = deal.get("contact", {})
        name = contact.get("name") or contact.get("username") or "клиент"
        lines.append(f"`{deal['deal_id']}` — {stage_label(deal['stage'])} — {name}")
    lines.append("\nОткрыть карточку: `/deal ID`")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["losses"])
def cmd_losses(msg):
    summary = loss_summary()
    if summary["total_lost"] == 0:
        bot.send_message(msg.chat.id, "Потерь пока нет.")
        return

    lines = [
        "🪦 *GTA IRL OS — Потери / отказы*",
        f"Всего: `{summary['total_lost']}`",
        "",
        "*По причинам:*",
    ]
    for reason, count in sorted(summary["by_reason"].items(), key=lambda item: item[1], reverse=True):
        lines.append(f"• {reason}: `{count}`")
    if summary["by_stage"]:
        lines.append("\n*По стадиям:*")
        for stage, count in sorted(summary["by_stage"].items()):
            lines.append(f"• {stage_label(stage)}: `{count}`")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(commands=["closed"])
def cmd_closed(msg):
    deals = list_closed_deals()
    if not deals:
        bot.send_message(msg.chat.id, "Архив закрытых сделок пуст.")
        return

    lines = ["📦 *Закрытые сделки*"]
    for deal in deals[:10]:
        contact = deal.get("contact", {})
        name = contact.get("name") or contact.get("username") or "клиент"
        result = deal.get("result") or deal.get("stage")
        lines.append(f"`{deal['deal_id']}` — {stage_label(deal['stage'])} — {result} — {name}")
    lines.append("\nОткрыть карточку: `/deal ID`")
    lines.append("История: `/timeline ID`")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown")


@bot.message_handler(content_types=["voice"])
def handle_voice(msg):
    if not should_respond_voice(msg):
        return
    thinking = bot.send_message(msg.chat.id, "🎤 Слушаю...", reply_to_message_id=msg.message_id)
    try:
        text = transcribe_voice(msg.voice.file_id)
        if not text:
            bot.edit_message_text("❌ Не смог распознать.", msg.chat.id, thinking.message_id)
            return
        bot.edit_message_text(f"🎤 _{text}_\n\n⏳", msg.chat.id, thinking.message_id, parse_mode="Markdown")
        reply = ask_groq(msg.from_user.id, text)
        bot.edit_message_text(f"🎤 _{text}_\n\n{reply}", msg.chat.id, thinking.message_id, parse_mode="Markdown")
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", msg.chat.id, thinking.message_id)


@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_text(msg):
    respond, clean_text = should_respond(msg)
    if not respond:
        return
    if not clean_text:
        clean_text = "что ты можешь делать?"

    thinking = bot.send_message(msg.chat.id, "⏳", reply_to_message_id=msg.message_id)
    try:
        reply = ask_groq(msg.from_user.id, clean_text)
        bot.edit_message_text(reply, msg.chat.id, thinking.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Ошибка: {e}", msg.chat.id, thinking.message_id)


# ── Inline кнопки воронки ────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    data = call.data
    chat_id = call.message.chat.id
    msg_id = call.message.message_id

    try:
        action, offer_id = data.split(":", 1)
    except:
        bot.answer_callback_query(call.id, "❌ Ошибка")
        return

    if action == "deal":
        try:
            next_stage, deal_id = offer_id.split(":", 1)
        except ValueError:
            bot.answer_callback_query(call.id, "❌ Ошибка карточки")
            return

        deal = get_deal(deal_id)
        if not deal:
            bot.answer_callback_query(call.id, "❌ Сделка не найдена")
            return

        if next_stage == "timeline":
            bot.answer_callback_query(call.id, "🧾 Timeline")
            bot.send_message(chat_id, format_deal_timeline(deal), parse_mode="Markdown")
            return

        if next_stage.startswith("close_lost_"):
            reason_code = next_stage.replace("close_lost_", "", 1)
            deal = close_deal(deal, "CLOSED_LOST", reason_code=reason_code)
            bot.answer_callback_query(call.id, "🪦 Сделка закрыта lost")
            bot.send_message(
                chat_id,
                f"🪦 Сделка `{deal_id}` закрыта как lost.\nПричина: {deal['loss']['reason']}",
                parse_mode="Markdown",
            )

        elif next_stage.startswith("close_rejected_"):
            reason_code = next_stage.replace("close_rejected_", "", 1)
            deal = close_deal(deal, "REJECTED", reason_code=reason_code)
            bot.answer_callback_query(call.id, "❌ Сделка отклонена")
            bot.send_message(
                chat_id,
                f"❌ Сделка `{deal_id}` отклонена.\nПричина: {deal['loss']['reason']}",
                parse_mode="Markdown",
            )

        elif next_stage == "prepare_proposal":
            try:
                deal = prepare_proposal(deal)
                bot.answer_callback_query(call.id, "📋 КП подготовлено")
                proposal_text = (deal.get("proposal") or {}).get("text") or deal.get("draft", "")
                if proposal_text:
                    bot.send_message(
                        chat_id,
                        f"📋 Черновик КП для сделки {deal_id}:\n\n{proposal_text}\n\nОтправить клиенту?",
                        reply_markup={
                            "inline_keyboard": [[
                                {"text": "📨 Отправить КП", "callback_data": f"deal:send_proposal:{deal_id}"},
                            ]]
                        },
                        disable_web_page_preview=True,
                    )
            except Exception as e:
                bot.answer_callback_query(call.id, "❌ Не смог подготовить КП")
                bot.send_message(chat_id, f"❌ Не смог подготовить КП: {e}")
                return

        elif next_stage == "send_proposal":
            proposal = deal.get("proposal") or {}
            proposal_text = proposal.get("text") or deal.get("draft")
            if not proposal_text:
                bot.answer_callback_query(call.id, "❌ КП не найдено")
                bot.send_message(chat_id, "❌ В сделке нет черновика КП. Сначала нажми «Подготовить КП».")
                return

            bot.answer_callback_query(call.id, "📨 Отправляю КП...")
            result = send_client_message(deal, proposal_text)
            if result.returncode == 0:
                proposal["status"] = "sent"
                proposal["sent_at"] = datetime.utcnow().isoformat()
                deal["proposal"] = proposal
                update_stage(deal, "PROPOSAL_SENT")
                add_message(deal, "outgoing", proposal_text)
                bot.send_message(
                    chat_id,
                    f"✅ КП отправлено клиенту.\nСделка `{deal_id}` → стадия: {stage_label('PROPOSAL_SENT')}",
                    parse_mode="Markdown",
                )
            else:
                bot.send_message(chat_id, f"❌ Ошибка отправки КП: {result.stderr[:200]}")
                return

        elif next_stage == "prepare_followup":
            try:
                deal = prepare_followup(deal)
                bot.answer_callback_query(call.id, "✍️ Follow-up готов")
                followup_text = (deal.get("followup") or {}).get("text") or deal.get("draft", "")
                if followup_text:
                    bot.send_message(
                        chat_id,
                        f"✉️ Черновик follow-up для сделки {deal_id}:\n\n{followup_text}\n\nОтправить клиенту?",
                        reply_markup={
                            "inline_keyboard": [[
                                {"text": "📨 Отправить follow-up", "callback_data": f"deal:send_followup:{deal_id}"},
                            ]]
                        },
                        disable_web_page_preview=True,
                    )
            except Exception as e:
                bot.answer_callback_query(call.id, "❌ Не смог подготовить follow-up")
                bot.send_message(chat_id, f"❌ Не смог подготовить follow-up: {e}")
                return

        elif next_stage == "send_followup":
            followup = deal.get("followup") or {}
            followup_text = followup.get("text") or deal.get("draft")
            if not followup_text:
                bot.answer_callback_query(call.id, "❌ Follow-up не найден")
                bot.send_message(chat_id, "❌ В сделке нет черновика follow-up. Сначала нажми «Follow-up».")
                return

            bot.answer_callback_query(call.id, "📨 Отправляю follow-up...")
            result = send_client_message(deal, followup_text)
            if result.returncode == 0:
                mark_followup_sent(deal, followup_text)
                bot.send_message(
                    chat_id,
                    f"✅ Follow-up отправлен клиенту по сделке `{deal_id}`.",
                    parse_mode="Markdown",
                )
            else:
                bot.send_message(chat_id, f"❌ Ошибка отправки follow-up: {result.stderr[:200]}")
                return

        elif next_stage == "record_prepayment":
            try:
                deal = record_prepayment(deal)
                bot.answer_callback_query(call.id, "💰 Предоплата записана")
                bot.send_message(
                    chat_id,
                    f"💰 Предоплата записана по сделке `{deal_id}`.\nСледующий шаг: план исполнения.",
                    parse_mode="Markdown",
                )
            except ValueError as e:
                bot.answer_callback_query(call.id, "⛔ Нельзя записать предоплату")
                bot.send_message(chat_id, f"⛔ Предоплата не записана: `{e}`", parse_mode="Markdown")
                return

        elif next_stage == "plan_execution":
            try:
                deal = plan_execution(deal)
                bot.answer_callback_query(call.id, "🧭 План исполнения")
            except ValueError as e:
                bot.answer_callback_query(call.id, "⛔ Нельзя перейти к плану")
                bot.send_message(chat_id, f"⛔ План исполнения не создан: `{e}`", parse_mode="Markdown")
                return

        elif next_stage == "start_execution":
            try:
                deal = start_execution(deal)
                bot.answer_callback_query(call.id, "⚙️ Сделка в работе")
            except ValueError as e:
                bot.answer_callback_query(call.id, "⛔ Нельзя начать работу")
                bot.send_message(chat_id, f"⛔ Работа не начата: `{e}`", parse_mode="Markdown")
                return

        elif next_stage == "mark_delivered":
            try:
                deal = mark_delivered(deal)
                bot.answer_callback_query(call.id, "📦 Сдано клиенту")
            except ValueError as e:
                bot.answer_callback_query(call.id, "⛔ Нельзя отметить сдачу")
                bot.send_message(chat_id, f"⛔ Сдача не записана: `{e}`", parse_mode="Markdown")
                return

        elif next_stage == "record_final_payment":
            try:
                deal = record_final_payment(deal)
                bot.answer_callback_query(call.id, "🏁 Сделка закрыта")
                bot.send_message(
                    chat_id,
                    f"🏁 Сделка `{deal_id}` закрыта успешно. Финальная оплата записана.",
                    parse_mode="Markdown",
                )
            except ValueError as e:
                bot.answer_callback_query(call.id, "⛔ Нельзя закрыть сделку")
                bot.send_message(chat_id, f"⛔ Сделка не закрыта: `{e}`", parse_mode="Markdown")
                return

        elif next_stage != "refresh":
            try:
                update_stage(deal, next_stage)
                bot.answer_callback_query(call.id, f"✅ {stage_label(next_stage)}")
            except ValueError as e:
                bot.answer_callback_query(call.id, "⛔ Нельзя перейти в эту стадию")
                bot.send_message(chat_id, f"⛔ Переход отклонён: `{e}`", parse_mode="Markdown")
                return
        else:
            bot.answer_callback_query(call.id, "🔄 Обновлено")

        fresh_deal = get_deal(deal_id) or deal
        send_deal_card(chat_id, fresh_deal, message_id=msg_id)
        return

    offer = get_offer(offer_id)
    if not offer:
        bot.answer_callback_query(call.id, "❌ Оффер не найден")
        return

    if action == "scam":
        update_offer(offer_id, status="SCAM")
        bot.answer_callback_query(call.id, "🚫 Помечен как скам")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
        bot.send_message(chat_id, f"🚫 Оффер `{offer_id}` помечен как *СКАМ*", parse_mode="Markdown")

    elif action == "hide":
        update_offer(offer_id, status="HIDDEN")
        bot.answer_callback_query(call.id, "👁 Скрыто")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)

    elif action == "delegate":
        update_offer(offer_id, status="DELEGATED")
        bot.answer_callback_query(call.id, "📤 Отмечено для делегирования")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
        bot.send_message(chat_id, f"📤 Оффер `{offer_id}` — *в делегирование*", parse_mode="Markdown")

    elif action == "respond":
        # Создаём сделку и генерируем черновик
        bot.answer_callback_query(call.id, "⏳ Генерирую черновик...")
        deal = create_deal(offer)
        update_offer(offer_id, status="RESPONDED", deal_id=deal["deal_id"])
        update_stage(deal, "RESPOND_DECIDED")
        update_stage(deal, "FIRST_MESSAGE_DRAFTED")

        draft = draft_first_message(deal)

        # Кнопки подтверждения
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Отправить", "callback_data": f"send_draft:{deal['deal_id']}:{offer_id}"},
                {"text": "✏️ Редактировать", "callback_data": f"edit_draft:{deal['deal_id']}"},
            ], [
                {"text": "❌ Отменить", "callback_data": f"cancel_draft:{deal['deal_id']}"},
            ]]
        }

        # Сохраняем черновик в сделку
        deal["draft"] = draft
        save_deal(deal)

        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
        bot.send_message(
            chat_id,
            f"✏️ *Черновик отклика* (сделка `{deal['deal_id']}`)\n\n_{draft}_\n\nОтправить?",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        send_deal_card(chat_id, deal)

    elif action == "send_draft":
        parts = offer_id.split(":", 1)
        deal_id = parts[0]
        real_offer_id = parts[1] if len(parts) > 1 else None

        deal = get_deal(deal_id)
        if not deal:
            bot.answer_callback_query(call.id, "❌ Сделка не найдена")
            return

        draft = deal.get("draft", "")
        contact_url = deal["contact"].get("contact_url", "")
        username = deal["contact"].get("username")

        bot.answer_callback_query(call.id, "📨 Отправляю...")

        # Отправляем через Telethon (через скрипт)
        try:
            import subprocess
            script = f"""
import asyncio
from telethon import TelegramClient
import os
async def send():
    client = TelegramClient('scripts/parser_session',
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'))
    await client.start()
    target = '{username}' if '{username}' != 'None' else int({deal['contact'].get('user_id', 0)})
    await client.send_message(target, '''{draft}''')
    await client.disconnect()
asyncio.run(send())
"""
            result = subprocess.run(
                ["python3", "-c", script],
                capture_output=True, text=True, timeout=20,
                env={**os.environ, "TELEGRAM_API_ID": os.getenv("TELEGRAM_API_ID", ""),
                     "TELEGRAM_API_HASH": os.getenv("TELEGRAM_API_HASH", "")}
            )
            if result.returncode == 0:
                update_stage(deal, "FIRST_MESSAGE_SENT")
                update_stage(deal, "WAITING_REPLY")
                add_message(deal, "outgoing", draft)
                bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
                bot.send_message(chat_id,
                    f"✅ *Отклик отправлен!*\nСделка `{deal_id}` → стадия: ⏳ ждём ответ клиента.\n\nСледующий шаг: контролировать входящий ответ.",
                    parse_mode="Markdown")
                fresh_deal = get_deal(deal_id)
                if fresh_deal:
                    send_deal_card(chat_id, fresh_deal)
            else:
                bot.send_message(chat_id, f"❌ Ошибка отправки: {result.stderr[:200]}")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка: {e}")

    elif action == "send_reply":
        deal_id = offer_id  # здесь offer_id = deal_id
        deal = get_deal(deal_id)
        if not deal:
            bot.answer_callback_query(call.id, "❌ Сделка не найдена")
            return

        draft = deal.get("draft", "")
        username = deal["contact"].get("username")
        user_id  = deal["contact"].get("user_id")

        bot.answer_callback_query(call.id, "📨 Отправляю...")

        try:
            import subprocess
            target = f"'{username}'" if username else str(user_id or 0)
            script = f"""
import asyncio, os
from telethon import TelegramClient
async def send():
    c = TelegramClient('scripts/parser_session',
        int(os.getenv('TELEGRAM_API_ID')),
        os.getenv('TELEGRAM_API_HASH'))
    await c.start()
    await c.send_message({target}, '''{draft}''')
    await c.disconnect()
asyncio.run(send())
"""
            result = subprocess.run(
                ["python3", "-c", script],
                capture_output=True, text=True, timeout=20,
                env={**os.environ,
                     "TELEGRAM_API_ID":   os.getenv("TELEGRAM_API_ID", ""),
                     "TELEGRAM_API_HASH": os.getenv("TELEGRAM_API_HASH", "")}
            )
            if result.returncode == 0:
                add_message(deal, "outgoing", draft)
                bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)
                bot.send_message(chat_id,
                    f"✅ *Отправлено!*\nСделка `{deal_id}`",
                    parse_mode="Markdown")
            else:
                bot.send_message(chat_id, f"❌ {result.stderr[:200]}")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Ошибка: {e}")

    elif action == "skip_reply":
        bot.answer_callback_query(call.id, "⏭ Пропущено")
        bot.edit_message_reply_markup(chat_id, msg_id, reply_markup=None)


# ── Запуск ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"GTA IRL OS Bot запущен — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Username: @{BOT_USERNAME}")
    print("Группа: отвечает только на @упоминания и реплаи")
    print("Слушаю...")
    bot.infinity_polling()
