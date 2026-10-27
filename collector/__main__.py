"""Kjør innsamleren: python -m collector [--config config.yaml] [--only elvia,ruter] [--out data]

Henter alle aktiverte kilder parallelt, skriver data/sources/<id>.json per kilde,
data/status.json (trafikklys) og data/nyheter_raw.json (RSS-snapshot for Nyhetsagenten).
En kilde som feiler beholder forrige vellykkede data i inntil stale_max_hours.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

from .common import UNKNOWN, Http, SourceResult, dump_json, load_json, now_iso, now_utc, parse_iso
from .status import build_status

VERSION = "0.1"
log = logging.getLogger("collector")


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["user_agent"] = cfg["user_agent"].format(contact=cfg.get("contact", ""))
    return cfg


def run_source(source_id: str, http: Http, cfg: dict) -> SourceResult:
    try:
        mod = importlib.import_module(f"collector.sources.{source_id}")
    except ImportError as e:
        return SourceResult(source_id, source_id, "", "varsler").fail(f"fant ikke modul: {e}")
    try:
        return mod.collect(http, cfg)
    except Exception as e:  # noqa: BLE001 – én kilde skal aldri stoppe de andre
        return SourceResult(mod.ID, mod.NAME, getattr(mod, "PUBLIC_URL", getattr(mod, "URL", "")), mod.CATEGORY).fail(f"uventet feil: {e}")


def apply_stale(result: SourceResult, previous: dict | None, max_hours: int) -> SourceResult:
    """Feilet henting: behold forrige data en stund, men merk dem som gamle."""
    if result.ok or not previous:
        return result
    prev = SourceResult.from_dict(previous)
    last = parse_iso(prev.last_success_at)
    if not last:
        return result
    age_h = (now_utc() - last).total_seconds() / 3600
    result.data = prev.data
    result.last_success_at = prev.last_success_at
    result.stale = True
    if age_h <= max_hours:
        result.signals = prev.signals
    else:
        result.signals = []
        result.add(UNKNOWN, f"{result.name} har ikke svart siden {prev.last_success_at}")
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="beredskap.oslo.no – innsamler")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--only", default="", help="kommaseparerte kilde-id-er")
    ap.add_argument("--out", default=None, help="utmappe (standard: output_dir i config)")
    ap.add_argument("--stale-max-hours", type=int, default=6)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    cfg = load_config(args.config)
    out = args.out or cfg.get("output_dir", "data")
    os.makedirs(os.path.join(out, "sources"), exist_ok=True)
    http = Http(cfg["user_agent"], timeout=int(cfg["http"]["timeout_seconds"]), retries=int(cfg["http"]["retries"]))

    wanted = [s.strip() for s in args.only.split(",") if s.strip()] or [k for k, on in cfg["sources"].items() if on]
    started = now_iso()
    results: list[SourceResult] = []
    with ThreadPoolExecutor(max_workers=int(cfg["http"]["workers"])) as ex:
        futs = {ex.submit(run_source, sid, http, cfg): sid for sid in wanted}
        for fut in as_completed(futs):
            r = fut.result()
            r = apply_stale(r, load_json(os.path.join(out, "sources", f"{r.id}.json")), args.stale_max_hours)
            results.append(r)
            log.info("%-16s %s %s", r.id, "OK " if r.ok else "FEIL", (r.signals[0].text if r.signals else r.error)[:110])

    results.sort(key=lambda r: r.id)
    for r in results:
        dump_json(os.path.join(out, "sources", f"{r.id}.json"), r.to_dict())

    status = build_status(results, generated_at=started, version=VERSION)
    dump_json(os.path.join(out, "status.json"), status)

    news = next((r for r in results if r.id == "rss_news"), None)
    if news is not None:
        dump_json(os.path.join(out, "nyheter_raw.json"), {
            "generated_at": started,
            "window_hours": news.data.get("window_hours"),
            "feeds_ok": news.data.get("feeds_ok"),
            "feeds_failed": news.data.get("feeds_failed"),
            "items": news.data.get("items", []),
        })

    failed = [r.id for r in results if not r.ok]
    log.info("Ferdig: %d kilder, %d feilet (%s). Samlet: %s", len(results), len(failed), ", ".join(failed), status["overall"]["summary"])
    return 2 if results and len(failed) == len(results) else 0


if __name__ == "__main__":
    sys.exit(main())
