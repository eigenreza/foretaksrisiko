"""The assistant page: ask anything about the project, or describe a made-up company in words.

A language model on a free tier (Groq) sorts each message. A question about the project is
answered from fixed facts and the group-level tables in demo_data. A company described in words
is turned into the inputs of the "Try it yourself" form, scored by the real model, and explained.
A question about a real, named company is declined: the demo has no data on single companies.
The question text is never stored; the log keeps only a hash, the length and the outcome.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import math
import os
import re
import threading
import time
from datetime import UTC, datetime

import httpx
import pandas as pd
import streamlit as st

from demo_ui import data
from demo_ui.texts import fmt_decimal, fmt_number, fmt_percent, text
from foretaksrisiko.demo.synthetic import INPUT_FIELDS, Inputs, build_features, drivers, score
from foretaksrisiko.figures.labels import Labels

log = logging.getLogger("foretaksrisiko.assistant")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Two free models with their own quotas. When the first is used up for the day, the second
# answers. Both are on the free tier, so this never leads to a paid option.
MODELS = ("openai/gpt-oss-120b", "qwen/qwen3.8-27b")
MAX_CHARS = 600
SESSION_LIMIT = 20
DAILY_LIMIT = int(os.environ.get("ASSISTANT_DAILY_LIMIT", "300"))
HISTORY_TURNS = 4
RETRY_SECONDS = 8
MAX_RETRY_SECONDS = 20

FACTS = {
    "en": """\
Project: foretaksrisiko, made by Reza Azad Gholami, source code at
github.com/eigenreza/foretaksrisiko. Research and demonstration only.
It finds statistically unusual patterns among Norwegian limited companies (AS and ASA) from open
data: the Brønnøysund registers (Enhetsregisteret, Regnskapsregisteret) and Statistics Norway code
lists. About 412,000 companies qualify. No personal data is kept; roles are turned into counts.
No results for single real companies are published, and no real company can be looked up.
Two questions are answered: (1) how unusual a company is compared with similar companies in the
same industry and size band (the anomaly score; three versions trained without labels: rule
baseline, Isolation Forest, robust Mahalanobis distance); (2) the probability of a registered
outcome (bankruptcy, forced liquidation or forced dissolution) within six months
(gradient-boosted trees, calibrated with isotonic regression). A high score never means a
company did anything wrong.
Results on the test split (82,141 companies, 462 outcomes, base rate 0.56 percent): calibrated
probability PR-AUC 0.47 (0.42 to 0.51), precision 0.32 and lift 57 among the top 1 percent,
ROC-AUC 0.95, Brier score 0.0038. The anomaly scores are close to chance (PR-AUC about 0.007 to
0.009), and they hardly overlap with the probability: unusual is not the same as likely to fail.
Accounts features carry most of the signal; without them PR-AUC falls to 0.15. Register and role
features alone give 0.12. Network and text features add nothing measurable. Much of the signal
comes from missing or old accounts, which is how many companies end in forced dissolution.
Strongest drivers: how old the latest accounts are, number of known account years, industry,
days from the end of the accounting year to filing, opting out of audit, equity, registered
employees.
Fairness: flags follow the base rate for size and mostly for age; accommodation and food
service, and companies under two years, are flagged more often than their precision justifies.
A per-group threshold was tried and not adopted.
Platform: PySpark, Spark SQL and Delta Lake on Databricks (bronze, silver, gold), MLflow,
Unity Catalog model registry with champion and challenger aliases, a promotion rule with manual
approval, a scheduled job per snapshot, drift monitoring with PSI, alerts and retraining rules.
The demo has six pages plus this assistant; "Try it yourself" scores a made-up company.
""",
    "no": """\
