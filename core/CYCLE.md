# The Operational Cycle — GTA IRL OS

The system runs one continuous loop. Every phase has a defined input, output, and owner.

---

```
Collect → Classify → Update → Analyze → Simulate → Prioritize → Collapse → Decide → Execute → Learn → ↻
```

---

## Phase 1 — Collect

**Input:** anything that happened in real life
**Output:** raw events in the inbox
**Owner (Phase 0):** you, manually
**Owner (Phase 2+):** bots, APIs, integrations

What counts as an event:
- Money received or spent
- Conversation with a client or partner
- Task completed or blocked
- New idea or opportunity
- Health or energy change
- Decision made

Rule: if it happened and it matters, it goes into Collect. Nothing stays in your head.

---

## Phase 2 — Classify

**Input:** raw events
**Output:** events routed to the correct module
**Owner (Phase 0):** you, manually
**Owner (Phase 1+):** AI classifier

Modules available for routing:
- `survival-economy` — money, income, expenses, branches
- `goals` — progress toward long-term objectives
- `health` — energy, sleep, physical state
- `learning` — skills, knowledge, study
- `content` — output, publishing, audience

Rule: every event belongs to exactly one module. If unclear, pick the most actionable one.

---

## Phase 3 — Update

**Input:** classified events
**Output:** updated module state
**Owner (Phase 0):** you, editing markdown files
**Owner (Phase 2+):** automated via event bus

What gets updated:
- MoneyBranch status, history, next_action
- SurvivalTarget balance and deficit
- StatusSnapshot for each affected module

---

## Phase 4 — Analyze

**Input:** current module states
**Output:** risk flags, probability updates, pattern observations
**Owner (Phase 0):** you, using the scoring matrix
**Owner (Phase 2+):** AI analysis agent with web access

Questions the system asks:
- Which branch has the best priority score right now?
- Is any branch stale (no progress in 2+ days)?
- Are there blocking factors that can be removed?
- Is CrisisMode condition met?

---

## Phase 5 — Simulate

**Input:** analyzed state + branch options
**Output:** "what happens if I do X vs Y" scenarios
**Owner (Phase 0):** not active — insufficient data
**Owner (Phase 1+):** AI agent building forward scenarios

Activated in Phase 1 after 30+ days of Learn data.

---

## Phase 6 — Prioritize

**Input:** analyzed branches + simulation results
**Output:** ranked list of branches and tasks
**Owner (Phase 0):** you, using priority score formula
**Owner (Phase 2+):** automated ranking with synergy graph

Priority score formula (lower = higher priority):
```
score = probability + required_energy + (days_to_income / 2)
```

Max active branches: 3 in normal mode, 1 in CrisisMode.

---

## Phase 7 — Collapse

**Input:** all StatusSnapshots + prioritized branches
**Output:** ContextCollapse document — one screen
**Owner (Phase 0):** you, filling the daily template
**Owner (Phase 1+):** AI generates the brief automatically

The Collapse document answers:
- Where am I right now? (key metrics)
- What is the single most important thing?
- What am I deliberately not doing today?
- What would I tell myself if I returned after one week away?

---

## Phase 8 — Decide

**Input:** ContextCollapse
**Output:** today's committed actions, written down
**Owner:** always you. In every phase. Forever.

Rule: no action begins without a written decision in DailyFocus.

---

## Phase 9 — Execute

**Input:** committed actions from DailyFocus
**Output:** real-world outcomes
**Owner:** you (Phase 0), partial automation (Phase 2+)

Rule: minimum viable action. Do the smallest thing that generates a signal.

---

## Phase 10 — Learn

**Input:** outcomes from Execute
**Output:** EveningUpdate + updated branch history
**Owner (Phase 0):** you, 10 minutes every evening
**Owner (Phase 2+):** AI-assisted pattern extraction

Questions the system asks every evening:
- What actually happened vs what was planned?
- Which branch moved? Which didn't?
- What needs to be corrected tomorrow?
- Did any assumption prove wrong?

Then: loop back to Collect. ↻

---

## Cadence — Phase 0

| Time | Action | Duration |
|------|--------|----------|
| Morning | Read yesterday's EveningUpdate, fill DailyFocus | 10 min |
| During day | Execute, log events to Collect | ongoing |
| Evening | Fill EveningUpdate, update branches | 10 min |

Total system overhead: ~20 minutes/day.
