# Metode

Dette dokumentet forklarer hvordan prosjektet går fra åpne registerdata til skårer. Det dekker innhenting og filtrering, lakehouset med tre lag, trekkene, utfallene og merkelappene, modellene og evalueringen. Datakildene står i `datakilder.md`, personvernet i `personvern.md`, evalueringsplanen i `valideringsrapport.md` og driften av modellen i `modellivssyklus.md`.

## Pipelinen steg for steg

1. **Innhenting på lokal maskin.** Filene med alle enheter, underenheter og roller leses direkte fra nettet, som strømmer. Bare aksjeselskap og allmennaksjeselskap som ikke står i Frivillighetsregisteret, beholdes. Roller gjøres om til tall og flagg i minnet. Deretter hentes endringshendelser for selskapene i populasjonen, regnskap for hvert selskap og kodelister fra SSB. Alt skrives som Parquet-filer i en egen mappe per øyeblikksbilde. Et manifest beskriver kilden, antall rader og hva som ble filtrert bort.
2. **Tekstlikhet på lokal maskin.** Selskapets formålstekst og beskrivelse av aktiviteten sammenlignes med den offisielle teksten for selskapets næringskode. Bare tallene går videre.
3. **Opplasting.** Filene lastes opp til et volum i Unity Catalog. De inneholder ingen personopplysninger.
4. **Bronse.** Filene lastes inn som de er, med nummer på øyeblikksbildet, dato og tidspunkt for innlasting. Hvert øyeblikksbilde skriver over sin egen del av tabellen. En kjøring kan derfor gjentas uten at data lagres dobbelt.
5. **Sølv.** Tabeller med riktige datatyper og uten duplikater. Her ligger også kodeverk for næring på både SN2007 og SN2025, fylker og kommuner, og en historikktabell. I historikktabellen har hver rad et intervall av øyeblikksbilder der raden gjelder.
6. **Gull.** Én bred rad per selskap per øyeblikksbilde, tabellen med utfall, merkelappene, trekkene, statistikk per sammenligningsgruppe og skårene.
7. **Modeller og overvåking.** Modellene trenes på gulltabellene. Kjøringene logges i MLflow, og modellen registreres i Unity Catalog. En planlagt jobb kjører steg 4 til 6 for hvert nytt øyeblikksbilde, skårer selskapene med hovedmodellen og skriver tabeller for overvåking.

Alt er skrevet i PySpark og Spark SQL på Delta-tabeller. Den samme koden kjører lokalt i testene, på syntetiske data, og på Databricks.

## Øyeblikksbilder

Et øyeblikksbilde er én full innhenting av registeret. Øyeblikksbildene nummereres 1, 2, 3 og så videre. Offentlig materiale viser bare til nummeret. Mellom to øyeblikksbilder hentes endringshendelsene for populasjonen. Dermed er historikken komplett også for selskap som senere forsvinner fra de åpne dataene. Regnskap kopieres fra forrige øyeblikksbilde for selskap som ikke har levert nytt årsregnskap. Nye selskap og selskap med ny innsending hentes på nytt. I tillegg hentes en tiendedel av populasjonen på nytt hver gang, etter tur. Hele bestanden blir dermed oppdatert i løpet av ti øyeblikksbilder.

## Datakvalitet

Hvert lag har kontroller. Resultatene skrives til tabellen `monitoring.quality_results`. Kontrollene sjekker at antall rader stemmer med manifestet og med laget før, og at tabellene har de kolonnene de skal ha. De sjekker at alle organisasjonsnumre har gyldig kontrollsiffer, at nok selskap har et gyldig næringshovedområde, og at nesten alle selskap kan kobles til fylke og kommune. De sjekker også at ingen datoer ligger i framtiden, og at historikktabellen har nøyaktig én gjeldende rad per selskap. Hvis en kontroll med nivå `error` feiler, stopper kjøringen. Kontroller med nivå `warn` skrives, men stopper ikke.

## Trekk

Alle trekk er på selskapsnivå. De regnes ut per øyeblikksbilde og design. Tabellen viser gruppene. De samme gruppene brukes i ablasjonene.

