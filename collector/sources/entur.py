"""Entur SIRI SX – avviksmeldinger for kollektivtransport (RUT, BNR, FLT, VYG …).

GET https://api.entur.io/realtime/v1/rest/sx?datasetId=RUT  (SIRI 2.0 XML)
NLOD. Header ET-Client-Name gir høyere kvote. Maks 4 kall/min, så vi henter
få datasett per kjøring. Parsingen er navneromsuavhengig.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from ..common import GREEN, RED, YELLOW, SourceResult, truncate

ID, NAME, CATEGORY = "entur", "Entur avvik (SIRI SX)", "transport"
URL = "https://api.entur.io/realtime/v1/rest/sx"

SEVERITY_LEVEL = {"severe": RED, "verysevere": RED, "slight": GREEN, "normal": GREEN, "noimpact": GREEN, "undefined": GREEN}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(el, name: str, lang: str | None = None) -> str | None:
    for child in el.iter():
        if _local(child.tag) == name:
            if lang is None:
                return (child.text or "").strip() or None
            if child.attrib.get("{http://www.w3.org/XML/1998/namespace}lang", "").lower().startswith(lang):
                return (child.text or "").strip() or None
    return None


def parse(xml_text: str | bytes, dataset: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for el in root.iter():
        if _local(el.tag) != "PtSituationElement":
            continue
        lines = sorted({(c.text or "").strip() for c in el.iter() if _local(c.tag) == "LineRef" and c.text})
        items.append({
            "dataset": dataset,
            "id": _text(el, "SituationNumber"),
            "severity": (_text(el, "Severity") or "undefined").lower(),
            "report_type": _text(el, "ReportType"),
            "progress": _text(el, "Progress"),
            "start": _text(el, "StartTime"),
            "end": _text(el, "EndTime"),
            "summary": truncate(_text(el, "Summary", "no") or _text(el, "Summary"), 200),
            "description": truncate(_text(el, "Description", "no") or _text(el, "Description"), 400),
            "lines": lines[:20],
        })
    return items


def collect(http, cfg) -> SourceResult:
    r = SourceResult(ID, NAME, "https://developer.entur.org/", CATEGORY, license="NLOD (Entur)")
    headers = {"ET-Client-Name": cfg.get("et_client_name", "beredskap-oslo")}
    all_items, errors = [], []
    for ds in cfg.get("entur_datasets", ["RUT"]):
        try:
            all_items += parse(http.get(URL, params={"datasetId": ds}, headers=headers, kind="bytes"), ds)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{ds}: {e}")
    if not all_items and errors:
        return r.fail("; ".join(errors))
    open_items = [i for i in all_items if (i["progress"] or "open").lower() != "closed"]
    by_ds: dict[str, int] = {}
    for i in open_items:
        by_ds[i["dataset"]] = by_ds.get(i["dataset"], 0) + 1
    r.data = {"situations": open_items, "count": len(open_items), "by_dataset": by_ds}
    severe = [i for i in open_items if SEVERITY_LEVEL.get(i["severity"], GREEN) == RED]
    if severe:
        r.add(YELLOW, f"Entur: {len(severe)} alvorlige avvik ({'; '.join(i['summary'] or '' for i in severe[:2])})", value=len(severe))
    else:
        r.add(GREEN, f"Entur: {len(open_items)} åpne avvik, ingen merket alvorlige", value=len(open_items))
    r.succeed()
    r.error = "; ".join(errors)
    return r
