# beredskap-oslo – innsamler

Innsamleren bak beredskap.oslo.no: et Python-program som henter status fra åpne kilder
(strøm, vann, varsler, transport, betaling, naboland, nyheter), oversetter alt til ett felles
JSON-format med trafikklys per kategori, og legger resultatet i et git-repo som nettsiden og
Claude-agentene leser. Ingen database, ingen server.

Uoffisiell tjeneste. Følg alltid Nødvarsel, politiet og Oslo kommune.

## Kjøre lokalt

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
# Sett kontaktadresse i config.yaml (MET avviser kall uten identifiserende User-Agent)
python -m collector --config config.yaml            # alle aktiverte kilder
python -m collector --only ruter,vegvesen -v        # bare noen, med mer logg
python -m pytest -q                                  # 28 tester, ingen nettverk
```

Resultatet havner i `data/`:

| Fil | Innhold | Leses av |
| --- | --- | --- |
| `data/status.json` | Trafikklys per kategori (`strom`, `vann`, `ekom`, `betaling`, `transport`, `varsler`, `lokalt`, `naboland`), signaler med tekst og kilde, kildehelse | Nettsiden, situasjonsagenten |
| `data/sources/<id>.json` | Rådata normalisert per kilde (f.eks. alle Vegvesen-situasjoner med geometri, alle Ruter-avvik) | Nettsidens undersider og kart |
| `data/nyheter_raw.json` | Siste 36 timer fra alle RSS-feeder: tittel, ingress (kuttet), lenke, kilde | Nyhetsagenten |

`docs/eksempel-data/` viser formatet, generert fra testfiksturene (ikke ekte tall).

Nivåer: `green` (0), `yellow` (1), `red` (2), `unknown` (-1). En kilde som feiler beholder forrige
vellykkede data i inntil 6 timer (`--stale-max-hours`) og merkes `stale`; etter det blir kategorien `unknown`.

## Kilder

| id | Kilde | Kategori | Tilgang | Verifisert 27.10.2026 |
| --- | --- | --- | --- | --- |
| elvia | Elvia strømbruddskart (ArcGIS bak kartet) | strom | åpen JSON, udokumentert | ja |
| statnett | Statnett driftsdata (kraftsituasjon NO1, flyt) | strom | åpen JSON, vilkår ikke funnet | ja |
| strompris | hvakosterstrommen.no NO1 | strom | åpen JSON, krediter | ja |
| nve | NVE flom/jordskred Oslo (v1.0.10), magasin NO1 | vann | åpen JSON, NLOD | ja |
| met | MET MetAlerts 2.0, county=03 | varsler | åpen GeoJSON, User-Agent | ja |
| nodvarsel | Nødvarsel RSS (aktive + tidligere) | varsler | RSS | ja |
| vegvesen | Vegvesen DATEX WFS: situasjoner, reisetid, kamera | transport | åpen GeoJSON, NLOD | ja |
| ruter | ruter.no/api/traffic-status.json | transport | åpen JSON, vilkår ikke oppgitt | ja |
| entur | Entur SIRI SX (RUT, BNR, FLT) | transport | åpen XML, NLOD, ET-Client-Name | ja |
| krisinformation | Krisinformation.se v3 (news, VMA) | naboland | åpen JSON | ja |
| vipps | Vipps MobilePay Statuspage (JSON, fallback RSS) | betaling | åpen | RSS ja, JSON antatt |
| avinor | Avinor XmlFeed OSL | transport | åpen XML, poll maks hvert 3. min | ja (kjørt fra Mac) |
| polisen | polisen.se/api/events | naboland | åpen JSON | ja |
| politiloggen | api.politiloggen.politiet.no /messages (JSON), reserve /feeds/rss | lokalt | åpen JSON, NLOD 2.0 | ja |
| cloudflare_radar | Cloudflare Radar utfall (NO) | ekom | token i `CLOUDFLARE_API_TOKEN` | nei, av som standard |
| rss_news | ca. 40 RSS-feeder | nyheter | RSS | de fleste |

«Verifisert» betyr at endepunktet ble åpnet og svarte med forventet innhold; parserne er
skrevet etter feltene vi så. Første ekte kjøring vil likevel avdekke avvik, derfor logger
innsamleren hver kilde og feiler mykt.

Schibsted-feedene (VG, Aftenposten, E24) ligger i `config.yaml` med `enabled: false` og
`requires_agreement: true` til avtale er på plass. Testen `test_schibsted_feeds_disabled_by_default`
sørger for at de ikke slås på ved et uhell.

Mobil og internett (`ekom`) har ingen automatisk kilde ennå: operatørene publiserer ikke
maskinlesbar status. Slå på `cloudflare_radar` med en gratis token, eller skriv en skraper
for ice.no/driftsmeldinger (ren HTML).

## GitHub Actions

`.github/workflows/collect.yml` kjører innsamleren hvert 10. minutt og publiserer `data/`
til grenen `data` som ett enkelt commit (force-push), slik at `main` holder seg liten.
Agent-filene `agent/*.json` fra `main` kopieres med. Nettsiden og agentene leser da alt fra:

```
https://raw.githubusercontent.com/<eier>/<repo>/data/status.json
https://raw.githubusercontent.com/<eier>/<repo>/data/nyheter_raw.json
https://raw.githubusercontent.com/<eier>/<repo>/data/nyheter.json
```

Et offentlig repo gir ubegrensede Actions-minutter. Legg `CLOUDFLARE_API_TOKEN` som
repo-secret om Radar skal brukes. GitHub kan forsinke skedulerte kjøringer med flere minutter;
trengs oppdatering oftere enn hvert 5. minutt, flytt innsamleren til Cloudflare Workers Cron.

## Claude-agentene

Tre skedulerte oppgaver i Claude, én per fil i `agent/`:

| Agent | Kjører | Leser | Skriver |
| --- | --- | --- | --- |
| `nyhetsagent.md` | hver time | `data/nyheter_raw.json` | `agent/nyheter.json` på main |
| `situasjonsagent.md` | hver 6. time | `data/status.json`, `nyheter.json` | `agent/situasjon.json` på main |
| `kildevakt.md` | daglig 07:00 | `status.json`, `nyheter_raw.json` | rapport til eieren, ingen commit |

Agentene leser fra GitHub (raw-URL-er) og committer til `main`. De trenger derfor skrivetilgang
til repoet: GitHub-koblingen i Claude, eller en finkornet token med bare `contents: write`
på dette ene repoet. Bytt ut `<EIER>/<REPO>` i promptene. Prompten limes inn som oppgavens
instruks; hver kjøring starter uten minne, så alt agenten trenger står i filen.

## Vilkår å huske

- MET: User-Agent med kontaktinfo, bruk `If-Modified-Since` i drift.
- Avinor: maks ett kall per 3 min, cache på egen server, merk «Flight data from Avinor».
- NVE: krediter «Varsler fra Flomvarslingen og Jordskredvarslingen i Norge», lenk til varsom.no, ikke filtrer bort varsler.
- hvakosterstrommen.no: «Strømpriser levert av Hva koster strømmen.no».
- Entur: maks 4 SX-kall per minutt; `ET-Client-Name` settes i `config.yaml`.
- Elvia (ArcGIS), Statnett og Ruter: ingen vilkår funnet; spør før produksjon.
- Nyheter: bare tittel, ingress og lenke lagres og vises. Aldri fulltekst.

## Struktur

```
collector/            innsamleren (python -m collector)
  common.py           Http, SourceResult, Signal, nivåer
  status.py           aggregator → status.json
  sources/*.py        én modul per kilde: ID, NAME, CATEGORY, parse(), collect()
agent/                prompter for Claude-agentene (+ JSON-filene de skriver)
tests/                pytest med fiksturer, ingen nettverk
docs/eksempel-data/   eksempel på output
config.yaml           kontakt, terskler, kilder av/på, feeder
```

Ny kilde: kopier en modul, implementer `parse(raw)` og `collect(http, cfg)`, legg id-en i
`config.yaml` under `sources`, og skriv en test med en liten fikstur.
