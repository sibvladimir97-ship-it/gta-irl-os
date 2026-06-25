#!/usr/bin/env python3
"""
GTA IRL OS — Daily Cycle CLI
Phase 0: Manual loop

Usage:
    python scripts/daily_cycle.py          # morning mode (default)
    python scripts/daily_cycle.py --evening  # evening update mode
    python scripts/daily_cycle.py --collapse # context collapse only

No external dependencies. Pure Python 3.
"""

import argparse
import os
import re
import sys
from datetime import date, datetime


# ── Config ────────────────────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SURVIVAL = os.path.join(ROOT, "modules", "survival-economy")
TARGET_FILE = os.path.join(SURVIVAL, "target.md")
BRANCHES_FILE = os.path.join(SURVIVAL, "branches.md")
DAILY_DIR = os.path.join(SURVIVAL, "daily")


# ── Terminal colours (no dependencies) ────────────────────────────────────────

RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def bold(s):   return f"{BOLD}{s}{RESET}"
def red(s):    return f"{RED}{s}{RESET}"
def yellow(s): return f"{YELLOW}{s}{RESET}"
def green(s):  return f"{GREEN}{s}{RESET}"
def cyan(s):   return f"{CYAN}{s}{RESET}"
def dim(s):    return f"{DIM}{s}{RESET}"
def line():    print(dim("─" * 60))


# ── Parsers ────────────────────────────────────────────────────────────────────

def parse_table_value(text, *fields):
    """Extract value from markdown table row: | Field | Value |"""
    for field in fields:
        pattern = rf"\|\s*{re.escape(field)}\s*\|\s*(.+?)\s*\|"
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def parse_number(s):
    """Extract first number from string like '23,000 THB' or '~3,000'."""
    if s is None:
        return 0
    s = s.replace(",", "").replace("~", "").replace("THB", "").strip()
    m = re.search(r"[\d]+(?:\.\d+)?", s)
    return float(m.group()) if m else 0


def parse_target(path):
    """Parse target.md -> dict with goal, balance, deficit, deadline, mode."""
    if not os.path.exists(path):
        return None
    text = open(path).read()

    goal     = parse_number(parse_table_value(text, "Goal amount"))
    balance  = parse_number(parse_table_value(text, "Current balance"))
    deadline = parse_table_value(text, "Deadline")
    mode_m   = re.search(r"\*\*Mode:\*\*\s*(\w+)", text)
    mode     = mode_m.group(1).upper() if mode_m else "NORMAL"

    # Always recompute deficit from live balance
    deficit = goal - balance if goal else 0

    # Days remaining
    days_remaining = None
    if deadline:
        clean = re.sub(r"\s*\(.*?\)", "", deadline).strip()
        try:
            dl = date.fromisoformat(clean)
            days_remaining = (dl - date.today()).days
        except ValueError:
            pass

    # Parse unpaid obligations
    obligations = []
    for row in re.finditer(
        r"\|\s*([^|]+?)\s*\|\s*([\d,~]+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(yes|no)\s*\|",
        text, re.IGNORECASE
    ):
        name, amount, due, dtype, layer, paid = [g.strip() for g in row.groups()]
        if paid.lower() == "no":
            obligations.append({
                "name": name,
                "amount": parse_number(amount),
                "due": due,
                "type": dtype,
                "layer": layer,
            })

    return {
        "goal": goal,
        "balance": balance,
        "deficit": deficit,
        "deadline": deadline,
        "days_remaining": days_remaining,
        "mode": mode,
        "obligations": obligations,
    }


