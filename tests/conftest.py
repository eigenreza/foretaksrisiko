"""Synthetic fixtures. No real units, no real persons.

privacy-scan: allow-person-fields
privacy-scan: allow-dates

Organisation numbers are invented so that they fail the MOD11 checksum and start with a digit
that is never used for real units. Person names are placeholders that the privacy tests search for
in every output, to prove they are discarded.
"""

from __future__ import annotations

import gzip
import io
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from foretaksrisiko.acquire.landing import Landing  # noqa: E402
from foretaksrisiko.config import ScopeConfig  # noqa: E402
from foretaksrisiko.orgnr import is_valid_orgnr, mod11_check_digit  # noqa: E402


def fake_orgnr(seed: int) -> str:
    """Nine digits starting with 1 whose check digit is deliberately wrong."""
    first8 = f"1{seed:07d}"
    valid = mod11_check_digit(first8)
    digit = 0 if valid is None else (valid + 1) % 10
    value = first8 + str(digit)
    assert not is_valid_orgnr(value)
    return value


FAKE_FIRST = "Testfornavn"
FAKE_LAST = "Testetternavn"
FAKE_BIRTH = "1961-02-03"
PERSON_MARKERS = (FAKE_FIRST, FAKE_LAST, FAKE_BIRTH)

AS_1 = fake_orgnr(1)
AS_2 = fake_orgnr(2)
ASA_1 = fake_orgnr(3)
AS_AUDITOR = fake_orgnr(4)
AS_FRIVILLIG = fake_orgnr(5)
ENK_1 = fake_orgnr(6)
FLI_1 = fake_orgnr(7)
DELETED_1 = fake_orgnr(8)
SUB_1 = fake_orgnr(9)
SUB_2 = fake_orgnr(10)
SUB_ENK = fake_orgnr(11)
ENK_ACCOUNTANT = fake_orgnr(12)

KEPT_UNITS = {AS_1, AS_2, ASA_1, AS_AUDITOR}
DROPPED_UNITS = {AS_FRIVILLIG, ENK_1, FLI_1, DELETED_1, SUB_ENK, ENK_ACCOUNTANT}


def unit(orgnr: str, form: str, **overrides) -> dict:
    base = {
        "organisasjonsnummer": orgnr,
        "navn": f"SYNTETISK {form} {orgnr[-3:]}",
        "organisasjonsform": {"kode": form, "beskrivelse": form},
        "registreringsdatoEnhetsregisteret": "2015-03-10",
        "stiftelsesdato": "2015-02-01",
        "vedtektsdato": "2015-02-01",
        "registrertIMvaregisteret": True,
        "registrertIForetaksregisteret": True,
        "registrertIFrivillighetsregisteret": False,
        "registrertIStiftelsesregisteret": False,
        "registrertIPartiregisteret": False,
        "naeringskode1": {"kode": "62.010", "beskrivelse": "Programmering"},
        "institusjonellSektorkode": {"kode": "2100", "beskrivelse": "Private aksjeselskaper"},
        "forretningsadresse": {
            "adresse": ["Testveien 1"],
            "postnummer": "0150",
            "poststed": "OSLO",
            "kommunenummer": "0301",
            "kommune": "OSLO",
            "landkode": "NO",
            "land": "Norge",
        },
        "postadresse": {"kommunenummer": "0301", "postnummer": "0150"},
        "kapital": {
            "belop": 30000.0,
            "antallAksjer": 300,
            "type": "Aksjekapital",
            "valuta": "NOK",
            "innbetalt": 30000.0,
            "fulltInnbetalt": True,
            "innfortDato": "2015-02-01",
        },
        "antallAnsatte": 12,
        "harRegistrertAntallAnsatte": True,
        "konkurs": False,
        "underAvvikling": False,
        "underTvangsavviklingEllerTvangsopplosning": False,
        "erIKonsern": False,
        "maalform": "Bokmaal",
        "sisteInnsendteAarsregnskap": "2024",
        "hjemmeside": "example.invalid",
        "historiskeNavn": [],
        "paategninger": [],
        "vedtektsfestetFormaal": ["Utvikling av programvare", "og tilhoerende tjenester"],
        "aktivitet": ["Programmering"],
        "_links": {"self": {"href": f"https://example.invalid/{orgnr}"}},
    }
    base.update(overrides)
    return base


def enheter_records() -> list[dict]:
    return [
        unit(AS_1, "AS"),
        unit(
            AS_2,
            "AS",
            konkurs=True,
            konkursdato="2024-11-20",
            naeringskode1={"kode": "41.200", "beskrivelse": "Bygg"},
            forretningsadresse={"kommunenummer": "4601", "postnummer": "5003", "landkode": "NO"},
            paategninger=[{"infotype": "AVVIKLING", "tekst": "x", "innfoertDato": "2024-11-20"}],
            historiskeNavn=[{"navn": "SYNTETISK GAMMELT"}],
            hjemmeside=None,
            antallAnsatte=None,
            harRegistrertAntallAnsatte=False,
        ),
        unit(
            ASA_1,
            "ASA",
            naeringskode1={"kode": "64.190", "beskrivelse": "Bank"},
            forretningsadresse={"kommunenummer": "1103", "postnummer": "4006", "landkode": "NO"},
            erIKonsern=True,
            kapital={"belop": 5000000.0, "antallAksjer": 50000, "valuta": "NOK"},
        ),
        unit(AS_AUDITOR, "AS", naeringskode1={"kode": "69.201", "beskrivelse": "Revisjon"}),
        unit(AS_FRIVILLIG, "AS", registrertIFrivillighetsregisteret=True),
        unit(ENK_1, "ENK", navn=f"{FAKE_LAST} {FAKE_FIRST} SNEKKER", kapital=None),
        unit(FLI_1, "FLI", kapital=None),
        {
            "respons_klasse": "SlettetEnhet",
            "organisasjonsnummer": DELETED_1,
            "navn": "SYNTETISK SLETTET",
            "organisasjonsform": {"kode": "AS", "beskrivelse": "Aksjeselskap"},
            "slettedato": "2023-01-15",
        },
    ]


