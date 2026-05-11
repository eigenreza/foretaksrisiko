# Valideringsrapport

Denne rapporten har to deler. Del 1 er en plan som ble skrevet ferdig før den endelige evalueringen ble kjørt. Planen endres ikke etterpå. Del 2 viser resultatene mot planen.

## Del 1: Forhåndsregistrert plan

### Formål

Modellene skal rangere norske aksjeselskap etter to ting: hvor uvanlige de er sammenlignet med lignende selskap, og hvor sannsynlig det er at de får et registrert utfall i en fast periode etter et referansetidspunkt. Rapporten skal vise hvor godt dette lykkes, med usikkerhet, og hvor det ikke lykkes. En høy skår betyr «uvanlig» eller «høy sannsynlighet for utfallet i registeret». Den betyr aldri noe annet.

### Data og populasjon

Populasjonen er alle aksjeselskap og allmennaksjeselskap i Enhetsregisteret ved et øyeblikksbilde, unntatt enheter i Frivillighetsregisteret. Alle trekk er på selskapsnivå. Trekkene er beskrevet i metodedokumentet og hentes fra gulltabellen for trekk. To unntak: identifikatorer og alle kolonner som starter med `masked_` brukes aldri som inndata til modellen. `masked_`-kolonnene finnes bare for å styre hvordan manglende verdier fylles ut. Ellers kunne manglende verdier som skyldes endringer etter referansetidspunktet, lekke informasjon om utfallet.

### Utfall og horisont

Primært utfall (strengt): konkurs åpnes, eller tvangsavvikling eller tvangsoppløsning besluttes, i løpet av seks måneder etter referansetidspunktet. Sekundært utfall (bredt): som primært, men frivillig avvikling tas også med. Det brede utfallet rapporteres bare som følsomhetsanalyse, fordi frivillig avvikling oftest er en administrativ avslutning.

Et selskap er med bare hvis det var registrert ved referansetidspunktet og ikke allerede hadde et av utfallene.

### To design

**Utviklingsdesign (bakoverskuende).** Referansetidspunktet er første dag i måneden seks måneder før øyeblikksbilde 1. Alle trekk begrenses til det som var kjent da. Datofelt brukes bare når datoen er før eller lik referansetidspunktet. Felt som ifølge endringsloggen ble endret etterpå, maskeres. Rollegrupper med senere endring maskeres. Regnskap brukes bare for regnskapsår som enten hadde passert lovens frist for innsending, eller som har en registrert innsending før referansetidspunktet. Utfallene leses fra registeret og endringsloggen slik de står i dag. Dette designet har en kjent svakhet: selskap som har gått konkurs, slettes fra registeret når bobehandlingen er ferdig. Omtrent en firedel av de sanne positive i vinduet er allerede borte. Dette er et problem med utvalget av positive, ikke støy i merkelappene. Tall fra dette designet brukes til utvikling, valg av modell og terskler.

**Evalueringsdesign (framoverskuende).** Referansetidspunktet er selve øyeblikksbildet. Utfallene hentes fra endringsloggen i ukene og månedene etterpå, også for selskap som senere slettes. Ingen maskering er nødvendig, og ingen positive går tapt. Dette er hovedevalueringen. Den rapporteres første gang når minst tre måneder av horisonten er observert, og oppdateres når hele horisonten er observert.

### Inndeling av data

I utviklingsdesignet deles selskapene tilfeldig i tre deler: 60 prosent til trening, 20 prosent til validering og 20 prosent til test. Delingen gjøres per selskap med et fast frø. Samme selskap havner aldri i flere deler. Valideringsdelen er frosset. Den brukes til kalibrering, valg av modell, og senere til regelen for forfremmelse i modellregisteret. Testdelen brukes én gang, til tallene i del 2.

I evalueringsdesignet er alle selskap test. Modellene som evalueres der, er trent på utviklingsdesignet. Evalueringen er derfor også en test på tvers av tid.

### Modeller

1. **Regelbasert referanse.** Antall robuste z-skårer utenfor tre innenfor sammenligningsgruppen. Største absolutte z-skår brukes som andre sorteringsnøkkel.
2. **Isolation Forest** på relative trekk og registertrekk, uten merkelapper.
3. **Robust Mahalanobis-avstand** på relative trekk, med robust kovarians, uten merkelapper.
4. **Gradientforsterkede trær** (histogrambaserte), trent på det strenge utfallet og kalibrert på valideringsdelen med isotonisk regresjon.

De tre første gir en avviksskår. Den fjerde gir en kalibrert sannsynlighet. De to typene svarer på ulike spørsmål. Rapporten viser begge, og hvor godt de stemmer overens.

### Trekk og ablasjoner

Hovedmodellen bruker alle trekkgruppene: register, roller, nettverk, regnskap, relative skårer og tekstlikhet. Tre ablasjoner kjøres med samme oppsett: uten nettverkstrekk, uten regnskapstrekk og uten teksttrekk. I tillegg kjøres en modell med bare register- og rolletrekk på hele populasjonen. Grunnen er at regnskapstrekk bare finnes for selskap der regnskap er hentet.

