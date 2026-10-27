"""Strømpris NO1 fra hvakosterstrommen.no (åpent, gratis, krediter kilden).

GET https://www.hvakosterstrommen.no/api/v1/prices/ÅÅÅÅ/MM-DD_NO1.json
Morgendagens priser finnes fra ca. kl. 13. Informasjon, ikke trafikklys.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from ..common import GREEN, SourceResult, to_float

ID, NAME, CATEGORY = "strompris", "Hva koster strømmen (NO1)", "strom"
BASE = "https://www.hvakosterstrommen.no/api/v1/prices"
OSLO_TZ = ZoneInfo("Europe/Oslo")
CREDIT = "Strømpriser levert av Hva koster strømmen.no"


def url_for(day: dt.date, area: str = "NO1") -> str:
    return f"{BASE}/{day:%Y}/{day:%m-%d}_{area}.json"


def parse(raw: list) -> dict:
    hours = []
    for h in raw or []:
        hours.append({
            "start": h.get("time_start"),
            "end": h.get("time_end"),
            "nok_per_kwh": to_float(h.get("NOK_per_kWh")),
            "eur_per_kwh": to_float(h.get("EUR_per_kWh")),
        })
    prices = [h["nok_per_kwh"] for h in hours if h["nok_per_kwh"] is not None]
    return {
        "hours": hours,
        "min_nok": min(prices) if prices else None,
        "max_nok": max(prices) if prices else None,
        "avg_nok": round(sum(prices) / len(prices), 4) if prices else None,
    }


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, "https://www.hvakosterstrommen.no/", CATEGORY, license=CREDIT)
    today = dt.datetime.now(OSLO_TZ).date()
    try:
        r.data["today"] = parse(http.get(url_for(today)))
        r.data["today"]["date"] = today.isoformat()
    except Exception as e:  # noqa: BLE001
        return r.fail(str(e))
    tomorrow = today + dt.timedelta(days=1)
    try:
        r.data["tomorrow"] = parse(http.get(url_for(tomorrow)))
        r.data["tomorrow"]["date"] = tomorrow.isoformat()
    except Exception:  # noqa: BLE001
        r.data["tomorrow"] = None  # normalt før kl. 13
    r.data["credit"] = CREDIT
    t = r.data["today"]
    if t["avg_nok"] is not None:
        r.add(GREEN, f"Strømpris NO1 i dag: snitt {t['avg_nok']:.2f} kr/kWh (maks {t['max_nok']:.2f})", value=t["avg_nok"])
    return r.succeed()
