# Rettferdighet

Dette dokumentet viser hvordan flaggene fra modellen fordeler seg på grupper av selskap, og hvor treffsikre flaggene er i hver gruppe. Gruppene er fylke, næringshovedområde, aldersbånd og størrelsesbånd. Målet er ikke at alle grupper skal flagges like ofte. Målet er at forskjellene skal være kjent, forklart og vurdert. Grupper med færre enn 20 selskap vises ikke.

## Hva som måles

For hver gruppe vises fire tall fra testdelen. **Antall selskap** er antallet i gruppen. **Grunnrate** er andelen selskap i gruppen som fikk det strenge utfallet i vinduet. **Andel flagget** er andelen av gruppen som er blant de 5 prosent høyest rangerte i hele testdelen, med én felles terskel. **Presisjon** er andelen av de flaggede i gruppen som fikk utfallet.

Tallene regnes ut for den kalibrerte sannsynligheten og for Isolation Forest. De skrives til tabellen `monitoring.fairness` for hver trening. Figuren for rettferdighet bygges fra den tabellen.

## Funn

Tallene er fra hovedmodellen, som er trent på hele populasjonen. Testdelen har omtrent 82 000 selskap og 462 positive. Samlet presisjon blant de flaggede er 8,9 prosent.

| Gruppe | Andel flagget, laveste til høyeste | Grunnrate, laveste til høyeste | Hva tallene viser |
|---|---|---|---|
| Størrelsesbånd | 0,7 til 7,6 prosent | 0,1 til 0,9 prosent | Andelen flagget følger grunnraten. Små selskap flagges oftest og har flest utfall. Store selskap flagges sjeldnest og har færrest |
| Aldersbånd | 2,3 til 8,6 prosent | 0,3 til 1,1 prosent | Selskap mellom to og fem år flagges oftest og har høyest grunnrate. Selskap over ti år flagges sjeldnest og har lavest. Selskap under to år flagges nesten like ofte som selskap mellom to og fem år, men grunnraten er under halvparten |
| Næringshovedområde | 0 til 27 prosent | 0 til 1,7 prosent | Overnatting og servering har høyest grunnrate og flagges oftest av alle, over fem ganger så ofte som gjennomsnittet. Presisjonen der er under gjennomsnittet. Bygg og anlegg og transport og lagring flagges omtrent to og en halv gang så ofte som gjennomsnittet. Presisjonen der er på eller over gjennomsnittet |
| Fylke | 3,1 til 6,1 prosent | 0,3 til 0,8 prosent | Forskjellene mellom fylkene er små sammenlignet med forskjellene mellom næringer. Oslo flagges oftest. De minste fylkene har bare noen få positive, så presisjonen der kan ikke skilles fra tilfeldig variasjon. Svalbard har omtrent 50 selskap i testdelen og ingen utfall, og er holdt utenfor tallene i denne raden |

To mønstre står igjen når vi tar hensyn til tilfeldig variasjon.

**Modellen flagger der utfallene er.** For størrelse går andel flagget og grunnrate i takt, og for alder gjør de det stort sett. Det er som ventet for en modell som er trent på utfallet. Det betyr at små selskap og selskap mellom to og fem år får en større del av flaggene enn andelen deres i populasjonen skulle gi.

**Noen grupper flagges oftere enn grunnraten skulle gi.** Overnatting og servering er det klareste eksempelet. Næringen har høyest grunnrate, men mer enn hvert fjerde selskap flagges, og presisjonen er lavere enn i testdelen samlet. Selskap under to år er det andre eksempelet. De flagges nesten like ofte som selskap mellom to og fem år, men presisjonen er omtrent en tredel. Næringskoden er blant de viktigste trekkene i modellen. En del av flaggene i slike grupper kommer derfor fra gruppen selv, ikke fra tallene til selskapet.

Isolation Forest bruker ikke utfallet og fordeler flaggene annerledes. Den flagger store selskap og små næringer oftest, fordi de er sjeldne i dataene. I den største tidelen flagges 28 prosent av selskapene. Presisjonen er lav i alle grupper, omtrent 1 prosent samlet. Det viser at «uvanlig» og «høy sannsynlighet for utfall» er to forskjellige spørsmål.

## Mottiltak som er prøvd

Planen krever at minst ett mottiltak prøves. Mottiltaket er en terskel per gruppe: de 5 prosent høyest rangerte i hver gruppe flagges, i stedet for de 5 prosent høyest rangerte i hele testdelen. Da får alle grupper alltid samme andel flagget.

Virkningen på presisjonen går begge veier. I næringer med høy grunnrate, som overnatting og servering, bygg og anlegg og transport og lagring, stiger presisjonen fra mellom 6 og 11 prosent til omtrent 21 prosent. Der fjernes flaggene med lavest sannsynlighet. I grupper med lav grunnrate, som store selskap, gamle selskap og eiendomsvirksomhet, faller presisjonen. Flaggene flyttes til selskap med lav sannsynlighet. I den største tidelen faller presisjonen fra 13 til under 3 prosent. Samlet flyttes flagg fra grupper med mange utfall til grupper med få.

Den samlede presisjonen faller lite. Med terskel per næringshovedområde faller den fra 8,9 til 8,6 prosent. Med terskel per fylke, aldersbånd eller størrelsesbånd er fallet under 0,1 prosentpoeng.

Mottiltaket er likevel ikke tatt i bruk i skåringen. En terskel per gruppe flagger 5 prosent også i grupper der nesten ingen får utfallet. I finansiell tjenesteyting er grunnraten under 0,1 prosent, og ingen av de flaggede der fikk utfallet. Når grunnratene virkelig er forskjellige, kan man ikke få lik andel flagget og lik presisjon samtidig. Prosjektet velger én felles terskel og viser forskjellene åpent. Valget er ikke opplagt, siden kostnaden i samlet presisjon er liten. Begge varianter ligger i tabellen `monitoring.fairness`, med en kolonne som sier hvilken terskel som er brukt.

## Begrensninger

Grunnratene er lave, og antall positive er lite i de minste gruppene. Det gjelder særlig små fylker og små næringer. Der er konfidensintervallene for presisjon brede, og forskjeller mellom enkeltgrupper betyr lite. Tallene gjelder det bakoverskuende designet. De oppdateres når framoverskuende utfall er observert for flere øyeblikksbilder.