Antall ansatte som nøyaktig tall brukes ikke i utviklingsdesignet, fordi det nesten alltid er maskert der. Flagget for registrerte ansatte og størrelsesbåndet brukes i stedet.

### Mål og usikkerhet

For alle skårer: areal under presisjon-gjenkallingskurven, presisjon og løft blant de 1 og 5 prosent høyest rangerte, og areal under ROC-kurven som sekundært mål. For den kalibrerte sannsynligheten i tillegg: Brier-skår, kalibreringskurve med ti like store grupper, og forventet kalibreringsfeil.

Alle mål rapporteres med 95 prosent konfidensintervall fra 1 000 bootstrap-trekk av selskap. Stabilitet i rangeringen måles som Spearman-korrelasjon og overlapp i topp 1 prosent mellom fem frø, og mellom øyeblikksbilder når flere finnes. Samsvar mellom avviksskår og sannsynlighet måles som Spearman-korrelasjon og overlapp i topp 1 og 5 prosent.

### Rettferdighet

Andel flagget blant de 5 prosent høyest rangerte og presisjon innenfor gruppen rapporteres for fylke, næringshovedområde, aldersbånd og størrelsesbånd. Grupper med færre enn 20 selskap slås sammen eller tas ut. Forskjeller forklares. Minst ett mottiltak prøves og rapporteres, uansett om det hjelper eller ikke.

### Forklaringer

Globale forklaringer: SHAP-verdier oppsummert per trekk for den trebaserte modellen, og gjennomsnittlige bidrag per trekk for de robuste avviksskårene. Ingen forklaringer på enkeltselskap publiseres.

### Hva som er låst

Denne planen, listen av trekk slik den står i gulltabellen når del 2 kjøres, frøet for inndelingen, modellfamiliene over og definisjonene av målene. Hyperparametre velges på valideringsdelen før testdelen brukes. Valgene føres i eksperimentloggen.

### Hva som rapporteres uansett

Grunnrater i hvert design og hver del, antall selskap med brukbare regnskap, antall positive, og alle svake eller negative funn, med samme vekt som de sterke.

## Del 2: Resultater

Resultatene gjelder modellene som er trent på hele populasjonen i øyeblikksbilde 1, med det bakoverskuende designet. Den framoverskuende evalueringen legges til når horisonten har gått ut.

### Grunnrater og antall

| Del | Kvalifiserte selskap | Positive, strengt utfall | Grunnrate | Med regnskap ved referansetidspunktet |
|---|---|---|---|---|
| Alle deler | 412 084 | 2 197 | 0,53 prosent | 372 635 |
| Treningsdelen | 247 703 | 1 287 | 0,52 prosent | 224 111 |
| Valideringsdelen | 82 240 | 448 | 0,54 prosent | 74 276 |
| Testdelen | 82 141 | 462 | 0,56 prosent | 74 248 |

Omtrent 90 prosent av selskapene i hver del hadde minst ett regnskap ved referansetidspunktet.

### Hovedmål på testdelen

Intervallene er 95 prosent konfidensintervall fra 1 000 bootstrap-trekk av selskap.

| Skår | Areal under PR-kurven | Presisjon topp 1 prosent | Presisjon topp 5 prosent | Løft topp 1 prosent | Areal under ROC |
|---|---|---|---|---|---|
| Kalibrert sannsynlighet | 0,47 (0,42 til 0,51) | 0,32 (0,28 til 0,36) | 0,09 | 57 | 0,95 |
| Regelbasert referanse | 0,007 (0,006 til 0,009) | 0,007 (0,002 til 0,013) | 0,007 | 1,3 | 0,57 |
| Isolation Forest | 0,009 (0,007 til 0,010) | 0,018 (0,010 til 0,028) | 0,013 | 3,2 | 0,60 |
| Robust Mahalanobis | 0,007 (0,006 til 0,009) | 0,006 (0,001 til 0,012) | 0,007 | 1,1 | 0,55 |

Den kalibrerte sannsynligheten ligger klart over grunnraten på alle mål. Blant de 1 prosent høyest rangerte fikk omtrent hvert tredje selskap utfallet. De tre avviksskårene ligger bare så vidt over grunnraten på 0,0056. Isolation Forest er den eneste med et tydelig løft blant de 1 prosent høyest rangerte, omtrent 3. For regelen og Mahalanobis-avstanden ligger grunnraten innenfor intervallet for presisjonen. Avviksskårene har altså en svak sammenheng med utfallet, og den er mye svakere enn for sannsynligheten. Dette er et svakt funn, og det står her som det er.

Figuren `topk` kan vise litt andre tall enn tabellen. Mange selskap har lik kalibrert sannsynlighet, og figuren og tabellen sorterer like verdier i ulik rekkefølge. Forskjellen er omtrent ett prosentpoeng i presisjon.

### Kalibrering