Prosjekt: foretaksrisiko, laget av Reza Azad Gholami, kildekode på
github.com/eigenreza/foretaksrisiko. Bare for forskning og demonstrasjon.
Prosjektet finner statistisk uvanlige mønstre blant norske aksjeselskap (AS og ASA) i åpne data
fra Brønnøysundregistrene (Enhetsregisteret og Regnskapsregisteret) og kodelister fra SSB. Om lag
412 000 selskap er med. Ingen personopplysninger lagres; roller gjøres om til tall. Ingen
resultater for virkelige enkeltselskap publiseres, og ingen virkelige selskap kan slås opp.
Prosjektet svarer på to spørsmål: (1) hvor uvanlig et selskap er sammenlignet med lignende
selskap i samme næring og størrelsesbånd (avviksskåren; tre varianter uten merkelapper:
regelbasert referanse, Isolation Forest og robust Mahalanobis-avstand); (2) sannsynligheten for
et registrert utfall (konkurs, tvangsavvikling eller tvangsoppløsning) innen seks måneder
(gradientforsterkede trær, kalibrert med isotonisk regresjon). En høy skår betyr aldri at et
selskap har gjort noe galt.
Resultater på testdelen (82 141 selskap, 462 utfall, grunnrate 0,56 prosent): den kalibrerte
sannsynligheten har gjennomsnittlig presisjon 0,47 (0,42 til 0,51), presisjon 0,32 og løft 57
blant de 1 prosent høyest rangerte, areal under ROC 0,95 og Brier-skår 0,0038. Avviksskårene er
nær tilfeldige (gjennomsnittlig presisjon om lag 0,007 til 0,009) og overlapper nesten ikke med
sannsynligheten: uvanlig er ikke det samme som utsatt.
Regnskapstrekkene bærer det meste av signalet; uten dem faller gjennomsnittlig presisjon til
0,15. Bare register og roller gir 0,12. Nettverk og tekst bidrar ikke målbart. Mye av signalet
kommer fra regnskap som mangler eller er gamle, og det er slik mange selskap ender i
tvangsoppløsning.
Sterkeste drivere: hvor gammelt siste regnskap er, antall kjente regnskapsår, næringen, dager fra
regnskapsårets slutt til levert regnskap, fravalg av revisjon, egenkapital og registrerte ansatte.
Rettferdighet: flaggingen følger grunnraten for størrelse og stort sett for alder; overnatting og
servering, og selskap under to år, flagges oftere enn presisjonen gir grunn til. En terskel per
gruppe ble prøvd og ikke tatt i bruk.
Plattform: PySpark, Spark SQL og Delta Lake på Databricks (bronse, sølv, gull), MLflow,
modellregister i Unity Catalog med aliasene champion og challenger, regel for forfremmelse med
manuell godkjenning, planlagt jobb per øyeblikksbilde, overvåking av drift med PSI, varsler og
regler for ny trening.
Demoen har seks sider i tillegg til assistenten; «Prøv selv» regner på et oppdiktet selskap.
""",
}

# The app's own words. The answer must use these, so the assistant speaks like the rest of
# the demo.
GLOSSARY = {
    "no": (
        "Bruk disse ordene, som resten av demoen: konkurs (aldri «bankrutt»), tvangsavvikling, "
        "tvangsoppløsning, registrert utfall, sannsynlighet for registrert utfall, avviksskår "
        "(aldri «anomali-score»), testdelen (aldri «testsettet»), grunnrate, prosentpoeng, "
        "næring (ikke «bransje»), fylke, regnskapsår. Skriv tall med desimalkomma, for eksempel "
        "0,56 %."
    ),
    "en": (
        "Use these words, like the rest of the demo: bankruptcy, forced liquidation, forced "
        "dissolution, registered outcome, probability of a registered outcome, anomaly score, "
        "test split, base rate, percentage points, industry, county, accounting year."
    ),
}

ROUTE_PROMPT = """\
You are the first step of the assistant in a demo about statistically unusual patterns and \
the risk of bankruptcy or forced dissolution among Norwegian limited companies. Read the last \
message, with the conversation before as background, and reply with JSON only:
{{"type": "company" | "project" | "real" | "other", "inputs": {{...}}}}

