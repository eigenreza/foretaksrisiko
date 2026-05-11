"""All text in the demo, in Norwegian bokmål ("no") and English ("en"), plus number formats.

Model, feature and metric names come from ``foretaksrisiko.figures.labels`` so that the demo
and the figures use the same words. The privacy page names the person fields that the project
discards, so this file carries the marker privacy-scan: allow-person-fields.
"""

from __future__ import annotations

LANGUAGE_NAMES = {"no": "Norsk", "en": "English"}
PAGE_KEYS = ("oversikt", "prov_selv", "monstre", "modellen", "overvaking", "personvern")

TEXT: dict[str, dict[str, str]] = {
    # Navigation
    "nav.title": {"no": "Sider", "en": "Pages"},
    "nav.language": {"no": "Språk", "en": "Language"},
    "nav.oversikt": {"no": "Oversikt", "en": "Overview"},
    "nav.monstre": {"no": "Mønstre i registeret", "en": "Patterns in the register"},
    "nav.modellen": {"no": "Modellen", "en": "The model"},
    "nav.prov_selv": {"no": "Prøv selv", "en": "Try it yourself"},
    "nav.overvaking": {"no": "Overvåking", "en": "Monitoring"},
    "nav.personvern": {"no": "Personvern og metode", "en": "Privacy and method"},
    "nav.note": {
        "no": "Alle tall gjelder grupper på minst 20 selskap. Ingen enkeltselskap vises.",
        "en": "All numbers are for groups of at least 20 companies. No single company is shown.",
    },
    "nav.author": {"no": "Laget av Reza Azad Gholami", "en": "Made by Reza Azad Gholami"},
    "nav.repo": {
        "no": "Kode og dokumentasjon: "
        "[github.com/eigenreza/foretaksrisiko](https://github.com/eigenreza/foretaksrisiko)",
        "en": "Code and documentation: "
        "[github.com/eigenreza/foretaksrisiko](https://github.com/eigenreza/foretaksrisiko)",
    },
    "common.missing": {
        "no": "Denne filen er ikke eksportert ennå.",
        "en": "This file has not been exported yet.",
    },
    "common.table": {"no": "Vis tallene som tabell", "en": "Show the numbers as a table"},
    "common.source": {
        "no": "Inneholder data under NLOD 2.0 fra Brønnøysundregistrene og kodelister fra "
        "Statistisk sentralbyrå under CC BY 4.0. Ingen av kildene står bak innholdet.",
        "en": "Contains data under NLOD 2.0 from the Brønnøysund Register Centre and code lists "
        "from Statistics Norway under CC BY 4.0. Neither source endorses the content.",
    },
    # Overview
    "oversikt.title": {"no": "foretaksrisiko", "en": "foretaksrisiko"},
    "oversikt.lead": {
        "no": "Her kan du se hva åpne registerdata kan fortelle om norske aksjeselskap (AS "
        "og ASA), og hva de ikke kan fortelle. Prosjektet leter etter selskap som er "
        "statistisk uvanlige. Det regner også ut hvor sannsynlig det er at et selskap "
        "får et registrert utfall, som konkurs eller tvangsoppløsning, innen seks "
        "måneder. Alt bygger på åpne data fra Brønnøysundregistrene.\n\nEn høy skår "
        "betyr «uvanlig sammenlignet med lignende selskap» eller «høyere sannsynlighet "
        "for et registrert utfall». Den betyr aldri at et selskap har gjort noe galt. "
        "Sidene viser bare tall for grupper, aldri for enkeltselskap.",
        "en": "This site shows what open register data can tell us about Norwegian limited "
        "companies (AS and ASA), and what it cannot. The project looks for companies "
        "that are statistically unusual. It also estimates how likely a company is to "
        "get a registered outcome, such as bankruptcy or forced dissolution, within "
        "six months. Everything builds on open data from the Brønnøysund Register "
        'Centre.\n\nA high score means "unusual compared with similar companies" or '
        '"higher probability of a registered outcome". It never means that a company '
        "did anything wrong. The pages show figures for groups only, never for single "
        "companies.",
    },
    "oversikt.try_title": {
        "no": "Start her: prøv selv",
        "en": "Start here: try it yourself",
    },
    "oversikt.try_text": {
        "no": "Den raskeste måten å forstå modellene på er å prøve dem. Sett sammen et "
        "oppdiktet selskap med næring, alder og regnskapstall. Du ser med en gang hvor "
        "uvanlig selskapet er, hvor sannsynlig et registrert utfall er, og hva som "
        "trekker skåren opp eller ned. Ingen virkelige selskap er med.",
        "en": "The quickest way to understand the models is to try them. Put together a "
        "made-up company with an industry, an age and some accounting figures. You see "
        "at once how unusual the company is, how likely a registered outcome is, and "
        "what pushes the score up or down. No real companies are involved.",
    },
    "oversikt.try_button": {
        "no": "Åpne Prøv selv",
        "en": "Open Try it yourself",
    },
    "oversikt.pages": {
        "no": "**Prøv selv** lar deg bygge et oppdiktet selskap og se skårene. **Mønstre i "
        "registeret** viser hvordan selskapene fordeler seg på næring, fylke og "
        "størrelse. **Modellen** viser hvor godt modellene treffer, og hvor de ikke "
        "gjør det. **Overvåking** viser hvordan dataene endrer seg fra ett "
        "øyeblikksbilde til det neste. **Personvern og metode** forklarer hvordan "
        "personopplysninger holdes utenfor.",
        "en": "**Try it yourself** lets you build a made-up company and see the scores. "
        "**Patterns in the register** shows how the companies are spread across "
        "industries, counties and sizes. **The model** shows how well the models hit, "
        "and where they do not. **Monitoring** shows how the data changes from one "
        "snapshot to the next. **Privacy and method** explains how personal data is "
        "kept out.",
    },
    "oversikt.what_title": {"no": "Hva prosjektet gjør", "en": "What the project does"},
    "oversikt.what": {
        "no": "Prosjektet henter hele bestanden fra Enhetsregisteret, endringshendelser, "
        "nøkkeltall fra Regnskapsregisteret og kodelister fra SSB. Bare AS og ASA er med, "
        "ingen frivillige organisasjoner og ingen personopplysninger.\n\n"
        "Dataene går inn i et lakehouse med tre lag på Databricks, med kvalitetskontroller "
        "per lag. Der regnes trekkene ut på selskapsnivå: register, roller som tall, nettverk "
        "mellom organisasjoner, regnskap, relative skårer og tekstlikhet.\n\n"
        "Modellene er tre avviksskårer uten merkelapper og én kalibrert sannsynlighet for et "
        "registrert utfall. Alt måles mot en plan som ble skrevet på forhånd.\n\n"
        "Modellen følges også opp etter treningen. Prosjektet har eksperimentlogg, "
        "modellregister med `champion` og `challenger`, regel for forfremmelse med manuell "
        "godkjenning, planlagt jobb, overvåking av drift og varsler.",
        "en": "The project fetches the full register of units, change events, key figures from "
        "the accounts register and code lists from Statistics Norway. Only AS and ASA are "
        "included, no voluntary organisations and no personal data.\n\n"
        "The data goes into a lakehouse with three layers on Databricks, with quality checks "
        "per layer. The features are computed there at company level: register, roles as "
        "counts, networks between organisations, accounts, relative scores and text "
        "similarity.\n\n"
        "The models are three anomaly scores trained without labels and one calibrated "
        "probability of a registered outcome. Everything is measured against a plan written "
        "in advance.\n\n"
        "The model is also followed up after training. The project has an experiment log, a "
        "model registry with `champion` and `challenger`, a promotion rule with manual "
        "approval, a scheduled job, drift monitoring and alerts.",
    },
    "oversikt.results_title": {"no": "Resultater i korte trekk", "en": "Results in brief"},
    "oversikt.results_text": {
        "no": "Tallene gjelder selskap som modellen aldri har sett under treningen. "
        "Gjennomsnittlig presisjon oppsummerer hvor godt modellen rangerer selskapene, "
        "fra 0 til 1. Presisjon i topp 1 prosent er andelen av de høyest rangerte "
        "selskapene som faktisk fikk utfallet. Løft sier hvor mange ganger oftere det "
        "er enn blant alle selskap. Brier-skåren måler hvor godt sannsynlighetene "
        "treffer. Der er lavere bedre.",
        "en": "The figures come from companies the model never saw during training. Average "
        "precision sums up how well the model ranks the companies, from 0 to 1. "
        "Precision in the top 1 percent is the share of the highest ranked companies "
        "that actually got the outcome. Lift says how many times more often that is "
        "than among all companies. The Brier score measures how well the probabilities "
        "hit. There, lower is better.",
    },
    "oversikt.results_note": {
        "no": "Målene gjelder den kalibrerte sannsynligheten på testdelen. Intervallene er "
        "95 prosent konfidensintervall fra bootstrap.",
        "en": "The measures apply to the calibrated probability on the test split. The "
        "intervals are 95 percent bootstrap confidence intervals.",
    },
    "oversikt.pipeline_title": {
        "no": "Fra lokal maskin til lakehouse",
        "en": "From local machine to lakehouse",
    },
    "oversikt.pipeline": {
        "no": "All nedlasting og all filtrering skjer på én lokal maskin. Der fjernes alt "
        "som ikke er AS eller ASA, og alle personopplysninger. Bare filtrerte filer på "
        "selskapsnivå lastes opp. Modellene trenes og skåres på Databricks, og "
        "resultatene som publiseres, gjelder bare grupper.",
        "en": "All downloading and filtering happens on one local machine. Everything that "
        "is not an AS or ASA is removed there, and so is all personal data. Only "
        "filtered, company-level files are uploaded. The models are trained and scored "
        "on Databricks, and the published results are for groups only.",
    },
    "oversikt.meaning_title": {"no": "Hva en skår betyr", "en": "What a score means"},
    "oversikt.meaning": {
        "no": "Modellene rangerer selskap etter to spørsmål. Hvor uvanlig er selskapet "
        "sammenlignet med lignende selskap i samme næring og størrelsesbånd? Og hvor sannsynlig "
        "er det at selskapet får et registrert utfall innen seks måneder, det vil si konkurs, "
        "tvangsavvikling eller tvangsoppløsning? Begge svarene er statistikk. De sier ingenting "
        "om hva et selskap har gjort, og prosjektet skal ikke brukes til beslutninger om "
        "virkelige selskap eller personer.",
        "en": "The models rank companies by two questions. How unusual is the company compared "
        "with similar companies in the same industry and size band? And how likely is a "
        "registered outcome within six months, that is bankruptcy, forced liquidation or forced "
        "dissolution? Both answers are statistics. They say nothing about what a company did, "
        "and the project must not be used for decisions about real companies or people.",
    },
    # Patterns
    "monstre.title": {"no": "Mønstre i registeret", "en": "Patterns in the register"},
    "monstre.lead": {
        "no": "Denne siden viser hvordan aksjeselskapene i Norge fordeler seg på næring, "
        "fylke og størrelse. Tallene gjelder alle aksjeselskap og allmennaksjeselskap "
        "i Enhetsregisteret ved det siste øyeblikksbildet, unntatt enheter i "
        "Frivillighetsregisteret. Du ser bare grupper. Grupper med færre enn 20 "
        "selskap er slått sammen eller tatt ut.",
        "en": "This page shows how Norwegian limited companies are spread across industries, "
        "counties and sizes. The figures cover every AS and ASA in the register of "
        "units at the latest snapshot, except units in the register of voluntary "
        "organisations. You see groups only. Groups with fewer than 20 companies are "
        "merged or removed.",
    },
    "monstre.section_title": {"no": "Etter næringshovedområde", "en": "By industry section"},
    "monstre.fylke_title": {"no": "Etter fylke", "en": "By county"},
    "monstre.base_title": {
        "no": "Grunnrate for utfallet per gruppe",
        "en": "Base rate of the outcome per group",
    },
    "monstre.base_text": {
        "no": "Grunnraten er andelen selskap i en gruppe som fikk et registrert utfall innen "
        "seks måneder etter referansetidspunktet. Den er målt på testdelen av "
        "øyeblikksbilde 1. Velg en gruppering under for å sammenligne. Små selskap og "
        "selskap mellom to og fem år har høyere grunnrate enn resten. Det er "
        "bakgrunnen du trenger når du leser skårene: noen grupper får oftere et utfall "
        "enn andre.",
        "en": "The base rate is the share of companies in a group that got a registered "
        "outcome within six months of the reference time. It is measured on the test "
        "split of snapshot 1. Pick a grouping below to compare. Small companies and "
        "companies between two and five years old have a higher base rate than the "
        "rest. That is the background you need when you read the scores: some groups "
        "get an outcome more often than others.",
    },
    "monstre.group_type": {"no": "Gruppering", "en": "Grouping"},
    "monstre.network_title": {
        "no": "Revisorer og regnskapsførere",
        "en": "Auditors and accountants",
    },
    "monstre.network_text": {
        "no": "Mange selskap deler revisor eller regnskapsfører. Figuren viser hvor mange "
        "selskap som bruker en revisor eller regnskapsfører med et gitt antall kunder "
        "blant aksjeselskapene. Noen få store aktører har svært mange kunder. Begge "
        "sider i koblingen er aksjeselskap. Prosjektet kobler aldri personer.",
        "en": "Many companies share an auditor or an accountant. The chart shows how many "
        "companies use an auditor or accountant with a given number of clients among "
        "the limited companies. A few large firms have very many clients. Both sides "
        "of the link are limited companies. The project never links people.",
    },
    "monstre.scores_title": {
        "no": "Fordelingen av skårene",
        "en": "The distribution of the scores",
    },
    "monstre.scores_text": {
        "no": "Kurvene viser hvordan hver skår fordeler seg på testdelen. Les dem fra "
        "venstre mot høyre: kurven viser hvilken skår selskapet på en gitt plass i "
        "rekken har. Avviksskårene har lange haler. Det betyr at noen få selskap "
        "ligger langt fra resten. Sannsynligheten er lav for nesten alle selskap, "
        "fordi grunnraten er omtrent en halv prosent. Det er omtrent ett av to hundre "
        "selskap.",
        "en": "The curves show how each score is spread across the test split. Read them "
        "from left to right: the curve gives the score of the company at a given place "
        "in the line. The anomaly scores have long tails, which means a few companies "
        "lie far from the rest. The probability is low for almost every company, "
        "because the base rate is about half a percent. That is roughly one company in "
        "two hundred.",
    },
    # Model
    "modellen.title": {"no": "Modellen", "en": "The model"},
    "modellen.lead": {
        "no": "Her ser du hvor godt modellene virker, og hvor de ikke virker. Prosjektet har "
        "én kalibrert sannsynlighet for et registrert utfall innen seks måneder, og "
        "tre avviksskårer uten merkelapper. Modellene er trent på det bakoverskuende "
        "designet fra øyeblikksbilde 1 og målt mot en plan som ble skrevet på forhånd. "
        "Testdelen er brukt én gang. Svake funn står her på lik linje med de sterke.",
        "en": "This page shows how well the models work, and where they do not. The project "
        "has one calibrated probability of a registered outcome within six months, and "
        "three anomaly scores trained without labels. The models are trained on the "
        "retrospective design from snapshot 1 and measured against a plan written in "
        "advance. The test split was used once. Weak findings are shown here on equal "
        "terms with the strong ones.",
    },
    "modellen.metrics_title": {"no": "Mål på testdelen", "en": "Measures on the test split"},
    "modellen.metrics_text": {
        "no": "Tabellen viser målene for alle fire skårer. Den kalibrerte sannsynligheten "
        "treffer klart best. Avviksskårene treffer utfallet bare så vidt: arealet "
        "under presisjon-gjenkallingskurven ligger like over grunnraten. Det er ikke "
        "en feil. Avviksskårene svarer på et annet spørsmål. «Uvanlig sammenlignet med "
        "gruppen» og «sannsynlig utfall» er i praksis to forskjellige egenskaper ved "
        "et selskap.",
        "en": "The table shows the measures for all four scores. The calibrated probability "
        "is clearly the best. The anomaly scores barely hit the outcome: their area "
        "under the precision-recall curve sits just above the base rate. That is not a "
        'fault. The anomaly scores answer a different question. "Unusual compared '
        'with the group" and "likely outcome" are in practice two different '
        "properties of a company.",
    },
    "modellen.col_metric": {"no": "Mål", "en": "Measure"},
    "modellen.col_model": {"no": "Modell", "en": "Model"},
    "modellen.col_value": {"no": "Verdi", "en": "Value"},
    "modellen.col_interval": {"no": "Intervall (95 %)", "en": "Interval (95%)"},
    "modellen.topk_title": {
        "no": "Presisjon og løft etter andel flagget",
        "en": "Precision and lift by share flagged",
    },
    "modellen.topk_text": {
        "no": "Tenk deg at du bare kan se nærmere på noen få selskap. Figurene viser hva som "
        "skjer når du velger de høyest rangerte. Flagger du de 1 prosent høyest "
        "rangerte, er presisjonen mange ganger grunnraten. Flagger du flere, faller "
        "presisjonen, og gjenkallingen stiger: du finner flere av utfallene, men flere "
        "av flaggene er feil.",
        "en": "Imagine you can only look closer at a few companies. The charts show what "
        "happens when you pick the highest ranked ones. If you flag the top 1 percent, "
        "the precision is many times the base rate. If you flag more, the precision "
        "falls and the recall rises: you find more of the outcomes, but more of the "
        "flags are wrong.",
    },
    "modellen.calibration_title": {"no": "Kalibrering", "en": "Calibration"},
    "modellen.calibration_text": {
        "no": "Kalibrering handler om at sannsynlighetene skal stemme. Hvis modellen sier 5 "
        "prosent for en gruppe selskap, skal omtrent 5 av 100 av dem få utfallet. "
        "Hvert punkt er en tidel av testdelen, sortert etter predikert sannsynlighet. "
        "Punkter nær den stiplede linjen betyr at sannsynlighetene kan leses som "
        "andeler.",
        "en": "Calibration is about the probabilities being right. If the model says 5 "
        "percent for a group of companies, about 5 in 100 of them should get the "
        "outcome. Each point is one tenth of the test split, sorted by predicted "
        "probability. Points near the dashed line mean the probabilities can be read "
        "as rates.",
    },
    "modellen.shap_title": {
        "no": "De viktigste trekkene",
        "en": "The most important features",
    },
    "modellen.shap_text": {
        "no": "Figuren viser hvilke trekk som betyr mest for sannsynligheten, målt som "
        "gjennomsnittlig absolutt SHAP-verdi på treningsdelen. Flere av de viktigste "
        "trekkene måler om selskapet leverer regnskap i tide. Det henger sammen med at "
        "mange tvangsoppløsninger skyldes manglende regnskap. Forklaringene gjelder "
        "hele modellen. Ingen forklaringer for virkelige enkeltselskap publiseres.",
        "en": "The chart shows which features matter most for the probability, measured as "
        "the mean absolute SHAP value on the training split. Several of the most "
        "important features measure whether the company files its accounts on time. "
        "That makes sense, because many forced dissolutions are caused by missing "
        "accounts. The explanations describe the model as a whole. No explanations for "
        "real single companies are published.",
    },
    "modellen.ablation_title": {"no": "Ablasjoner", "en": "Ablations"},
    "modellen.ablation_text": {
        "no": "Hva skjer hvis modellen mister en type opplysninger? Her er modellen trent på "
        "nytt uten én gruppe av trekk om gangen. Regnskapstrekkene bærer det meste av "
        "signalet. Nettverk og tekst endrer ikke resultatet målbart.",
        "en": "What happens if the model loses one kind of information? Here the model was "
        "retrained without one group of features at a time. The accounts features "
        "carry most of the signal. Network and text do not change the result "
        "measurably.",
    },
    "modellen.fairness_title": {
        "no": "Andel flagget og grunnrate per gruppe",
        "en": "Flag rate and base rate per group",
    },
    "modellen.fairness_text": {
        "no": "En modell kan flagge noen grupper oftere enn andre. Figuren viser om det "
        "følger grunnraten. Andelen flagget er andelen av gruppen som havner blant de "
        "5 prosent høyest rangerte. Når andelen flagget følger grunnraten, flagger "
        "modellen ikke gruppen oftere enn utfallene gir grunn til. Noen grupper "
        "flagges likevel oftere, for eksempel overnatting og servering og selskap "
        "under to år. En terskel per gruppe ble prøvd som mottiltak. Den flytter flagg "
        "fra grupper med mange utfall til grupper med få.",
        "en": "A model can flag some groups more often than others. The chart shows whether "
        "that follows the base rate. The flag rate is the share of the group that "
        "lands in the top 5 percent. When the flag rate follows the base rate, the "
        "model does not flag the group more often than the outcomes give reason for. "
        "Some groups are still flagged more often, for example accommodation and food "
        "service and companies under two years old. A per-group threshold was tried as "
        "a countermeasure. It moves flags from groups with many outcomes to groups "
        "with few.",
    },
    "modellen.fairness_model": {"no": "Modell", "en": "Model"},
    "modellen.fairness_threshold": {
        "no": "Vis mottiltaket med terskel per gruppe",
        "en": "Show the countermeasure with a per-group threshold",
    },
    # Try it yourself
    "prov.title": {"no": "Prøv selv", "en": "Try it yourself"},
    "prov.lead": {
        "no": "Her bygger du ditt eget oppdiktede selskap og ser hva modellene sier om det. "
        "Du trenger ingen forkunnskaper. Selskapet finnes bare i denne nettleserøkten. "
        "Ingen oppslag gjøres mot registrene, og ingen virkelige selskap kan slås opp.",
        "en": "Here you build your own made-up company and see what the models say about it. "
        "You need no background knowledge. The company exists only in this browser "
        "session. Nothing is looked up in the registers, and no real company can be "
        "looked up.",
    },
    "prov.how_title": {
        "no": "Slik gjør du",
        "en": "How to use it",
    },
    "prov.how": {
        "no": "Velg næring, alder og regnskapstall til venstre. Alt du ikke rører, har en "
        "typisk verdi: medianen eller den vanligste verdien i treningsdataene. Til "
        "høyre ser du resultatet med en gang.\n\nSannsynligheten svarer på hvor ofte "
        "selskap som ligner, får et registrert utfall innen seks måneder. Avviksskåren "
        "svarer på hvor uvanlig selskapet er sammenlignet med gruppen sin. De to "
        "følger ikke alltid hverandre.\n\nNoen ting å prøve: Gjør det siste regnskapet "
        "eldre, fjern regnskapet helt, eller gi selskapet negativ egenkapital. Da "
        "stiger sannsynligheten. Sett så en svært høy driftsmargin og sterk vekst. Da "
        "stiger avviksskåren mye, mens sannsynligheten endrer seg mindre.",
        "en": "Choose an industry, an age and some accounting figures on the left. "
        "Everything you leave alone has a typical value: the median or the most common "
        "value in the training data. The result appears at once on the right.\n\nThe "
        "probability answers how often companies like this one get a registered "
        "outcome within six months. The anomaly score answers how unusual the company "
        "is compared with its group. The two do not always move together.\n\nSome "
        "things to try: make the latest accounts older, remove the accounts "
        "altogether, or give the company negative equity. The probability goes up. "
        "Then set a very high operating margin and strong growth. The anomaly score "
        "rises a lot, while the probability changes less.",
    },
    "prov.missing": {
        "no": "Modellfilene for demoen mangler. Kjør `foretaksrisiko demo export` først.",
        "en": "The demo's model files are missing. Run `foretaksrisiko demo export` first.",
    },
    "prov.disclaimer": {
        "no": "Skårene gjelder et oppdiktet selskap og sier ingenting om noe virkelig selskap.",
        "en": "The scores apply to a made-up company and say nothing about any real company.",
    },
    "prov.group_register": {"no": "Register", "en": "Register"},
    "prov.group_roles": {"no": "Roller", "en": "Roles"},
    "prov.group_accounts": {"no": "Regnskap", "en": "Accounts"},
    "prov.reset": {"no": "Tilbake til et typisk selskap", "en": "Back to a typical company"},
    "prov.in.nace_division": {"no": "Næring (tosifret NACE)", "en": "Industry division"},
    "prov.in.fylke_code": {"no": "Fylke", "en": "County"},
    "prov.in.age_years": {"no": "Alder (år)", "en": "Age (years)"},
    "prov.in.share_capital": {"no": "Aksjekapital (kroner)", "en": "Share capital (NOK)"},
    "prov.in.registered_employees": {
        "no": "Antall ansatte er registrert",
        "en": "Employee count is registered",
    },
    "prov.in.registered_vat": {"no": "Registrert i MVA-registeret", "en": "Registered for VAT"},
    "prov.in.in_group": {"no": "Del av et konsern", "en": "Part of a group"},
    "prov.in.n_changes_12m": {
        "no": "Registerendringer siste 12 måneder",
        "en": "Register changes in the last 12 months",
    },
    "prov.in.board_size": {"no": "Styrestørrelse", "en": "Board size"},
    "prov.in.has_ceo": {"no": "Har daglig leder", "en": "Has a CEO"},
    "prov.in.ceo_is_chair": {
        "no": "Daglig leder er også styreleder",
        "en": "The CEO is also the chair",
    },
    "prov.in.has_auditor": {"no": "Har revisor", "en": "Has an auditor"},
    "prov.in.has_accountant": {"no": "Har regnskapsfører", "en": "Has an accountant"},
    "prov.in.n_role_events_12m": {
        "no": "Rolleendringer siste 12 måneder",
        "en": "Role changes in the last 12 months",
    },
    "prov.in.days_since_board_change": {
        "no": "Dager siden siste styreendring",
        "en": "Days since the last board change",
    },
    "prov.in.days_since_ceo_change": {
        "no": "Dager siden skifte av daglig leder",
        "en": "Days since the last CEO change",
    },
    "prov.in.has_accounts": {"no": "Har levert regnskap", "en": "Has filed accounts"},
    "prov.in.total_assets": {"no": "Sum eiendeler (kroner)", "en": "Total assets (NOK)"},
    "prov.in.revenue": {"no": "Driftsinntekter (kroner)", "en": "Operating income (NOK)"},
    "prov.in.equity_ratio": {"no": "Egenkapitalandel", "en": "Equity ratio"},
    "prov.in.operating_margin": {"no": "Driftsmargin", "en": "Operating margin"},
    "prov.in.current_ratio": {"no": "Likviditetsgrad", "en": "Current ratio"},
    "prov.in.cash_ratio": {"no": "Kontantandel av kortsiktig gjeld", "en": "Cash ratio"},
    "prov.in.revenue_growth": {"no": "Omsetningsvekst", "en": "Revenue growth"},
    "prov.in.asset_growth": {"no": "Vekst i eiendeler", "en": "Asset growth"},
    "prov.in.acc_age_days": {
        "no": "Dager siden siste regnskapsår",
        "en": "Days since the latest accounting year",
    },
    "prov.in.acc_filing_lag_days": {
        "no": "Dager etter fristen regnskapet ble levert",
        "en": "Days after the deadline the accounts were filed",
    },
    "prov.in.acc_n_statements_known": {
        "no": "Antall kjente regnskapsår",
        "en": "Number of known accounting years",
    },
    "prov.out.probability": {
        "no": "Sannsynlighet for registrert utfall",
        "en": "Probability of a registered outcome",
    },
    "prov.out.probability_help": {
        "no": "Kalibrert sannsynlighet for konkurs, tvangsavvikling eller tvangsoppløsning "
        "innen seks måneder.",
        "en": "Calibrated probability of bankruptcy, forced liquidation or forced dissolution "
        "within six months.",
    },
    "prov.out.higher_than": {
        "no": "Høyere enn {pct} av selskapene i testdelen",
        "en": "Higher than {pct} of the companies in the test split",
    },
    "prov.out.mahalanobis": {"no": "Avviksskår", "en": "Anomaly score"},
    "prov.out.mahalanobis_help": {
        "no": "Robust Mahalanobis-avstand fra de relative skårene. Høyere betyr mer uvanlig "
        "sammenlignet med gruppen.",
        "en": "Robust Mahalanobis distance from the relative scores. Higher means more unusual "
        "compared with the group.",
    },
    "prov.out.higher_than_reference": {
        "no": "Høyere enn {pct} av referanseselskapene",
        "en": "Higher than {pct} of the reference companies",
    },
    "prov.out.extreme": {"no": "Ekstreme relative skårer", "en": "Extreme relative scores"},
    "prov.out.extreme_help": {
        "no": "Antall trekk der selskapet ligger mer enn tre robuste standardavvik fra "
        "medianen i sammenligningsgruppen.",
        "en": "Number of features where the company lies more than three robust standard "
        "deviations from the median of its peer group.",
    },
    "prov.out.peer_group": {"no": "Sammenligningsgruppe", "en": "Peer group"},
    "prov.out.peer_group_help": {
        "no": "Næring og størrelsesbånd. Grupper med færre enn 20 selskap faller tilbake til "
        "næringshovedområdet, og så til størrelsesbåndet alene.",
        "en": "Industry division and size band. Groups with fewer than 20 companies fall back "
        "to the industry section, and then to the size band alone.",
    },
    "prov.peer_division": {"no": "næring {code}", "en": "division {code}"},
    "prov.peer_section": {"no": "hovedområde {code}", "en": "section {code}"},
    "prov.peer_all": {"no": "alle næringer", "en": "all industries"},
    "prov.peer_band": {"no": "størrelsesbånd {band}", "en": "size band {band}"},
    "prov.tab_peers": {"no": "Sammenlignet med gruppen", "en": "Compared with the group"},
    "prov.tab_drivers": {"no": "Hva driver skåren", "en": "What drives the score"},
    "prov.tab_features": {"no": "Alle trekk", "en": "All features"},
    "prov.peers_text": {
        "no": "Her ser du hvor selskapet ditt ligger sammenlignet med lignende selskap, "
        "altså selskap i samme næring og størrelsesbånd. Hver stolpe er en robust "
        "z-skår: avstanden fra medianen i sammenligningsgruppen, målt i robuste "
        "standardavvik. En stolpe nær null betyr at selskapet er som de fleste. "
        "Stolper utenfor de stiplede linjene teller som ekstreme.",
        "en": "This shows where your company lies compared with similar companies, that is "
        "companies in the same industry and size band. Each bar is a robust z-score: "
        "the distance from the peer group median, measured in robust standard "
        "deviations. A bar near zero means the company is like most others. Bars "
        "beyond the dashed lines count as extreme.",
    },
    "prov.peers_none": {
        "no": "Uten regnskap finnes det bare relative skårer for aksjekapital, alder og "
        "styrestørrelse.",
        "en": "Without accounts there are relative scores only for share capital, age and "
        "board size.",
    },
    "prov.z_label": {"no": "Robust z-skår", "en": "Robust z-score"},
    "prov.z_extreme": {"no": "Ekstrem", "en": "Extreme"},
    "prov.drivers_text": {
        "no": "Her ser du hvilke av valgene dine som betyr mest. Hver stolpe viser hvor mye "
        "sannsynligheten endrer seg når én innstilling settes tilbake til den typiske "
        "verdien. En positiv verdi betyr at innstillingen trekker sannsynligheten opp. "
        "Dette er en enkel forklaring for ett oppdiktet selskap, ikke en egenskap ved "
        "modellen i seg selv.",
        "en": "This shows which of your choices matter most. Each bar shows how much the "
        "probability changes when one setting is put back to its typical value. A "
        "positive value means the setting pushes the probability up. This is a simple "
        "explanation for one made-up company, not a property of the model itself.",
    },
    "prov.drivers_none": {
        "no": "Alle innstillinger har typiske verdier, så det er ingenting å forklare ennå.",
        "en": "Every setting has its typical value, so there is nothing to explain yet.",
    },
    "prov.delta_label": {
        "no": "Endring i sannsynlighet (prosentpoeng)",
        "en": "Change in probability (percentage points)",
    },
    "prov.delta_up": {"no": "Trekker opp", "en": "Pushes up"},
    "prov.delta_down": {"no": "Trekker ned", "en": "Pushes down"},
    "prov.col_input": {"no": "Innstilling", "en": "Setting"},
    "prov.col_value": {"no": "Verdi", "en": "Value"},
    "prov.col_typical": {"no": "Typisk verdi", "en": "Typical value"},
    "prov.col_delta": {"no": "Endring (prosentpoeng)", "en": "Change (percentage points)"},
    "prov.col_feature": {"no": "Trekk", "en": "Feature"},
    "prov.col_median": {"no": "Median i gruppen", "en": "Group median"},
    "prov.col_z": {"no": "z", "en": "z"},
    "prov.col_pct": {"no": "Prosentil i gruppen", "en": "Percentile in group"},
    "prov.col_n": {"no": "Selskap i gruppen", "en": "Companies in group"},
    "prov.features_text": {
        "no": "Alle trekkene modellen ser, for det oppdiktede selskapet. Verdier som ikke er "
        "satt, er typiske verdier.",
        "en": "Every feature the model sees, for the made-up company. Values that were not "
        "set are typical values.",
    },
    # Monitoring
    "overvaking.title": {"no": "Overvåking", "en": "Monitoring"},
    "overvaking.lead": {
        "no": "En modell som var god i går, er ikke nødvendigvis god i morgen. Selskapene "
        "endrer seg, og dataene med dem. Derfor skåres hvert nytt øyeblikksbilde av "
        "hovedmodellen og sammenlignes med referansen, som er øyeblikksbildet modellen "
        "ble trent på.\n\nDrift måles med populasjonsstabilitetsindeks (PSI) per "
        "trekk, endring i andel manglende verdier, endring i kategoriandeler, PSI for "
        "skårene og andel flagget. En PSI over 0,10 gir en advarsel, og over 0,25 en "
        "alarm. En alarm skriver et varsel og lar varseloppgaven i jobben feile, slik "
        "at jobben sender e-post.",
        "en": "A model that was good yesterday is not necessarily good tomorrow. Companies "
        "change, and the data changes with them. That is why every new snapshot is "
        "scored by the champion and compared with the reference, which is the snapshot "
        "the model was trained on.\n\nDrift is measured with the population stability "
        "index (PSI) per feature, the change in the share of missing values, the "
        "change in category shares, the PSI of the scores and the share flagged. A PSI "
        "above 0.10 gives a warning, and above 0.25 an alert. An alert writes a record "
        "and fails the job's alert task, so that the job sends an email.",
    },
    "overvaking.missing": {
        "no": "Overvåkingsdata finnes fra øyeblikksbilde 2. Filene er ikke eksportert ennå.",
        "en": "Monitoring data exists from snapshot 2 on. The files have not been exported yet.",
    },
    "overvaking.scenario": {"no": "Scenario", "en": "Scenario"},
    "overvaking.scenario_text": {
        "no": "Velg scenario for å se forskjellen. Det vanlige scenarioet bruker tersklene "
        "over. Scenarioet «simulated_breach» bruker svært lave terskler. Det ble kjørt "
        "for å vise at varslingen virker.",
        "en": "Pick a scenario to see the difference. The regular scenario uses the "
        'thresholds above. The scenario "simulated_breach" uses very low thresholds. '
        "It was run to show that the alerting works.",
    },
    "overvaking.snapshot": {"no": "Øyeblikksbilde", "en": "Snapshot"},
    "overvaking.metric": {"no": "Mål", "en": "Measure"},
    "overvaking.drift_title": {
        "no": "Trekkene med størst endring",
        "en": "The features with the largest shift",
    },
    "overvaking.scores_title": {
        "no": "Skårene per øyeblikksbilde",
        "en": "The scores per snapshot",
    },
    "overvaking.flag_share": {"no": "Andel flagget", "en": "Share flagged"},
    "overvaking.p50": {"no": "Median skår", "en": "Median score"},
    "overvaking.events_title": {"no": "Varsler", "en": "Alerts"},
    "overvaking.no_events": {
        "no": "Ingen advarsler eller alarmer i dette scenarioet.",
        "en": "No warnings or alerts in this scenario.",
    },
    # Privacy and method
    "personvern.title": {"no": "Personvern og metode", "en": "Privacy and method"},
    "personvern.privacy_title": {"no": "Personvern", "en": "Privacy"},
    "personvern.privacy": {
        "no": "Prosjektet handler om selskap, ikke om personer. Personopplysninger finnes bare "
        "i minnet på én lokal maskin, i det øyeblikket rolledataene leses. Navn og fødselsdato "
        "gjøres straks om til tall per selskap: hvor mange har roller, og er daglig leder også "
        "styreleder. Ingen personopplysninger skrives til disk, lastes opp eller "
        "publiseres.\n\n"
        "Enkeltpersonforetak og andre organisasjonsformer enn AS og ASA fjernes mens filene "
        "leses. Enheter i Frivillighetsregisteret fjernes også, så roller i frivillig arbeid "
        "aldri møter roller i næringslivet. Prosjektet har ingen nøkkel for personer. "
        "Nettverkstrekkene bygger bare på organisasjoner.\n\n"
        "Alt som publiseres, gjelder grupper på minst 20 selskap. Demoen viser ingen "
        "organisasjonsnumre, navn, adresser eller skårer for virkelige enkeltselskap. Reglene "
        "er testet automatisk: en skanning feiler på gyldige organisasjonsnumre, feltnavn for "
        "personopplysninger og kalenderdatoer i offentlige filer.",
        "en": "The project is about companies, not people. Personal data exists only in "
        "memory on one local machine, at the moment the role data is read. Names and birth "
        "dates are turned at once into counts per company: how many hold roles, and is the "
        "CEO also the chair. No personal data is written to disk, uploaded or published.\n\n"
        "Sole proprietorships and every organisation form other than AS and ASA are dropped "
        "while the files are read. Units in the register of voluntary organisations are "
        "dropped too, so roles in voluntary work never meet roles in business. The project "
        "has no key for people. The network features build on organisations only.\n\n"
        "Everything published is for groups of at least 20 companies. The demo shows no "
        "organisation numbers, names, addresses or scores for real single companies. The "
        "rules are tested automatically: a scan fails on valid organisation numbers, person "
        "field names and calendar dates in public files.",
    },
    "personvern.method_title": {"no": "Metode", "en": "Method"},
    "personvern.method": {
        "no": "**Kilder.** Enhetsregisteret og Regnskapsregisteret (NLOD 2.0) og kodelister fra "
        "SSB (CC BY 4.0).\n\n"
        "**Utfall.** Konkurs, tvangsavvikling eller tvangsoppløsning innen seks måneder etter "
        "referansetidspunktet. Det bakoverskuende designet legger referansetidspunktet seks "
        "måneder før øyeblikksbildet, så utfallet er kjent. Det framoverskuende designet "
        "måles når horisonten har gått ut.\n\n"
        "**Trekk.** Register, roller som tall, nettverk mellom organisasjoner, regnskap, "
        "relative skårer mot sammenligningsgruppen (næring og størrelsesbånd) og likhet "
        "mellom formålstekst og næringskode.\n\n"
        "**Modeller.** Regel, Isolation Forest og robust Mahalanobis uten merkelapper, og "
        "gradientforsterkede trær med isotonisk kalibrering for sannsynligheten.\n\n"
        "**Evaluering.** Delt 60, 20 og 20 prosent på selskapsnivå, konfidensintervall fra "
        "bootstrap, stabilitet over frø, ablasjoner og rettferdighet per gruppe.\n\n"
        "**Livssyklus.** Eksperimentlogg i MLflow, modellregister i Unity Catalog, regel for "
        "forfremmelse med manuell godkjenning, planlagt jobb per øyeblikksbilde, overvåking "
        "av drift, varsler, og regler for ny trening og tilbakerulling.",
        "en": "**Sources.** The register of units and the accounts register (NLOD 2.0) and code "
        "lists from Statistics Norway (CC BY 4.0).\n\n"
        "**Outcome.** Bankruptcy, forced liquidation or forced dissolution within six months "
        "of the reference time. The retrospective design places the reference time six months "
        "before the snapshot, so the outcome is known. The prospective design is measured "
        "once the horizon has passed.\n\n"
        "**Features.** Register, roles as counts, networks between organisations, accounts, "
        "relative scores against the peer group (industry and size band) and similarity "
        "between the purpose text and the industry code.\n\n"
        "**Models.** A rule, Isolation Forest and robust Mahalanobis without labels, and "
        "gradient boosted trees with isotonic calibration for the probability.\n\n"
        "**Evaluation.** A 60, 20 and 20 percent split by company, bootstrap confidence "
        "intervals, stability across seeds, ablations and fairness per group.\n\n"
        "**Lifecycle.** Experiment log in MLflow, model registry in Unity Catalog, a promotion "
        "rule with manual approval, a scheduled job per snapshot, drift monitoring, alerts, "
        "and rules for retraining and rollback.",
    },
    "personvern.docs": {
        "no": "Koden og dokumentene ligger åpent på GitHub: "
        "[github.com/eigenreza/foretaksrisiko](https://github.com/eigenreza/foretaksrisiko). "
        "Der står alt i detalj: metode, datakilder, personvern, modellkort, "
        "valideringsrapport, rettferdighet og modellivssyklus.",
        "en": "The code and the documents are open on GitHub: "
        "[github.com/eigenreza/foretaksrisiko](https://github.com/eigenreza/foretaksrisiko). "
        "Everything is described there in detail: method, data sources, privacy, model "
        "card, validation report, fairness and model lifecycle.",
    },
}


def text(key: str, lang: str) -> str:
    return TEXT[key][lang]


def fmt_number(value: float, lang: str) -> str:
    """A count with a thin space (Norwegian) or a comma (English) as thousands separator."""
    formatted = f"{value:,.0f}"
    return formatted.replace(",", " ") if lang == "no" else formatted


def fmt_decimal(value: float, lang: str, decimals: int = 2) -> str:
    formatted = f"{value:.{decimals}f}"
    return formatted.replace(".", ",") if lang == "no" else formatted


def fmt_percent(value: float, lang: str, decimals: int = 1) -> str:
    """A share between 0 and 1 as a percentage with the language's conventions."""
    formatted = f"{value * 100:.{decimals}f}"
    if lang == "no":
        return formatted.replace(".", ",") + " %"
    return formatted + "%"


def fmt_money(value: float, lang: str) -> str:
    return fmt_number(value, lang) + (" kr" if lang == "no" else " NOK")
