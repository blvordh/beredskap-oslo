"""RSS-snapshot for Nyhetsagenten.

Henter alle feeder i config.news_feeds med enabled: true, beholder bare saker
innenfor news_window_hours, og skriver dem samlet. Bare overskrift, ingress
(kuttet) og lenke lagres – aldri fulltekst. Feeder med requires_agreement
(Schibsted) står avslått til avtale foreligger.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from concurrent.futures import ThreadPoolExecutor

import feedparser

from ..common import GREEN, SourceResult, entry_get, now_utc, parse_iso, truncate

ID, NAME, CATEGORY = "rss_news", "Nyhetsfeeder (RSS)", "nyheter"


def _entry_date(e) -> dt.datetime | None:
    for key in ("published", "updated", "created", "published_parsed", "updated_parsed"):
        d = parse_iso(entry_get(e, key))
        if d:
            return d
    return None


def parse_feed(text: str | bytes, feed_cfg: dict, cutoff: dt.datetime | None = None) -> list[dict]:
    feed = feedparser.parse(text)
    items = []
    for e in feed.entries:
        d = _entry_date(e)
        if cutoff and d and d < cutoff:
            continue
        link = e.get("link") or ""
        key = hashlib.sha1(f"{feed_cfg['id']}|{link or e.get('title', '')}".encode()).hexdigest()[:12]
        items.append({
            "key": key,
            "source": feed_cfg["id"],
            "source_name": feed_cfg.get("name"),
            "group": feed_cfg.get("group"),
            "lang": feed_cfg.get("lang"),
            "title": truncate(e.get("title"), 220),
            "summary": truncate(e.get("summary") or e.get("description"), 320),
            "link": link,
            "published": d.isoformat() if d else None,
        })
    return items


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, "", CATEGORY)
    feeds = [f for f in cfg.get("news_feeds", []) if f.get("enabled")]
    cutoff = now_utc() - dt.timedelta(hours=int(cfg.get("news_window_hours", 36)))
    results: dict[str, dict] = {}

    def one(f):
        try:
            items = parse_feed(http.get(f["url"], kind="bytes"), f, cutoff)
            return f["id"], {"ok": True, "count": len(items), "items": items, "error": ""}
        except Exception as e:  # noqa: BLE001
            return f["id"], {"ok": False, "count": 0, "items": [], "error": truncate(str(e), 200)}

    with ThreadPoolExecutor(max_workers=int(cfg.get("http", {}).get("workers", 8))) as ex:
        for fid, res in ex.map(one, feeds):
            results[fid] = res

    items = [it for res in results.values() for it in res["items"]]
    items.sort(key=lambda x: x["published"] or "", reverse=True)
    ok_feeds = [k for k, v in results.items() if v["ok"]]
    failed = {k: v["error"] for k, v in results.items() if not v["ok"]}
    r.data = {
        "window_hours": int(cfg.get("news_window_hours", 36)),
        "feeds_ok": len(ok_feeds),
        "feeds_failed": failed,
        "item_count": len(items),
        "items": items,
    }
    if not ok_feeds:
        return r.fail("Ingen feeder svarte")
    r.add(GREEN, f"{len(items)} saker fra {len(ok_feeds)} feeder siste {r.data['window_hours']} t ({len(failed)} feeder feilet)", value=len(items))
    r.succeed()
    if failed:
        r.error = f"{len(failed)} feeder feilet: {', '.join(list(failed)[:8])}"
    return r
