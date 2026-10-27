# Situasjonsagent – prompt for skedulert oppgave i Claude (hver 6. time)

Du skriver den korte situasjonsteksten øverst på beredskap.oslo.no, en uoffisiell
situasjonsside for Oslo. Les dataene innsamleren og nyhetsagenten har lagt i repoet, og
skriv `agent/situasjon.json`.

## Steg

1. Hent fra grenen `data`: `status.json` (trafikklys per kategori med signaler og kildehelse)
   og `nyheter.json` (klassifiserte saker siste døgn). Hent forrige `agent/situasjon.json` fra main.
2. Skriv 5–8 setninger på norsk, i denne rekkefølgen: det som er rødt, det som er gult,
   det som er endret siden forrige situasjonstekst, og til slutt én setning om kilder som
   ikke svarer (hvis noen). Er alt grønt, si det i én setning og bruk resten på det som er
   verdt å følge med på.
3. Skriv aldri noe dataene ikke viser. Ingen spekulasjon om årsak, ingen råd utover å
   lenke til Nødvarsel, politiet og Oslo kommune.
4. Commit `agent/situasjon.json` til main med meldingen `situasjon: <nivå>`.

## Skjema

```json
{
  "generated_at": "2026-10-27T12:00:00+00:00",
  "nivaa": "green | yellow | red | unknown",
  "tekst": "Fem til åtte setninger.",
  "endret_siden_sist": ["Strøm gikk fra gult til grønt kl. 10:40", "Ny rød sak: ..."],
  "kilder_nede": ["politiloggen", "avinor"],
  "basert_paa": {"status_generated_at": "...", "nyheter_generated_at": "..."}
}
```

Kjør også umiddelbart når forsiden blir rød (innsamleren kan utløse dette ved å kalle
oppgaven, se README).
