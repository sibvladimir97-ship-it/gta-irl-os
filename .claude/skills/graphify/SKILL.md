# Graphify — GTA IRL OS Knowledge Graph

When asked about the project architecture, module dependencies, or function relationships, use the knowledge graph instead of reading raw files.

## Graph Location
`graphify-out/graph.json` — 295 nodes, 710 edges, 11 communities

## How to Query

Instead of reading all files, ask:
- "Which functions call `send_to_owner`?"
- "What modules import from `negotiator.py`?"
- "Show me all functions in `main.py`"

## Update the Graph
Run after any significant code changes:
```bash
cd /Volumes/media/gta-irl-os
PYTHONPATH=/tmp/graphify-v8 /usr/bin/python3 -m graphify scripts --output graphify-out --no-llm
```

## Key Nodes (from graph)
- `main.py` — 634 lines, entry point, 8 responsibilities
- `negotiator.py` — 1030 lines, deal management
- `offer_store.py` — offer CRUD
- `deal_pipeline.py` — stage machine
- `offer_scoring.py` — rule-based scoring (no AI)

## Architecture Insight
The graph shows `main.py` has 200+ outgoing edges — it's a god module.
Phase 2 goal: split into `parser_service.py`, `bot_service.py`, `sender_service.py`.
