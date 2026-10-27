"""Politiloggen (politiet.no) for Oslo politidistrikt. NLOD 2.0.

API: https://api.politiloggen.politiet.no (Swagger på samme vert).
  GET /messages?Districts=Oslo&Take=50&SortBy=Date&SortOrder=Descending
      → {"messages": [{id, threadId, text, district, category, municipality, area,
                       createdOn, updatedOn, isActive, ...}], "hasMoreResults": bool}
  GET /feeds/rss?districts=Oslo  (reserve)
Distrikter: Oslo, Øst, Innlandet, SørØst, Agder, SørVest, Vest, MøreOgRomsdal, Trøndelag, Nordland, Troms, Finnmark.
Verifisert 27.10.2026 (JSON). Vert api.politiet.no nekter tilkobling – ikke bruk den.
"""
from __future__ import annotations

import feedparser

from ..common import GREEN, YELLOW, SourceResult, entry_get, parse_iso, truncate

ID, NAME, CATEGORY = "politiloggen", "Politiloggen Oslo", "lokalt"
BASE = "https://api.politiloggen.politiet.no"
URL_JSON = f"{BASE}/messages"
URL_RSS = f"{BASE}/feeds/rss"
PUBLIC_URL = "https://www.politiet.no/politiloggen/"

# Kategorier og ord som løfter en melding til «alvorlig»
SERIOUS_CATEGORIES = ("brann", "voldshendelse", "eksplosjon", "skyting", "trussel", "bombe", "terror", "gass", "ulykke")
SERIOUS_WORDS = ("evakuer", "eksplosjon", "skudd", "skyting", "bombe", "trusselsituasjon", "væpnet", "bevæpnet", "gasslekkasje", "storbrann", "omkommet", "livstruende")


def _get(d: dict, *names, default=None):
    """Nøkkeloppslag uansett om API-et bruker camelCase eller PascalCase."""
    lower = {str(k).lower(): v for k, v in d.items()}
    for n in names:
        if n.lower() in lower:
            return lower[n.lower()]
    return default


def _is_serious(category: str | None, text: str | None) -> bool:
    c = (category or "").lower()
    t = (text or "").lower()
    return any(w in c for w in SERIOUS_CATEGORIES if w != "ulykke") or any(w in t for w in SERIOUS_WORDS)


def parse_json(raw: dict) -> dict:
    entries = []
    for m in (raw or {}).get("messages", []) or []:
        if not isinstance(m, dict):
            continue
        created = parse_iso(_get(m, "createdOn"))
        entries.append({
            "id": _get(m, "id"),
            "thread_id": _get(m, "threadId"),
            "text": truncate(_get(m, "text"), 500),
            "category": _get(m, "category"),
            "municipality": _get(m, "municipality"),
            "area": _get(m, "area"),
            "created": created.isoformat() if created else _get(m, "createdOn"),
            "updated": _get(m, "updatedOn"),
            "active": bool(_get(m, "isActive", default=False)),
            "link": f"{PUBLIC_URL}hendelse/{_get(m, 'id')}" if _get(m, "id") else PUBLIC_URL,
        })
    # Én oppføring per tråd (nyeste melding først i svaret)
    threads: dict = {}
    for e in entries:
        threads.setdefault(e["thread_id"] or e["id"], e)
    serious_active = [t for t in threads.values() if t["active"] and _is_serious(t["category"], t["text"])]
    return {
        "entries": entries,
        "count": len(entries),
        "threads": len(threads),
        "active_threads": sum(1 for t in threads.values() if t["active"]),
        "serious": serious_active[:20],
        "has_more": bool((raw or {}).get("hasMoreResults")),
    }


def parse_rss(text: str | bytes, limit: int = 50) -> dict:
    feed = feedparser.parse(text)
    entries = []
    for e in feed.entries[:limit]:
        d = parse_iso(entry_get(e, "published")) or parse_iso(entry_get(e, "updated")) or parse_iso(entry_get(e, "published_parsed"))
        cat = ", ".join(t.get("term", "") for t in e.get("tags", []) if t.get("term"))
        entries.append({
            "id": None, "thread_id": None,
            "text": truncate(f"{e.get('title', '')}. {e.get('summary') or e.get('description') or ''}", 500),
            "category": cat or None, "municipality": None, "area": None,
            "created": d.isoformat() if d else None, "updated": None, "active": True,
            "link": e.get("link"),
        })
    serious = [x for x in entries if _is_serious(x["category"], x["text"])]
    return {"entries": entries, "count": len(entries), "threads": len(entries), "active_threads": len(entries),
            "serious": serious[:20], "has_more": False}


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, PUBLIC_URL, CATEGORY, license="NLOD 2.0 (Politiet)")
    try:
        r.data = parse_json(http.get(URL_JSON, params={"Districts": "Oslo", "Take": 50, "SortBy": "Date", "SortOrder": "Descending"}))
        r.data["via"] = "json"
    except Exception as e:  # noqa: BLE001
        r.error = f"json: {e}"
        try:
            r.data = parse_rss(http.get(URL_RSS, params={"districts": "Oslo"}, kind="bytes"))
            r.data["via"] = "rss"
        except Exception as e2:  # noqa: BLE001
            return r.fail(f"{r.error}; rss: {e2}")
    if not r.data["count"]:
        return r.fail("Svarte uten meldinger")
    serious = r.data["serious"]
    if serious:
        s = serious[0]
        where = ", ".join(x for x in (s.get("area"), s.get("municipality")) if x)
        r.add(YELLOW, f"Politiloggen: {len(serious)} alvorlige aktive hendelser ({s['category'] or 'hendelse'}{' i ' + where if where else ''})",
              since=s.get("created"), value=len(serious))
    else:
        r.add(GREEN, f"Politiloggen: {r.data['active_threads']} aktive hendelser, ingen flagget som alvorlige", value=0)
    keep = r.error
    r.succeed()
    r.error = keep
    return r
