# Modellivssyklus

Dette dokumentet beskriver hvordan modellen følges opp etter at den er trent. Det forklarer hvordan versjoner registreres, og hvilken regel som avgjør om en utfordrer kan bli ny hovedmodell. Det forklarer også hvordan en forfremmelse rulles tilbake, hva den planlagte jobben gjør for hvert nytt øyeblikksbilde, hva som overvåkes, og hvilke regler som fører til ny trening. Alle terskler ligger i `configs/default.yaml`. Alle beslutninger skrives til tabeller i skjemaet `monitoring`.

## Register og aliaser

Modellen registreres i Unity Catalog, i gullskjemaet. Hver trening gir en ny versjon. To aliaser peker på versjoner. `champion` er hovedmodellen. Den brukes til å skåre nye øyeblikksbilder. `challenger` er den sist trente kandidaten. Den vurderes mot hovedmodellen.

Ny trening gir alltid en utfordrer, aldri en ny hovedmodell direkte. Hver hendelse i registeret skrives til tabellen `monitoring.registry_events`: registrering, endring av alias, vurdering, forfremmelse, tilbakerulling og avslag. Hver rad har tidspunkt, versjon, beslutning og hvem som utførte den.

## Regel for forfremmelse

Utfordreren vurderes på den frosne valideringsdelen. Delen er frosset fordi selskapene fordeles til trening, validering og test med en saltet hash av organisasjonsnummeret. Hver kandidat måles derfor på de samme selskapene. Regelen ligger i `registry/promotion.py`. Alle kravene under må være oppfylt:

| Mål på valideringsdelen | Krav |
|---|---|
| Antall positive utfall | minst 30 |
| Gjennomsnittlig presisjon | minst 0,10 |
| Presisjon i øverste prosent | minst 0,05 |
| Brier-skår | høyst 0,02 |
| Forventet kalibreringsfeil | høyst 0,02 |
| Mot gjeldende hovedmodell | gjennomsnittlig presisjon høyst 5 prosent lavere |

Det siste kravet gjelder bare når det finnes en hovedmodell. Regelen avgjør om en versjon er kvalifisert. Selve forfremmelsen er et manuelt steg som må godkjennes:

```bash
foretaksrisiko registry evaluate 3 --profile foretaksrisiko
```

```bash
foretaksrisiko registry promote 3 --approve --profile foretaksrisiko
```

Uten `--approve` viser kommandoen bare resultatet av regelen og endrer ingenting. Med `--approve` flyttes aliaset `champion` til versjonen, hvis regelen er oppfylt. Den forrige hovedmodellen lagres som `previous_champion_version` på den registrerte modellen. En forfremmelse som ikke oppfyller regelen, avslås selv om den er godkjent. Avslaget logges.

## Tilbakerulling

Tilbakerulling flytter aliaset `champion` tilbake til den forrige hovedmodellen. Også dette er et manuelt steg som må godkjennes:

```bash
foretaksrisiko registry rollback --approve --profile foretaksrisiko
```

Versjonen det rulles tilbake fra, lagres som ny `previous_champion_version`. En tilbakerulling kan derfor selv rulles tilbake. Ingen versjoner slettes.

## Planlagt jobb

Jobben `snapshot_pipeline` i `databricks.yml` kjøres per øyeblikksbilde, ukentlig etter innhentingen. Den kan også startes for hånd, med nummeret på øyeblikksbildet som parameter. Oppgavene kjører i rekkefølge:

1. `bronze`: landingsfilene lastes inn som de er, med kvalitetskontroller.
2. `silver`: rensede tabeller, kodeverk og historikktabell.
3. `gold`: selskapstabellen for øyeblikksbildet.
4. `features`: utfall, merkelapper og trekk for begge design.
5. `score`: hovedmodellen skårer alle selskap i øyeblikksbildet med de framoverskuende trekkene og skriver `gold.champion_scores`. Hvis det ikke finnes en hovedmodell, hopper steget over, og overvåkingen noterer det.
6. `monitor`: driftmål mot referanseøyeblikksbildet, oppsummering av skårene, varsler og anbefaling om ny trening.
7. `alert`: feiler hvis det finnes varsler på nivå `alert` for øyeblikksbildet. Feilen gjør at jobben sender et varsel på e-post.

E-postadressen settes ved utrulling og ligger ikke i kodelageret. Jobben `train_challenger` trener og registrerer en utfordrer når ny trening er anbefalt. Den startes for hånd.

## Overvåking