| Gruppe | Innhold |
|---|---|
| Register | Alder siden stiftelse og siden registrering, aksjekapital, antall ansatte og om tallet er registrert, næringshovedområde og næringskode etter SN2025, fylke, om postadressen er i en annen kommune, registrering i Mva-registeret og Foretaksregisteret, fravalg av revisjon, konsernflagg, antall tidligere navn og påtegninger, om selskapet har hjemmeside, e-post og telefon, målform, institusjonell sektor, antall underenheter, antall underenheter som åpnet og stengte siste år, og antall endringer av adresse, navn, næringskode og kapital siste halvår og siste år |
| Roller | Antall i styret (leder, nestleder, medlemmer, varamedlemmer og observatører), om selskapet har daglig leder, styreleder, revisor, regnskapsfører og kontaktperson, om daglig leder er styreleder, antall personer og antall ulike personer med roller, antall organisasjoner med roller, antall avsluttede roller, dager siden siste endring i styret og i ledelsen, og antall rollehendelser siste halvår og siste år |
| Nettverk | Hvor mange kunder revisjonsselskapet og regnskapsførerselskapet har i populasjonen, hvor stor andel av de andre kundene som fikk et utfall de siste to årene før referansetidspunktet, og om revisor står utenfor populasjonen |
| Regnskap | Sumtall fra siste kjente årsregnskap: driftsinntekter, driftsresultat, årsresultat, eiendeler, egenkapital, gjeld og finansposter, oppstillingsplan, revisjonsflagg og regnskapsregler, hvor gammelt regnskapet er og hvor sent det ble levert, antall kjente regnskapsår, sumtall fra året før, og nøkkeltall: egenkapitalandel, gjeldsgrad, driftsmargin, avkastning på eiendelene, likviditetsgrad, kontantandel, rentebelastning, vekst i inntekter og eiendeler, og flagg for negativ egenkapital, null inntekt og underskudd |
| Relative | Robuste z-skårer (median og MAD) og persentiler for nøkkeltallene, aksjekapital, alder og styrestørrelse, regnet innenfor sammenligningsgruppen, og antall ekstreme z-skårer |
| Tekst | Likhet mellom selskapets formålstekst og teksten for egen næringskode, likhet med den koden som passer best, rangering av egen kode, likhet med eget næringshovedområde, og lengden på teksten |

Sammenligningsgruppen er næringskode på tosifret nivå kombinert med størrelsesbånd. Størrelsesbåndene er kvartiler og øverste tidel av logaritmen av sum eiendeler. Selskap uten regnskap får et eget bånd. Hvis en gruppe har færre enn 20 selskap, brukes næringshovedområde og størrelsesbånd i stedet, og deretter bare størrelsesbånd.

Tekstlikheten regnes med TF-IDF over tegn-n-gram og kosinuslikhet, på den lokale maskinen. Planen åpnet også for en norsk setningsinnbyggingsmodell. Den er ikke brukt i denne versjonen. Ablasjonen uten teksttrekk viser at trekkene slik de er nå, ikke gir noen målbar forbedring.

### Maskering i det bakoverskuende designet

I det bakoverskuende designet ligger referansetidspunktet før øyeblikksbildet. Registeret viser verdiene slik de er nå, ikke slik de var da. Hvis endringsloggen viser at et felt ble endret etter referansetidspunktet, settes verdien til manglende, og en egen `masked_`-kolonne settes til sann. Dette gjelder antall ansatte, adresse, næringskode, kapital, Mva-registrering, konsernflagg, formålsteksten og hver rollegruppe. Regnskap brukes bare for regnskapsår som enten hadde passert fristen for innsending eller var levert før referansetidspunktet. `masked_`-kolonnene er aldri inndata til modellen. De styrer bare hvordan manglende verdier fylles ut. Ellers kunne mønsteret i hva som er maskert, lekke informasjon om utfallet.

## Utfall og merkelapper

Tabellen med utfall samler første kjente dato for konkurs, tvangsavvikling eller tvangsoppløsning, frivillig avvikling og rekonstruksjon per selskap. Den bygges fra alle øyeblikksbilder og alle endringshendelser. Derfor dekker den også selskap som senere slettes fra de åpne dataene.

Det strenge utfallet er konkurs, tvangsavvikling eller tvangsoppløsning innen seks måneder etter referansetidspunktet. Det brede utfallet tar også med frivillig avvikling. Det brede utfallet brukes bare til å sjekke hvor følsomme resultatene er. Et selskap er med bare hvis det var registrert ved referansetidspunktet og ikke allerede hadde et utfall.

Merkelappene regnes ut for to design.

**Bakoverskuende.** Referansetidspunktet er første dag i måneden seks måneder før øyeblikksbildet. Dette gir treningsdata allerede fra første øyeblikksbilde. Ulempen er at selskap som er slettet etter konkurs, mangler i de åpne dataene. Omtrent en firedel av de sanne positive i vinduet er derfor borte.