def underenheter_records() -> list[dict]:
    def sub(orgnr: str, parent: str, kommune: str) -> dict:
        return {
            "organisasjonsnummer": orgnr,
            "navn": f"SYNTETISK UNDERENHET {orgnr[-3:]}",
            "organisasjonsform": {"kode": "BEDR", "beskrivelse": "Bedrift"},
            "overordnetEnhet": parent,
            "naeringskode1": {"kode": "62.010", "beskrivelse": "Programmering"},
            "beliggenhetsadresse": {
                "kommunenummer": kommune,
                "postnummer": "0150",
                "landkode": "NO",
            },
            "antallAnsatte": 5,
            "harRegistrertAntallAnsatte": True,
            "registrertIMvaregisteret": True,
            "registreringsdatoEnhetsregisteret": "2016-01-01",
            "oppstartsdato": "2016-01-01",
        }

    return [sub(SUB_1, AS_1, "0301"), sub(SUB_2, AS_1, "4601"), sub(SUB_ENK, ENK_1, "0301")]


def person(first: str, last: str, birth: str = FAKE_BIRTH, dead: bool = False) -> dict:
    return {"navn": {"fornavn": first, "etternavn": last}, "fodselsdato": birth, "erDoed": dead}


def role(type_code: str, holder: dict, deregistered: bool = False, **extra) -> dict:
    out = {
        "type": {"kode": type_code, "beskrivelse": type_code},
        "avregistrert": deregistered,
        "rekkefolge": 0,
    }
    out.update(holder)
    out.update(extra)
    return out


def org_holder(orgnr: str, form: str, status: str | None = None) -> dict:
    return {
        "enhet": {
            "organisasjonsnummer": orgnr,
            "organisasjonsform": {"kode": form, "beskrivelse": form},
            "navn": [f"SYNTETISK {form}"],
            "godkjenningsstatus": status,
            "erSlettet": False,
        }
    }


def group(code: str, roles: list[dict], changed: str = "2024-06-01") -> dict:
    return {"type": {"kode": code, "beskrivelse": code}, "sistEndret": changed, "roller": roles}


def roller_records() -> list[dict]:
    p1 = {"person": person(FAKE_FIRST, FAKE_LAST)}
    p2 = {"person": person("Annen", FAKE_LAST, "1975-05-05")}
    p3 = {"person": person("Tredje", FAKE_LAST, "1980-06-06")}
    p4 = {"person": person("Fjerde", FAKE_LAST, "1985-07-07", dead=True)}
    p5 = {"person": person("Femte", FAKE_LAST, "1990-08-08")}
    p6 = {"person": person("Sjette", FAKE_LAST, "1995-09-09")}
    return [
        {
            "organisasjonsnummer": AS_1,
            "rollegrupper": [
                group(
                    "STYR",
                    [
                        role("LEDE", p1),
                        role("MEDL", p2),
                        role("MEDL", p3, deregistered=True),
                        role("VARA", p3),
                    ],
                    changed="2024-06-01",
                ),
                group("DAGL", [role("DAGL", p1)], changed="2023-01-01"),
                group("REVI", [role("REVI", org_holder(AS_AUDITOR, "AS", "GODKJENT"))]),
                group("REGN", [role("REGN", org_holder(ENK_ACCOUNTANT, "ENK"))]),
            ],
        },
        {
            "organisasjonsnummer": ENK_1,
            "rollegrupper": [group("INNH", [role("INNH", p1)])],
        },
        {
            "organisasjonsnummer": ASA_1,
            "rollegrupper": [
                group(
                    "STYR",
                    [
                        role("LEDE", p4),
                        role("MEDL", p5, valgtAv={"kode": "ANSA", "beskrivelse": "Ansatte"}),
                        role("NEST", p6),
                    ],
                ),
                group("DAGL", [role("DAGL", p5)]),
                group("KONT", [role("KONT", p6)]),
            ],
        },
    ]


def gz_array(items: list[dict]) -> bytes:
    return gzip.compress(json.dumps(items, ensure_ascii=False).encode("utf-8"))


def opener_for(data: bytes):
    @contextmanager
    def opener():
        yield gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb")

    return opener


@pytest.fixture
def scope() -> ScopeConfig:
    return ScopeConfig()


@pytest.fixture
def landing(tmp_path: Path) -> Landing:
    return Landing(tmp_path / "landing", 1)


@pytest.fixture
def enheter_opener():
    return opener_for(gz_array(enheter_records()))


@pytest.fixture
def underenheter_opener():
    return opener_for(gz_array(underenheter_records()))


@pytest.fixture
def roller_opener():
    return opener_for(gz_array(roller_records()))
