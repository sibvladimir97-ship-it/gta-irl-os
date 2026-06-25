# Module: Health

**Category:** Foundation (schema) + Runtime (data)
**Status:** SKELETON
**Activates:** When survival-economy exits Crisis Mode

---

## Purpose

Single responsibility: track energy, sleep, and physical state.
The system needs this data because energy is a finite resource that the Prioritize phase must account for.
A branch scored "required_energy: 4" on a day when health status is "low" should be deprioritized automatically.

---

## Core entities (defined, not yet populated)

### DailyHealth

```
DailyHealth {
  date:          date
  energy:        1-5        // 1 = depleted, 5 = peak
  sleep_hours:   number
  sleep_quality: 1-5
  physical:      "fine" | "minor issue" | "blocked"
  notes:         string | null
}
```

### HealthSnapshot (for StatusSnapshot export)

```
HealthSnapshot {
  date:         date
  energy_today: 1-5
  trend:        "improving" | "stable" | "declining"
  flag:         string | null  // e.g. "low energy — deprioritize high-energy branches today"
}
```

---

## Integration with survival-economy

When health module is active:
- DailyFocus generation reads today's energy score
- Branches with `required_energy > today_energy + 1` are flagged, not blocked
- EveningUpdate asks: "did energy affect execution today?"

---

## Activation checklist

1. Start logging DailyHealth every evening (2 minutes)
2. After 7 days: review whether energy scores correlate with branch progress
3. After 14 days: enable energy-aware branch flagging in DailyFocus

---

## StatusSnapshot (current)

```
module:      health
status:      yellow
headline:    Module not yet active
key_metric:  n/a
blocker:     Activate after crisis resolves
next_action: Begin daily energy logging on activation
```