Brier-skåren er 0,0038 (0,0034 til 0,0042). En konstant prediksjon lik grunnraten ville gitt 0,0056. Forventet kalibreringsfeil er 0,0003. I tidelen med høyest predikert sannsynlighet er gjennomsnittlig prediksjon 4,9 prosent, og observert andel er 4,8 prosent. I de åtte laveste tidelene ligger både prediksjon og observasjon under 0,2 prosent. Kalibreringskurven er figuren `calibration`.

### Stabilitet

Over fem frø har den kalibrerte sannsynligheten en gjennomsnittlig Spearman-korrelasjon på 0,91 og 80 prosent overlapp i topp 1 prosent. Isolation Forest er litt mer stabil over frø, med 0,97 og 87 prosent. Mellom øyeblikksbilde 1 og 2 er Spearman-korrelasjonen for sannsynligheten 0,999, og 99,9 prosent av topp 1 prosent er de samme selskapene. Sammenligningen gjelder de 433 943 selskapene som finnes i begge øyeblikksbildene. Regnskapene i øyeblikksbilde 2 er for det meste kopiert fra øyeblikksbilde 1, så høy stabilitet er ventet.

### Samsvar mellom skårene

Rangkorrelasjonen mellom den kalibrerte sannsynligheten og hver av avviksskårene er svakt negativ, mellom minus 0,09 og minus 0,22. Overlappet i topp 1 prosent er 1 til 2 prosent, og i topp 5 prosent 6 til 7 prosent. Det er lite mer enn det tilfeldighet gir. Selskapene som er mest uvanlige sammenlignet med gruppen sin, er altså ikke selskapene med høyest sannsynlighet for et registrert utfall. Hvorfor korrelasjonen er negativ, er ikke undersøkt.

### Ablasjoner

| Modell | Areal under PR-kurven | Presisjon topp 1 prosent | Brier-skår |
|---|---|---|---|
| Alle trekk | 0,47 | 0,32 | 0,0038 |
| Uten nettverkstrekk | 0,47 | 0,32 | 0,0038 |
| Uten teksttrekk | 0,47 | 0,32 | 0,0038 |
| Uten regnskapstrekk | 0,15 | 0,18 | 0,0051 |
| Bare register og roller | 0,12 | 0,16 | 0,0052 |

Regnskapstrekkene bærer det meste av signalet. Uten dem faller arealet under presisjon-gjenkallingskurven fra 0,47 til 0,15. En modell med bare register- og rolletrekk får 0,12. Det er likevel omtrent 20 ganger grunnraten, så register og roller har et eget signal. Nettverkstrekkene og teksttrekkene bidrar ikke målbart. Forskjellene mellom de tre øverste radene er mindre enn 0,01 og ligger godt innenfor konfidensintervallet.

### Forklaringer

De fire trekkene med størst gjennomsnittlig absolutt SHAP-verdi er hvor gammelt siste kjente regnskap er, antall kjente regnskapsår, næringskoden og hvor sent regnskapet ble levert. De seks neste er om selskapet har valgt bort revisjon, egenkapitalen, lengden på regnskapsperioden, om antall ansatte er registrert, om selskapet har revisor, og netto finansposter. For avviksskårene er det z-skårene for vekst i inntekter, rentebelastning og driftsmargin som skiller de høyest rangerte mest fra resten. Figuren `shap_summary` viser de femten øverste.

### Rettferdighet

Andelen flagget følger grunnraten for størrelse og stort sett for alder. To grupper flagges oftere enn presisjonen gir grunn til: selskap under to år, og overnatting og servering. Terskel per gruppe ble prøvd som mottiltak. Den jevner ut andelen flagget og koster lite i samlet presisjon, men den flagger også i grupper der nesten ingen får utfallet. Detaljene står i `rettferdighet.md`.

### Svake og negative funn

- Avviksskårene uten merkelapper har bare en svak sammenheng med utfallet, og lite samsvar med sannsynligheten.
- Nettverkstrekkene bidrar ikke målbart.
- Teksttrekkene bidrar ikke målbart.
- Blant de 1 prosent høyest rangerte får omtrent to av tre selskap ikke utfallet i vinduet. Presisjonen er 0,32, med et intervall fra 0,28 til 0,36.
- Selskap under to år flagges ofte, men får sjelden utfallet. Presisjonen i denne gruppen er omtrent en tredel av presisjonen i testdelen samlet.
- Det bakoverskuende designet mangler omtrent en firedel av de sanne positive. Tallene gjelder derfor et utvalg av utfallene.

### Avvik fra planen

Ingen avvik fra planen i del 1. Modellfamiliene, målene, frøet, inndelingen og trekkgruppene er som beskrevet. Setningsinnbyggingen som planen åpnet for, er ikke tatt i bruk. Teksttrekkene er bare TF-IDF-baserte.

Modellene ble først trent og evaluert på et stratifisert utvalg på omtrent 50 000 selskap. Inndelingen følger organisasjonsnummeret. Selskapene i testdelen av utvalget, omtrent 9 400, ligger derfor også i testdelen her og var brukt i en evaluering før. Hyperparametrene for modellen her ble valgt på nytt på valideringsdelen.
