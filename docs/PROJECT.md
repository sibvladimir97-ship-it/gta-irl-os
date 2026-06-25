# PROJECT.md — GTA IRL OS

Live project state. Updated as the system evolves.
This is the only document that contains current operational data.
Core documents (README, GLOSSARY, PRINCIPLES, ROADMAP) remain stable.

---

## Current phase

**Phase 0 — Manual loop**
Started: 2026-06-25

The system runs on markdown files and manual daily cycles.
No automation. No agents. No web app.
Goal: validate the vocabulary and cycle through real usage.

---

## Active modules

| Module | Status | Since |
|--------|--------|-------|
| survival-economy | ACTIVE | 2026-06-25 |
| goals | SKELETON | — |
| health | SKELETON | — |
| learning | SKELETON | — |
| content | SKELETON | — |

---

## Active cases

| Case | Module | Status | Ref |
|------|--------|--------|-----|
| June 2026 survival crisis | survival-economy | IN PROGRESS | `docs/cases/2026-06-survival.md` |

---

## System health

| Layer | Status | Notes |
|-------|--------|-------|
| Core vocabulary | stable | GLOSSARY.md v1 |
| Operational cycle | defined | CYCLE.md v1 |
| Principles | stable | PRINCIPLES.md, P1–P9 |
| Storage | markdown | Phase 0 only |
| Agents | not built | Phase 1+ |
| Interfaces | not built | Phase 2+ |

---

## Open architectural questions

| Question | Deferred until |
|----------|----------------|
| Database schema for Phase 1 | After 30 days of Phase 0 data |
| Agent architecture (which framework) | After manual cycle is validated |
| Cross-module synergy graph structure | After 3+ modules are active |
| Multi-user / platform architecture | Phase 3+ |

---

## Session log

**2026-06-25** — Architecture sessions 1–5. Full repository skeleton created (22 files).
P9 added. Emergency Mode isolation established. June 2026 crisis classified as first case dataset.
Repository pushed to GitHub. Phase 0 manual loop begins.

---

## Next session priorities

1. First complete daily cycle: morning DailyFocus → Execute → EveningUpdate
2. Choose next implementation artifact after first cycle completes
