"""Parser- og signaltester per kilde, med fiksturer formet etter feltene som ble
verifisert mot kildene 27.10.2026. Ingen nettverkstilgang kreves."""
from __future__ import annotations

import datetime as dt

from conftest import FakeHttp

from collector.common import GREEN, RED, UNKNOWN, YELLOW
from collector.sources import (avinor, cloudflare_radar, elvia, entur, krisinformation, met, nodvarsel, nve, polisen,
                               politiloggen, rss_news, ruter, statnett, strompris, vegvesen, vipps)

NOW_MS = int(dt.datetime(2026, 10, 27, 8, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)


# ---------- Elvia ----------
ELVIA = {"features": [
    {"attributes": {"antallkunder": 91, "beskrivelse": "Planlagt arbeid", "avbruddstype": "Planned", "statusavbrudd": "deenergized",
                    "strombruddoppdaget": None, "utkoblingstart": NOW_MS, "utkoblingslutt": NOW_MS + 3600000,
                    "postnummer": "0580", "poststed": "OSLO", "kommunenummer": "0301", "kommune": "Oslo"}},
    {"attributes": {"antallkunder": 1200, "beskrivelse": "Feil på nettstasjon", "avbruddstype": "Unplanned", "statusavbrudd": "deenergized",
                    "strombruddoppdaget": NOW_MS, "utkoblingstart": None, "utkoblingslutt": None,
                    "postnummer": "0680", "poststed": "OSLO", "kommunenummer": "0301", "kommune": "Oslo"}},
]}


def test_elvia_parse_and_signal(cfg):
    d = elvia.parse(ELVIA)
    assert d["count"] == 2 and d["unplanned_count"] == 1
    assert d["customers_unplanned"] == 1200 and d["customers_planned"] == 91
    assert d["outages"][0]["start"] == "2026-10-27T08:00:00+00:00"
    r = elvia.collect(FakeHttp({elvia.URL: ELVIA}), cfg)
    assert r.ok and r.signals[0].level == YELLOW and "1200" in r.signals[0].text


def test_elvia_arcgis_error(cfg):
    r = elvia.collect(FakeHttp({elvia.URL: {"error": {"code": 400, "message": "Invalid query"}}}), cfg)
    assert not r.ok and "ArcGIS" in r.error


# ---------- Statnett ----------
STATNETT_SIT = {"powerSituations": [
    {"elspotArea": "NO1", "powerSituation": "Normal", "text": "Normal kraftsituasjon"},
    {"elspotArea": "NO2", "powerSituation": "Stram", "text": "Stram"},
]}
STATNETT_FLOW = [{"OutAreaElspotId": "NO1", "InAreaElspotId": "SE3", "Value": 512.5, "MeasureDate": NOW_MS},
                 {"OutAreaElspotId": "NO5", "InAreaElspotId": "NO2", "Value": 100, "MeasureDate": NOW_MS}]


def test_statnett_parse():
    areas = statnett.parse_situations(STATNETT_SIT)["areas"]
    assert areas["NO1"]["status"] == "Normal" and areas["NO2"]["status"] == "Stram"
    flows = statnett.parse_flow(STATNETT_FLOW, "NO1")
    assert len(flows) == 1 and flows[0]["to"] == "SE3" and flows[0]["mw"] == 512.5
    assert statnett.level_for("Svært stram") == RED and statnett.level_for("Normal") == GREEN
    assert statnett.level_for("tull") == UNKNOWN


def test_statnett_collect_partial_failure(cfg):
    http = FakeHttp({statnett.URL_SITUATION: STATNETT_SIT, statnett.URL_FLOW: RuntimeError("nede")})
    r = statnett.collect(http, cfg)
    assert r.ok and r.signals[0].level == GREEN and "flyt" in r.error and "oversikt" in r.error


def test_statnett_overview_survives_big_payload():
    """Første ekte kjøring: svaret var >20 kB og ble kuttet midt i en streng. Nå plukkes bare (tittel, tall)."""
    big = {"MeasuredAt": 1793093329000, "ProductionData": [{"titleTranslationId": f"PC.Row{i}", "value": f"1{i:04d}"} for i in range(400)],
           "Nested": {"title": "Norway consumption", "value": "15 757", "junk": "x" * 30000}}
    o = statnett.parse_overview(big)
    assert o["measured_at"] == "2026-10-27T09:28:49+00:00" and len(o["items"]) == 80 and o["items"][0]["value"] == 10000.0
    import json
    json.dumps(o)  # må være gyldig JSON uten kutt


# ---------- Strømpris ----------
PRICES = [{"NOK_per_kWh": 0.5 + i / 100, "EUR_per_kWh": 0.045, "EXR": 11.2,
           "time_start": f"2026-10-27T{i:02d}:00:00+01:00", "time_end": f"2026-10-27T{i + 1:02d}:00:00+01:00"} for i in range(24)]


def test_strompris(cfg):
    d = strompris.parse(PRICES)
    assert d["min_nok"] == 0.5 and d["max_nok"] == 0.73 and len(d["hours"]) == 24
    assert strompris.url_for(dt.date(2026, 10, 27)) == "https://www.hvakosterstrommen.no/api/v1/prices/2026/10-27_NO1.json"
    r = strompris.collect(FakeHttp({strompris.BASE: PRICES}), cfg)
    assert r.ok and r.data["today"]["avg_nok"] and r.signals[0].level == GREEN


# ---------- NVE ----------
NVE_FLOOD = [{"ActivityLevel": "2", "MainText": "Gult nivå", "WarningText": "Mye regn", "ValidFrom": "2026-10-27T00:00:00", "ValidTo": "2026-10-27T23:59:00"}]
NVE_LAND = [{"ActivityLevel": "1", "MainText": "Grønt nivå"}, {"ActivityLevel": 1, "MainText": "Grønt nivå"}]
NVE_MAG = [{"omrType": "EL", "omrnr": 1, "iso_aar": 2026, "iso_uke": 42, "fyllingsgrad": 0.7475, "endring_fyllingsgrad": -0.012, "kapasitet_TWh": 5.9},
           {"omrType": "EL", "omrnr": 2, "iso_aar": 2026, "iso_uke": 42, "fyllingsgrad": 0.6}]


def test_nve(cfg):
    assert nve.parse_warnings(NVE_FLOOD, "flom")["max_level"] == 2
    assert nve.parse_magasin(NVE_MAG)["fill_pct"] == 74.8
    http = FakeHttp({nve.FLOOD.split("{")[0]: NVE_FLOOD, nve.LANDSLIDE.split("{")[0]: NVE_LAND, nve.MAGASIN: NVE_MAG})
    r = nve.collect(http, cfg)
    assert r.ok
    vann = [s for s in r.signals if s.category == "vann"][0]
    assert vann.level == YELLOW and "gult" in vann.text
    strom = [s for s in r.signals if s.category == "strom"][0]
    assert "74.8" in strom.text


# ---------- MET ----------
MET_EMPTY = {"type": "FeatureCollection", "features": []}
MET_ORANGE = {"type": "FeatureCollection", "features": [{
    "type": "Feature",
    "properties": {"id": "2.49.0.1.578.0.1", "event": "rain", "title": "Oransje farevarsel for ekstremt mye regn, Oslo",
                   "awareness_level": "3; orange; Severe", "riskMatrixColor": "Orange", "area": "Oslo", "severity": "Severe",
                   "certainty": "Likely", "description": "Det ventes 80 mm.", "instruction": "Hold deg hjemme."},
    "when": {"interval": ["2026-10-27T06:00:00+00:00", "2026-10-28T06:00:00+00:00"]},
}]}


def test_met(cfg):
    assert met.parse(MET_ORANGE)["max_level"] == 3
    r = met.collect(FakeHttp({met.URL: MET_ORANGE}), cfg)
    assert r.ok and r.signals[0].level == RED and "oransje" in r.signals[0].text
    r2 = met.collect(FakeHttp({met.URL: MET_EMPTY}), cfg)
    assert r2.signals[0].level == GREEN
    http = FakeHttp({met.URL: MET_EMPTY})
    met.collect(http, cfg)
    assert http.calls[0][1]["county"] == "03"


# ---------- Nødvarsel ----------
RSS_NODVARSEL = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:a10="http://www.w3.org/2005/Atom"><channel><title>Aktive</title>
<item><title>EKSPLOSJONSFARE</title><link>https://www.nodvarsel.no/varsler/1</link>
<description>Hold deg unna Lutvann, Oslo.</description><a10:updated>2026-10-27T07:30:00Z</a10:updated></item>
</channel></rss>"""
RSS_EMPTY = b"""<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>Aktive</title></channel></rss>"""


def test_nodvarsel(cfg):
    items = nodvarsel.parse_feed(RSS_NODVARSEL)
    assert items[0]["title"] == "EKSPLOSJONSFARE" and items[0]["updated"] == "2026-10-27T07:30:00+00:00"
    r = nodvarsel.collect(FakeHttp({nodvarsel.ACTIVE: RSS_NODVARSEL, nodvarsel.PREVIOUS: RSS_EMPTY}), cfg)
    assert r.ok and r.signals[0].level == RED and "Oslo" in r.signals[0].text
    outside = RSS_NODVARSEL.replace(b"Lutvann, Oslo", b"Sortland")
    r2 = nodvarsel.collect(FakeHttp({nodvarsel.ACTIVE: outside, nodvarsel.PREVIOUS: RSS_EMPTY}), cfg)
    assert r2.signals[0].level == YELLOW
    r3 = nodvarsel.collect(FakeHttp({nodvarsel.ACTIVE: RSS_EMPTY, nodvarsel.PREVIOUS: RSS_NODVARSEL}), cfg)
    assert r3.signals[0].level == GREEN and "EKSPLOSJONSFARE" in r3.signals[0].text


# ---------- Vegvesen ----------
def _feat(props):
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[10.8, 59.9], [10.9, 59.95]]}, "properties": props}


VV_SIT = {"type": "FeatureCollection", "features": [
    _feat({"ROAD_NUMBER": "E 6", "LOCATION_DESCRIPTION": "Vålerengtunnelen", "DESCRIPTION": "Stengt pga. ulykke", "SITUATION_TYPE": "AccidentsAndIncidents",
           "SECONDARY_TYPES": "roadClosed", "SEVERITY": "high", "START_TIME": "2026-10-27T07:00:00Z", "END_TIME": None, "ACTIVE": 1}),
    _feat({"ROAD_NUMBER": "Fv 150", "LOCATION_DESCRIPTION": "Ring 3", "DESCRIPTION": "Vegarbeid", "SITUATION_TYPE": "MaintenanceWorks",
           "SECONDARY_TYPES": "", "SEVERITY": "low", "ACTIVE": 1}),
    _feat({"ROAD_NUMBER": "E18", "LOCATION_DESCRIPTION": "Gammel", "DESCRIPTION": "roadClosed", "SITUATION_TYPE": "x", "ACTIVE": 0}),
]}
VV_TT = {"type": "FeatureCollection", "features": [
    _feat({"LOCATION_DESCRIPTION": "Skedsmovollen - Karihaugen", "EXPECTED_TIME": 600, "ACTUAL_TIME": 1000, "DELAYED_PERCENT": 66.7, "TRAFFIC_STATUS_VALUE": "heavy", "MISSING_DATA": 0}),
    _feat({"LOCATION_DESCRIPTION": "Karihaugen - Helsfyr", "EXPECTED_TIME": 500, "ACTUAL_TIME": 900, "DELAYED_PERCENT": 80, "TRAFFIC_STATUS_VALUE": "congested", "MISSING_DATA": 0}),
    _feat({"LOCATION_DESCRIPTION": "Mosseporten - Kambo", "EXPECTED_TIME": 300, "ACTUAL_TIME": 300, "DELAYED_PERCENT": 0, "TRAFFIC_STATUS_VALUE": "freeFlow", "MISSING_DATA": 1}),
]}
VV_CAM = {"type": "FeatureCollection", "features": [_feat({"CAMERA_ID": "123", "ROAD_NUMBER": "E6", "LOCATION_DESCRIPTION": "Karihaugen",
                                                           "STILL_IMAGE_URL": "https://kamera.atlas.vegvesen.no/api/images/123"})]}


def test_vegvesen_parse(cfg):
    s = vegvesen.parse_situations(VV_SIT, cfg["oslo"]["hovedveier"])
    assert s["count"] == 2 and len(s["closures_main_roads"]) == 1 and s["closures_main_roads"][0]["road"] == "E6"
    assert vegvesen.norm_road("R4") == "RV4" and vegvesen.norm_road("Fv 150") == "FV150"
    t = vegvesen.parse_traveltimes(VV_TT)
    assert t["count"] == 3 and t["with_data"] == 2
    assert vegvesen.parse_cameras(VV_CAM)[0]["image_url"].endswith("/123")


def test_vegvesen_collect(cfg):
    def route(url, params, headers, kind):
        return {"SituationSimple_v2": VV_SIT, "TravelTimeSimple_v2": VV_TT, "CctvSimple_v2": VV_CAM}[params["typeNames"].split(":")[1]]
    r = vegvesen.collect(FakeHttp({vegvesen.WFS: route}), cfg)
    assert r.ok
    levels = [s.level for s in r.signals]
    assert levels == [RED, GREEN]  # stengt E6 = rødt; 2 trege strekninger er under terskelen (4 over 75 %)
    assert "Vålerengtunnelen" in r.signals[0].text


def test_vegvesen_traveltime_thresholds(cfg):
    th = cfg["thresholds"]["transport"]

    def tt(n, pct):
        return {"type": "FeatureCollection", "features": [
            _feat({"LOCATION_DESCRIPTION": f"Strekning {i}", "EXPECTED_TIME": 600, "ACTUAL_TIME": 600 * (1 + pct / 100),
                   "DELAYED_PERCENT": pct, "TRAFFIC_STATUS_VALUE": "congested", "MISSING_DATA": 0}) for i in range(n)]}

    def run(payload):
        def route(url, params, headers, kind):
            t = params["typeNames"].split(":")[1]
            return payload if t == "TravelTimeSimple_v2" else {"type": "FeatureCollection", "features": []}
        return [s.level for s in vegvesen.collect(FakeHttp({vegvesen.WFS: route}), cfg).signals]

    assert run(tt(8, 60))[1] == GREEN      # vanlig rush: mange strekninger, moderat forsinkelse
    assert run(tt(th["traveltime_yellow_min_stretches"], th["traveltime_yellow_delay_percent"]))[1] == YELLOW
    assert run(tt(th["traveltime_red_min_stretches"], th["traveltime_red_delay_percent"]))[1] == RED


# ---------- Ruter ----------
RUTER = {"fetchedAt": "2026-10-27T08:00:00Z", "staleAfter": "2026-10-27T08:01:00Z", "situations": [
    {"id": "RUT:1", "summary": "T-banen stengt mellom Majorstuen og Tøyen", "reportType": "INCIDENT",
     "lines": [{"id": "RUT:Line:1", "publicCode": "1", "transportMode": "metro"}], "stopPlaces": [{"id": "x", "name": "Majorstuen"}]},
    {"id": "RUT:2", "summary": "Buss 31 omkjøring", "reportType": "GENERAL", "lines": [{"publicCode": "31", "transportMode": "bus"}]},
], "plannedChanges": [{"id": "p1"}]}


def test_ruter(cfg):
    d = ruter.parse(RUTER)
    assert d["incident_count"] == 1 and d["incidents_by_mode"] == {"metro": 1} and d["planned_changes"] == 1
    assert d["serious_count"] == 1  # «T-banen stengt mellom …» = hel strekning ute
    r = ruter.collect(FakeHttp({ruter.URL: RUTER}), cfg)
    assert r.ok and r.signals[0].level == GREEN
    # Tre T-banelinjer med stans → rødt (ruter_red_rail)
    rail = {"situations": [dict(RUTER["situations"][0], id=f"RUT:{i}") for i in range(3)]}
    assert ruter.collect(FakeHttp({ruter.URL: rail}), cfg).signals[0].level == RED


def test_ruter_real_morning_is_green(cfg):
    """Ekte meldinger fra 27.10.2026 kl. 09:36 som alle er hverdag, pluss én ekte alvorlig."""
    everyday = [
        {"summary": "Avgangen innstilt", "description": "Avgangen fra Sandvika bussterminal kl. 10:42 i retning Kolsås er innstilt. Dette skyldes en stengt vei.", "modes": ["bus"]},
        {"summary": "Linje 215A stopper ikke mellom Tangen og Sykehusveien", "description": "Dette skyldes en stengt vei.", "modes": ["bus"]},
        {"summary": "Linje 13: Buss for trikk mellom Thune og Lilleaker", "description": "Vi kjører buss for trikk (linje 13B). Bussen stopper ikke på Sollerud.", "modes": ["bus", "tram"]},
        {"summary": "Avstigning med rullestol på Frognerseteren stasjon", "description": "Plattformen er kort.", "modes": ["metro"]},
        {"summary": "Holdeplass Thune: Buss for trikk 13B stopper på andre siden", "description": "Gangavstand ca. 140 meter.", "modes": ["bus", "tram"]},
        {"summary": "Avgangen er ca. 20 minutter forsinket", "description": "", "modes": ["bus"]},
    ]
    assert not any(ruter.is_serious(s) for s in everyday)
    assert ruter.is_serious({"summary": "Linje 335 er innstilt", "description": "Dette skyldes en stengt vei.", "modes": ["bus"]})
    assert ruter.is_serious({"summary": "T-banen kjører ikke mellom Majorstuen og Stortinget", "description": "Signalfeil.", "modes": ["metro"]})
    assert ruter.is_serious({"summary": "Linje 12: Innstilt mellom Jernbanetorget og Kjelsås", "description": "", "modes": ["tram"]})


def test_ruter_ignores_everyday_noise(cfg):
    """En vanlig morgen: 66 INCIDENT, nesten alle enkeltavganger som er forsinket (ekte data 27.10.2026)."""
    noise = [{"id": f"RUT:{i}", "summary": f"Avgangen er ca. {10 + i} minutter forsinket", "reportType": "INCIDENT",
              "lines": [{"publicCode": str(100 + i), "transportMode": "bus"}]} for i in range(60)]
    detour = [{"id": "RUT:d", "summary": "500 og 500N: omkjøring", "reportType": "INCIDENT", "lines": [{"publicCode": "500", "transportMode": "bus"}]}]
    d = ruter.parse({"situations": noise + detour})
    assert d["incident_count"] == 61 and d["serious_count"] == 0
    assert ruter.collect(FakeHttp({ruter.URL: {"situations": noise + detour}}), cfg).signals[0].level == GREEN
    cancelled = [{"id": f"RUT:c{i}", "summary": f"Linje {i} er innstilt", "reportType": "INCIDENT", "lines": [{"publicCode": str(i), "transportMode": "bus"}]} for i in range(5)]
    assert ruter.collect(FakeHttp({ruter.URL: {"situations": noise + cancelled}}), cfg).signals[0].level == YELLOW


# ---------- Entur ----------
SIRI = b"""<?xml version="1.0" encoding="UTF-8"?>
<Siri xmlns="http://www.siri.org.uk/siri" version="2.0"><ServiceDelivery><SituationExchangeDelivery><Situations>
<PtSituationElement><SituationNumber>RUT:SituationNumber:823966</SituationNumber><Severity>severe</Severity>
<ReportType>incident</ReportType><Progress>open</Progress>
<ValidityPeriod><StartTime>2026-10-27T06:00:00+01:00</StartTime></ValidityPeriod>
<Summary xml:lang="NO">Innstilt: linje 1</Summary><Summary xml:lang="EN">Cancelled: line 1</Summary>
<Description xml:lang="NO">Signalfeil.</Description>
<Affects><Networks><AffectedNetwork><AffectedLine><LineRef>RUT:Line:1</LineRef></AffectedLine></AffectedNetwork></Networks></Affects>
</PtSituationElement>
<PtSituationElement><SituationNumber>RUT:SituationNumber:2</SituationNumber><Severity>slight</Severity><Progress>closed</Progress>
<Summary xml:lang="NO">Gammel</Summary></PtSituationElement>
</Situations></SituationExchangeDelivery></ServiceDelivery></Siri>"""


def test_entur(cfg):
    items = entur.parse(SIRI, "RUT")
    assert items[0]["summary"] == "Innstilt: linje 1" and items[0]["lines"] == ["RUT:Line:1"] and items[0]["severity"] == "severe"
    http = FakeHttp({entur.URL: SIRI})
    r = entur.collect(http, cfg)
    assert r.ok and r.data["count"] == len(cfg["entur_datasets"]) and r.signals[0].level == YELLOW
    assert http.calls[0][1]["datasetId"] == cfg["entur_datasets"][0]


# ---------- Krisinformation ----------
KRIS_NEWS = [{"identifier": "n1", "published": "2026-10-26T10:00:00Z", "headline": "Störning i elnätet", "preamble": "Kort", "web": "https://www.krisinformation.se/x",
              "area": {"type": "county", "description": "Stockholms län"}, "event": "El", "senderName": "Svenska kraftnät"}]


def test_krisinformation(cfg):
    assert krisinformation.parse_news(KRIS_NEWS)[0]["area"] == "Stockholms län"
    r = krisinformation.collect(FakeHttp({krisinformation.VMAS: [], krisinformation.NEWS: KRIS_NEWS}), cfg)
    assert r.ok and r.signals[0].level == GREEN and "1 krisenyheter" in r.signals[0].text
    r2 = krisinformation.collect(FakeHttp({krisinformation.VMAS: KRIS_NEWS, krisinformation.NEWS: []}), cfg)
    assert r2.signals[0].level == RED


# ---------- Vipps ----------
VIPPS_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Vipps</title>
<item><title>Degraded performance on ePayments</title><link>https://status.vippsmobilepay.com/incidents/1</link>
<pubDate>Mon, 27 Oct 2026 07:00:00 +0000</pubDate><description>&lt;p&gt;Investigating - We are looking into it.&lt;/p&gt;</description></item>
<item><title>Login API</title><pubDate>Sun, 26 Oct 2026 07:00:00 +0000</pubDate><description>Resolved - Fixed.</description></item>
</channel></rss>"""


def test_vipps_json_and_rss_fallback(cfg):
    r = vipps.collect(FakeHttp({vipps.STATUS_JSON: {"status": {"indicator": "major", "description": "Major outage"}},
                                vipps.UNRESOLVED: {"incidents": [{"name": "Payments down", "status": "investigating", "impact": "major", "components": [{"name": "Payment Processing"}]}]}}), cfg)
    assert r.ok and r.signals[0].level == RED and r.data["incidents"][0]["components"] == ["Payment Processing"]
    r2 = vipps.collect(FakeHttp({vipps.STATUS_JSON: RuntimeError("403"), vipps.HISTORY_RSS: VIPPS_RSS}), cfg)
    assert r2.ok and r2.signals[0].level == YELLOW and "ePayments" in r2.signals[0].text and "status.json" in r2.error


# ---------- Avinor ----------
AVINOR = b"""<?xml version="1.0" encoding="utf-8"?><airport name="OSL"><flights lastUpdate="2026-10-27T08:00:00Z">
<flight uniqueID="1"><airline>SK</airline><flight_id>SK1460</flight_id><dom_int>D</dom_int><schedule_time>2026-10-27T09:00:00Z</schedule_time><arr_dep>D</arr_dep><airport>BGO</airport><status code="C" time="2026-10-27T08:00:00Z"/></flight>
<flight uniqueID="2"><airline>DY</airline><flight_id>DY740</flight_id><dom_int>D</dom_int><schedule_time>2026-10-27T09:10:00Z</schedule_time><arr_dep>D</arr_dep><airport>TRD</airport><status code="E" time="2026-10-27T09:40:00Z"/></flight>
<flight uniqueID="3"><airline>WF</airline><flight_id>WF123</flight_id><dom_int>D</dom_int><schedule_time>2026-10-27T09:20:00Z</schedule_time><arr_dep>D</arr_dep><airport>SVG</airport></flight>
</flights></airport>"""


def test_avinor(cfg):
    d = avinor.parse(AVINOR)
    assert d["count"] == 3 and d["cancelled"] == 1 and d["delayed"] == 1 and d["flights"][0]["flight_id"] == "SK1460"
    assert d["flights"][1]["delay_min"] == 30 and d["flights"][1]["delayed"]
    # E-status med ny tid bare 3 min etter rutetid er ikke forsinkelse
    on_time = AVINOR.replace(b'time="2026-10-27T09:40:00Z"', b'time="2026-10-27T09:13:00Z"')
    assert avinor.parse(on_time)["delayed"] == 0
    r = avinor.collect(FakeHttp({avinor.URL: AVINOR}), cfg)
    assert r.ok and r.signals[0].level == GREEN and "2 innstilte" in r.signals[0].text and "2 forsinket" in r.signals[0].text


# ---------- Polisen / Politiloggen ----------
POLISEN = [{"id": 1, "datetime": "2026-10-27 07:00:00 +01:00", "name": "27 oktober 07:00, Brand, Stockholm", "summary": "Brand i källare.",
            "url": "/aktuellt/handelser/2026/oktober/27/brand-stockholm/", "type": "Brand", "location": {"name": "Stockholm", "gps": "59.3,18.0"}},
           {"id": 2, "datetime": "2026-10-27 06:00:00 +01:00", "name": "Fylleri", "summary": "x", "url": "/a", "type": "Fylleri/LOB", "location": {"name": "Malmö"}}]


def test_polisen(cfg):
    d = polisen.parse(POLISEN)
    assert d["count"] == 2 and len(d["flagged"]) == 1 and d["events"][0]["url"].startswith("https://polisen.se/")
    assert polisen.collect(FakeHttp({polisen.URL: POLISEN}), cfg).ok


POLITI_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Politiloggen Oslo</title>
<item><title>Brann, Grünerløkka</title><link>https://www.politiet.no/politiloggen/hendelse/1</link><category>Brann</category>
<pubDate>Mon, 27 Oct 2026 07:45:00 +0000</pubDate><description>Melding om røykutvikling i leilighet. Nødetatene på stedet.</description></item>
<item><title>Trafikk, Ring 3</title><category>Trafikk</category><pubDate>Mon, 27 Oct 2026 07:30:00 +0000</pubDate><description>Bil med motorstopp.</description></item>
</channel></rss>""".encode("utf-8")


POLITI_JSON = {"messages": [
    {"id": "m3", "threadId": "266wgp", "text": "Politiet har flere patruljer i området etter en trusselsituasjon i Rudsveien. Nærmeste naboer er evakuert.",
     "district": "Oslo politidistrikt", "category": "Trussel", "municipality": "Bærum", "area": "Gjettum", "createdOn": "2026-10-27T08:50:00Z", "isActive": True},
    {"id": "m2", "threadId": "26zb4w", "text": "Demontering av kran er ferdig, sperringene er fjernet.", "category": "Annet", "municipality": "Oslo", "area": "Sentrum",
     "createdOn": "2026-10-27T08:10:00Z", "isActive": False},
    {"id": "m1", "threadId": "26zb4w", "text": "Demontering av kran pågår.", "category": "Annet", "municipality": "Oslo", "area": "Sentrum",
     "createdOn": "2026-10-27T06:00:00Z", "isActive": False},
], "hasMoreResults": True}


def test_politiloggen_json(cfg):
    d = politiloggen.parse_json(POLITI_JSON)
    assert d["count"] == 3 and d["threads"] == 2 and d["active_threads"] == 1 and d["has_more"]
    assert len(d["serious"]) == 1 and d["serious"][0]["area"] == "Gjettum" and d["entries"][0]["created"] == "2026-10-27T08:50:00+00:00"
    http = FakeHttp({politiloggen.URL_JSON: POLITI_JSON})
    r = politiloggen.collect(http, cfg)
    assert r.ok and r.data["via"] == "json" and r.signals[0].level == YELLOW and "Gjettum, Bærum" in r.signals[0].text
    assert http.calls[0][1]["Districts"] == "Oslo"
    # PascalCase-nøkler skal også virke
    pascal = {"messages": [{"Id": "x", "ThreadId": "t", "Text": "Rolig natt.", "Category": "Annet", "IsActive": True, "CreatedOn": "2026-10-27T01:00:00Z"}]}
    assert politiloggen.parse_json(pascal)["active_threads"] == 1


def test_politiloggen_rss_fallback(cfg):
    d = politiloggen.parse_rss(POLITI_RSS)
    assert d["count"] == 2 and d["entries"][0]["category"] == "Brann" and len(d["serious"]) == 1
    r = politiloggen.collect(FakeHttp({politiloggen.URL_JSON: RuntimeError("nede"), politiloggen.URL_RSS: POLITI_RSS}), cfg)
    assert r.ok and r.data["via"] == "rss" and r.signals[0].level == YELLOW and "json" in r.error
    assert not politiloggen.collect(FakeHttp({politiloggen.URL_JSON: RuntimeError("nede"), politiloggen.URL_RSS: RSS_EMPTY}), cfg).ok


# ---------- Cloudflare Radar ----------
def test_cloudflare_radar(cfg, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    assert not cloudflare_radar.collect(FakeHttp({}), cfg).ok
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "x")
    raw = {"result": {"annotations": [
        {"id": "a", "locations": ["NO"], "startDate": "2026-10-27T05:00:00Z", "endDate": None, "outage": {"outageCause": "CABLE_CUT", "outageType": "PARTIAL"}},
        {"id": "b", "locations": ["SE"], "startDate": "2026-10-20T05:00:00Z", "endDate": "2026-10-20T06:00:00Z", "outage": {}},
    ]}}
    r = cloudflare_radar.collect(FakeHttp({cloudflare_radar.URL: raw}), cfg)
    assert r.ok and r.signals[0].level == RED and "CABLE_CUT" in r.signals[0].text


# ---------- RSS-snapshot ----------
def _rss(title, when):
    return (f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>'
            f'<item><title>{title} sak</title><link>https://ex.no/{title}</link><pubDate>{when}</pubDate><description>Ingress</description></item>'
            f'</channel></rss>').encode()


def test_rss_news_window_and_failures(cfg):
    fresh = dt.datetime.now(dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    old = "Mon, 01 Jan 2024 00:00:00 +0000"
    feeds = [{"id": "a", "name": "A", "url": "https://a.example/rss", "lang": "no", "group": "nyheter", "enabled": True},
             {"id": "b", "name": "B", "url": "https://b.example/rss", "lang": "no", "group": "nyheter", "enabled": True},
             {"id": "c", "name": "C", "url": "https://c.example/rss", "lang": "no", "group": "nyheter", "enabled": True},
             {"id": "vg", "name": "VG", "url": "https://vg.example/rss", "lang": "no", "group": "nyheter", "enabled": False, "requires_agreement": True}]
    local_cfg = dict(cfg, news_feeds=feeds, news_window_hours=36)
    http = FakeHttp({"https://a.example": _rss("A", fresh), "https://b.example": _rss("B", old), "https://c.example": RuntimeError("timeout")})
    r = rss_news.collect(http, local_cfg)
    assert r.ok and r.data["item_count"] == 1 and r.data["items"][0]["source"] == "a"
    assert r.data["feeds_ok"] == 2 and "c" in r.data["feeds_failed"] and "vg" not in {u for u, _ in http.calls}


def test_schibsted_feeds_disabled_by_default(cfg):
    for f in cfg["news_feeds"]:
        if f.get("requires_agreement"):
            assert f["enabled"] is False, f["id"]
