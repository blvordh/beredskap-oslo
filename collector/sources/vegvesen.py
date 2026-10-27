"""Statens vegvesen – trafikkmeldinger, reisetider og vegkamera via åpen WFS (GeoJSON).

https://ogckart-sn1.atlas.vegvesen.no/datex_3_1/wfs (Fees: NONE, AccessConstraints: NONE, NLOD).
Verifisert 27.10.2026: 217 situasjoner i Oslo-bbox. Reisetidsdataene saneres fra
november 2026 (AutoPASS-antenner fases ut), så den delen kan bli tynnere over tid.
"""
from __future__ import annotations

import re

from ..common import GREEN, RED, YELLOW, SourceResult, to_float, to_int, truncate

ID, NAME, CATEGORY = "vegvesen", "Statens vegvesen trafikkmeldinger", "transport"
WFS = "https://ogckart-sn1.atlas.vegvesen.no/datex_3_1/wfs"
PUBLIC_URL = "https://www.vegvesen.no/trafikk"

CLOSED_WORDS = ("roadclosed", "stengt", "closed", "roadblocked")


def _params(type_name: str, bbox: list, count: int = 500) -> dict:
    lat0, lon0, lat1, lon1 = bbox
    return {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": f"datex_3_1:{type_name}",
        "outputFormat": "application/json",
        "count": count,
        "bbox": f"{lat0},{lon0},{lat1},{lon1},urn:ogc:def:crs:EPSG::4326",
    }


def norm_road(road: str | None) -> str:
    """'E 18', 'Rv4', 'R4', 'FV 150' → 'E18', 'RV4', 'RV4', 'FV150'."""
    s = re.sub(r"\s+", "", str(road or "")).upper()
    s = re.sub(r"^R(?=\d)", "RV", s)
    return s


def is_closure(p: dict) -> bool:
    blob = f"{p.get('SITUATION_TYPE', '')} {p.get('SECONDARY_TYPES', '')} {p.get('DESCRIPTION', '')}".lower()
    return any(w in blob for w in CLOSED_WORDS)


def parse_situations(raw: dict, hovedveier: list[str]) -> dict:
    main = {norm_road(r) for r in hovedveier}
    items = []
    for feat in (raw or {}).get("features", []) or []:
        p = feat.get("properties", {}) or {}
        if to_int(p.get("ACTIVE"), 1) == 0:
            continue
        road = norm_road(p.get("ROAD_NUMBER"))
        items.append({
            "road": road,
            "location": truncate(p.get("LOCATION_DESCRIPTION"), 200),
            "description": truncate(p.get("DESCRIPTION"), 300),
            "type": p.get("SITUATION_TYPE"),
            "secondary": p.get("SECONDARY_TYPES"),
            "severity": p.get("SEVERITY"),
            "start": p.get("START_TIME"),
            "end": p.get("END_TIME"),
            "updated": p.get("LAST_UPDATE_TIME"),
            "closure": is_closure(p),
            "main_road": road in main,
            "geometry": feat.get("geometry"),
        })
    closures_main = [i for i in items if i["closure"] and i["main_road"]]
    return {
        "situations": items,
        "count": len(items),
        "closures_main_roads": closures_main,
    }


def parse_traveltimes(raw: dict) -> dict:
    items = []
    for feat in (raw or {}).get("features", []) or []:
        p = feat.get("properties", {}) or {}
        items.append({
            "stretch": truncate(p.get("LOCATION_DESCRIPTION"), 120),
            "expected_s": to_int(p.get("EXPECTED_TIME")),
            "actual_s": to_int(p.get("ACTUAL_TIME")),
            "delay_pct": to_float(p.get("DELAYED_PERCENT")),
            "status": p.get("TRAFFIC_STATUS_VALUE"),
            "trend": p.get("TREND_TYPE"),
            "missing": to_int(p.get("MISSING_DATA"), 0) == 1,
            "valid_at": p.get("VALID_AT_TIME"),
        })
    with_data = [i for i in items if not i["missing"] and i["delay_pct"] is not None]
    return {"stretches": items, "count": len(items), "with_data": len(with_data)}


def parse_cameras(raw: dict) -> list[dict]:
    cams = []
    for feat in (raw or {}).get("features", []) or []:
        p = feat.get("properties", {}) or {}
        cams.append({
            "id": p.get("CAMERA_ID") or p.get("ID"),
            "road": norm_road(p.get("ROAD_NUMBER")),
            "name": truncate(p.get("LOCATION_DESCRIPTION") or p.get("NAME"), 120),
            "image_url": p.get("STILL_IMAGE_URL"),
            "updated": p.get("LAST_UPDATE_TIME"),
            "geometry": feat.get("geometry"),
        })
    return cams


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, PUBLIC_URL, CATEGORY, license="NLOD (Statens vegvesen)")
    bbox = cfg["oslo"]["bbox"]
    th = cfg["thresholds"]["transport"]
    errors = []
    try:
        r.data["situations"] = parse_situations(http.get(WFS, params=_params("SituationSimple_v2", bbox)), cfg["oslo"]["hovedveier"])
    except Exception as e:  # noqa: BLE001
        errors.append(f"situasjoner: {e}")
    try:
        r.data["traveltimes"] = parse_traveltimes(http.get(WFS, params=_params("TravelTimeSimple_v2", bbox)))
    except Exception as e:  # noqa: BLE001
        errors.append(f"reisetid: {e}")
    try:
        r.data["cameras"] = parse_cameras(http.get(WFS, params=_params("CctvSimple_v2", bbox)))
    except Exception as e:  # noqa: BLE001
        errors.append(f"kamera: {e}")

    if "situations" not in r.data and "traveltimes" not in r.data:
        return r.fail("; ".join(errors))

    s = r.data.get("situations")
    if s:
        if s["closures_main_roads"]:
            c = s["closures_main_roads"][0]
            r.add(RED, f"Stengt hovedvei: {c['road']} {c['location']}", value=len(s["closures_main_roads"]))
        else:
            r.add(GREEN, f"Ingen stengte hovedveier; {s['count']} aktive trafikkmeldinger i Oslo-regionen", value=0)
    t = r.data.get("traveltimes")
    if t:
        ok = [x for x in t["stretches"] if not x["missing"] and x["delay_pct"] is not None]
        slow = [x for x in ok if x["delay_pct"] >= th["traveltime_yellow_delay_percent"]]
        very_slow = [x for x in ok if x["delay_pct"] >= th["traveltime_red_delay_percent"]]
        if len(very_slow) >= th["traveltime_red_min_stretches"]:
            names = "; ".join(x["stretch"] for x in very_slow[:3])
            r.add(RED, f"Kø langt over normalt: {len(very_slow)} strekninger med over {th['traveltime_red_delay_percent']} % forsinkelse ({names})", value=len(very_slow))
        elif len(slow) >= th["traveltime_yellow_min_stretches"]:
            names = "; ".join(x["stretch"] for x in slow[:3])
            r.add(YELLOW, f"Kø: {len(slow)} strekninger med over {th['traveltime_yellow_delay_percent']} % forsinkelse ({names})", value=len(slow))
        elif ok:
            r.add(GREEN, f"Reisetider: {len(slow)} av {len(ok)} strekninger med vesentlig forsinkelse", value=len(slow))
    r.succeed()
    r.error = "; ".join(errors)
    return r
