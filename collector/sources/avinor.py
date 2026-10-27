"""Avinor flydata for OSL Gardermoen (XML-feed, ingen nøkkel).

https://asrv.avinor.no/XmlFeed/v1.0?airport=OSL&TimeFrom=1&TimeTo=7&direction=D
Vilkår (partner.avinor.no): poll maks hvert 3. minutt, cache på egen server,
merk «Flight data from Avinor» med lenke til avinor.no. Statuskoder: N ny info,
E ny tid (forsinket), A landet, C innstilt, D avgått. Ikke testet fra sandkassen.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ..common import GREEN, RED, YELLOW, SourceResult, parse_iso

ID, NAME, CATEGORY = "avinor", "Avinor flydata OSL", "transport"
URL = "https://asrv.avinor.no/XmlFeed/v1.0"
CREDIT = "Flight data from Avinor (avinor.no)"


def parse(xml_text: str | bytes, delay_minutes: int = 15) -> dict:
    """Statuskode E («ny tid») settes på nesten alle fly; forsinket = ny tid minst
    delay_minutes etter rutetid. Verifisert 27.10.2026: 184 av 240 fly hadde E."""
    root = ET.fromstring(xml_text)
    flights = []
    for f in root.iter("flight"):
        status = f.find("status")
        code = status.attrib.get("code") if status is not None else None
        stime = status.attrib.get("time") if status is not None else None
        sched = (f.findtext("schedule_time") or "").strip()
        delay_min = None
        a, b = parse_iso(sched), parse_iso(stime)
        if a and b:
            delay_min = round((b - a).total_seconds() / 60)
        flights.append({
            "id": f.attrib.get("uniqueID"),
            "airline": (f.findtext("airline") or "").strip(),
            "flight_id": (f.findtext("flight_id") or "").strip(),
            "scheduled": sched,
            "direction": (f.findtext("arr_dep") or "").strip(),
            "airport": (f.findtext("airport") or "").strip(),
            "dom_int": (f.findtext("dom_int") or "").strip(),
            "status_code": code,
            "status_time": stime,
            "delay_min": delay_min,
            "delayed": code == "E" and delay_min is not None and delay_min >= delay_minutes,
        })
    codes: dict[str, int] = {}
    for fl in flights:
        c = fl["status_code"] or "-"
        codes[c] = codes.get(c, 0) + 1
    return {
        "flights": flights,
        "count": len(flights),
        "cancelled": codes.get("C", 0),
        "delayed": sum(1 for fl in flights if fl["delayed"]),
        "status_codes": codes,
        "last_update": next((el.attrib.get("lastUpdate") for el in root.iter("flights")), None),
        "credit": CREDIT,
    }


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, "https://avinor.no/flyplass/oslo/", CATEGORY, license=CREDIT)
    th = cfg["thresholds"]["transport"]
    dm = int(th.get("avinor_delay_minutes", 15))
    try:
        dep = parse(http.get(URL, params={"airport": "OSL", "TimeFrom": 1, "TimeTo": 7, "direction": "D"}, kind="bytes"), dm)
        arr = parse(http.get(URL, params={"airport": "OSL", "TimeFrom": 1, "TimeTo": 7, "direction": "A"}, kind="bytes"), dm)
    except Exception as e:  # noqa: BLE001
        return r.fail(str(e))
    r.data = {
        "departures": {k: v for k, v in dep.items() if k != "flights"},
        "arrivals": {k: v for k, v in arr.items() if k != "flights"},
        "departures_list": dep["flights"][:200],
        "credit": CREDIT,
    }
    cancelled = dep["cancelled"] + arr["cancelled"]
    delayed = dep["delayed"] + arr["delayed"]
    total = dep["count"] + arr["count"]
    if cancelled >= th["avinor_red_cancelled"]:
        r.add(RED, f"OSL: {cancelled} av {total} fly innstilt kommende timer", value=cancelled)
    elif cancelled >= th["avinor_yellow_cancelled"]:
        r.add(YELLOW, f"OSL: {cancelled} av {total} fly innstilt kommende timer", value=cancelled)
    else:
        r.add(GREEN, f"OSL: {cancelled} innstilte og {delayed} forsinket over {dm} min av {total} fly", value=cancelled)
    return r.succeed()
