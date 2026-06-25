# Module: Goals

**Category:** Foundation (schema) + Runtime (data)
**Status:** SKELETON
**Activates:** When survival-economy exits Crisis Mode AND 1 week stable

---

## Purpose

Single responsibility: track progress toward long-term objectives.
Every MoneyBranch and every daily action should connect to at least one Goal.
Goals give the system a way to measure strategic value numerically, not subjectively.

---

## Core entities (defined, not yet populated)

### Goal

```
Goal {
  id:              string       // slug, e.g. "financial-independence"
  name:            string
  horizon:         "1y" | "3y" | "10y"
  layer:           "survival" | "stability" | "growth"
  metric:          string       // what "done" looks like, measurable
  current:         string       // current measured state
  target:          string       // target measured state
  deadline:        date | null
  linked_branches: string[]     // MoneyBranch ids contributing to this goal
  status:          "active" | "paused" | "achieved"
  updated:         date
}
```

---

## Activation checklist

1. Define 3–5 Goals across different horizons (1y, 3y, 10y)
2. Link every active MoneyBranch to at least one Goal
3. Add `strategic_value` auto-scoring: branch linked to 10y goal = high, 1y only = medium
4. Begin exporting StatusSnapshot to ContextCollapse

---

## StatusSnapshot (current)

```
module:      goals
status:      yellow
headline:    Module not yet active — survival crisis in progress
key_metric:  n/a
blocker:     Activate after survival-economy exits Crisis Mode
next_action: Define 3–5 long-term goals after crisis resolves
```

---

## Cold start instructions

Read this file top to bottom. Then read `goals.md` (created at activation). That is sufficient context to continue.
