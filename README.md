# GTA IRL OS

> Personal operating system for life. Not a tool. Not an app. A system that evolves.

## What this is

GTA IRL OS is a personal operating system built around one continuous cycle:

**Collect → Classify → Update → Analyze → Simulate → Prioritize → Collapse → Decide → Execute → Learn**

The system processes events from real life, updates module states, evaluates opportunities, and compresses everything into a single daily decision point — Context Collapse.

The system never decides for you. It makes the right decision obvious.

## Core principles

1. **One responsibility per module.** No module does two things.
2. **Stable vocabulary, not stable structure.** Concepts outlive implementations.
3. **Every module must survive a cold start.** Return after a month → system tells you what to do next.
4. **Crisis Mode exists.** When deficit > 80% and deadline < 72h, the system activates single-branch focus.
5. **Decide always belongs to the human.** Every other step can and will be automated. This one never.
6. **Architecture evolves through building, not discussion.**

## Three questions for every decision

1. How does this help me today?
2. How does this scale in one year?
3. How does this work in ten years?

## Financial layers

Every expense and income belongs to exactly one layer:

- **Survival** — mandatory costs that keep life operational
- **Stability** — debt reduction, reserves, recurring obligations
- **Growth** — investments in skills, tools, business, new opportunities

## Project structure

```
gta-irl-os/
├── README.md               ← you are here
├── core/
│   ├── GLOSSARY.md         ← canonical entity definitions
│   ├── CYCLE.md            ← the 10-phase operational loop
│   └── PRINCIPLES.md       ← architectural decisions (P1–P9) + ADR log
├── docs/
│   ├── PROJECT.md          ← live project status (the only file with current data)
│   ├── ROADMAP.md          ← phase definitions and exit criteria
│   └── cases/              ← real situations used as architecture validation datasets
├── modules/
│   ├── survival-economy/   ← ACTIVE: Phase 0
│   │   ├── MODULE.md
│   │   ├── target.md
│   │   ├── branches.md
│   │   ├── idea-hold.md
│   │   └── daily/
│   ├── goals/              ← skeleton
│   ├── health/             ← skeleton
│   ├── learning/           ← skeleton
│   └── content/            ← skeleton
├── agents/                 ← Phase 1+
├── memory/                 ← snapshots + archive
└── data/schemas/           ← JSON schemas for all core entities
```

## Current phase

**Phase 0 — Manual loop**
Active module: `survival-economy`
Cycle cadence: daily

For current operational state, see:
- `docs/PROJECT.md` — project status and active priorities
- `modules/survival-economy/MODULE.md` — active module state
- `docs/ROADMAP.md` — development timeline

## Status

Started: 2026-06-25
Last updated: 2026-06-25