type: company when the user describes a company or asks how a kind of company would score, \
also in general terms ("a young restaurant with losses"). project for questions about the \
project, its data, model, results, risk factors, industries, counties, fairness or how it \
works. real when the user asks about a specific real company by name or organisation number. \
other for anything else.
inputs: only for company. Include only the fields the message states or clearly implies, \
with these names and units: nace_division (two-digit code from the list), fylke_code \
(two-digit code from the list), age_years, share_capital (NOK), registered_employees (true or \
false), registered_vat, in_group, board_size, has_ceo, ceo_is_chair, has_auditor, \
has_accountant, n_changes_12m, n_role_events_12m, has_accounts, total_assets (NOK), \
revenue (NOK), equity_ratio (equity divided by assets, -1 to 1), operating_margin (-1 to 1), \
current_ratio, cash_ratio, revenue_growth (-1 to 3, 0.2 means 20 percent), asset_growth, \
acc_age_days (days since the end of the latest accounting year with accounts, typical 400 \
to 500), acc_filing_lag_days (days from the end of the accounting year to filing; the \
deadline is day 212), acc_n_statements_known (number of years with accounts). Give numbers \
only where the message gives a number or a clear fact; vague words such as "late accounts" \
or "losses" are handled after this step, so leave those fields out.

Industry codes: {divisions}
County codes: {fylker}

Conversation before:
{history}

Last message: {message}"""

ANSWER_PROMPT = """\
You are the friendly assistant of the demo foretaksrisiko. Answer the user's last message in \
the user's own language, clearly and briefly: at most six sentences of plain running text, \
with no headings, no lists, no bold text and no dashes. Use only the facts and numbers below, \
and use the positions exactly as they are worded below.

Words: {glossary}

Say what a score means and does not mean: statistics about similar \
companies, never a judgement of a real company. If the user asks about a real named company, \
explain kindly that the demo has no data on single companies and invite them to describe a \
made-up company instead. If the user asks what raises or lowers the risk, or what makes a \
company safer, answer it: explain which factors the model and the data link to a higher or \
lower probability, as statistics and not as personal advice. If the question is outside the \
project, say so briefly and suggest what the demo can answer. Do not invent numbers.

Facts about the project:
{facts}

Group statistics from the test split (base rate = share with an outcome within six months):
{groups}

{company}
Conversation before:
{history}

