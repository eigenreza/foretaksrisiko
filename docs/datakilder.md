<!-- privacy-scan: allow-person-fields -->
# Datakilder

Prosjektet bruker bare åpne data. All nedlasting og all filtrering skjer lokalt. Bare opplysninger på selskapsnivå om aksjeselskap (AS) og allmennaksjeselskap (ASA) går videre til lakehouset. Denne siden beskriver hver kilde: hvilke felt som brukes, hva som filtreres bort, og hvorfor.

## Enhetsregisteret

Kilde: Brønnøysundregistrene, åpne data fra Enhetsregisteret. Lisens: Norsk lisens for offentlige data (NLOD) 2.0.

### Hovedenheter

Hele bestanden lastes ned som en komprimert JSON-fil. Filen leses som en strøm, ett selskap om gangen. Bare enheter med organisasjonsform AS eller ASA beholdes. Alle andre organisasjonsformer fjernes i minnet og skrives aldri til disk. Enheter som er registrert i Frivillighetsregisteret, fjernes også. Det samme gjelder enheter som er merket som slettet.

Felt som beholdes, gruppert etter bruk:

| Bruk | Felt |
|---|---|
| Nøkkel og omfang | organisasjonsnummer, organisasjonsform, registrertIFrivillighetsregisteret |
| Alder | registreringsdatoEnhetsregisteret, stiftelsesdato, vedtektsdato |
| Kapital | kapital (beløp, antall aksjer, type, valuta, innbetalt, fullt innbetalt, dato) |
| Størrelse | antallAnsatte, harRegistrertAntallAnsatte, registreringsdato for ansatte |
| Næring og sektor | naeringskode1, naeringskode2, naeringskode3, hjelpeenhetskode, institusjonellSektorkode |
| Geografi | kommunenummer, postnummer og landkode fra forretningsadressen, kommunenummer fra postadressen |
| Registerstatus | registrering i Mva-registeret, Foretaksregisteret, Stiftelsesregisteret og Partiregisteret, med datoer |
| Utfall | konkurs og konkursdato, underAvvikling og dato, underTvangsavviklingEllerTvangsopplosning, datoer for tvangsavvikling og tvangsoppløsning med årsak, dato for rekonstruksjon og for utenlandsk insolvensbehandling |
| Revisjon og regnskap | fravalgRevisjonDato, fravalgRevisjonBeslutningsDato, sisteInnsendteAarsregnskap |
| Annet | erIKonsern, maalform, antall tidligere navn, antall påtegninger og typer påtegninger |
| Gjort om til ja/nei | hjemmeside, e-postadresse, telefon og mobil blir bare til flaggene har_hjemmeside, har_epostadresse og har_telefon |
| Fritekst | vedtektsfestetFormaal og aktivitet lagres i en egen lokal tabell. Teksten publiseres aldri |

Felt som fjernes: selskapets navn, gateadresser, kontaktopplysninger, felt om registrering i utlandet, og overordnet enhet i offentlig sektor.

### Underenheter

Underenheter lastes ned på samme måte. Bare underenheter som hører til en beholdt hovedenhet, skrives til disk. Felt som beholdes: organisasjonsnummer, overordnet enhet, næringskode, kommunenummer, postnummer og landkode for beliggenhetsadressen, antall ansatte, Mva-status, registreringsdato, oppstartsdato, dato for nedleggelse og dato for eierskifte. Navn og gateadresser fjernes.

### Roller

Filen med alle roller inneholder navn og fødselsdato for personer. Filen leses direkte fra nettet og skrives aldri til disk. For hvert selskap i populasjonen leses rollene i minnet og gjøres straks om til tall og flagg. Personfelt brukes bare til to ting innenfor ett selskap: å telle hvor mange ulike personer som har roller, og å avgjøre om daglig leder også er styreleder. Resultatet er et tall og et ja eller nei. Ingen personopplysninger skrives, logges eller lagres. Det lages ingen identifikator for personer, verken åpen eller hashet.

Verdier per selskap: antall rollegrupper og roller, antall i styret (styreleder, nestleder og styremedlemmer), antall varamedlemmer og observatører, og om selskapet har daglig leder, styreleder, revisor, regnskapsfører og kontaktperson. I tillegg kommer om daglig leder er styreleder, antall roller valgt av en gruppe, antall personer og ulike personer med roller, antall avsluttede roller, antall organisasjoner med roller, og dato for siste endring per rollegruppe.

Organisasjoner med roller, for eksempel revisjonsselskap og regnskapsførerselskap, beholdes med organisasjonsnummer bare når de selv er AS eller ASA i populasjonen. Da lagres en kobling mellom de to selskapene, med rolletype og status for godkjenning. Alle andre organisasjoner med roller blir bare telt.

Roller for enheter utenfor populasjonen, for eksempel enkeltpersonforetak, hoppes over helt.

### Oppdateringer

Enhetsregisteret publiserer endringshendelser for enheter, underenheter og roller. Mellom to øyeblikksbilder hentes hendelsene for selskapene i populasjonen. De gjøres om til antall hendelser per selskap og type endring, med første og siste tidspunkt. Hendelser av typen Fjernet brukes som datoen for når en enhet forsvant fra de åpne dataene. Dermed kan utfall regnes riktig også for selskap som senere slettes.

### Konsernstruktur

Enhetsregisteret har et endepunkt som gir konsernstrukturen for ett selskap om gangen. Det er ikke tatt i bruk. Nettverkstrekkene bygger på koblingene til revisjonsselskap og regnskapsførerselskap fra rolledataene. Begge sider i en kobling er AS eller ASA i populasjonen.

