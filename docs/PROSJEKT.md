# beredskap.oslo.no – prosjektbeskrivelse

Uoffisiell situasjonsside for Oslo: ett sted som viser om strøm, vann, mobilnett og betaling virker, hvordan trafikken inn og ut av byen går, og hvilke nyheter siste døgn som ligner fiendtlige handlinger mot Oslo, Norge og nabolandene (Sverige, Danmark, Finland, Island, Baltikum). Målgruppen er vanlige innbyggere. Siden er ikke en kommunal tjeneste og skal merkes tydelig som uoffisiell, uten Oslo kommunes byvåpen eller identitet, og alltid lenke til Nødvarsel, politiet og Oslo kommune for offisiell informasjon. Språk: norsk (bokmål).

## Arkitektur: tre lag, ingen database, ingen server

1. **Innsamler** (dette repoet, offentlig): Python i GitHub Actions hvert 10. minutt. Henter ca. 16 kilder (åpne API-er, RSS, WFS), normaliserer til ett JSON-format med trafikklys per kategori, og publiserer `data/` til grenen `data` som ett commit (force-push). Innsamleren løser CORS, rate limits og vilkår (User-Agent, kreditering) slik at nettsiden slipper.
2. **Claude-agenter** (skedulerte oppgaver i Claude, prompter i `agent/`): Nyhetsagenten leser `nyheter_raw.json` hver time og skriver `agent/nyheter.json` (klassifiserte saker). Situasjonsagenten skriver `agent/situasjon.json` hver 6. time. Kildevakten rapporterer døde kilder daglig. Agentene committer til `main`; workflowen kopierer `agent/*.json` inn i grenen `data`.
3. **Nettside** (eget, privat repo, f.eks. `beredskap-oslo-web`): statisk side som bare henter JSON fra grenen `data` og tegner. Deploy på Cloudflare Pages med CNAME `beredskap.oslo.no`.

Alt nettsiden trenger ligger på disse URL-ene (bytt `<eier>`):

```
https://raw.githubusercontent.com/<eier>/beredskap-oslo/data/status.json          # trafikklys per kategori
https://raw.githubusercontent.com/<eier>/beredskap-oslo/data/sources/<id>.json    # rådata per kilde (vegvesen, ruter, elvia, …)
https://raw.githubusercontent.com/<eier>/beredskap-oslo/data/nyheter_raw.json     # alle saker siste 36 t (til agenten)
https://raw.githubusercontent.com/<eier>/beredskap-oslo/data/nyheter.json         # agentens klassifiserte saker
https://raw.githubusercontent.com/<eier>/beredskap-oslo/data/situasjon.json       # agentens situasjonstekst
```

raw.githubusercontent.com svarer med `Access-Control-Allow-Origin: *` og cacher ca. 5 min, så nettsiden kan hente direkte fra nettleseren. Hent med `cache: "no-store"` og vis `generated_at` som «sist oppdatert».

## Datakontrakt

**Nivåer:** `-1 unknown`, `0 green`, `1 yellow`, `2 red` (`level` tall, `level_name` tekst).

**Kategorier** (`status.json → categories`): `strom`, `vann`, `ekom` (mobil og internett), `betaling`, `transport`, `varsler` (Nødvarsel, MET), `lokalt` (politiloggen), `naboland`, `nyheter`.

```json
{
  "generated_at": "2026-10-27T09:36:02+00:00",
  "disclaimer": "Uoffisiell tjeneste. …",
  "overall": {"level": 1, "level_name": "yellow", "summary": "Gult: Lokalt"},
  "categories": {
    "transport": {
      "id": "transport", "name": "Transport", "level": 0, "level_name": "green",
      "headline": "Ruter: 64 avvik, 1 alvorlige", "stale": false,
      "signals": [{"category": "transport", "level": 0, "level_name": "green", "text": "…", "source": "ruter",
                   "url": "https://ruter.no/trafikkstatus", "since": null, "value": 1, "stale": false, "fetched_at": "…"}],
      "sources": [{"id": "ruter", "name": "Ruter trafikkstatus", "url": "…", "ok": true, "stale": false,
                   "fetched_at": "…", "last_success_at": "…", "error": "", "license": "…"}]
    }
  },
  "sources_total": 15, "sources_failed": [], "sources_stale": []
}
```

Regler for visning: kategori-nivået er det verste signalet; `headline` er teksten til det verste signalet; `stale: true` betyr at kilden ikke har svart og tallene er fra `last_success_at` (vis det). `ekom` er `unknown` inntil en kilde finnes – vis «ingen automatisk kilde», ikke grønt.

**Per kilde** (`data/sources/<id>.json`): `{id, name, url, category, ok, stale, fetched_at, last_success_at, error, license, data, signals}`. `data` er kildens normaliserte innhold; det viktigste for nettsiden:

