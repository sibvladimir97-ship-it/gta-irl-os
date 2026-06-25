# Module: Content

**Category:** Foundation (schema) + Runtime (data)
**Status:** SKELETON
**Activates:** When stability layer is partially covered (post-crisis)

---

## Purpose

Single responsibility: track content output and how it generates inbound MoneyBranches.
Content is not tracked as a creative output — it is tracked as a distribution mechanism
that converts skills and knowledge into audience, which converts into clients.

---

## Core entities (defined, not yet populated)

### ContentPiece

```
ContentPiece {
  id:            string
  title:         string
  format:        "post" | "video" | "thread" | "article" | "demo" | "tutorial"
  platform:      string        // "telegram" | "instagram" | "github" | "youtube" | etc.
  status:        "idea" | "draft" | "published" | "archived"
  topic:         string        // what skill or project it showcases
  linked_skill:  string | null
  linked_branch: string | null // MoneyBranch it supports or generates
  published:     date | null
  reach:         number | null
  outcome:       string | null // did it generate a lead, client, or opportunity?
}
```

---

## Key design decision

Content is downstream of Learning and survival-economy — not upstream.
Publish what you are already building, not what you think you should build.

---

## Activation checklist

1. Review what has already been built in Phase 0
2. Identify which pieces can be published with minimal extra effort
3. Define one primary platform for Phase 1 content
4. Create first ContentPiece entry

---

## StatusSnapshot (current)

```
module:      content
status:      yellow
headline:    Module not yet active — content produced but not tracked
key_metric:  n/a
blocker:     Activate after stability layer partially covered
next_action: Identify first publishable piece after crisis resolves
```
