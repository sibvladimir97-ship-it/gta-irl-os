# Architectural Principles — GTA IRL OS

Every principle here exists because of a specific decision made at a specific point.
If a principle is ever changed, record why.

---

## P1 — Stable vocabulary, not stable structure

**Decision:** Define entities in GLOSSARY.md. Implementation (file formats, databases, APIs) can change freely. Vocabulary cannot change without a versioned update to GLOSSARY.md.

**Why:** The system will be rewritten multiple times over 10 years. What must survive each rewrite is the meaning of MoneyBranch, StatusSnapshot, ContextCollapse — not the format they're stored in.

**Consequence:** Never define what a term means inside a module file. Always reference GLOSSARY.md.

---

## P2 — One responsibility per module

**Decision:** Each module owns exactly one domain of life. No module reaches into another module's state directly.

**Why:** Modules that share responsibility become impossible to reason about after 6 months.

**Consequence:** Cross-module communication happens only through StatusSnapshot, exported to ContextCollapse. Modules are islands. The Collapse layer is the bridge.

---

## P3 — Cold start in under 60 seconds

**Decision:** Any module must be resumable after an absence of any length. MODULE.md always contains: current status, last decision, next concrete action.

**Why:** The biggest risk to this system is abandonment followed by inability to re-enter.

**Consequence:** Every evening update must answer: "what would I tell myself if I came back in one month?"

---

## P4 — Decide belongs to the human, always

**Decision:** The system never takes an action on behalf of the user without explicit written confirmation in DailyFocus.

**Why:** A system that decides for you is a system you stop trusting.

**Consequence:** Automation is allowed in Collect, Classify, Update, Analyze, Simulate, Prioritize, Collapse. Never in Decide.

---

## P5 — Crisis Mode changes the interface, not the architecture

**Decision:** When CrisisMode conditions are met, the system surfaces exactly one branch and suppresses all others from the daily view. The data remains intact.

**Why:** Under acute financial pressure, optionality is not a feature — it's a threat.

**Consequence:** CrisisMode is a view filter, not a data deletion.

---

## P6 — Throw away fast and cheaply

**Decision:** MVP implementations are intentionally minimal. They are expected to be rewritten.

**Why:** "Build it so you don't have to rewrite it" leads to over-engineering at Phase 0.

**Consequence:** Phase 0 uses markdown files. The vocabulary (P1) is what carries forward, not the files.

---

## P7 — Simulate is earned, not assumed

**Decision:** The Simulate phase is not active until 30+ days of Learn data exists.

**Why:** Simulation without historical data produces hallucination, not insight.

**Consequence:** Phase 0 has no Simulate.

---

## P8 — Maximum 3 active branches in normal mode, 1 in crisis

**Decision:** The system enforces a hard limit on active MoneyBranches at the Prioritize phase.

**Why:** More than 3 active branches means none of them receive sufficient energy.

**Consequence:** When a 4th branch is added as "active", the system flags it and asks which to freeze.

---

## P9 — Emergency Mode never captures the architecture

**Decision:** When CrisisMode is active, it changes what the system *surfaces* — not what the system *is*. Crisis-specific data lives exclusively inside the active module. It never propagates to core documents, README, ROADMAP, or other modules.

**Why:** A system designed around today's emergency becomes useless the moment the emergency ends. The architecture must remain coherent from the perspective of someone reading it in three years.

**Consequence:**
- `README.md` never contains specific financial figures or deadlines
- `ROADMAP.md` never lists a crisis as a milestone
- `PRINCIPLES.md` never references specific clients or situations
- Crisis datasets are archived as `docs/cases/YYYY-MM-case-name.md` after resolution
- The test "would this make sense to a reader in 5 years?" applies to every core document

**Corollary:** Every real situation that exercises the system becomes a *case* — a dataset that validates the architecture, not a constraint that shapes it.

---

## ADR log (Architectural Decision Records)

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-25 | Context Collapse chosen over Decision Engine | Engine hides context behind algorithm; Collapse keeps human in control while compressing information |
| 2026-06-25 | Markdown files for Phase 0 storage | Zero setup cost, version-controlled, readable without tools |
| 2026-06-25 | Survival/Stability/Growth financial layers | Every financial event needs exactly one classification to avoid ambiguity |
| 2026-06-25 | MoneyBranch as first-class entity | Income opportunities treated as structured data, not mental notes |
| 2026-06-25 | P9 added: Emergency Mode never captures the architecture | Crisis data must not leak into core documents; real situations become cases, not constraints |