def parse_branches(path):
    """Parse branches.md -> list of branch dicts."""
    if not os.path.exists(path):
        return []
    text = open(path).read()

    branches = []
    sections = re.split(r"^### ", text, flags=re.MULTILINE)
    for section in sections[1:]:
        lines = section.strip().split("\n")
        branch_id = lines[0].strip()
        body = "\n".join(lines[1:])

        status = parse_table_value(body, "Статус", "Status") or "unknown"
        status = re.sub(r"\*+", "", status).strip()

        branches.append({
            "id":              branch_id,
            "name":            parse_table_value(body, "Название", "Name") or branch_id,
            "status":          status,
            "layer":           parse_table_value(body, "Слой", "Layer") or "—",
            "expected_value":  parse_table_value(body, "Ожидаемая сумма", "Expected value") or "TBD",
            "earliest_income": parse_table_value(body, "Ближайший доход", "Earliest income") or "—",
            "probability":     parse_table_value(body, "Вероятность", "Probability") or "—",
            "required_energy": parse_table_value(body, "Требуемая энергия", "Required energy") or "—",
            "blocking":        parse_table_value(body, "Блокеры", "Blocking factors") or "—",
            "next_action":     parse_table_value(body, "Следующий шаг", "Next action") or "—",
            "next_action_by":  parse_table_value(body, "Срок следующего шага", "Next action by") or "—",
            "frozen_reason":   parse_table_value(body, "Причина заморозки", "Frozen reason") or None,
            "strategic_value": parse_table_value(body, "Стратегическая ценность", "Strategic value") or "—",
        })

    return branches


def priority_score(branch):
    """Lower = higher priority. probability + energy + days_to_income/2."""
    try:
        prob   = float(re.search(r"\d+", branch["probability"]).group())
        energy = float(re.search(r"\d+", branch["required_energy"]).group())
    except (AttributeError, TypeError):
        return 99

    income_str = branch["earliest_income"]
    days = 14
    m = re.search(r"(\d{4}-\d{2}-\d{2})", income_str)
    if m:
        try:
            inc_date = date.fromisoformat(m.group(1))
            days = max(0, (inc_date - date.today()).days)
        except ValueError:
            pass

    return prob + energy + (days / 2)


# ── Display ────────────────────────────────────────────────────────────────────

def show_context_collapse(target, branches):
    """Print the daily Context Collapse — one screen."""
    today = date.today().isoformat()
    now   = datetime.now().strftime("%H:%M")

    print()
    print(bold("╔══════════════════════════════════════════════════════════╗"))
    print(bold("║           GTA IRL OS — Context Collapse                  ║"))
    print(bold("╚══════════════════════════════════════════════════════════╝"))
    print(dim(f"  {today}  {now}"))
    print()

    if target:
        mode_color = red if target["mode"] == "CRISIS" else yellow
        print(bold("  SURVIVAL TARGET"))
        line()
        print(f"  Mode       : {mode_color(bold(target['mode']))}")
        bal_str = f"{target['balance']:,.0f} THB"
        print(f"  Balance    : {green(bal_str)}")
        print(f"  Goal       : {target['goal']:,.0f} THB")

        deficit = target["deficit"]
        deficit_str = f"{deficit:,.0f} THB"
        print(f"  Deficit    : {red(bold(deficit_str)) if deficit > 0 else green('0 — COVERED')}")

        if target["days_remaining"] is not None:
            dr = target["days_remaining"]
            dr_color = red if dr <= 2 else yellow if dr <= 7 else green
            dr_str = f"{dr} days"
            print(f"  Deadline   : {target['deadline']}  ({dr_color(dr_str)})")

            if dr > 0 and deficit > 0:
                dpd = deficit / dr
                dpd_str = f"{dpd:,.0f} THB/day"
                print(f"  Need/day   : {red(dpd_str)}")
        print()

        unpaid = target["obligations"]
        if unpaid:
            print(bold("  UNPAID OBLIGATIONS"))
            line()
            for ob in unpaid:
                tag = red("[HARD]") if "hard" in ob["type"].lower() else yellow("[soft]")
                print(f"  {tag} {ob['name']:20s} {ob['amount']:>8,.0f} THB   due {ob['due']}")
            print()

    active = [b for b in branches if b["status"].lower() == "active"]
    frozen = [b for b in branches if b["status"].lower() == "frozen"]
    active.sort(key=priority_score)

    print(bold("  MONEY BRANCHES"))
    line()

    if not active and not frozen:
        print(yellow("  No branches found."))
    else:
        if active:
            print(bold(f"  ACTIVE ({len(active)})"))
            for b in active:
                score = priority_score(b)
                print(f"  {green('●')} {bold(b['name'])}")
                print(f"      Next   : {b['next_action']}")
                print(f"      By     : {b['next_action_by']}")
                print(f"      Income : {b['earliest_income']}")
                if b["blocking"] and b["blocking"] != "—":
                    print(f"      Block  : {yellow(b['blocking'])}")
                print(f"      Score  : {score:.1f}  (lower = higher priority)")
                print()

        if frozen:
            print(dim(f"  FROZEN ({len(frozen)})"))
            for b in frozen:
                print(dim(f"  ○ {b['name']}  —  {b['frozen_reason'] or 'no reason given'}"))
            print()

    line()
    insight = generate_insight(target, active, frozen)
    print(f"  {cyan('INSIGHT')}  {insight}")
    print()


