"""Ruter trafikkstatus – https://ruter.no/api/traffic-status.json (oppdateres hvert 60 s).

Vilkår ikke oppgitt i feeden; avklar med Ruter før produksjon.
"""
from __future__ import annotations

import re

from ..common import GREEN, RED, YELLOW, SourceResult, truncate

ID, NAME, CATEGORY = "ruter", "Ruter trafikkstatus", "transport"
URL = "https://ruter.no/api/traffic-status.json"
PUBLIC_URL = "https://ruter.no/trafikkstatus"


def parse(raw: dict) -> dict:
    situations = []
    for s in (raw or {}).get("situations", []) or []:
        lines = s.get("lines") or []
        modes = sorted({str(l.get("transportMode") or "") for l in lines if l.get("transportMode")})
        situations.append({
            "id": s.get("id"),
            "summary": truncate(s.get("summary"), 200),
            "description": truncate(s.get("description"), 400),
            "report_type": s.get("reportType"),
            "lines": [l.get("publicCode") for l in lines if l.get("publicCode")],
            "modes": modes,
            "stop_places": [p.get("name") for p in (s.get("stopPlaces") or []) if p.get("name")][:10],
            "valid_from": s.get("validFrom"),
            "valid_to": s.get("validTo"),
            "info_url": s.get("infoUri"),
        })
    incidents = [s for s in situations if (s["report_type"] or "").upper() == "INCIDENT"]
    serious = [s for s in incidents if is_serious(s)]
    return {
        "fetched_at_source": (raw or {}).get("fetchedAt"),
        "stale_after": (raw or {}).get("staleAfter"),
        "situations": situations,
        "planned_changes": len((raw or {}).get("plannedChanges", []) or []),
        "incident_count": len(incidents),
        "incidents_by_mode": _count_modes(incidents),
        "serious_count": len(serious),
        "serious": serious[:30],
    }


# En vanlig hverdag har Ruter 50–80 «INCIDENT» (ekte data 27.10.2026, kl. 09:36: 64):
# enkeltavganger som er forsinket eller innstilt, linjer som hopper over holdeplasser,
# buss for trikk under planlagt arbeid. Alvorlig = en hel linje eller strekning er ute.
RAIL_MODES = {"metro", "tram", "rail", "water"}
SERIOUS_PATTERNS = (
    r"linje [\w/ ,og]+ er innstilt",   # «Linje 335 er innstilt»
    r"innstilt mellom",
    r"stengt mellom",
    r"ingen avganger",
    r"kjører ikke",
    r"står stille",
    r"er stanset",
    r"stans i",
    r"all trafikk",
    r"ikke i drift",
    r"evakuer",
    r"t-banen (er )?stengt",
    r"trikken (er )?stengt",
)
NOISE_PATTERNS = (
    r"^avgangen",                      # én avgang forsinket/innstilt
    r"minutter? forsinket",
    r"stopper ikke",
    r"holdeplass",
    r"rullestol",
    r"gangavstand",
)
_SERIOUS = re.compile("|".join(SERIOUS_PATTERNS))
_NOISE = re.compile("|".join(NOISE_PATTERNS))


def is_serious(s: dict) -> bool:
    summary = (s.get("summary") or "").lower().strip()
    text = f"{summary} {(s.get('description') or '').lower()}"
    return bool(_SERIOUS.search(text)) and not _NOISE.search(summary)


def _count_modes(items: list[dict]) -> dict:
    out: dict[str, int] = {}
    for s in items:
        for m in s["modes"] or ["ukjent"]:
            out[m] = out.get(m, 0) + 1
    return out


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, PUBLIC_URL, CATEGORY, license="Vilkår ikke oppgitt; avklar med Ruter")
    try:
        r.data = parse(http.get(URL))
    except Exception as e:  # noqa: BLE001
        return r.fail(str(e))
    th = cfg["thresholds"]["transport"]
    n, total = r.data["serious_count"], r.data["incident_count"]
    rail = [s for s in r.data["serious"] if set(s["modes"]) & RAIL_MODES]
    example = f" ({r.data['serious'][0]['summary']})" if r.data["serious"] else ""
    if n >= th["ruter_red_serious"] or len(rail) >= th["ruter_red_rail"]:
        r.add(RED, f"Ruter: {n} alvorlige avvik, {len(rail)} på bane/trikk/båt{example}", value=n)
    elif n >= th["ruter_yellow_serious"]:
        r.add(YELLOW, f"Ruter: {n} alvorlige avvik av {total}{example}", value=n)
    else:
        r.add(GREEN, f"Ruter: {total} avvik, {n} alvorlige", value=n)
    return r.succeed()