**Framoverskuende.** Referansetidspunktet er selve øyeblikksbildet. Utfallene kommer gjennom hendelsene i senere øyeblikksbilder, uten tap. Dette designet brukes til skåring i drift, til overvåking, og til hovedevalueringen når horisonten har gått ut.

Merkelappene regnes på nytt fra all kunnskap ved hver kjøring. En egen kolonne sier om hele vinduet har gått.

## Modeller

Selskapene deles i trening, validering og test med 60, 20 og 20 prosent. Delingen bruker en saltet hash av organisasjonsnummeret, så et selskap havner alltid i samme del. Maskerte verdier fylles med medianen eller den vanligste verdien fra treningsdelen. Kategoriske trekk får en egen kategori for manglende verdi.

| Modell | Hva den gjør |
|---|---|
| Regelbasert referanse | Teller relative z-skårer med absoluttverdi over 3. Største absolutte z-skår brukes som andre sorteringsnøkkel |
| Isolation Forest | 300 trær på inntil 50 000 tilfeldig valgte selskap, på alle numeriske trekk, uten merkelapper |
| Robust Mahalanobis | Z-skårene skaleres robust med median og kvartilavstand. Kovariansen regnes ut med Minimum Covariance Determinant på 20 000 selskap. Skåren er avstanden fra sentrum |
| Gradientforsterkede trær | Histogrambasert klassifikator på det strenge utfallet. Et lite rutenett av læringsrate, antall blader og minste bladstørrelse velges etter gjennomsnittlig presisjon på valideringsdelen, med tidlig stopp. Sannsynlighetene kalibreres med isotonisk regresjon på valideringsdelen |

De tre første gir en avviksskår. Den svarer på spørsmålet «hvor uvanlig er selskapet sammenlignet med gruppen sin». Den fjerde gir en kalibrert sannsynlighet for det strenge utfallet. Rapportene viser begge, og hvor godt de stemmer overens.

Trening og evaluering kjører som en jobb på Databricks. Hver kjøring logger parametre, nummer på øyeblikksbildet, versjonene av tabellene som ble brukt, alle mål og modellens signatur til MLflow. Den kalibrerte modellen registreres som utfordrer i Unity Catalog.

## Evaluering

Evalueringen følger planen i `valideringsrapport.md`. Planen ble skrevet ferdig før evalueringen ble kjørt.

For alle fire skårer måles arealet under presisjon-gjenkallingskurven, presisjon og løft blant de 1 og 5 prosent høyest rangerte, og arealet under ROC-kurven. For sannsynlighetene måles også Brier-skår, en kalibreringskurve med ti grupper og forventet kalibreringsfeil. Hovedmålene får 95 prosent konfidensintervall fra 1 000 bootstrap-trekk av selskap.

Stabiliteten i rangeringen måles over fem frø, som Spearman-korrelasjon og overlapp i topp 1 prosent. Samsvaret mellom sannsynligheten og hver avviksskår måles også. Ablasjonene trener modellen uten nettverkstrekk, uten regnskapstrekk og uten teksttrekk, og med bare register- og rolletrekk.

De globale forklaringene er gjennomsnittlig absolutt SHAP-verdi per trekk for trærne. For avviksskårene brukes gjennomsnittlig absolutt z-skår blant de høyest rangerte, delt på det samme tallet for hele testdelen.

Andel flagget og presisjon regnes ut per fylke, næringshovedområde, aldersbånd og størrelsesbånd. Grupper under 20 selskap tas ut. En terskel per gruppe prøves som mottiltak.

Resultatene skrives til tabeller i skjemaet `monitoring` og til MLflow. Alle figurer bygges fra disse tabellene av et skript. Tallene i dokumentasjonen er hentet fra de samme filene med gruppetall i `demo_data/`.

## Valg underveis

Antall ansatte som nøyaktig tall brukes ikke i det bakoverskuende designet. Feltet er nesten alltid maskert der. Flagget for registrerte ansatte og størrelsesbåndet brukes i stedet.

Setningsinnbygging for tekst er ikke tatt i bruk. Tekstlikheten bygger på tegn-n-gram. Konsernstrukturen fra registeret er heller ikke brukt som nettverkstrekk. Nettverket består av koblinger til revisjonsselskap og regnskapsførerselskap.

Regnskap ble først hentet for et stratifisert utvalg på omtrent 50 000 selskap, trukket etter næringshovedområde og fylke. Den første versjonen av modellen ble trent på dette utvalget. Deretter ble regnskap hentet for hele populasjonen. Gjeldende hovedmodell er trent på alle kvalifiserte selskap.