## Regnskapsregisteret

Kilde: Brønnøysundregistrene, åpent API for nøkkeltall fra årsregnskap. Lisens: NLOD 2.0.

API-et gir ett svar per organisasjonsnummer. Svaret er en liste med inntil tre regnskapsår. Hvert år er merket som selskapsregnskap eller konsernregnskap. Svaret har ingen dato for innsending, så forsinkelse kan ikke måles direkte fra denne kilden. Året for siste innsendte årsregnskap finnes derimot i Enhetsregisteret.

Felt som beholdes: type regnskap, regnskapsperiode, valuta, om det er et avviklingsregnskap, oppstillingsplan, flagg for revisjon, regnskapsprinsipper, flagg for morselskap, og alle sumposter for egenkapital og gjeld, eiendeler og resultat. Ett felt er stavet feil i kilden (sumInnskuttEgenkaptial). Koden leser både den stavemåten og den riktige.

Henting skjer med ett kall per selskap, høyst fire kall i sekundet. Henteren kan stoppes og startes igjen uten å hente samme selskap to ganger. Først ble et stratifisert utvalg på omtrent 50 000 selskap hentet, trukket etter næringshovedområde og fylke. Dette utvalget ble brukt under utviklingen. Deretter ble hele populasjonen hentet.

I øyeblikksbilde 1 har 400 587 av 434 074 selskap minst ett regnskap i registeret. 33 332 selskap har ingen regnskap der. For 155 selskap ga API-et en serverfeil ved hvert forsøk. Disse selskapene regnes som selskap uten tilgjengelig regnskap. De er 0,04 prosent av populasjonen.

To forhold i regnskapsdataene er verdt å kjenne til. Noen få regnskap har en periode som begynner og slutter samme dag. Begge datoene regnes med, så perioden er én dag lang og gyldig. Omtrent 0,2 prosent av regnskapene har negativ sum eiendeler i registeret. Radene beholdes, og kvalitetskontrollen gir en advarsel.

Fra og med øyeblikksbilde 2 kopieres svarene fra forrige øyeblikksbilde. Et selskap som hadde et endelig svar, enten regnskap eller ingen regnskap, får svaret kopiert, med en merknad om hvilket øyeblikksbilde det kom fra. Tre grupper hentes på nytt: nye selskap, selskap der registeret viser en ny innsending siden sist, og en tiendedel av populasjonen. Tiendedelen velges med en hash av organisasjonsnummeret. Hele bestanden er dermed oppdatert etter ti øyeblikksbilder. I øyeblikksbilde 2 ble svarene for omtrent 390 500 selskap kopiert, og omtrent 43 600 selskap ble hentet på nytt.

## Kodelister fra SSB

Kilde: Statistisk sentralbyrå, Klass. Lisens: Creative Commons Navngivelse 4.0 Internasjonal (CC BY 4.0).

| Kodeliste | Bruk |
|---|---|
| Standard for næringsgruppering, SN2007 | Eldre næringskoder og beskrivelser |
| Standard for næringsgruppering, SN2025 | Gjeldende næringskoder og beskrivelser, også til tekstlikheten i modellen |
| Korrespondansetabell SN2025 til SN2007 | Kobling mellom standardene i begge retninger |
| Fylkesinndeling | Fylkesnavn. De to første sifrene i kommunenummeret er fylkesnummeret |
| Kommuneinndeling | Kommunenavn, med korrespondanse til forrige inndeling |

Næringskodene gikk over fra SN2007 til SN2025. Tabellen som kobler de to standardene, er ikke en-til-en i noen retning. Mange SN2007-koder er delt på flere SN2025-koder, og mange SN2025-koder samler flere SN2007-koder. Prosjektet løser det slik: hvert selskap får næringshovedområde og næringskode etter SN2025, som er standarden registeret bruker nå. Når en kode må oversettes og har flere mulige motparter, velges den motparten som deler flest siffer med kilden. Selskapet merkes da med at oversettelsen er usikker. Tekstene som brukes i tekstlikheten, hentes alltid fra samme standard som selskapets kode.

## Hva som er filtrert bort, og hvorfor

| Filtrert bort | Hvorfor |
|---|---|
| Enkeltpersonforetak og alle andre organisasjonsformer enn AS og ASA | Et enkeltpersonforetak er en person, og navnet inneholder eierens etternavn. Andre former er utenfor formålet |
| Enheter i Frivillighetsregisteret | Roller i frivillige organisasjoner skal ikke vises sammen med roller i næringslivet, jf. enhetsregisterloven § 9-1 |
| Navn, fødselsdato og alle andre personfelt | Personopplysninger. Bare tall og flagg på selskapsnivå beholdes |
| Navn, gateadresser og kontaktopplysninger for selskap | Trengs ikke i analysen, og holder publiserte resultater fri for detaljer som kan identifisere |
| Organisasjoner med roller som ikke er AS eller ASA i populasjonen | Beholdes bare som antall |

## Høflig bruk av API-ene

Koden sender høyst fire kall i sekundet. Ved feilkoder venter den med økende pause og litt tilfeldig variasjon. Den følger Retry-After og bruker en generisk User-Agent uten personlige opplysninger. Der det er mulig, laster den ned hele bestanden i stedet for å sende enkeltkall.

## Kreditering

Inneholder data under Norsk lisens for offentlige data (NLOD) 2.0, tilgjengeliggjort av Brønnøysundregistrene. Inneholder kodelister fra Statistisk sentralbyrå under CC BY 4.0. Ingen av kildene har godkjent eller står bak innholdet i dette prosjektet.
