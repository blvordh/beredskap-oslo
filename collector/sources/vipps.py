"""Vipps MobilePay driftsstatus (Atlassian Statuspage).

Prøver først Statuspage-JSON (/api/v2/status.json og /api/v2/incidents/unresolved.json),
faller tilbake til history.rss som er verifisert. Samme parser kan brukes for
Netaxept (netaxept-status.developers.nets.eu).
"""
from __future__ import annotations

import feedparser

from ..common import GREEN, RED, UNKNOWN, YELLOW, SourceResult, entry_get, parse_iso, truncate

ID, NAME, CATEGORY = "vipps", "Vipps MobilePay status", "betaling"
BASE = "https://status.vippsmobilepay.com"
STATUS_JSON = f"{BASE}/api/v2/status.json"
UNRESOLVED = f"{BASE}/api/v2/incidents/unresolved.json"
HISTORY_RSS = f"{BASE}/history.rss"

OPEN_WORDS = ("investigating", "identified", "monitoring")


def parse_status_json(raw: dict) -> dict:
    st = (raw or {}).get("status") or {}
    return {"indicator": (st.get("indicator") or "none").lower(), "description": st.get("description")}


def parse_unresolved(raw: dict) -> list[dict]:
    out = []
    for inc in (raw or {}).get("incidents", []) or []:
        out.append({
            "name": truncate(inc.get("name"), 200),
            "status": inc.get("status"),
            "impact": inc.get("impact"),
            "started": inc.get("started_at") or inc.get("created_at"),
            "url": inc.get("shortlink"),
            "components": [c.get("name") for c in inc.get("components", []) or []][:10],
        })
    return out


def parse_history_rss(text: str | bytes, limit: int = 10) -> list[dict]:
    feed = feedparser.parse(text)
    items = []
    for e in feed.entries[:limit]:
        d = parse_iso(entry_get(e, "published")) or parse_iso(entry_get(e, "updated")) or parse_iso(entry_get(e, "published_parsed"))
        summary = truncate(e.get("summary") or e.get("description"), 500)
        items.append({
            "name": truncate(e.get("title"), 200),
            "published": d.isoformat() if d else None,
            "summary": summary,
            "url": e.get("link"),
            "open": "resolved" not in summary.lower() and any(w in summary.lower() for w in OPEN_WORDS),
        })
    return items


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, BASE, CATEGORY)
    levels = cfg["thresholds"]["betaling"]["indicator_levels"]
    try:
        r.data["status"] = parse_status_json(http.get(STATUS_JSON))
        try:
            r.data["incidents"] = parse_unresolved(http.get(UNRESOLVED))
        except Exception:  # noqa: BLE001
            r.data["incidents"] = []
        ind = r.data["status"]["indicator"]
        lvl = levels.get(ind, UNKNOWN)
        r.add(lvl, f"Vipps MobilePay: {r.data['status']['description'] or ind}")
        return r.succeed()
    except Exception as e:  # noqa: BLE001
        r.error = f"status.json: {e}"
    try:
        r.data["history"] = parse_history_rss(http.get(HISTORY_RSS, kind="bytes"))
    except Exception as e:  # noqa: BLE001
        return r.fail(f"{r.error}; history.rss: {e}")
    open_inc = [h for h in r.data["history"] if h["open"]]
    if open_inc:
        r.add(YELLOW, f"Vipps MobilePay: pågående hendelse – {open_inc[0]['name']}", since=open_inc[0]["published"])
    else:
        r.add(GREEN, "Vipps MobilePay: ingen pågående hendelser i historikken")
    keep = r.error
    r.succeed()
    r.error = keep
    return r
