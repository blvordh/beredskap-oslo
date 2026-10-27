"""MET MetAlerts 2.0 – farevarsler for Oslo fylke (03) som GeoJSON.

https://api.met.no/weatherapi/metalerts/2.0/current.json?county=03
Krever User-Agent med kontaktinfo (ellers 403). Bruk If-Modified-Since i drift.
Lisens: CC BY 4.0 (iflg. MET), krediter «Meteorologisk institutt».
"""
from __future__ import annotations

from ..common import GREEN, RED, YELLOW, SourceResult, to_int

ID, NAME, CATEGORY = "met", "MET farevarsel (Oslo)", "varsler"
URL = "https://api.met.no/weatherapi/metalerts/2.0/current.json"

# awareness_level: "2; yellow; Moderate" → 2 (gult), 3 oransje, 4 rødt
LEVEL = {1: GREEN, 2: YELLOW, 3: RED, 4: RED}
COLOR = {2: "gult", 3: "oransje", 4: "rødt"}


def awareness_number(props: dict) -> int:
    s = str(props.get("awareness_level") or "")
    return to_int(s.split(";")[0], 0)


def parse(raw: dict) -> dict:
    alerts = []
    for feat in (raw or {}).get("features", []) or []:
        p = feat.get("properties", {}) or {}
        when = (feat.get("when") or {}).get("interval") or []
        alerts.append({
            "id": p.get("id"),
            "event": p.get("event"),
            "title": p.get("title"),
            "level": awareness_number(p),
            "color": p.get("riskMatrixColor"),
            "area": p.get("area"),
            "severity": p.get("severity"),
            "certainty": p.get("certainty"),
            "description": (p.get("description") or "")[:500],
            "instruction": (p.get("instruction") or "")[:300],
            "start": when[0] if len(when) > 0 else None,
            "end": when[1] if len(when) > 1 else None,
        })
    return {"alerts": alerts, "count": len(alerts), "max_level": max([a["level"] for a in alerts] or [0])}


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, "https://www.yr.no/nb/farevarsler", CATEGORY, license="CC BY 4.0, Meteorologisk institutt")
    try:
        r.data = parse(http.get(URL, params={"county": cfg["oslo"]["fylkesnummer"], "lang": "no"}))
    except Exception as e:  # noqa: BLE001
        return r.fail(str(e))
    if not r.data["alerts"]:
        r.add(GREEN, "Ingen farevarsler fra MET for Oslo")
    else:
        worst = r.data["max_level"]
        titles = "; ".join(a["title"] or a["event"] or "" for a in r.data["alerts"][:3])
        r.add(LEVEL.get(worst, YELLOW), f"MET {COLOR.get(worst, 'gult')} farevarsel: {titles}", value=worst)
    return r.succeed()
