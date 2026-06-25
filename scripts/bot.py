#!/usr/bin/env python3
"""
GTA IRL OS — Telegram Assistant Bot
Phase 0: Context-aware assistant connected to the OS files

Commands:
    /start    — welcome
    /status   — current survival target status
    /branches — active and frozen money branches
    /collapse — full context collapse view
    /today    — today's daily focus
    /help     — command list
"""

import os
import re
import telebot
from datetime import date, datetime

# ── Config ─────────────────────────────────────────────────────────────────────

TOKEN = "8980844354:AAFKX_wtKvLx1kgoWaZ6V9i8S48209GqpcM"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURVIVAL = os.path.join(ROOT, "modules", "survival-economy")
TARGET_FILE = os.path.join(SURVIVAL, "target.md")
BRANCHES_FILE = os.path.join(SURVIVAL, "branches.md")
DAILY_DIR = os.path.join(SURVIVAL, "daily")

bot = telebot.TeleBot(TOKEN)


# ── Parsers (same logic as daily_cycle.py) ────────────────────────────────────

def parse_table_value(text, field):
    pattern = rf"\|\s*{re.escape(field)}\s*\|\s*(.+?)\s*\|"
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def parse_number(s):
    if s is None:
        return 0
    s = s.replace(",", "").replace("~", "").replace("THB", "").strip()
    m = re.search(r"[\d]+(?:\.\d+)?", s)
    return float(m.group()) if m else 0


def parse_target():
    if not os.path.exists(TARGET_FILE):
        return None
    text = open(TARGET_FILE).read()
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
            dl = date.fromisoformat(clean)
            days_remaining = (dl - date.today()).days
        except ValueError:
            pass

    obligations = []
    for row in re.finditer(
        r"\|\s*([^|]+?)\s*\|\s*([\d,~]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(yes|no)\s*\|",
        text, re.IGNORECASE
    ):
        name, amount, due, dtype, layer, paid = [g.strip() for g in row.groups()]
        if paid.lower() == "no":
            obligations.append({
                "name": name, "amount": parse_number(amount),
                "due": due, "type": dtype,
            })

    return {
        "goal": goal, "balance": balance, "deficit": deficit,
        "deadline": deadline, "days_remaining": days_remaining,
        "mode": mode, "obligations": obligations,
    }


def parse_branches():
    if not os.path.exists(BRANCHES_FILE):
        return []
    text = open(BRANCHES_FILE).read()
    branches = []
    sections = re.split(r"^### ", text, flags=re.MULTILINE)
    for section in sections[1:]:
        lines = section.strip().split("\n")
        branch_id = lines[0].strip()
        body = "\n".join(lines[1:])
        status = parse_table_value(body, "Status") or "unknown"
        status = re.sub(r"\*+", "", status).strip()
        branches.append({
            "id":              branch_id,
            "name":            parse_table_value(body, "Name") or branch_id,
            "status":          status,
            "expected_value":  parse_table_value(body, "Expected value") or "TBD",
            "earliest_income": parse_table_value(body, "Earliest income") or "—",
            "probability":     parse_table_value(body, "Probability") or "—",
            "required_energy": parse_table_value(body, "Required energy") or "—",
            "blocking":        parse_table_value(body, "Blocking factors") or "—",
            "next_action":     parse_table_value(body, "Next action") or "—",
            "frozen_reason":   parse_table_value(body, "Frozen reason") or None,
        })
    return branches


def read_today():
    today = date.today().isoformat()
    path = os.path.join(DAILY_DIR, f"{today}.md")
    if os.path.exists(path):
        return open(path).read()
    return None


# ── Message builders ──────────────────────────────────────────────────────────

def build_status(t):
    if not t:
        return "❌ target.md not found"

    mode_icon = "🚨" if t["mode"] == "CRISIS" else "🟡"
    lines = [
        f"{mode_icon} *{t['mode']} MODE*",
        f"",
        f"💰 Balance:  `{t['balance']:,.0f} THB`",
        f"🎯 Goal:     `{t['goal']:,.0f} THB`",
        f"📉 Deficit:  `{t['deficit']:,.0f} THB`",
    ]

    if t["days_remaining"] is not None:
        dr = t["days_remaining"]
        icon = "🔴" if dr <= 2 else "🟡" if dr <= 7 else "🟢"
        lines.append(f"⏰ Deadline: {t['deadline']}  {icon} {dr} days")
        if dr > 0 and t["deficit"] > 0:
            dpd = t["deficit"] / dr
            lines.append(f"📊 Need/day: `{dpd:,.0f} THB/day`")

    if t["obligations"]:
        lines.append("")
        lines.append("*Unpaid obligations:*")
        for ob in t["obligations"]:
            icon = "🔴" if "hard" in ob["type"].lower() else "🟡"
            lines.append(f"{icon} {ob['name']}: `{ob['amount']:,.0f} THB`  due {ob['due']}")

    return "\n".join(lines)