Last message: {message}"""


def _key() -> str:
    return os.environ.get("GROQ_API_KEY", "")


@st.cache_resource
def _daily() -> dict:
    return {"day": "", "count": 0, "lock": threading.Lock()}


def _allow() -> bool:
    state = _daily()
    today = datetime.now(UTC).date().isoformat()
    with state["lock"]:
        if state["day"] != today:
            state["day"], state["count"] = today, 0
        if state["count"] >= DAILY_LIMIT:
            return False
        state["count"] += 1
        return True


def _chat(prompt: str, max_tokens: int) -> str:
    """One call to the first model that has quota left.

    The free tier also limits tokens per minute. When every model says "try again shortly",
    the call waits a few seconds and tries once more before it gives up.
    """
    last_error = "no model"
    for attempt in range(2):
        busy, wait = False, RETRY_SECONDS
        for model in MODELS:
            body = {"model": model, "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens, "temperature": 0}  # fmt: skip
            if model.startswith("openai/"):
                body["reasoning_effort"] = "low"
            try:
                response = httpx.post(GROQ_URL, json=body, timeout=60,
                                      headers={"Authorization": f"Bearer {_key()}"})  # fmt: skip
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
                continue
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"] or ""
            last_error = f"HTTP {response.status_code}"
            if response.status_code in (429, 503):
                try:
                    asked = float(response.headers.get("retry-after", RETRY_SECONDS))
                except ValueError:
                    asked = RETRY_SECONDS
                wait = min(asked, wait) if busy else asked
                busy = True
            if response.status_code not in (429, 500, 502, 503):
                break
        if attempt == 0 and busy:
            time.sleep(min(max(wait, 2.0), MAX_RETRY_SECONDS))
    raise RuntimeError(last_error)


def _json(text_value: str) -> dict:
    start, end = text_value.find("{"), text_value.rfind("}")
    try:
        value = json.loads(text_value[start : end + 1]) if 0 <= start < end else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


ENGLISH_WORDS = frozenset(
    "the is are am was will would can could should do does did what which who how when where "
    "why my me you your if have has had a an of and with about this that from in on to for it "
    "company companies industry industries bankrupt bankruptcy risk model score unusual".split()
)


def _lang_code(message: str) -> str:
    """'en' or 'no', from the share of common English words in the message."""
    words = [w.strip(".,?!:;()\"'").lower() for w in message.split()]
    words = [w for w in words if w]
    english = bool(words) and sum(w in ENGLISH_WORDS for w in words) / len(words) >= 0.25
    return "en" if english else "no"


def _language(message: str) -> str:
    if _lang_code(message) == "en":
        return "English"
    return "Norwegian (bokmål), or nynorsk if the message is in nynorsk"


# Fixed meanings for vague words. They are applied after the model has read the message, so
# the same description gives the same inputs whichever model answers. A rule only sets the
# fields it owns, and it wins over the model.
VAGUE_WORDS = (
    (
        r"ikke (har )?levert regnskap|har ikke levert|aldri levert regnskap|hasn'?t filed|"
        r"has not filed|never filed|not filed (any |its )?accounts|stopped filing",
        {"acc_age_days": 900},
    ),
    (
        r"sen\w* (levert\w* )?regnskap|regnskap\w* (er |ble |blir )?levert sent|levert sent|"
        r"sent levert|for sent|late (filed )?accounts|accounts (were |are )?(filed )?late|"
        r"filed late|late filing|files late",
        {"acc_filing_lag_days": 260},
    ),
    (
        r"store tap|stort underskudd|heavy loss|large loss|big loss|huge loss",
        {"operating_margin": -0.3},
    ),
    (
        r"underskudd|går med tap|taper penger|\btap\b|\blosses\b|\bloss\b|loss-making|unprofitable|"
        r"making a loss|losing money",
        {"operating_margin": -0.1},
    ),
    (r"negativ egenkapital|negative equity", {"equity_ratio": -0.2}),
    (r"overskudd|lønnsom|går godt|profitable|making a profit", {"operating_margin": 0.08}),
)


def _fixed_meanings(message: str) -> dict:
    """Inputs set by the vague-word rules; the first rule that owns a field wins."""
    found: dict = {}
    lowered = message.lower()
    for pattern, values in VAGUE_WORDS:
        if re.search(pattern, lowered):
            for name, value in values.items():
                found.setdefault(name, value)
    return found


# Words the models sometimes use that the app does not, with the app's own word.
NORWEGIAN_WORDS = (
    (r"\bbankrutt\w*|\bbankrupt\w*", "konkurs"),
    (r"\bavviksskåre\b", "avviksskår"),
    (r"\banomali[\s\u2011-]?scoren\b", "avviksskåren"),
    (r"\banomali[\s\u2011-]?score\w*|\banomalitets\w*", "avviksskår"),
    (r"\btest[\s\u2011-]?settet\b|\btest[\s\u2011-]?datasettet\b", "testdelen"),
    (r"\btest[\s\u2011-]?sett\b", "testdel"),
)


def _plain(answer: str, lang: str) -> str:
    """Plain running text: no headings, lists, bold or dashes, and the app's own words."""
    lines = []
    for line in answer.splitlines():
        line = re.sub(r"^\s*(#+\s*|[-*\u2022]\s+|\d+[.)]\s+)", "", line).strip()
        if line:
            # A list item or heading becomes a sentence of its own.
            lines.append(line if re.search(r"[.!?:]\**$", line) else line + ".")
    text_value = " ".join(lines)
    text_value = re.sub(r"\*\*|__|(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)", "", text_value)
    between = r"\1 til \2" if lang == "no" else r"\1 to \2"
    text_value = re.sub(r"(\d)\s*[\u2013\u2014]\s*(\d)", between, text_value)
    # A dash right before a number, after a space or bracket, is a minus sign.
    text_value = re.sub(r"(^|[\s(])[\u2013\u2014](?=\d)", r"\1-", text_value)
    text_value = re.sub(r"\s*[\u2013\u2014]\s*", ", ", text_value)
    text_value = text_value.replace("\u2011", "-")
    if lang == "no":
        text_value = re.sub(r"(\d)\.(\d)", r"\1,\2", text_value)
        for pattern, word in NORWEGIAN_WORDS:
            text_value = re.sub(
                pattern,
                lambda m, w=word: w.capitalize() if m.group(0)[:1].isupper() else w,
                text_value,
                flags=re.IGNORECASE,
            )
    return re.sub(r"\s{2,}", " ", text_value).strip()


