# Case: June 2026 Survival Crisis

**Category:** Case Data
**Type:** Financial survival
**Period:** 2026-06-25 — open
**Module:** survival-economy
**Status:** IN PROGRESS

---

## Situation at case open

| Field | Value |
|-------|-------|
| Balance | 200 THB |
| Required | ~23,000 THB |
| Deadline | 2026-06-27 (rent negotiable) |
| Days available | 2 |

Obligations: Rent 13,000 · Motorbike 5,000 · Internet 2,000 · Utilities ~3,000 THB

---

## Branch triage

| Branch | Decision | Reason |
|--------|----------|--------|
| dani-ai-agent | Active | Highest strategic value + fastest realistic path to income |
| elnur-instagram | Frozen | Payment timeline incompatible with 48h deadline |
| freelance-production | Frozen (fallback) | Activate only if Dani stalls |
| new-ai-clients | Frozen | Sales cycle minimum 1–2 weeks |
| dota-camp | Removed | No reliable signal |

---

## What this case tests in the architecture

- MoneyBranch schema under real pressure (13-field model)
- CrisisMode branch filtering (single active branch)
- Priority score formula: `probability + energy + days_to_income/2`
- Anti-Abandon Protocol (cold start resumability)
- P9: Emergency Mode isolation from core documents

---

## Architectural insights (append-only)

- 2026-06-25: Building GTA IRL OS and building the Dani demo are synergistic — same technical work, two outcomes. First validated instance of branch synergy field in MoneyBranch schema.
- 2026-06-25: CrisisMode correctly identified 4 of 5 branches as non-viable within 48h. Single-branch focus validated by situation, not imposed on it.
- 2026-06-25: Human correctly overrode system's push for immediate action in favour of building technical confidence first. Confirms P4: Decide belongs to the human.
- 2026-06-25: Rent deadline is soft (negotiable). Hard vs soft deadline distinction added to Obligation schema in GLOSSARY v1.

---

## Outcome

*(fill when case closes)*

**Closed:** —
**Resolution:** —
**Income by deadline:** —
**Schema changes triggered:** —
