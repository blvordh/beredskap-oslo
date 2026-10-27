"""NVE: flom- og jordskredvarsel for Oslo (varsom) og magasinfylling NO1.

Flom/jordskred: api01.nve.no/hydrology/forecast/{flood|landslide}/v1.0.10/api/Warning/Municipality/{kommune}/1
(bare v1.0.10 virker). NLOD; krediter «Varsler fra Flomvarslingen/Jordskredvarslingen i Norge»
og lenk til varsom.no. Varsler skal ikke filtreres bort etter eget skjønn.
Magasin: biapi.nve.no/magasinstatistikk (ukentlig).
"""
from __future__ import annotations

from ..common import GREEN, RED, UNKNOWN, YELLOW, SourceResult, to_float, to_int

ID, NAME, CATEGORY = "nve", "NVE varsom og magasinstatistikk", "vann"
FLOOD = "https://api01.nve.no/hydrology/forecast/flood/v1.0.10/api/Warning/Municipality/{k}/1"
LANDSLIDE = "https://api01.nve.no/hydrology/forecast/landslide/v1.0.10/api/Warning/Municipality/{k}/1"
MAGASIN = "https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/HentOffentligDataSisteUke"
CREDIT = "Varsler fra Flomvarslingen og Jordskredvarslingen i Norge, www.varsom.no"

# Aktsomhetsnivå 1 (grønt) – 4 (rødt)
LEVEL = {1: GREEN, 2: YELLOW, 3: RED, 4: RED}


def parse_warnings(raw, kind: str) -> dict:
    items = []
    for w in raw or []:
        if not isinstance(w, dict):
            continue
        lvl = to_int(w.get("ActivityLevel"), 0)
        items.append({
            "kind": kind,
            "activity_level": lvl,
            "main_text": w.get("MainText"),
            "warning_text": (w.get("WarningText") or "")[:500],
            "valid_from": w.get("ValidFrom"),
            "valid_to": w.get("ValidTo"),
            "publish_time": w.get("PublishTime"),
        })
    return {"warnings": items, "max_level": max([i["activity_level"] for i in items] or [0])}


def parse_magasin(raw, omrnr: int = 1) -> dict | None:
    for row in raw or []:
        if isinstance(row, dict) and str(row.get("omrType", "EL")) == "EL" and to_int(row.get("omrnr"), -1) == omrnr:
            return {
                "week": f"{row.get('iso_aar')}-W{row.get('iso_uke')}",
                "fill_pct": round(100 * (to_float(row.get("fyllingsgrad")) or 0), 1),
                "change_pct": round(100 * (to_float(row.get("endring_fyllingsgrad")) or 0), 1),
                "capacity_twh": to_float(row.get("kapasitet_TWh")),
                "next_publish": row.get("neste_Publiseringsdato"),
            }
    return None


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, "https://varsom.no/", CATEGORY, license=f"NLOD. {CREDIT}")
    k = cfg["oslo"]["kommunenummer"]
    errors = []
    for kind, url in (("flom", FLOOD), ("jordskred", LANDSLIDE)):
        try:
            r.data[kind] = parse_warnings(http.get(url.format(k=k), headers={"Accept": "application/json"}), kind)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{kind}: {e}")
    try:
        r.data["magasin_no1"] = parse_magasin(http.get(MAGASIN))
    except Exception as e:  # noqa: BLE001
        errors.append(f"magasin: {e}")

    levels = [r.data[k]["max_level"] for k in ("flom", "jordskred") if k in r.data]
    if not levels:
        return r.fail("; ".join(errors))
    worst = max(levels)
    lvl = LEVEL.get(worst, UNKNOWN if worst == 0 else GREEN)
    names = {1: "grønt", 2: "gult", 3: "oransje", 4: "rødt"}
    r.add(lvl, f"NVE: flom- og jordskredvarsel for Oslo på {names.get(worst, 'ukjent')} nivå", value=worst)
    if r.data.get("magasin_no1"):
        m = r.data["magasin_no1"]
        r.add(GREEN, f"Magasinfylling NO1 uke {m['week']}: {m['fill_pct']} %", category="strom", value=m["fill_pct"])
    r.succeed()
    r.error = "; ".join(errors)
    return r