def _position(percentile: float | None, lang: str, kind: str) -> str:
    """A worded position for a percentile, so the model does not have to read raw numbers."""
    if percentile is None:
        return ""
    bands = {
        "probability": {
            "no": ("lavere enn hos de fleste selskap", "omtrent som hos et vanlig selskap",
                   "høyere enn hos de fleste selskap", "blant de 10 prosent høyeste"),
            "en": ("lower than for most companies", "about the same as for a typical company",
                   "higher than for most companies", "among the highest 10 percent"),
        },
        "anomaly": {
            "no": ("mindre uvanlig enn de fleste", "typisk, ikke spesielt uvanlig",
                   "mer uvanlig enn de fleste", "blant de 10 prosent mest uvanlige"),
            "en": ("less unusual than most", "typical, not especially unusual",
                   "more unusual than most", "among the 10 percent most unusual"),
        },
    }[kind][lang]  # fmt: skip
    if percentile < 0.25:
        return bands[0]
    if percentile < 0.75:
        return bands[1]
    if percentile < 0.9:
        return bands[2]
    return bands[3]


def _history(turns: list[dict]) -> str:
    lines = [f"{t['role']}: {' '.join(str(t['content']).split())[:400]}"
             for t in turns[-HISTORY_TURNS:]]  # fmt: skip
    return "\n".join(lines) or "(none)"


def _groups(lang: str) -> str:
    """Base rates per group, with the group names and number format of the language."""
    frame = data.table("fairness")
    if frame is None:
        return "(not available)"
    frame = frame[frame["model"] == "hgb_calibrated"]
    frame = frame[frame["per_group_threshold"].astype(str).str.lower() == "false"]
    labels = Labels(lang)
    name = "group_label_no" if lang == "no" else "group_label_en"
    lines = []
    for group, part in frame.groupby("group_type"):
        part = part.sort_values("base_rate", ascending=False)
        items = [
            f"{getattr(row, name)}: {fmt_percent(row.base_rate, lang, 2)} "
            f"(n={fmt_number(row.n, lang)})"
            for row in part.itertuples()
        ]
        lines.append(f"{labels.group_type(group)}: " + "; ".join(items))
    return "\n".join(lines)


def _clean_inputs(raw: dict, art, typical: Inputs) -> dict:
    """Keep only known fields with sensible values."""
    divisions = set(art.divisions["code"])
    fylker = set(art.fylker["code"])
    out: dict = {}
    for name, value in (raw or {}).items():
        if name not in INPUT_FIELDS or value is None:
            continue
        current = getattr(typical, name)
        try:
            if isinstance(current, bool):
                out[name] = value if isinstance(value, bool) else str(value).lower() == "true"
            elif name == "nace_division":
                code = str(value).zfill(2)[:2]
                if code in divisions:
                    out[name] = code
            elif name == "fylke_code":
                code = str(value).zfill(2)[:2]
                if code in fylker:
                    out[name] = code
            elif isinstance(current, int):
                out[name] = int(float(value))
            else:
                number = float(value)
                if not math.isnan(number):
                    out[name] = number
        except (TypeError, ValueError):
            continue
    for name, low, high in (
        ("equity_ratio", -1.0, 1.0),
        ("operating_margin", -1.0, 1.0),
        ("revenue_growth", -1.0, 3.0),
        ("asset_growth", -1.0, 3.0),
        ("age_years", 0.0, 60.0),
        ("board_size", 1, 10),
        ("acc_age_days", 0, 2000),
        ("acc_filing_lag_days", 0, 500),
    ):
        if name in out:
            out[name] = type(getattr(typical, name))(min(max(out[name], low), high))
    return out  # fmt: skip


def _score_company(changes: dict, art) -> tuple[Inputs, object, pd.DataFrame]:
    typical = art.typical_inputs()
    inputs = dataclasses.replace(typical, **changes)
    features, _ = build_features(inputs, art)
    reference = data.probability_quantiles()
    result = score(features, art, reference)
    table = drivers(inputs, art, typical)
    return inputs, result, table


