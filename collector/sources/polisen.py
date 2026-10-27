"""Polisen (Sverige) – händelser som åpent JSON: https://polisen.se/api/events

Felt: id, datetime, name, summary, url, type, location{name, gps}.
Vilkår: polisen.se/psidata. Brukes som bakgrunn for Nyhetsagenten (naboland).
"""
from __future__ import annotations

from ..common import GREEN, SourceResult, truncate

ID, NAME, CATEGORY = "polisen", "Polisen händelser (SE)", "naboland"
URL = "https://polisen.se/api/events"

# Hendelsestyper som er interessante for et beredskapsbilde
INTERESTING = ("Bombhot", "Sabotage", "Explosion", "Brand", "Skottlossning", "Terror", "Farligt föremål",
               "Sprängning", "Detonation", "Olaga hot", "Försvunnen", "Trafikolycka", "Allvarlig")


def parse(raw) -> dict:
    events = []
    for e in (raw or []):
        if not isinstance(e, dict):
            continue
        loc = e.get("location") or {}
        events.append({
            "id": e.get("id"),
            "datetime": e.get("datetime"),
            "name": truncate(e.get("name"), 200),
            "summary": truncate(e.get("summary"), 300),
            "type": e.get("type"),
            "location": loc.get("name"),
            "gps": loc.get("gps"),
            "url": f"https://polisen.se{e.get('url')}" if str(e.get("url", "")).startswith("/") else e.get("url"),
        })
    flagged = [ev for ev in events if any(w.lower() in f"{ev['type']} {ev['name']}".lower() for w in INTERESTING)]
    return {"events": events[:200], "count": len(events), "flagged": flagged[:50]}


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, "https://polisen.se/aktuellt/handelser/", CATEGORY, license="Se polisen.se/psidata")
    try:
        r.data = parse(http.get(URL))
    except Exception as e:  # noqa: BLE001
        return r.fail(str(e))
    r.add(GREEN, f"Polisen: {r.data['count']} hendelser, {len(r.data['flagged'])} flagget for gjennomsyn", value=len(r.data["flagged"]))
    return r.succeed()
