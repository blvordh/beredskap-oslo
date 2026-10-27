"""Cloudflare Radar – registrerte internettutfall. Krever CLOUDFLARE_API_TOKEN (gratis «Radar Read»).

GET https://api.cloudflare.com/client/v4/radar/annotations/outages?dateRange=7d
Vi filtrerer selv på locations som inneholder «NO».
"""
from __future__ import annotations

import os

from ..common import GREEN, RED, SourceResult, truncate

ID, NAME, CATEGORY = "cloudflare_radar", "Cloudflare Radar utfall", "ekom"
URL = "https://api.cloudflare.com/client/v4/radar/annotations/outages"


def parse(raw: dict, country: str = "NO") -> dict:
    hits = []
    for a in ((raw or {}).get("result") or {}).get("annotations", []) or []:
        locs = [str(l).upper() for l in (a.get("locations") or [])]
        if country in locs:
            outage = a.get("outage") or {}
            hits.append({
                "id": a.get("id"),
                "start": a.get("startDate"),
                "end": a.get("endDate"),
                "asns": a.get("asns"),
                "cause": outage.get("outageCause"),
                "type": outage.get("outageType"),
                "description": truncate(a.get("description"), 300),
                "open": not a.get("endDate"),
            })
    return {"outages_no": hits, "open": [h for h in hits if h["open"]]}


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, "https://radar.cloudflare.com/no", CATEGORY)
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        return r.fail("CLOUDFLARE_API_TOKEN mangler")
    try:
        r.data = parse(http.get(URL, params={"dateRange": "7d", "format": "json"}, headers={"Authorization": f"Bearer {token}"}))
    except Exception as e:  # noqa: BLE001
        return r.fail(str(e))
    if r.data["open"]:
        o = r.data["open"][0]
        r.add(RED, f"Cloudflare Radar: pågående internettutfall i Norge ({o['cause'] or o['type'] or 'ukjent årsak'})", since=o["start"])
    else:
        r.add(GREEN, f"Cloudflare Radar: ingen pågående utfall i Norge ({len(r.data['outages_no'])} siste 7 dager)")
    return r.succeed()