def _shown_value(name: str, value, art, lang: str) -> str:
    """An input value the way a reader would write it."""
    if name == "nace_division":
        column = "name_no" if lang == "no" else "name_en"
        names = dict(zip(art.divisions["code"].astype(str).str.zfill(2), art.divisions[column],
                         strict=True))  # fmt: skip
        return f"{value} {names.get(str(value).zfill(2), '')}".strip()
    if name == "fylke_code":
        column = "name_no" if lang == "no" else "name_en"
        names = dict(zip(art.fylker["code"].astype(str).str.zfill(2), art.fylker[column],
                         strict=True))  # fmt: skip
        return names.get(str(value).zfill(2), str(value))
    if isinstance(value, bool):
        return ("ja" if value else "nei") if lang == "no" else ("yes" if value else "no")
    if name in ("equity_ratio", "operating_margin", "revenue_growth", "asset_growth"):
        return fmt_percent(float(value), lang, 0)
    if isinstance(value, float):
        return fmt_decimal(value, lang, 2) if not value.is_integer() else fmt_number(value, lang)
    return fmt_number(value, lang) if isinstance(value, int) else str(value)


def _company_facts(inputs: Inputs, result, table: pd.DataFrame, changes: dict, art,
                   lang: str) -> str:  # fmt: skip
    """The scored company, in the words and number format of the answer's language."""
    labels = Labels(lang)
    given = "; ".join(f"{labels.feature(name)}: {_shown_value(name, value, art, lang)}"
                      for name, value in changes.items()) or "-"  # fmt: skip
    lines = ["The user described a company without naming a real one, so treat it as a made-up "
             "example: present the scores below and explain them. Do not refuse, and do not give "
             "investment advice.",
             "A made-up company was scored by the real model. Every input not given takes the "
             "typical value of the population.",
             f"Inputs given or implied: {given}",
             f"Probability of a registered outcome within six months: "
             f"{fmt_percent(result.probability, lang, 2)}. The base rate is "
             f"{fmt_percent(0.0056, lang, 2)}: the share of all companies in the test split "
             "that got a registered outcome, not the rate for companies like this one.",
             "Position of the probability: "
             f"{_position(result.probability_percentile, lang, 'probability')}."
             if result.probability_percentile is not None else "",
             f"Anomaly score: {fmt_decimal(result.mahalanobis, lang, 2)}. Position: "
             f"{_position(result.mahalanobis_percentile, lang, 'anomaly')}."
             if result.mahalanobis_percentile is not None else "",
             f"Number of extreme relative scores: {result.n_extreme_z}."]  # fmt: skip
    if not table.empty:
        typical = score(build_features(art.typical_inputs(), art)[0], art).probability
        top = table.reindex(table["delta_probability"].abs().sort_values(ascending=False).index)
        effects = [f"{labels.feature(r.input)} = {_shown_value(r.input, r.value, art, lang)}: "
                   f"{fmt_decimal(r.delta_probability * 100, lang, 2)} percentage points"
                   for r in top.head(5).itertuples()]  # fmt: skip
        note = DRIVERS_NOTE.format(
            typical=fmt_percent(typical, lang, 2),
            total=fmt_decimal(table["delta_probability"].sum() * 100, lang, 2),
        )
        lines.append(note + " " + "; ".join(effects))
    if not inputs.has_accounts:
        lines.append("Note: companies without known accounts are mostly new companies in the "
                     "data, so the model gives them a low probability.")  # fmt: skip
    return "\n".join(line for line in lines if line)


DRIVERS_NOTE = (
    "Contribution of each input to the difference between this company's probability and the "
    "probability of a company with only typical values ({typical}), in percentage points. The "
    "contributions are Shapley values and add up to that difference ({total} percentage "
    "points in all); if you mention them, you may say so. Call the reference a company with "
    "typical values; it is not the average and not the base rate."
)