Referanseøyeblikksbildet er øyeblikksbildet hovedmodellen ble trent på, hvis ikke et annet oppgis. Overvåkingen leser de framoverskuende trekkene for referansen og for det gjeldende øyeblikksbildet. Den skriver tre tabeller. Tidligere rader for samme øyeblikksbilde og scenario erstattes.

Tabellen `monitoring.drift` har ett mål per trekk. For talltrekk regnes populasjonsstabilitetsindeks (PSI) ut over desiler fra referansen, sammen med endringen i andelen manglende verdier. For kategoriske trekk regnes PSI ut over andelene per kategori, sammen med den største endringen i andelen for én kategori og andelen manglende verdier. For skårene regnes PSI ut, sammen med andelen selskap over flaggterskelen. Terskelen er skåren som flagger de øverste 5 prosentene i referanseøyeblikksbildet. Mange selskap har lik sannsynlighet, og selskap som ligger nøyaktig på terskelen, flagges ikke. Andelen flagget kan derfor være lavere enn 5 prosent.

Tabellen `monitoring.score_summary` har antall, gjennomsnitt, persentiler, flaggterskel og andel flagget, for referansen og for det gjeldende øyeblikksbildet.

Tabellen `monitoring.alerts` har ett varsel per mål som går over en terskel, med nivå `warn` eller `alert`. Den får også en rad `retraining_recommended` når en regel for ny trening slår til.

Grensene mellom desilene er glattet. Et selskap som ligger nær en grense, telles delvis i begge grupper. Båndet rundt hver grense er 2 prosent av avstanden mellom 10- og 90-persentilen i referansen. Uten glatting gir noen trekk høy PSI uten at fordelingen har endret seg. Det gjelder trekk der mange selskap deler samme verdi, for eksempel antall kunder revisjonsselskapet har. Hvis et stort revisjonsselskap får noen få kunder færre, flytter alle kundene seg over en grense samtidig. Mellom øyeblikksbilde 1 og 2 ga dette en PSI langt over terskelen for varsel uten glatting, og nær null med glatting. For trekk uten slike blokker endrer glattingen PSI med noen få prosent.

Terskler i standardoppsettet:

| Mål | warn | alert |
|---|---|---|
| PSI per trekk | 0,10 | 0,25 |
| Endring i andel manglende verdier | 0,02 | 0,05 |
| Største endring i andel for en kategori | 0,05 | 0,10 |
| PSI for skårene | 0,10 | 0,25 |
| Relativ endring i andel flagget | 25 prosent | 50 prosent |

Hvis en av sidene har under 1 000 selskap, beregnes ingen driftverdier. Små øyeblikksbilder utløser derfor aldri varsler ved en tilfeldighet. Seks måneder etter et øyeblikksbilde er alle utfallene kjent. Da kan ytelsen følges opp med de samme målene som i valideringsrapporten.

Mellom øyeblikksbilde 1 og 2 er ingen mål over terskelen for `warn`. Høyeste PSI for et trekk er under 0,01. Andelen flagget er 3,8 prosent i begge øyeblikksbildene.

## Regler for ny trening

Ny trening anbefales når minst én regel slår til. Den settes aldri i gang automatisk:

- R1 datadrift: minst 3 trekk har PSI på nivå `alert`.
- R2 prediksjonsdrift: PSI for skårene eller andelen flagget er på nivå `alert`.
- R3 modne utfall: minst 200 nye positive utfall er ferdig observert etter øyeblikksbildet hovedmodellen ble trent på.
- R4 alder: hovedmodellen er minst 26 øyeblikksbilder gammel.

Anbefalingen skrives som en rad i `monitoring.alerts`, med begrunnelse. Ny trening gir en utfordrer. Den må gjennom regelen for forfremmelse og en manuell godkjenning før den tas i bruk.

## Scenarioer for demonstrasjon

Et scenario er et navngitt sett med terskler i konfigurasjonen. Scenarioet `simulated_breach` senker tersklene så mye at vanlige forskjeller mellom to øyeblikksbilder gir varsler. Det brukes for å vise at varsler og e-post virker. Rader som skrives under et scenario, har navnet på scenarioet. De kan derfor skilles fra vanlig overvåking.

```bash
databricks bundle run snapshot_pipeline --params snapshot_id=2,scenario=simulated_breach
```

Kjørt på øyeblikksbilde 2 ga scenarioet tre mål på nivå `alert`: PSI for to nettverkstrekk, og endring i andelen manglende verdier for ett trekk. Steget `alert` feilet, slik det skal. Regelen R1 krever tre trekk med PSI på nivå `alert`. Den slo derfor ikke til, og ny trening ble ikke anbefalt.
