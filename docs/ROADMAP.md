# ROADMAP — GTA IRL OS

Development roadmap. Phases define capability levels, not calendar dates.
A phase is complete when its exit criteria are met — not when time passes.

---

## Phase 0 — Manual loop

**Goal:** Prove the cycle works with a human doing every step manually.

**What exists:**
- Core vocabulary (GLOSSARY.md)
- Operational cycle (CYCLE.md)
- Architectural principles (PRINCIPLES.md)
- survival-economy module (active)
- Module skeletons for all other domains
- Daily markdown-based cycle

**Exit criteria:**
- 30 consecutive days of completed DailyFocus + EveningUpdate
- At least 2 modules active simultaneously
- At least 1 case archived in docs/cases/
- ContextCollapse template used daily without friction

**Current status:** ACTIVE — started 2026-06-25

---

## Phase 1 — AI-assisted loop

**Goal:** Replace manual Classify, Analyze, and Collapse with AI agents.
Human still owns Decide. Always.

**What gets built:**
- AI classifier agent (Classify phase)
- AI analysis agent with web search access (Analyze phase)
- AI-generated ContextCollapse brief (Collapse phase)
- Structured data storage (move from markdown to lightweight DB)
- goals module activated with long-term objective tracking

**Exit criteria:**
- AI classifier routes events with >85% accuracy vs manual
- ContextCollapse generated automatically each morning
- 3+ modules active and exporting StatusSnapshot
- First Simulate prototype built on Phase 0 data

**Dependencies:** Phase 0 exit criteria met

---

## Phase 2 — Connected loop

**Goal:** System collects events automatically. Human input becomes optional for Collect.

**What gets built:**
- Telegram bot integration (event input)
- Bank/financial API integration (balance auto-update)
- GitHub activity integration (learning/projects tracking)
- Event bus connecting modules
- Synergy graph for MoneyBranch cross-connections
- Simulate phase activated with 90+ days of historical data

**Exit criteria:**
- Collect phase requires zero manual input for routine events
- All modules active and interconnected via event bus
- Simulate generates useful forward scenarios (validated against outcomes)
- Web interface prototype usable daily

**Dependencies:** Phase 1 exit criteria met

---

## Phase 3 — Platform

**Goal:** System is stable, autonomous, and shareable with other people.

**What gets built:**
- Web application (primary interface)
- Mobile interface
- Multi-user architecture
- Public API
- Onboarding flow for new users
- Documentation site

**Exit criteria:**
- System runs 30 days with minimal manual intervention
- At least 3 external users running their own instances
- Architecture review: nothing from Phase 0 vocabulary has broken

**Dependencies:** Phase 2 exit criteria met

---

## Phase 4 — Scale

**Goal:** Platform used by many people. GTA IRL OS becomes infrastructure.

**Scope:** Defined at Phase 3 exit based on what was learned.

---

## What never changes across all phases

1. **Decide belongs to the human.** In Phase 4 as in Phase 0.
2. **One responsibility per module.** New modules added; existing ones not expanded.
3. **Cold start in 60 seconds.** Every module resumable at any phase.
4. **Stable vocabulary.** GLOSSARY.md terms versioned, not silently redefined.
5. **Emergency Mode never captures the architecture.** (P9)

---

## Cases — real situations that validated the architecture

| Case | Phase | Period | Key learning |
|------|-------|--------|--------------|
| June 2026 survival crisis | 0 | 2026-06 | First test of MoneyBranch model and CrisisMode |

*(Each closed case links to `docs/cases/YYYY-MM-name.md`)*
