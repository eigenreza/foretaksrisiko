<!-- privacy-scan: allow-person-fields -->
# Personvern

Prosjektet handler om selskap, ikke om personer. Opplysninger om aksjeselskap er ikke personopplysninger. Men to av kildene inneholder personopplysninger. Rolledataene i Enhetsregisteret har navn og fødselsdato for personer med roller. Og et enkeltpersonforetak er en person, med eierens etternavn i navnet. Denne siden forklarer hvordan prosjektet holder personopplysningene utenfor, fra nedlasting til publisering.

## Når personopplysninger er i bruk

Personopplysninger finnes bare i minnet på én lokal maskin, og bare i det korte øyeblikket hver enhet leses fra nettet.

**Roller.** Filen med alle roller leses direkte fra nettet. Den skrives aldri til disk, verken pakket eller upakket. Hvert selskap behandles for seg. Personfeltene brukes bare til to spørsmål om det ene selskapet: hvor mange ulike personer har roller, og er daglig leder også styreleder. Svarene er et tall og et ja eller nei. Etter det finnes bare tallene igjen.

**Enheter.** Filen med alle enheter leses også som en strøm. Alle andre organisasjonsformer enn AS og ASA fjernes i minnet før noe skrives. Ingen post om et enkeltpersonforetak lagres, i noen form.

**Endringer i roller.** Hendelsene gjøres om til antall per selskap og rollegruppe, med første og siste tidspunkt. Personfelt i hendelsene fjernes på samme måte.

Regnskapsregisteret gir bare nøkkeltall per selskap. Kodelistene fra SSB har ingen opplysninger om enkeltenheter. Ingen av dem inneholder personopplysninger.

## Bare det nødvendige beholdes

| Beholdes, per selskap | Fjernes |
|---|---|
| Antall i styret, varamedlemmer og observatører | Navn og fødselsdato |
| Om selskapet har daglig leder, styreleder, revisor, regnskapsfører og kontaktperson | Alle andre felt om personer |
| Om daglig leder er styreleder | Hvilke roller en bestemt person har |
| Antall personer og antall ulike personer med roller | Alle typer identifikator for personer, også hashet |
| Antall organisasjoner med roller | Selskapets navn, gateadresse og kontaktopplysninger |
| Organisasjonsnummer for revisjonsselskap og regnskapsførerselskap, men bare når de selv er AS eller ASA i populasjonen | Organisasjonsnummer for alle andre organisasjoner med roller |

Selskapets navn, adresse og kontaktopplysninger er ikke personopplysninger. Men analysen trenger dem ikke. Uten dem er det også vanskeligere å kjenne igjen et enkelt selskap i mellomresultater.

## Ingen kobling av personer

Prosjektet har ingen nøkkel for personer. Ingen tabell kan brukes til å finne rollene til en person, verken i ett selskap eller på tvers av selskap. Nettverkstrekkene i modellen bygger derfor bare på organisasjoner: hvilket revisjonsselskap eller regnskapsførerselskap et selskap bruker, og hvordan det går med de andre kundene til samme selskap. Begge sider i en slik kobling er aksjeselskap i populasjonen.

## Frivillige organisasjoner

Enhetsregisterloven § 9-1 sier at en persons rolle i en frivillig organisasjon ikke skal vises sammen med personens roller i næringslivet. Prosjektet løser dette enkelt: alle enheter som er registrert i Frivillighetsregisteret, fjernes mens enhetsfilen leses. Rollene deres leses aldri. Derfor kan en rolle i frivillig arbeid aldri møte en rolle i næringslivet noe sted i prosjektet.

## Ingen overføring av personopplysninger

All nedlasting og all filtrering skjer på én lokal maskin. Til lakehouset i Databricks lastes bare filtrerte filer på selskapsnivå: registeropplysninger om AS og ASA, tall og flagg fra rollene, koblinger mellom organisasjoner, regnskapstall og kodelister. Rådataene fra rollefilen finnes ikke på disk. Derfor kan de heller ikke lastes opp ved en feil.

## Ingen utdata om personer, og ingen offentlige utdata om enkeltselskap

Modellene gir en skår per selskap. Disse tabellene brukes til evaluering og overvåking. De finnes bare i lakehouset og i lokale mapper som ikke er med i kodelageret. De eksporteres ikke, og prosjektet lager ingen liste over selskap til noen.

Ingenting som publiseres, gjelder enkeltselskap. Kodelageret, README, dokumentene, figurene, demoen og demodataene inneholder bare tall for grupper på minst 20 selskap, mål for hele modellen, globale forklaringer og syntetiske eksempler. Grupper med færre enn 20 selskap slås sammen eller tas ut. Ingen organisasjonsnumre, navn, adresser, skårer for enkeltselskap eller fritekst fra registrene blir publisert. Testdataene er syntetiske. Organisasjonsnumrene i dem har feil kontrollsiffer, så de kan ikke tilhøre en ekte enhet.

## Automatiske kontroller

Reglene over er ikke bare beskrevet. De er også testet. Tester viser at enkeltpersonforetak og andre fjernede organisasjonsformer aldri kommer inn i en utdatafil. De viser også at personfelt aldri finnes i noen skrevet fil, og at offentlige filer ikke inneholder gyldige organisasjonsnumre.

En skanning av hele kodelageret feiler på nisifrede tall med gyldig kontrollsiffer, på kjente feltnavn for personopplysninger og på kalenderdatoer i offentlige filer. En stilskanning feiler på ord som ville gitt skårene en annen mening enn «uvanlig». Kontrollene kjøres sammen med de andre testene.

## Hva en skår betyr

En høy skår betyr «uvanlig sammenlignet med lignende selskap» eller «høyere sannsynlighet for et registrert utfall». Den sier ingenting om noen person. Den sier heller ikke at et selskap har gjort noe galt. Prosjektet er forskning og demonstrasjon. Det skal ikke brukes til beslutninger om virkelige selskap eller personer.