def build_branches(branches):
    active = [b for b in branches if b["status"].lower() == "active"]
    frozen = [b for b in branches if b["status"].lower() == "frozen"]

    lines = []

    if active:
        lines.append("*🟢 ACTIVE*")
        for b in active:
            lines.append(f"")
            lines.append(f"● *{b['name']}*")
            lines.append(f"  Next: {b['next_action']}")
            lines.append(f"  Income: {b['earliest_income']}")
            if b["blocking"] and b["blocking"] != "—":
                lines.append(f"  ⚠️ Block: {b['blocking']}")

    if frozen:
        lines.append("")
        lines.append("*⚫ FROZEN*")
        for b in frozen:
            reason = b["frozen_reason"] or "no reason"
            lines.append(f"○ {b['name']} — _{reason}_")

    return "\n".join(lines) if lines else "No branches found"


def build_collapse(t, branches):
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")

    lines = [
        f"*🧠 GTA IRL OS — Context Collapse*",
        f"_{today}  {now}_",
        f"",
        build_status(t),
        f"",
        f"─────────────────────",
        f"",
        build_branches(branches),
        f"",
        f"─────────────────────",
        f"",
    ]

    # Insight
    active = [b for b in branches if b["status"].lower() == "active"]
    if t:
        dr = t.get("days_remaining", 99)
        deficit = t.get("deficit", 0)
        if dr is not None and dr <= 2 and deficit > 0:
            dpd = deficit / max(dr, 1)
            lines.append(f"💡 *INSIGHT:* 48h window. Need `{dpd:,.0f} THB/day`. Every hour counts.")
        elif not active:
            lines.append("💡 *INSIGHT:* No active branches. Add one now.")
        else:
            lines.append("💡 *INSIGHT:* System nominal. Execute and update tonight.")

    return "\n".join(lines)


# ── Handlers ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(msg):
    text = (
        "👋 *GTA IRL OS Assistant*\n\n"
        "I'm connected to your personal operating system.\n\n"
        "*Commands:*\n"
        "/status — survival target & deficit\n"
        "/branches — active & frozen money branches\n"
        "/collapse — full context collapse\n"
        "/today — today's daily focus\n"
        "/help — this message"
    )
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")


@bot.message_handler(commands=["help"])
def cmd_help(msg):
    cmd_start(msg)


@bot.message_handler(commands=["status"])
def cmd_status(msg):
    t = parse_target()
    bot.send_message(msg.chat.id, build_status(t), parse_mode="Markdown")


@bot.message_handler(commands=["branches"])
def cmd_branches(msg):
    branches = parse_branches()
    bot.send_message(msg.chat.id, build_branches(branches), parse_mode="Markdown")


@bot.message_handler(commands=["collapse"])
def cmd_collapse(msg):
    t = parse_target()
    branches = parse_branches()
    bot.send_message(msg.chat.id, build_collapse(t, branches), parse_mode="Markdown")


@bot.message_handler(commands=["today"])
def cmd_today(msg):
    content = read_today()
    if not content:
        today = date.today().isoformat()
        bot.send_message(
            msg.chat.id,
            f"No daily file for {today} yet.\nRun: `python3 scripts/daily_cycle.py`",
            parse_mode="Markdown"
        )
        return
    # Trim to fit Telegram's 4096 char limit
    if len(content) > 4000:
        content = content[:4000] + "\n\n_...truncated_"
    bot.send_message(msg.chat.id, f"```\n{content}\n```", parse_mode="Markdown")


@bot.message_handler(func=lambda m: True)
def handle_text(msg):
    text = msg.text.strip().lower()

    # Simple keyword routing
    if any(w in text for w in ["status", "деньги", "дефицит", "баланс"]):
        cmd_status(msg)
    elif any(w in text for w in ["branch", "ветк", "dani", "даня"]):
        cmd_branches(msg)
    elif any(w in text for w in ["collapse", "коллапс", "приоритет"]):
        cmd_collapse(msg)
    elif any(w in text for w in ["today", "сегодня", "фокус"]):
        cmd_today(msg)
    else:
        bot.send_message(
            msg.chat.id,
            "Use /collapse to see full system status.\nOr try: /status /branches /today",
            parse_mode="Markdown"
        )


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"GTA IRL OS Bot started — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Reading files from: {SURVIVAL}")
    print("Polling for messages...")
    bot.infinity_polling()
