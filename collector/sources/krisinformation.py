"""Krisinformation.se API v3 – svenske myndigheters krisenyheter og VMA.

GET https://api.krisinformation.se/v3/news?language=sv&days=1
GET https://api.krisinformation.se/v3/vmas?language=sv&allCounties=true
Åpent JSON uten nøkkel (testet 27.10.2026). Vilkår ikke oppgitt.
"""
from __future__ import annotations

from ..common import GREEN, RED, SourceResult, truncate

ID, NAME, CATEGORY = "krisinformation", "Krisinformation.se", "naboland"
NEWS = "https://api.krisinformation.se/v3/news"
VMAS = "https://api.krisinformation.se/v3/vmas"


def _item(n: dict) -> dict:
    area = n.get("area") or {}
    if isinstance(area, list):
        area = area[0] if area else {}
    return {
        "id": n.get("identifier"),
        "published": n.get("published"),
        "updated": n.get("updated"),
        "headline": truncate(n.get("headline"), 200),
        "preamble": truncate(n.get("preamble"), 400),
        "url": n.get("web"),
        "area": area.get("description") if isinstance(area, dict) else None,
        "event": n.get("event"),
        "sender": n.get("senderName"),
    }


def parse_news(raw) -> list[dict]:
    return [_item(n) for n in (raw or []) if isinstance(n, dict)]


def parse_vmas(raw) -> list[dict]:
    return [_item(n) for n in (raw or []) if isinstance(n, dict)]


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, "https://www.krisinformation.se/", CATEGORY)
    errors = []
    try:
        r.data["vmas"] = parse_vmas(http.get(VMAS, params={"language": "sv", "allCounties": "true"}))
    except Exception as e:  # noqa: BLE001
        errors.append(f"vma: {e}")
    try:
        r.data["news"] = parse_news(http.get(NEWS, params={"language": "sv", "days": 2}))
    except Exception as e:  # noqa: BLE001
        errors.append(f"news: {e}")
    if "vmas" not in r.data and "news" not in r.data:
        return r.fail("; ".join(errors))
    vmas = r.data.get("vmas") or []
    if vmas:
        r.add(RED, f"VMA i Sverige: {'; '.join(v['headline'] for v in vmas[:2])}", value=len(vmas))
    else:
        r.add(GREEN, f"Ingen aktive VMA i Sverige; {len(r.data.get('news') or [])} krisenyheter siste to døgn", value=0)
    r.succeed()
    r.error = "; ".join(errors)
    return r