def reply(message: str, history: list[dict], lang: str) -> dict:
    """Route the message, score a described company if there is one, and write the answer."""
    art = data.artefacts()
    started = time.perf_counter()
    divisions = "; ".join(f"{r.code} {r.name_en}" for r in art.divisions.itertuples())
    fylker = "; ".join(f"{r.code} {r.name_en}" for r in art.fylker.itertuples())
    route_prompt = ROUTE_PROMPT.format(
        divisions=divisions, fylker=fylker, history=_history(history), message=message
    )
    route = _json(_chat(route_prompt, 400))
    kind = (
        route.get("type")
        if route.get("type") in ("company", "project", "real", "other")
        else "project"
    )
    # A message that gives details of a company is a description, whatever the first step
    # called it, unless it names a real company.
    fixed = _fixed_meanings(message)
    if kind in ("project", "other") and len(route.get("inputs") or {}) + len(fixed) >= 2:
        kind = "company"
    answer_lang = _lang_code(message)
    company, scored = "", None
    if kind == "company":
        typical = art.typical_inputs()
        raw = {k: v for k, v in (route.get("inputs") or {}).items() if k not in fixed}
        if "acc_filing_lag_days" in fixed and "acc_age_days" not in fixed:
            raw.pop("acc_age_days", None)
        changes = {**_clean_inputs(raw, art, typical), **fixed}
        inputs, result, table = _score_company(changes, art)
        company = _company_facts(inputs, result, table, changes, art, answer_lang) + "\n"
        scored = {"probability": result.probability, "mahalanobis": result.mahalanobis,
                  "percentile": result.probability_percentile, "changes": changes}  # fmt: skip
    answer_prompt = (
        ANSWER_PROMPT.format(
            facts=FACTS[answer_lang],
            glossary=GLOSSARY[answer_lang],
            groups=_groups(answer_lang),
            company=company,
            history=_history(history),
            message=message,
        )
        + f"\n\nWrite the answer in {_language(message)}."
    )
    answer = _plain(_chat(answer_prompt, 650), answer_lang)
    log.info(json.dumps({"event": "assistant",
                         "sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
                         "length": len(message), "kind": kind,
                         "seconds": round(time.perf_counter() - started, 2)}))  # fmt: skip
    return {"role": "assistant", "content": answer.strip(), "kind": kind, "scored": scored}


def page(lang: str) -> None:
    st.title(text("assistent.title", lang))
    st.markdown(text("assistent.lead", lang))
    st.info(text("assistent.privacy", lang), icon=":material/lock:")
    if data.artefacts() is None:
        st.warning(text("prov.missing", lang))
        return
    if not _key():
        st.warning(text("assistent.off", lang))
        return
    history: list[dict] = st.session_state.setdefault("assistant_chat", [])
    if not history:
        with st.chat_message("assistant"):
            st.markdown(text("assistent.hello", lang))
            examples = [text(f"assistent.example{n}", lang) for n in (1, 2, 3)]
            # One button per row, so the whole question is always readable.
            for example in examples:
                if st.button(example, key=f"assistant_ex_{example}", width="stretch"):
                    st.session_state["assistant_pending"] = example
                    st.rerun()
    for turn in history:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
            scored = turn.get("scored")
            if scored:
                one, two = st.columns(2)
                one.metric(text("prov.out.probability", lang),
                           fmt_percent(scored["probability"], lang, 2))  # fmt: skip
                two.metric(
                    text("prov.out.mahalanobis", lang), fmt_decimal(scored["mahalanobis"], lang, 2)
                )
                if scored["changes"]:
                    with st.expander(text("assistent.inputs", lang)):
                        st.json(scored["changes"])
    if history and st.button(text("assistent.new", lang)):
        st.session_state["assistant_chat"] = []
        st.rerun()

    message = st.chat_input(text("assistent.placeholder", lang), max_chars=MAX_CHARS)
    message = message or st.session_state.pop("assistant_pending", None)
    if not message:
        return
    user_turns = sum(1 for t in history if t["role"] == "user")
    if user_turns >= SESSION_LIMIT or not _allow():
        st.warning(text("assistent.limit", lang))
        return
    history.append({"role": "user", "content": message})
    with st.spinner(text("assistent.thinking", lang)):
        try:
            turn = reply(message, history[:-1], lang)
        except RuntimeError:
            turn = {"role": "assistant", "content": text("assistent.error", lang)}
    history.append(turn)
    st.rerun()
