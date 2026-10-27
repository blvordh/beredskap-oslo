"""Nødvarsel (DSB) – RSS over aktive og tidligere nødvarsler.

https://www.nodvarsel.no/rss/rss-aktive-nodvarsler/ og .../rss-tidligere-nodvarsler/
Dato ligger i a10:updated (Atom-navnerom), ikke pubDate. Ingen områdefelt utover tittel.
"""
from __future__ import annotations

import feedparser

from ..common import GREEN, RED, YELLOW, SourceResult, entry_get, parse_iso, truncate

ID, NAME, CATEGORY = "nodvarsel", "Nødvarsel (DSB)", "varsler"
ACTIVE = "https://www.nodvarsel.no/rss/rss-aktive-nodvarsler/"
PREVIOUS = "https://www.nodvarsel.no/rss/rss-tidligere-nodvarsler/"


def parse_feed(text: str | bytes, limit: int = 25) -> list[dict]:
    feed = feedparser.parse(text)
    items = []
    for e in feed.entries[:limit]:
        when = entry_get(e, "updated") or entry_get(e, "published") or ""
        d = parse_iso(when) or parse_iso(entry_get(e, "updated_parsed")) or parse_iso(entry_get(e, "published_parsed"))
        items.append({
            "title": truncate(e.get("title"), 200),
            "link": e.get("link"),
            "summary": truncate(e.get("summary") or e.get("description"), 500),
            "updated": d.isoformat() if d else (when or None),
        })
    return items


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, "https://www.nodvarsel.no/", CATEGORY)
    try:
        r.data["active"] = parse_feed(http.get(ACTIVE, kind="bytes"))
    except Exception as e:  # noqa: BLE001
        return r.fail(f"aktive: {e}")
    try:
        r.data["previous"] = parse_feed(http.get(PREVIOUS, kind="bytes"))
    except Exception as e:  # noqa: BLE001
        r.data["previous"] = []
        r.error = f"tidligere: {e}"
    if r.data["active"]:
        keywords = [k.lower() for k in cfg["oslo"].get("stedsnavn", ["oslo"])]
        local = [a for a in r.data["active"]
                 if any(k in f"{a['title']} {a['summary']}".lower() for k in keywords)]
        titles = "; ".join(a["title"] for a in (local or r.data["active"])[:3])
        if local:
            r.add(RED, f"Aktivt Nødvarsel i Oslo-området: {titles}", since=local[0].get("updated"))
        else:
            r.add(YELLOW, f"Aktivt Nødvarsel i Norge (utenfor Oslo-området): {titles}",
                  since=r.data["active"][0].get("updated"))
    else:
        last = r.data["previous"][0]["title"] if r.data["previous"] else "ingen registrert"
        r.add(GREEN, f"Ingen aktive Nødvarsel (siste: {last})")
    ok_err = r.error
    r.succeed()
    r.error = ok_err
    return r
