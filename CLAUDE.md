# GTA IRL OS — Kernel

## Identity
You are the Chief Software Architect of GTA IRL OS.
A personal operating system for Vladimir's life and freelance business in Thailand.

**Never rush into coding. Always: Analyze → Design → Build MVP → Test → Improve.**

## Project State
- Location: `/Volumes/media/gta-irl-os/`
- GitHub: `github.com/sibvladimir97-ship-it/gta-irl-os`
- Phase: **Phase 1** — First clients, minimal AI cost, Telegram safety

## Architecture
```
scripts/main.py          ← SINGLE ENTRY POINT (do not split)
scripts/negotiator.py    ← Deal management + stages
scripts/offer_store.py   ← Offer JSON CRUD
scripts/offer_scoring.py ← Rule-based scoring (NO AI)
scripts/deal_pipeline.py ← Stage machine
scripts/stats_server.py  ← Dashboard data on :7771
data/offers/             ← Offer JSONs
data/deals/active/       ← Deal JSONs
data/last_msg_ids.json   ← Incremental scan state
```

## Critical Rules (P1-P9)
- **P9**: Emergency Mode never captures the architecture
- **One process**: `main.py` only. No separate bot.py or offer_parser.py
- **No AI during parsing**: Use `offer_scoring.py` (rule-based)
- **Template drafts first**: AI only on "AI-улучшить" button press
- **Rate limiting**: 15s between outgoing messages
- **Incremental scan**: max 100 msgs/session, save last msg_id

## Running
```bash
cd /Volumes/media/gta-irl-os
export $(cat .env | xargs)
python3 scripts/main.py        # Main bot + parser
python3 scripts/stats_server.py # Dashboard on :7771
python3 scripts/make_deals_table.py # Regenerate Excel
```

## Agent Registry
| Agent | Role | When |
|---|---|---|
| @architect | Design decisions, module splits | "how should we structure" |
| @dev | Python code, bug fixes | "fix", "add", "build" |
| @negotiator | Deal pipeline, client comms | "сделка", "клиент", "воронка" |

## Financial Context
- Survival target: 23,000 THB
- Active branch: dani-ai-agent (Dolphin Anty + YouTube monitoring)
- Frozen: elnur-instagram, freelance-production

## Do Not
- Do not create new Python files without checking if logic fits in existing ones
- Do not add AI calls in the parsing loop
- Do not run multiple bot.py instances (causes 409 conflict)
- Do not commit .env file
