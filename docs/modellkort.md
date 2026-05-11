# Modellkort

Dette modellkortet beskriver modellene i foretaksrisiko: hva de er laget for, hva de er trent på, hvor godt de virker, og hvor de ikke skal brukes. Tallene kommer fra evalueringen mot planen i `valideringsrapport.md`. Fordelingen på grupper står i `rettferdighet.md`.

## Formål

Modellene rangerer norske aksjeselskap og allmennaksjeselskap etter to spørsmål. Det første er hvor uvanlig selskapet er sammenlignet med lignende selskap i samme næring og størrelsesbånd. Tre avviksskårer uten merkelapper svarer på dette. Det andre er hvor sannsynlig det er at selskapet får et registrert utfall innen seks måneder. Utfallet er konkurs, tvangsavvikling eller tvangsoppløsning. Én kalibrert sannsynlighet svarer på dette.

En høy skår betyr «uvanlig» eller «høyere sannsynlighet for et registrert utfall». Den betyr ikke at selskapet har gjort noe galt.

## Hva modellene skal brukes til

Modellene er laget for forskning og demonstrasjon. De viser hva åpne registerdata kan og ikke kan si om uvanlige mønstre, og de viser en komplett modellivssyklus. De skal ikke brukes til beslutninger om virkelige selskap eller personer, verken om kreditt, tilsyn, kontroll eller kontrakter. Prosjektet publiserer ingen skårer for enkeltselskap og lager ingen liste over selskap til noen.

## Modellene

| Navn i tabellene | Type | Inndata | Utdata |
|---|---|---|---|
| `rule` | Regel | Relative z-skårer | Antall ekstreme z-skårer |
| `isolation_forest` | Isolation Forest | Alle numeriske trekk | Avviksskår |
| `mahalanobis` | Robust Mahalanobis-avstand | Relative z-skårer | Avviksskår |
| `hgb_calibrated` | Histogrambaserte gradientforsterkede trær med isotonisk kalibrering | Alle trekk | Sannsynlighet for det strenge utfallet |

Den kalibrerte modellen registreres i Unity Catalog og brukes til skåring i drift. Modellen med alias `champion` er den gjeldende hovedmodellen. Gjeldende hovedmodell er versjon 2. Den er trent på hele populasjonen i øyeblikksbilde 1 og ble forfremmet etter regelen i `modellivssyklus.md`. Versjon 1 var trent på et stratifisert utvalg på omtrent 50 000 selskap.

## Data

Populasjonen er alle aksjeselskap og allmennaksjeselskap i Enhetsregisteret ved et øyeblikksbilde, unntatt enheter i Frivillighetsregisteret. Trekkene er beskrevet i `metode.md`. Alle er på selskapsnivå: register, roller som tall, nettverk mellom organisasjoner, regnskap, relative skårer og tekstlikhet. Ingen personopplysninger er med.

Modellene er trent på det bakoverskuende designet fra øyeblikksbilde 1. Der ligger referansetidspunktet seks måneder før øyeblikksbildet. Selskapene er delt i trening, validering og test med 60, 20 og 20 prosent, på selskapsnivå. Hyperparametrene ble valgt på valideringsdelen. Kalibreringen ble gjort på valideringsdelen. Testdelen ble brukt én gang for denne modellen.

Omtrent 412 000 selskap er kvalifisert i dette designet, og 2 197 av dem har det strenge utfallet. Omtrent 90 prosent av selskapene hadde minst ett regnskap ved referansetidspunktet.

## Ytelse

Testdelen har omtrent 82 000 selskap og 462 positive. Grunnraten er 0,56 prosent. Intervallene er 95 prosent konfidensintervall fra 1 000 bootstrap-trekk av selskap.

| Mål, kalibrert sannsynlighet | Verdi | Intervall |
|---|---|---|
| Areal under presisjon-gjenkallingskurven | 0,47 | 0,42 til 0,51 |
| Presisjon blant de 1 prosent høyest rangerte | 0,32 | 0,28 til 0,36 |
| Presisjon blant de 5 prosent høyest rangerte | 0,09 | |
| Løft blant de 1 prosent høyest rangerte | 57 | |
| Løft blant de 5 prosent høyest rangerte | 16 | |
| Areal under ROC-kurven | 0,95 | |
| Brier-skår | 0,0038 | 0,0034 til 0,0042 |
| Forventet kalibreringsfeil | 0,0003 | |