def generate_insight(target, active, frozen):
    """Rule-based insight — no AI needed."""
    if not target:
        return "No active SurvivalTarget found. Update target.md."

    deficit = target.get("deficit", 0)
    dr = target.get("days_remaining", 99)
    mode = target.get("mode", "NORMAL")

    if mode == "CRISIS" and len(active) == 0:
        return red("CRISIS MODE with no active branches. Add at least one now.")

    if mode == "CRISIS" and len(active) > 1:
        n = len(active)
        return yellow(f"CRISIS MODE should have 1 active branch. You have {n}. Freeze the rest.")

    if dr is not None and dr <= 0 and deficit > 0:
        deficit_str = f"{deficit:,.0f}"
        return red(f"Deadline passed. Deficit {deficit_str} THB still open. Update target.md.")

    if dr is not None and dr <= 2 and deficit > 0:
        dpd = deficit / max(dr, 1)
        dpd_str = f"{dpd:,.0f}"
        return red(f"48h window. Need {dpd_str} THB/day. Every hour counts.")

    if len(active) == 0:
        return yellow("No active branches. System cannot prioritize without at least one.")

    stale = [b for b in active if b["next_action_by"] and b["next_action_by"] < date.today().isoformat()]
    if stale:
        names = ", ".join(b["id"] for b in stale)
        return yellow(f"Overdue next_action on: {names}. Update branches.md.")

    return green("System nominal. Execute today's tasks, update this evening.")


# ── Daily file ─────────────────────────────────────────────────────────────────

def daily_path(today=None, daily_dir=DAILY_DIR):
    if today is None:
        today = date.today().isoformat()
    return os.path.join(daily_dir, f"{today}.md")


