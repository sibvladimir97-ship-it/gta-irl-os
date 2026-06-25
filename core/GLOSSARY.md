# Glossary — GTA IRL OS

Canonical definitions. When a term is used anywhere in the system, it means exactly this.
Do not redefine terms in module files. If a definition needs updating, update it here.

---

## SurvivalTarget

The active financial survival contract for a crisis period.

```
SurvivalTarget {
  goal_amount:     number        // total THB needed
  current_balance: number        // THB available right now
  deficit:         number        // goal_amount - current_balance
  deadline:        date          // hard date
  days_remaining:  number        // calculated daily
  deficit_per_day: number        // deficit / days_remaining
  obligations:     Obligation[]  // itemized required payments
  layer:           "survival"    // always survival
  status:          "active" | "closed"
}
```

One active SurvivalTarget at a time. When closed, archived — never deleted.

---

## Obligation

A single mandatory payment within a SurvivalTarget.

```
Obligation {
  name:          string   // "Rent", "Motorbike", "Internet", "Utilities"
  amount:        number   // THB
  due_date:      date
  deadline_type: "hard" | "soft"   // hard = cannot negotiate, soft = can delay
  layer:         "survival" | "stability"
  paid:          boolean
}
```

---

## MoneyBranch

Any idea, action, or opportunity that can produce income.
First-class entity. Every potential income source is a MoneyBranch — nothing lives in someone's head.

```
MoneyBranch {
  id:                  string    // slug, e.g. "dani-ai-agent"
  name:                string    // human-readable
  type:                "freelance" | "client" | "product" | "passive" | "other"
  status:              "active" | "negotiation" | "frozen" | "closed" | "won"
  layer:               "survival" | "stability" | "growth"

  expected_value:      number    // THB, best estimate. 0 if unknown.
  value_confidence:    "high" | "medium" | "low" | "unknown"
  earliest_income:     date      // when money could realistically arrive
  deadline:            date | null

  probability:         1-5       // 1 = almost certain, 5 = very uncertain
  required_energy:     1-5       // 1 = light, 5 = full drain
  required_time_days:  number    // active working days to complete
  dependencies:        string[]  // other branch ids or external factors
  blocking_factors:    string[]  // what is stopping progress right now

  strategic_value:     "high" | "medium" | "low"
  automation_potential: "high" | "medium" | "low" | "none"
  synergies:           string[]  // branch ids this one amplifies

  next_action:         string    // exactly one concrete action, not a plan
  next_action_by:      date | null

  frozen_reason:       string | null   // required when status is frozen

  history:             Event[]   // append-only log of what happened
  created:             date
  updated:             date
}
```

Priority score (lower = higher priority):
`priority = probability + required_energy + (days_to_income / 2)`

---

## Event

An append-only record of something that happened to a branch or module.

```
Event {
  date:    datetime
  type:    "update" | "action" | "outcome" | "decision" | "block"
  note:    string    // plain text, what actually happened
}
```

---

## DailyFocus

Created every morning. One per day. Never edited after the evening update.

```
DailyFocus {
  date:            date
  mode:            "normal" | "crisis"
  deficit_today:   number | null    // null when no active SurvivalTarget
  active_branches: string[]         // 1-3 branch ids. 1 max in crisis mode.
  tasks:           Task[]
  frozen_today:    FrozenItem[]     // what is deliberately not touched and why
  evening_update:  EveningUpdate | null
}
```

---

## Task

One concrete action within a DailyFocus.

```
Task {
  branch_id: string
  action:    string    // specific and completable today
  done:      boolean
}
```

---

## EveningUpdate

Appended to DailyFocus at end of day.

```
EveningUpdate {
  balance_now:     number     // actual THB after today
  progress:        string     // what moved forward
  what_didnt:      string     // what didn't move and why
  blocker:         string | null
  corrections:     string     // what to adjust tomorrow
  next_priorities: string[]   // branch ids for tomorrow
}
```

---

## IdeaHold

A frozen idea that is not competing for today's energy.

```
IdeaHold {
  id:        string
  idea:      string
  captured:  date
  review_by: date | null
  reason:    string    // why frozen, not deleted
}
```

---

## StatusSnapshot

What every module exports to the Context Collapse engine.
Standardized format — one per module, updated daily.

```
StatusSnapshot {
  module:      string
  updated:     date
  status:      "green" | "yellow" | "red"
  headline:    string       // one sentence: what is happening right now
  key_metric:  string       // the one number or fact that matters most
  blocker:     string | null
  next_action: string       // one concrete step
}
```

---

## ContextCollapse

The daily compressed view of all StatusSnapshots.
Input for Decide. Never a substitute for it.

```
ContextCollapse {
  date:       date
  mode:       "normal" | "crisis"
  snapshots:  StatusSnapshot[]
  top_branch: string         // branch id with lowest priority score
  insight:    string         // one observation the human might miss
  decision:   string | null  // filled by human after reading. Never pre-filled.
}
```

---

## CrisisMode

Activated automatically when:
- deficit > 80% of SurvivalTarget.goal_amount, AND
- days_remaining < 3

Effect: system surfaces only the single highest-priority MoneyBranch.
All other branches frozen until CrisisMode exits.
CrisisMode is a view filter, not a data deletion.

---

## Layers (financial)

- **Survival** — expenses and income that keep life operational. Always first.
- **Stability** — debt, reserves, recurring obligations. Second priority.
- **Growth** — skills, tools, business, new opportunities. Only after Survival is covered.
