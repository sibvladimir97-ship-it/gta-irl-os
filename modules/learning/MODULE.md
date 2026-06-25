# Module: Learning

**Category:** Foundation (schema) + Runtime (data)
**Status:** SKELETON
**Activates:** When survival-economy exits Crisis Mode

---

## Purpose

Single responsibility: track skills acquisition and how learning converts into new MoneyBranches or improves existing ones.
Learning is not tracked for its own sake — it is tracked because new skills expand the MoneyBranch possibility space.

---

## Core entities (defined, not yet populated)

### Skill

```
Skill {
  id:              string     // e.g. "telegram-bot-api"
  name:            string
  category:        "technical" | "business" | "creative" | "language" | "other"
  level:           "exploring" | "building" | "proficient" | "expert"
  last_practiced:  date
  linked_branches: string[]   // MoneyBranch ids this skill enables or improves
  notes:           string | null
}
```

### LearningSession

```
LearningSession {
  date:      date
  skill_id:  string
  duration:  number    // minutes
  output:    string    // what was built, learned, or validated
  next:      string    // what to do next time
}
```

---

## Key insight already captured

Building the Dani agent and building GTA IRL OS are both implicit learning sessions for:
- `telegram-bot-api`
- `ai-agent-architecture`
- `python-automation`

These skills directly expand `new-ai-clients` MoneyBranch viability.
First documented example of Learning → MoneyBranch synergy.

---

## Activation checklist

1. Audit current skill set — list what you can already build
2. Map each skill to at least one existing or potential MoneyBranch
3. Begin logging LearningSession for any technical work done
4. After 14 days: identify skill gaps blocking highest-value branches

---

## StatusSnapshot (current)

```
module:      learning
status:      yellow
headline:    Module not yet active — tracking implicitly through branch work
key_metric:  n/a
blocker:     Activate after crisis resolves
next_action: Skill audit after crisis resolution
```