def create_morning_focus(target, branches, today=None, daily_dir=DAILY_DIR, quiet=False):
    """Write today's DailyFocus template if it doesn't exist."""
    today = today or date.today().isoformat()
    path = daily_path(today, daily_dir)

    if os.path.exists(path):
        content = open(path).read()
        complete = "**Balance now:**" in content and "_____ THB" not in content
        if not quiet:
            if complete:
                print(green(f"  Today's file already complete: daily/{today}.md"))
            else:
                print(yellow(f"  Today's file already exists: daily/{today}.md"))
                print(dim("  Edit it directly or run --evening to add the evening update."))
        return {"path": path, "created": False, "complete": complete}

    active = [b for b in branches if b["status"].lower() == "active"]
    frozen = [b for b in branches if b["status"].lower() == "frozen"]
    mode   = target["mode"] if target else "NORMAL"

    deficit_line = ""
    if target and target["deficit"] > 0:
        deficit_line = f"**Deficit:** {target['deficit']:,.0f} THB\n"
    dr_line = ""
    if target and target["days_remaining"] is not None:
        dr_line = f"**Days to deadline:** {target['days_remaining']}\n"

    tasks_rows = ["| # | Branch | Action | Done |", "|---|--------|--------|------|"]
    for i, b in enumerate(active, 1):
        action = b["next_action"].replace("|", "/")
        tasks_rows.append(f"| {i} | {b['id']} | {action} | [ ] |")

    frozen_rows = ["| What | Why |", "|------|-----|"]
    for b in frozen:
        reason = (b["frozen_reason"] or "frozen").replace("|", "/")
        frozen_rows.append(f"| {b['id']} | {reason} |")

    active_list = "\n".join(
        f"{i+1}. `{b['id']}` — {b['name']}" for i, b in enumerate(active)
    ) or "_No active branches_"

    content = (
        f"# Daily Focus — {today}\n\n"
        f"**Category:** Runtime\n"
        f"**Mode:** {mode}\n"
        f"{deficit_line}"
        f"{dr_line}"
        f"\n---\n\n"
        f"## Active branches today\n\n"
        f"{active_list}\n\n"
        f"## Tasks\n\n"
        f"{chr(10).join(tasks_rows)}\n\n"
        f"## Deliberately not doing today\n\n"
        f"{chr(10).join(frozen_rows)}\n\n"
        f"---\n\n"
        f"## Evening update\n\n"
        f"**Balance now:** _____ THB\n"
        f"**What moved:**\n"
        f"**What didn't:**\n"
        f"**Blocker encountered:**\n"
        f"**Corrections for tomorrow:**\n"
        f"**Next priorities:**\n"
    )

    os.makedirs(daily_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    if not quiet:
        print(green(f"  Created: modules/survival-economy/daily/{today}.md"))
    return {"path": path, "created": True, "complete": False}


def run_morning_cycle(
    target_file=TARGET_FILE,
    branches_file=BRANCHES_FILE,
    daily_dir=DAILY_DIR,
    today=None,
):
    """Run the real morning Daily Cycle and return a Russian Telegram report."""
    today = today or date.today().isoformat()
    target = parse_target(str(target_file))
    branches = parse_branches(str(branches_file))

    if not target:
        raise RuntimeError("SurvivalTarget не найден")

    active = [b for b in branches if b["status"].lower() == "active"]
    active.sort(key=priority_score)
    focus = create_morning_focus(
        target,
        branches,
        today=today,
        daily_dir=str(daily_dir),
        quiet=True,
    )

    mission = (
        active[0]["next_action"]
        if active
        else "Определить одну активную ветку и записать следующий шаг."
    )
    file_state = "создан" if focus["created"] else "уже существует"
    mode = "КРИЗИС" if target["mode"] == "CRISIS" else target["mode"]

    lines = [
        f"🌅 Daily Cycle — {today}",
        f"📍 Режим: {mode}",
        f"💰 Баланс: {target['balance']:,.0f} THB",
        f"📉 Дефицит: {target['deficit']:,.0f} THB",
    ]
    if target["days_remaining"] is not None:
        lines.append(f"⏳ До дедлайна: {target['days_remaining']} дн.")
    lines.extend(
        [
            "",
            f"🎯 Миссия дня: {mission.rstrip('.')}.",
            f"🗂 Дневной фокус {file_state}: daily/{today}.md",
        ]
    )
    return "\n".join(lines)


def add_evening_update(target):
    """Interactive evening update — fills in the template fields."""
    today = date.today().isoformat()
    path  = daily_path(today)

    if not os.path.exists(path):
        print(yellow(f"  No morning file found for {today}."))
        print(dim("  Run without --evening first to create it."))
        return

    content = open(path).read()

    if "**Balance now:**" in content and "_____ THB" not in content:
        print(yellow("  Evening update already filled in for today."))
        return

    print()
    print(bold("  EVENING UPDATE"))
    line()
    print(dim("  Press Enter to skip any field.\n"))

    def ask(prompt, default=""):
        try:
            val = input(f"  {prompt}: ").strip()
            return val if val else default
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(0)

    cur_balance = target["balance"] if target else 0
    balance_input = ask("Balance now (THB)", str(int(cur_balance)))
    try:
        new_balance = float(balance_input.replace(",", ""))
    except ValueError:
        new_balance = cur_balance

    moved    = ask("What moved forward")
    didnt    = ask("What didn't move")
    blocker  = ask("Blocker encountered (leave blank if none)")
    correct  = ask("Corrections for tomorrow")
    next_pri = ask("Next priorities (branch IDs, comma-separated)")

    evening_block = (
        f"**Balance now:** {new_balance:,.0f} THB\n"
        f"**What moved:** {moved}\n"
        f"**What didn't:** {didnt}\n"
        f"**Blocker encountered:** {blocker if blocker else '—'}\n"
        f"**Corrections for tomorrow:** {correct}\n"
        f"**Next priorities:** {next_pri}"
    )

    placeholder = (
        "**Balance now:** _____ THB\n"
        "**What moved:**\n"
        "**What didn't:**\n"
        "**Blocker encountered:**\n"
        "**Corrections for tomorrow:**\n"
        "**Next priorities:**"
    )

    updated = content.replace(placeholder, evening_block)
    with open(path, "w") as f:
        f.write(updated)

    if new_balance != cur_balance and target:
        update_target_balance(new_balance, target)

    print()
    print(green(f"  Evening update saved to daily/{today}.md"))
    if new_balance != cur_balance:
        new_deficit = target["goal"] - new_balance
        delta = new_balance - cur_balance
        sign = "+" if delta >= 0 else ""
        print(f"  Balance : {cur_balance:,.0f} → {new_balance:,.0f} THB  ({sign}{delta:,.0f})")
        print(f"  Deficit : {new_deficit:,.0f} THB remaining")


def update_target_balance(new_balance, target):
    """Update Current balance and Deficit in target.md and append to history."""
    path = TARGET_FILE
    text = open(path).read()
    new_deficit = target["goal"] - new_balance

    def replace_thb_field(field_name, new_val):
        pattern = rf"(\|\s*{re.escape(field_name)}\s*\|\s*)[\d,]+([\s]*THB[\s]*\|)"
        replacement = lambda m: f"{m.group(1)}{new_val:,.0f} THB{m.group(2)}"
        return re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    text = replace_thb_field("Current balance", new_balance)
    text = replace_thb_field("Deficit", new_deficit)

    today = date.today().isoformat()
    entry = f"- {today}: Balance updated to {new_balance:,.0f} THB. Deficit {new_deficit:,.0f} THB.\n"
    text = text.rstrip() + "\n" + entry

    with open(path, "w") as f:
        f.write(text)

    print(green("  target.md updated with new balance."))


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="GTA IRL OS — Daily Cycle CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/daily_cycle.py             # morning: show collapse + create daily file
  python scripts/daily_cycle.py --evening   # evening: add update to today's file
  python scripts/daily_cycle.py --collapse  # show Context Collapse only, no file changes
        """
    )
    parser.add_argument("--evening",  action="store_true", help="Evening update mode")
    parser.add_argument("--collapse", action="store_true", help="Show Context Collapse only")
    args = parser.parse_args()

    target   = parse_target(TARGET_FILE)
    branches = parse_branches(BRANCHES_FILE)

    if args.evening:
        show_context_collapse(target, branches)
        add_evening_update(target)
    elif args.collapse:
        show_context_collapse(target, branches)
    else:
        show_context_collapse(target, branches)
        print(bold("  MORNING FOCUS"))
        line()
        create_morning_focus(target, branches)
        print()
        print(dim("  Run with --evening tonight to log results."))
        print()


if __name__ == "__main__":
    main()
