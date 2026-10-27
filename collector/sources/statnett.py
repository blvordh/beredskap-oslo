"""Statnett driftsdata – kraftsituasjon per prisområde, produksjon/forbruk, flyt.

Åpent JSON uten nøkkel (https://driftsdata.statnett.no/restapi). Vilkår ikke
funnet; avklar med Statnett før produksjon. Feltnavnene i svarene er bare delvis
kjent, så parsingen leter etter 'NO1' og 'powerSituation' i stedet for å anta skjema.
"""
from __future__ import annotations

import json
from typing import Any, Iterable

from ..common import GREEN, RED, UNKNOWN, YELLOW, SourceResult, epoch_ms_to_iso, to_float

ID, NAME, CATEGORY = "statnett", "Statnett driftsdata", "strom"
BASE = "https://driftsdata.statnett.no/restapi"
URL_SITUATION = f"{BASE}/ElspotPowerSituation/GetPowerSituations/"
URL_OVERVIEW = f"{BASE}/ProductionConsumption/GetLatestDetailedOverview"
URL_FLOW = f"{BASE}/PhysicalFlowMap/GetFlow"

# Statnetts trappetrinn: Normal → Stram → Svært stram → Rasjonering
SITUATION_LEVEL = {
    "normal": GREEN,
    "stram": YELLOW,
    "strained": YELLOW,
    "svært stram": RED,
    "svaert stram": RED,
    "very strained": RED,
    "rasjonering": RED,
    "rationing": RED,
}


def _walk(obj: Any) -> Iterable[dict]:
    """Alle dict-noder i et vilkårlig JSON-tre."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def parse_situations(raw: Any) -> dict:
    """Finner status per prisområde uansett hvordan listen er pakket."""
    areas: dict[str, dict] = {}
    for node in _walk(raw):
        status = node.get("powerSituation") or node.get("PowerSituation")
        if not status:
            continue
        blob = json.dumps(node, ensure_ascii=False)
        area = next((f"NO{i}" for i in range(1, 6) if f"NO{i}" in blob), None)
        if not area:
            continue
        text = node.get("text") or node.get("Text") or node.get("description") or ""
        areas[area] = {"status": str(status), "text": str(text)[:300]}
    return {"areas": areas}


def parse_flow(raw: Any, area: str = "NO1") -> list[dict]:
    flows = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            out_a, in_a = str(item.get("OutAreaElspotId", "")), str(item.get("InAreaElspotId", ""))
            if area in (out_a, in_a):
                flows.append({
                    "from": out_a,
                    "to": in_a,
                    "mw": to_float(item.get("Value")),
                    "measured_at": epoch_ms_to_iso(item.get("MeasureDate")) or item.get("MeasureDate"),
                })
    return flows


def parse_overview(raw: Any, limit: int = 80) -> dict:
    """Skjemaet er udokumentert: plukker alle (tittel, tallverdi)-par og MeasuredAt.

    Første ekte kjøring viste at svaret er for stort til å lagres rått (>20 kB),
    så vi beholder bare det som kan brukes i en tabell.
    """
    items = []
    measured = None
    for node in _walk(raw):
        if measured is None:
            measured = node.get("MeasuredAt") or node.get("measuredAt")
        title = node.get("titleTranslationId") or node.get("title") or node.get("Title") or node.get("name") or node.get("Name")
        value = node.get("value", node.get("Value"))
        if title and value is not None and not isinstance(value, (dict, list)):
            num = to_float(str(value).replace(" ", "").replace(" ", ""))
            if num is not None:
                items.append({"title": str(title)[:80], "value": num})
        if len(items) >= limit:
            break
    return {"measured_at": epoch_ms_to_iso(measured) if isinstance(measured, (int, float)) else measured, "items": items}


def level_for(status: str) -> int:
    s = (status or "").strip().lower()
    for key, lvl in SITUATION_LEVEL.items():
        if s.startswith(key):
            return lvl
    return UNKNOWN


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, "https://driftsdata.statnett.no/", CATEGORY, license="Vilkår ikke funnet; avklar med Statnett")
    errors = []
    try:
        r.data.update(parse_situations(http.get(URL_SITUATION)))
    except Exception as e:  # noqa: BLE001
        errors.append(f"situasjon: {e}")
    try:
        r.data["flows_no1"] = parse_flow(http.get(URL_FLOW), "NO1")
    except Exception as e:  # noqa: BLE001
        errors.append(f"flyt: {e}")
    try:
        r.data["overview"] = parse_overview(http.get(URL_OVERVIEW))
    except Exception as e:  # noqa: BLE001
        errors.append(f"oversikt: {e}")

    no1 = (r.data.get("areas") or {}).get("NO1")
    if not no1:
        r.error = "; ".join(errors)
        if not r.data.get("flows_no1"):
            return r.fail(r.error or "Fant ikke NO1 i svaret")
        r.add(UNKNOWN, "Statnett: fikk ikke lest kraftsituasjonen for NO1")
        r.ok = True
        r.last_success_at = r.fetched_at
        return r
    lvl = level_for(no1["status"])
    r.add(lvl, f"Statnett: kraftsituasjon NO1 er «{no1['status']}»")
    r.succeed()
    r.error = "; ".join(errors)  # delvis feil (flyt/oversikt) beholdes som merknad
    return r
