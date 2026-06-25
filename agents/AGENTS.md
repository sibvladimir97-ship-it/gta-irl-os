# Agents — GTA IRL OS

**Category:** Foundation

Agents are the AI automation layer of the operational cycle.
Each agent owns exactly one phase of the cycle — same single-responsibility rule as modules.
Agents are built in Phase 1+. This file defines what each agent does when built.

No agent is built until the manual loop (Phase 0) validates the cycle for 30+ days.

---

## Agent registry

| Agent | Cycle phase | Status | Builds in |
|-------|------------|--------|-----------|
| classifier-agent | Classify | not built | Phase 1 |
| analysis-agent | Analyze | not built | Phase 1 |
| collapse-agent | Collapse | not built | Phase 1 |
| simulate-agent | Simulate | not built | Phase 2 |
| collect-agent | Collect | not built | Phase 2 |

---

## classifier-agent

**Owns:** Cycle phase 2 — Classify
**Input:** Raw event text (from any source)
**Output:** `{ module, event_type, entities }`
**Replaces:** Manual routing of events to modules

Reads raw event → identifies module → extracts structured entities (amounts, dates, branch ids) → writes to module inbox → flags ambiguous events for human review (never silently drops).

Accuracy threshold before removing human fallback: 85% over 50 events.

---

## analysis-agent

**Owns:** Cycle phase 4 — Analyze
**Input:** Current state of all modules (StatusSnapshots + branch data)
**Output:** Risk flags, stale branch alerts, priority score updates, pattern observations

Checks every active branch for staleness (2+ days no movement) → detects CrisisMode conditions → optionally web-searches market signals relevant to active branches → outputs observations only, never decisions.

---

## collapse-agent

**Owns:** Cycle phase 7 — Collapse
**Input:** All StatusSnapshots + ranked branch list
**Output:** ContextCollapse document — one screen, ready to read

Assembles StatusSnapshots → identifies highest-priority branch → writes one insight the human might miss → formats daily brief → delivers as markdown file (Phase 1), push notification (Phase 3).

---

## simulate-agent

**Owns:** Cycle phase 5 — Simulate
**Input:** Current state + 90+ days of Learn data
**Output:** 2–3 forward scenarios per active branch

Only activates after 90 days of data (P7). Builds scenarios from historical patterns.
Each scenario: probability + expected income + required energy + key risk.
Never recommends. Presents options only.

---

## collect-agent

**Owns:** Cycle phase 1 — Collect (automated sources)
**Input:** Telegram, bank webhooks, GitHub, calendar
**Output:** Raw events as standard Event objects → classifier-agent

Listens to configured integrations → formats signals → passes to classifier.
Human input channel always remains open in parallel.
