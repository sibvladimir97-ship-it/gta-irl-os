---
description: Start session — update knowledge graph and show system state
---

## Step 1 — Update knowledge graph
Run this to refresh the graph after recent code changes:
```bash
cd /Volumes/media/gta-irl-os
PYTHONPATH=/tmp/graphify-v8 /usr/bin/python3 -m graphify scripts --output graphify-out --no-llm
```

## Step 2 — Check processes
```bash
ps aux | grep -E "scripts/main|stats_server" | grep -v grep
```

## Step 3 — Show system state
Read data/deals/active/ and report:
- How many active deals and their stages
- Who has been waiting > 24h without response (check messages[].timestamp)
- Current priority action

Keep report under 10 lines. Do not write any code unless explicitly asked.
