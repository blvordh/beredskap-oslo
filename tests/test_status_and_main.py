"""Aggregator og hovedløp (med FakeHttp i stedet for nett)."""
from __future__ import annotations

import json
import os

from conftest import FakeHttp

import collector.__main__ as main_mod
from collector.common import GREEN, RED, UNKNOWN, YELLOW, SourceResult
from collector.status import build_status


def _res(sid, cat, level=None, text="", ok=True, stale=False):
    r = SourceResult(sid, sid.title(), f"https://{sid}.example", cat)
    if level is not None:
        r.add(level, text)
    if ok:
        r.succeed()
    else:
        r.fail("nede")
    r.stale = stale
    return r


def test_build_status_levels():
    results = [
        _res("elvia", "strom", GREEN, "ok"),
        _res("statnett", "strom", YELLOW, "stram"),
        _res("ruter", "transport", RED, "kaos"),
        _res("vipps", "betaling", ok=False),
        _res("nve", "vann", GREEN, "grønt", stale=True),
    ]
    st = build_status(results, generated_at="2026-10-27T08:00:00+00:00")
    c = st["categories"]
    assert c["strom"]["level"] == YELLOW and c["strom"]["headline"] == "stram"
    assert c["transport"]["level"] == RED
    assert c["betaling"]["level"] == UNKNOWN and "nede" in c["betaling"]["headline"]
    assert c["vann"]["stale"] and "siste vellykkede" in c["vann"]["headline"]
    assert c["ekom"]["level"] == UNKNOWN and "Ingen automatisk kilde" in c["ekom"]["headline"]
    assert st["overall"]["level"] == RED and "Transport" in st["overall"]["summary"]
    assert st["sources_failed"] == ["vipps"] and st["sources_stale"] == ["nve"]


def test_signal_in_other_category():
    r = _res("nve", "vann", GREEN, "grønt")
    r.add(GREEN, "magasin 74 %", category="strom")
    st = build_status([r])
    assert st["categories"]["strom"]["signals"][0]["text"] == "magasin 74 %"
    assert [s["id"] for s in st["categories"]["strom"]["sources"]] == []  # kilden listes bare i egen kategori


def test_apply_stale_keeps_recent_signals():
    prev = _res("ruter", "transport", GREEN, "alt vel")
    prev.last_success_at = main_mod.now_iso()
    failed = _res("ruter", "transport", ok=False)
    out = main_mod.apply_stale(failed, prev.to_dict(), max_hours=6)
    assert out.stale and not out.ok and out.signals[0].text == "alt vel"
    prev.last_success_at = "2020-01-01T00:00:00+00:00"
    out2 = main_mod.apply_stale(_res("ruter", "transport", ok=False), prev.to_dict(), max_hours=6)
    assert out2.signals[0].level == UNKNOWN and "ikke svart" in out2.signals[0].text


def test_main_end_to_end(tmp_path, monkeypatch):
    """Kjører hele løpet med to kilder: én som svarer, én som feiler."""
    ruter_payload = {"fetchedAt": "x", "situations": [], "plannedChanges": []}

    def fake_http(*a, **k):
        return FakeHttp({"https://ruter.no/api/traffic-status.json": ruter_payload})

    monkeypatch.setattr(main_mod, "Http", fake_http)
    rc = main_mod.main(["--config", os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml"),
                        "--only", "ruter,elvia", "--out", str(tmp_path)])
    assert rc == 0
    status = json.load(open(tmp_path / "status.json", encoding="utf-8"))
    assert status["categories"]["transport"]["level"] == GREEN
    assert status["sources_failed"] == ["elvia"]
    assert (tmp_path / "sources" / "ruter.json").exists() and (tmp_path / "sources" / "elvia.json").exists()
    # Andre kjøring: elvia feiler fortsatt, ruter får stale-data hvis den nå feiler
    monkeypatch.setattr(main_mod, "Http", lambda *a, **k: FakeHttp({}))
    rc2 = main_mod.main(["--config", os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml"),
                         "--only", "ruter,elvia", "--out", str(tmp_path)])
    assert rc2 == 2  # alle feilet
    status2 = json.load(open(tmp_path / "status.json", encoding="utf-8"))
    assert status2["categories"]["transport"]["stale"] is True
    assert status2["categories"]["transport"]["level"] == GREEN
