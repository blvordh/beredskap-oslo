"""Elvia strømbrudd i Oslo – ArcGIS FeatureServer bak strømbruddskartet.

Udokumentert, åpent endepunkt uten nøkkel. Lag 1 = polygoner med attributter
per avbrudd. Verifisert 27.10.2026. Kan endres uten varsel, derfor defensiv parsing.
"""
from __future__ import annotations

from ..common import GREEN, RED, YELLOW, SourceResult, epoch_ms_to_iso, to_int

ID, NAME, CATEGORY = "elvia", "Elvia strømbruddskart", "strom"
URL = ("https://services-eu1.arcgis.com/AcdYbPzrkOfBOQDL/arcgis/rest/services/"
       "avbrudd2_offentlig_visning/FeatureServer/1/query")
PUBLIC_URL = "https://www.elvia.no/strombruddskart/"


def parse(raw: dict) -> dict:
    """Normaliserer ArcGIS-svar til en liste av avbrudd."""
    outages = []
    for feat in raw.get("features", []) or []:
        a = feat.get("attributes", {}) or {}
        kind = str(a.get("avbruddstype") or "").strip()
        planned = kind.lower().startswith("plan")
        outages.append({
            "customers": to_int(a.get("antallkunder")),
            "planned": planned,
            "type": kind,
            "status": a.get("statusavbrudd"),
            "description": a.get("beskrivelse"),
            "detected_at": epoch_ms_to_iso(a.get("strombruddoppdaget")),
            "start": epoch_ms_to_iso(a.get("utkoblingstart")),
            "end": epoch_ms_to_iso(a.get("utkoblingslutt")),
            "postcode": a.get("postnummer"),
            "place": a.get("poststed"),
            "substation": a.get("nettstasjon"),
        })
    unplanned = [o for o in outages if not o["planned"]]
    return {
        "outages": outages,
        "count": len(outages),
        "unplanned_count": len(unplanned),
        "customers_unplanned": sum(o["customers"] for o in unplanned),
        "customers_planned": sum(o["customers"] for o in outages if o["planned"]),
    }


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, PUBLIC_URL, CATEGORY, license="Udokumentert ArcGIS-tjeneste, ingen vilkår funnet")
    kommune = cfg["oslo"]["kommunenummer"]
    params = {
        "f": "json",
        "where": f"kommunenummer IN ('{kommune}')",
        "outFields": "*",
        "returnGeometry": "false",
        "outSR": "4326",
    }
    try:
        raw = http.get(URL, params=params)
        if "error" in raw:
            return r.fail(f"ArcGIS-feil: {raw['error']}")
        r.data = parse(raw)
    except Exception as e:  # noqa: BLE001
        return r.fail(str(e))

    th = cfg["thresholds"]["strom"]
    n = r.data["customers_unplanned"]
    if n >= th["elvia_red_customers"]:
        r.add(RED, f"{n} kunder uten strøm i Oslo (uplanlagt)", value=n)
    elif n >= th["elvia_yellow_customers"]:
        r.add(YELLOW, f"{n} kunder uten strøm i Oslo (uplanlagt)", value=n)
    elif r.data["unplanned_count"]:
        r.add(GREEN, f"{n} kunder berørt av {r.data['unplanned_count']} mindre strømbrudd", value=n)
    else:
        r.add(GREEN, f"Ingen uplanlagte strømbrudd i Oslo; {r.data['customers_planned']} kunder i planlagt utkobling", value=0)
    return r.succeed()
