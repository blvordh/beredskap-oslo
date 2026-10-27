"""Aggregator: fra kilderesultater til status.json med trafikklys per kategori."""
from __future__ import annotations

from .common import CATEGORIES, GREEN, LEVEL_NAME, RED, UNKNOWN, YELLOW, SourceResult, now_iso

CATEGORY_NAMES = {
    "strom": "Strøm",
    "vann": "Vann",
    "ekom": "Mobil og internett",
    "betaling": "Betaling og bank",
    "transport": "Transport",
    "varsler": "Varsler",
    "lokalt": "Lokalt",
    "naboland": "Naboland",
    "nyheter": "Nyheter",
}

NO_SOURCE_NOTE = {
    "ekom": "Ingen automatisk kilde ennå: operatørenes driftssider må skrapes, eller Cloudflare Radar slås på med token.",
}


def _source_summary(r: SourceResult) -> dict:
    return {
        "id": r.id,
        "name": r.name,
        "url": r.url,
        "ok": r.ok,
        "stale": r.stale,
        "fetched_at": r.fetched_at,
        "last_success_at": r.last_success_at,
        "error": r.error,
        "license": r.license,
    }


def build_status(results: list[SourceResult], generated_at: str | None = None, version: str = "0.1") -> dict:
    cats = {
        c: {"id": c, "name": CATEGORY_NAMES.get(c, c), "level": UNKNOWN, "level_name": "unknown",
            "headline": "", "stale": False, "signals": [], "sources": []}
        for c in CATEGORIES
    }
    for r in results:
        cats.setdefault(r.category, {"id": r.category, "name": CATEGORY_NAMES.get(r.category, r.category), "level": UNKNOWN,
                                     "level_name": "unknown", "headline": "", "stale": False, "signals": [], "sources": []})
        cats[r.category]["sources"].append(_source_summary(r))
        for s in r.signals:
            d = s.to_dict()
            d["stale"] = r.stale
            d["fetched_at"] = r.last_success_at or r.fetched_at
            cats.setdefault(s.category, cats[r.category])
            cats[s.category]["signals"].append(d)

    for c, cat in cats.items():
        known = [s for s in cat["signals"] if s["level"] != UNKNOWN]
        if known:
            worst = max(s["level"] for s in known)
            lead = next(s for s in sorted(known, key=lambda s: -s["level"]))
            cat["level"] = worst
            cat["headline"] = lead["text"]
            cat["stale"] = any(s["stale"] for s in known)
            if cat["stale"]:
                cat["headline"] += " (siste vellykkede henting " + (lead.get("fetched_at") or "ukjent") + ")"
        elif cat["sources"]:
            cat["headline"] = "Kildene svarte ikke: " + "; ".join(
                f"{s['name']}: {s['error'] or 'ukjent feil'}" for s in cat["sources"] if not s["ok"]
            )[:300]
        else:
            cat["headline"] = NO_SOURCE_NOTE.get(c, "Ingen kilde konfigurert")
        cat["level_name"] = LEVEL_NAME[cat["level"]]
        cat["signals"].sort(key=lambda s: -s["level"])

    levels = [c["level"] for c in cats.values() if c["level"] != UNKNOWN and c["id"] != "nyheter"]
    overall = max(levels) if levels else UNKNOWN
    red = [c["name"] for c in cats.values() if c["level"] == RED]
    yellow = [c["name"] for c in cats.values() if c["level"] == YELLOW]
    if overall == RED:
        summary = "Rødt: " + ", ".join(red)
    elif overall == YELLOW:
        summary = "Gult: " + ", ".join(yellow)
    elif overall == GREEN:
        summary = "Ingen avvik registrert i de automatiske kildene"
    else:
        summary = "Ingen kilder svarte"
    return {
        "generated_at": generated_at or now_iso(),
        "generator": f"beredskap-oslo-collector {version}",
        "disclaimer": "Uoffisiell tjeneste. Automatisk sammenstilt fra åpne kilder; følg alltid Nødvarsel, politiet og Oslo kommune.",
        "overall": {"level": overall, "level_name": LEVEL_NAME[overall], "summary": summary},
        "categories": cats,
        "sources_total": len(results),
        "sources_failed": [r.id for r in results if not r.ok],
        "sources_stale": [r.id for r in results if r.stale],
    }