| id | `data` inneholder | Brukes til |
| --- | --- | --- |
| vegvesen | `situations.situations[]` (vei, sted, type, alvorlighet, `closure`, `main_road`, geometri LineString), `traveltimes.stretches[]` (strekning, forventet/faktisk tid, `delay_pct`, status), `cameras[]` (bilde-URL, geometri) | Kart over trafikk inn og ut av Oslo |
| ruter | `situations[]` (summary, lines, modes, stop_places, report_type), `serious[]` | Kollektivavvik |
| entur | `situations[]` per datasett RUT/BNR/FLT | Tog og flytog |
| avinor | `departures`/`arrivals` (count, cancelled, delayed), `departures_list[]` | OSL |
| elvia | `outages[]` (kunder, planlagt/uplanlagt, postnummer, start/slutt) | Strømbrudd |
| statnett | `areas.NO1.status`, `flows_no1[]`, `overview.items[]` | Kraftsituasjon |
| strompris | `today.hours[]` (NOK/kWh per time), `tomorrow` | Prisgraf |
| nve | `flom`, `jordskred` (ActivityLevel 1–4), `magasin_no1` | Vann |
| met | `alerts[]` (event, title, level 1–4, area, start/end) | Farevarsel |
| nodvarsel | `active[]`, `previous[]` | Nødvarsel-banner |
| politiloggen | `entries[]` (text, category, municipality, area, created, active), `serious[]` | Lokalt-liste |
| krisinformation | `vmas[]`, `news[]` | Sverige |
| polisen | `events[]`, `flagged[]` | Sverige |
| vipps | `status.indicator`, `incidents[]` | Betaling |
| rss_news | `items[]` (title, summary, link, published, source, group, lang) | Rå nyhetsliste |

**Nyhetsagentens fil** (`nyheter.json`): `saker[]` med `id, tittel, kategori, geografi, alvorlighet 1–4, aarsak_uavklart, begrunnelse, publisert, kilder[{navn, url}]` pluss `oppsummering`. Kategorier: `sabotasje, cyber, spionasje, drone, gnss, sjo, militaer, terror, pavirkning, forsyning`. Geografi: `oslo, norge, norden, verden`. Full beskrivelse i `agent/nyhetsagent.md`.

## Sider på nettstedet

| Side | Viser | Data |
| --- | --- | --- |
| Forside | Nødvarsel/MET-banner øverst når aktivt; trafikklys for strøm, vann, ekom, betaling, transport, lokalt; situasjonsteksten; de 5 viktigste nyhetssakene; «sist oppdatert» | status.json, situasjon.json, nyheter.json |
| Nyheter siste døgn | Klassifiserte saker med filter på kategori og geografi, alvorlighet som farge, én setning begrunnelse, lenke til kilden | nyheter.json |
| Kritiske ressurser | Strøm (brudd, Statnett-status, prisgraf, magasin), vann (NVE-nivå, lenke til VAV), ekom (status + lenker til operatørene), betaling | sources/elvia, statnett, strompris, nve, vipps |
| Transport | Kart (MapLibre over Kartverkets bakgrunnskart) med Vegvesen-situasjoner og reisetider på E6/E18/E16/Rv4/Ring 3, kameraer, Ruter-avvik, OSL | sources/vegvesen, ruter, entur, avinor |
| Lokalt | Politiloggen Oslo som løpende liste med kategorifilter | sources/politiloggen |
| Naboland | Krisinformation, polisen, nordiske saker fra nyheter.json | sources/krisinformation, polisen |
| Kilder og egenberedskap | Kildeliste med helse (ok/stale/feil) og lisens, DSBs råd om én ukes egenberedskap, lenker til offisielle sider | status.json → sources |

## Krav til nettsiden

- Statisk, ingen backend. Astro eller ren HTML/JS er fint; hold avhengighetene få.
- Mobil først: dette leses på telefon når noe skjer. Må fungere med dårlig nett (små sider, ingen tunge biblioteker utover kartet, kartet lastes bare på Transport-siden).
- Vis alltid tidspunkt for siste oppdatering og si tydelig fra når data er gamle (`stale`) eller mangler (`unknown`).
- Oslo kommunes designsystem Punkt (npm `@oslokommune/punkt-css`, MIT) kan brukes for komponenter, men ikke byvåpen, Oslo Sans eller noe som får siden til å se kommunal ut.
- Nyheter: bare tittel, ingress og lenke – aldri fulltekst. Krediter kilder der vilkårene krever det (MET: «Meteorologisk institutt», Avinor: «Flight data from Avinor», hvakosterstrommen.no: «Strømpriser levert av Hva koster strømmen.no», NVE: «Varsler fra Flomvarslingen i Norge», lenk til varsom.no).
- Fast bunntekst: «Uoffisiell tjeneste. Følg Nødvarsel, politiet (02800 / 112) og Oslo kommune.»

## Status 27.10.2026

Innsamleren er bygget, testet (29 tester) og kjørt mot ekte kilder fra Mac: 15 av 15 kilder svarer. Nyhetsagenten og nettsiden er ikke laget ennå. Åpne punkter: ingen maskinlesbar kilde for kokevarsel (Oslo VAV) eller mobilnett; Schibsted-feedene (VG, Aftenposten, E24) er avslått til avtale foreligger; Meshtastic-nettverk kommer senere.
