#!/usr/bin/env python3
"""
GTA IRL OS — Stats Server
Локальный HTTP сервер на порту 7771.
Читает данные из data/ и отдаёт JSON для дашборда.
"""

import os
import json
import glob
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFERS_DIR  = os.path.join(ROOT, "data", "offers")
DEALS_DIR   = os.path.join(ROOT, "data", "deals", "active")
LAST_IDS    = os.path.join(ROOT, "data", "last_msg_ids.json")


def get_stats():
    # Офферы
    offers = []
    for f in glob.glob(os.path.join(OFFERS_DIR, "*.json")):
        try:
            offers.append(json.load(open(f)))
        except:
            pass

    by_status = {}
    for o in offers:
        s = o.get("status", "NEW")
        by_status[s] = by_status.get(s, 0) + 1

    recent = sorted(offers, key=lambda x: x.get("created_at", ""), reverse=True)[:8]
    recent_out = []
    for o in recent:
        recent_out.append({
            "id":     o.get("offer_id", "")[:8],
            "status": o.get("status", "NEW"),
            "chat":   o.get("display", {}).get("chat_name", ""),
            "date":   o.get("created_at", ""),
        })

    # Сделки
    deals = []
    for f in glob.glob(os.path.join(DEALS_DIR, "*.json")):
        try:
            deals.append(json.load(open(f)))
        except:
            pass

    by_stage = {}
    for d in deals:
        s = d.get("stage", "")
        by_stage[s] = by_stage.get(s, 0) + 1

    # Last msg ids
    last_ids = {}
    if os.path.exists(LAST_IDS):
        try:
            last_ids = json.load(open(LAST_IDS))
        except:
            pass

    return {
        "offers_total":     len(offers),
        "offers_new":       by_status.get("NEW", 0),
        "offers_responded": by_status.get("RESPONDED", 0),
        "offers_hidden":    by_status.get("HIDDEN", 0),
        "offers_scam":      by_status.get("SCAM", 0),
        "offers_delegated": by_status.get("DELEGATED", 0),
        "deals_total":      len(deals),
        "deals_sent":       by_stage.get("FIRST_MESSAGE_SENT", 0),
        "deals_waiting":    by_stage.get("WAITING_REPLY", 0) + by_stage.get("CLIENT_REPLIED", 0),
        "deals_qualifying": by_stage.get("QUALIFYING", 0),
        "deals_inwork":     by_stage.get("IN_WORK", 0),
        "last_msg_ids":     last_ids,
        "recent_offers":    recent_out,
        "updated_at":       datetime.now().strftime("%H:%M:%S"),
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/stats", "/stats/"):
            data = json.dumps(get_stats(), ensure_ascii=False)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # тихий режим


if __name__ == "__main__":
    port = 7771
    print(f"GTA IRL OS Stats Server → http://localhost:{port}/stats")
    HTTPServer(("localhost", port), Handler).serve_forever()
