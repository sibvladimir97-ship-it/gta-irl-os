# Memory — GTA IRL OS

**Category:** Foundation (structure) + Runtime (content)

The memory layer stores what the system has learned across all cycles.
Separate from module state (current) and cases (historical situations).
Memory is what makes the system smarter over time without requiring re-explanation of context.

---

## Structure

```
memory/
├── README.md          ← this file
├── snapshots/         ← daily ContextCollapse documents (auto-archived)
│   └── YYYY-MM-DD.md
└── archive/           ← closed branches, resolved targets
    └── YYYY-MM/
```

---

## snapshots/

Every ContextCollapse document is saved here after the day closes.
Purpose: the simulate-agent reads this directory to build forward models.
Format: one file per day, named `YYYY-MM-DD.md`.
Written by: collapse-agent (Phase 1+) or human (Phase 0).

---

## archive/

When a MoneyBranch reaches status `won` or `closed`:
→ full history copied to `archive/YYYY-MM/branch-id.md`
→ original entry in branches.md replaced with a one-line reference

When a SurvivalTarget reaches status `closed`:
→ copied to `archive/YYYY-MM/target-name.md`
→ target.md starts fresh

Cases in `docs/cases/` are never archived — they are permanent reference material.

---

## What memory is NOT

Memory is not a journal. Journals live in `modules/*/daily/`.
Memory is not documentation. Documentation lives in `core/` and `docs/`.
Memory is the structured residue of completed cycles — the input for future simulation.
