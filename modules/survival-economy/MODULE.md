# Module: Survival Economy

**Category:** Runtime
**Status:** ACTIVE
**Phase:** 0 — Manual loop
**Started:** 2026-06-25
**Last updated:** 2026-06-25

---

## Purpose

Single responsibility: track all income opportunities and financial obligations.
Ensure the human always knows the deficit, the best next action, and which branches are real.

This module is always active. It does not deactivate when a survival crisis ends —
it transitions from Crisis Mode to Normal Mode.

---

## Current state

| Field | Value |
|-------|-------|
| Mode | CRISIS |
| Balance | 200 THB |
| Target | 23,000 THB |
| Deficit | 22,800 THB |
| Deadline | 2026-06-27 |
| Days remaining | 2 |
| Active branches | 1 (dani-ai-agent) |

---

## Last decision

2026-06-25: Single focus on dani-ai-agent. All other branches frozen.
Practice building the agent tonight → confidence → offer to Dani.

---

## Next action

Build Telegram channel monitoring agent prototype. Use result as Dani offer basis.

---

## Cold start instructions

If returning after any absence:
1. Read `target.md` — what is the current deficit and deadline?
2. Read `branches.md` — which branch is active, what is its next_action?
3. Read the latest file in `daily/` — what happened last and what was planned?
4. That is enough context to continue.

---

## Files

| File | Category | Purpose |
|------|----------|---------|
| `target.md` | Runtime | Active SurvivalTarget — balance, deficit, obligations |
| `branches.md` | Runtime | All MoneyBranches — live ranked list |
| `idea-hold.md` | Runtime | Frozen ideas not competing for energy |
| `daily/YYYY-MM-DD.md` | Runtime | DailyFocus + EveningUpdate per day |

---

## Module rules

1. Max 3 active branches in Normal Mode. Max 1 in Crisis Mode.
2. Every branch has exactly one `next_action` — specific, actionable today.
3. Branch with no movement in 2 days → review or freeze.
4. Every evening: update balance, branch histories, EveningUpdate.
5. New ideas that don't serve the current target → idea-hold immediately.
6. Crisis Mode ends when deficit < 20% of goal amount.