Kalibreringen er god. I tidelen med høyest predikert sannsynlighet er den observerte andelen utfall nær den predikerte. I de laveste tidelene ligger begge nær null. Rangeringen er stabil over frø: Spearman-korrelasjonen er omtrent 0,91, og omtrent 80 prosent av topp 1 prosent er de samme selskapene.

Avviksskårene treffer utfallet bare så vidt. Arealet under presisjon-gjenkallingskurven er 0,007 til 0,009 for de tre skårene, mot en grunnrate på 0,006. Isolation Forest er den beste av dem, med et løft på omtrent 3 blant de 1 prosent høyest rangerte. Den kalibrerte sannsynligheten har et løft på 57. Sammenhengen mellom sannsynligheten og avviksskårene er også svak. Rangkorrelasjonen er svakt negativ, og overlappet i toppen er lite større enn det tilfeldighet gir. Det betyr at «uvanlig sammenlignet med gruppen» og «sannsynlig utfall i registeret» i praksis er to forskjellige egenskaper ved et selskap. Avviksskårene må derfor vurderes for seg, ikke mot utfallet.

### Hva som driver sannsynligheten

Ablasjonene viser at regnskapstrekkene bærer det meste av signalet. Uten regnskap faller arealet under presisjon-gjenkallingskurven fra 0,47 til 0,15. En modell med bare register- og rolletrekk får 0,12. Det er likevel omtrent 20 ganger grunnraten, så opplysningene i registeret har et eget signal. Uten nettverkstrekk og uten teksttrekk endrer resultatet seg ikke målbart.

Trekkene med størst gjennomsnittlig betydning i SHAP-analysen er hvor gammelt siste kjente regnskap er, antall kjente regnskapsår, næringskoden og hvor sent regnskapet ble levert. Deretter følger om selskapet har valgt bort revisjon, egenkapitalen, lengden på regnskapsperioden, om antall ansatte er registrert, og om selskapet har revisor. Flere av disse måler om selskapet leverer regnskap i tide. Det henger tett sammen med tvangsoppløsning på grunn av manglende regnskap. Forklaringene er globale. Ingen forklaringer for enkeltselskap publiseres.

### Rettferdighet

Andelen som flagges, følger grunnraten for størrelse og stort sett for alder. To grupper flagges oftere enn presisjonen gir grunn til: selskap under to år, og overnatting og servering. En terskel per gruppe ble prøvd som mottiltak. Den jevner ut andelen flagget, men den flagger også i grupper der nesten ingen får utfallet. Detaljene står i `rettferdighet.md`.

## Begrensninger

Det bakoverskuende designet mangler omtrent en firedel av de sanne positive, fordi selskap slettes fra de åpne dataene etter konkurs. Tallene over gjelder derfor et utvalg av de positive. Den framoverskuende evalueringen kommer når horisonten har gått ut.

Utfallet er en hendelse i registeret, ikke økonomisk virkelighet. Mange tvangsoppløsninger skyldes manglende regnskap eller manglende revisor. Modellen lærer i stor grad å kjenne igjen selskap som er på vei ut av registeret.

Grunnraten er lav. Testdelen har 462 positive, og valideringsdelen har 448. Små forskjeller mellom modeller betyr lite.

Modellen bruker næringskode og fylke som trekk. En del av flaggingen kommer derfor fra næringen og stedet, ikke fra selskapet selv. Regnskap finnes bare for selskap som har levert. Omtrent 8 prosent av selskapene i øyeblikksbilde 1 har ingen regnskap i kilden. Selskap uten regnskap får et eget størrelsesbånd og manglende verdier i regnskapstrekkene. Tekstlikheten bygger på tegn-n-gram og gir ingen målbar forbedring.

Skårene gjelder øyeblikksbildet de er regnet ut for. Drift overvåkes, og modellen trenes på nytt etter reglene i `modellivssyklus.md`.

## Lisens og kilder

Modellene er trent på åpne data fra Brønnøysundregistrene under NLOD 2.0 og på kodelister fra Statistisk sentralbyrå under CC BY 4.0. Koden er lisensiert under MIT.
