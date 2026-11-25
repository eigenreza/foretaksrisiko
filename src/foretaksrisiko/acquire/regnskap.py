"""Accounts (Regnskapsregisteret): one call per company, resumable and idempotent."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from foretaksrisiko.acquire.fields import dig, to_bool, to_date, to_float, to_int
from foretaksrisiko.acquire.http import PoliteClient, RetryError
from foretaksrisiko.acquire.landing import Landing, read_table

log = logging.getLogger(__name__)

_F = pa.float64()

NUMERIC_PATHS: dict[str, tuple[str, ...]] = {
    "sum_egenkapital_gjeld": ("egenkapitalGjeld", "sumEgenkapitalGjeld"),
    "sum_egenkapital": ("egenkapitalGjeld", "egenkapital", "sumEgenkapital"),
    "sum_opptjent_egenkapital": (
        "egenkapitalGjeld",
        "egenkapital",
        "opptjentEgenkapital",
        "sumOpptjentEgenkapital",
    ),
    # The source spells this field "sumInnskuttEgenkaptial"; see also the fallback below.
    "sum_innskutt_egenkapital": (
        "egenkapitalGjeld",
        "egenkapital",
        "innskuttEgenkapital",
        "sumInnskuttEgenkaptial",
    ),
    "sum_gjeld": ("egenkapitalGjeld", "gjeldOversikt", "sumGjeld"),
    "sum_kortsiktig_gjeld": (
        "egenkapitalGjeld",
        "gjeldOversikt",
        "kortsiktigGjeld",
        "sumKortsiktigGjeld",
    ),
    "sum_langsiktig_gjeld": (
        "egenkapitalGjeld",
        "gjeldOversikt",
        "langsiktigGjeld",
        "sumLangsiktigGjeld",
    ),
    "sum_eiendeler": ("eiendeler", "sumEiendeler"),
    "goodwill": ("eiendeler", "goodwill"),
    "sum_varer": ("eiendeler", "sumVarer"),
    "sum_fordringer": ("eiendeler", "sumFordringer"),
    "sum_investeringer": ("eiendeler", "sumInvesteringer"),
    "sum_bankinnskudd_og_kontanter": ("eiendeler", "sumBankinnskuddOgKontanter"),
    "sum_omloepsmidler": ("eiendeler", "omloepsmidler", "sumOmloepsmidler"),
    "sum_anleggsmidler": ("eiendeler", "anleggsmidler", "sumAnleggsmidler"),
    "sum_driftsinntekter": (
        "resultatregnskapResultat",
        "driftsresultat",
        "driftsinntekter",
        "sumDriftsinntekter",
    ),
    "salgsinntekter": (
        "resultatregnskapResultat",
        "driftsresultat",
        "driftsinntekter",
        "salgsinntekter",
    ),
    "sum_driftskostnad": (
        "resultatregnskapResultat",
        "driftsresultat",
        "driftskostnad",
        "sumDriftskostnad",
    ),
    "loennskostnad": (
        "resultatregnskapResultat",
        "driftsresultat",
        "driftskostnad",
        "loennskostnad",
    ),
    "driftsresultat": ("resultatregnskapResultat", "driftsresultat", "driftsresultat"),
    "netto_finans": ("resultatregnskapResultat", "finansresultat", "nettoFinans"),
    "sum_finansinntekter": (
        "resultatregnskapResultat",
        "finansresultat",
        "finansinntekt",
        "sumFinansinntekter",
    ),
    "sum_finanskostnad": (
        "resultatregnskapResultat",
        "finansresultat",
        "finanskostnad",
        "sumFinanskostnad",
    ),
    "annen_rentekostnad": (
        "resultatregnskapResultat",
        "finansresultat",
        "finanskostnad",
        "annenRentekostnad",
    ),
    "rentekostnad_samme_konsern": (
        "resultatregnskapResultat",
        "finansresultat",
        "finanskostnad",
        "rentekostnadSammeKonsern",
    ),
    "ordinaert_resultat_foer_skattekostnad": (
        "resultatregnskapResultat",
        "ordinaertResultatFoerSkattekostnad",
    ),
    "ordinaert_resultat_skattekostnad": (
        "resultatregnskapResultat",
        "ordinaertResultatSkattekostnad",
    ),
    "ekstraordinaere_poster": ("resultatregnskapResultat", "ekstraordinaerePoster"),
    "skattekostnad_ekstraordinaert_resultat": (
        "resultatregnskapResultat",
        "skattekostnadEkstraordinaertResultat",
    ),
    "aarsresultat": ("resultatregnskapResultat", "aarsresultat"),
    "totalresultat": ("resultatregnskapResultat", "totalresultat"),
}

REGNSKAP_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("regnskap_id", pa.int64()),
        ("regnskapstype", pa.string()),
        ("regnskapsperiode_fra_dato", pa.date32()),
        ("regnskapsperiode_til_dato", pa.date32()),
        ("valuta", pa.string()),
        ("avviklingsregnskap", pa.bool_()),
        ("oppstillingsplan", pa.string()),
        ("ikke_revidert_aarsregnskap", pa.bool_()),
        ("fravalg_revisjon", pa.bool_()),
        ("smaa_foretak", pa.bool_()),
        ("regnskapsregler", pa.string()),
        ("morselskap", pa.bool_()),
    ]
    + [(name, _F) for name in NUMERIC_PATHS]
)

REGNSKAP_STATUS_SCHEMA = pa.schema(
    [
        ("organisasjonsnummer", pa.string()),
        ("http_status", pa.int32()),
        ("n_regnskap", pa.int32()),
        # Snapshot whose request produced the row: the current one, or an earlier snapshot when
        # the accounts were carried forward without a new request.
        ("source_snapshot_id", pa.int32()),
    ]
)
FILING_FIELD = "sisteInnsendteAarsregnskap"


def flatten_regnskap(orgnr: str, item: dict) -> dict:
    row = {
        "organisasjonsnummer": orgnr,
        "regnskap_id": to_int(item.get("id")),
        "regnskapstype": item.get("regnskapstype"),
        "regnskapsperiode_fra_dato": to_date(dig(item, ("regnskapsperiode", "fraDato"))),
        "regnskapsperiode_til_dato": to_date(dig(item, ("regnskapsperiode", "tilDato"))),
        "valuta": item.get("valuta"),
        "avviklingsregnskap": to_bool(item.get("avviklingsregnskap")),
        "oppstillingsplan": item.get("oppstillingsplan"),
        "ikke_revidert_aarsregnskap": to_bool(dig(item, ("revisjon", "ikkeRevidertAarsregnskap"))),
        "fravalg_revisjon": to_bool(dig(item, ("revisjon", "fravalgRevisjon"))),
        "smaa_foretak": to_bool(dig(item, ("regnkapsprinsipper", "smaaForetak"))),
        "regnskapsregler": dig(item, ("regnkapsprinsipper", "regnskapsregler")),
        "morselskap": to_bool(dig(item, ("virksomhet", "morselskap"))),
    }
    for column, path in NUMERIC_PATHS.items():
        value = dig(item, path)
        if value is None and path[-1] == "sumInnskuttEgenkaptial":
            value = dig(item, path[:-1] + ("sumInnskuttEgenkapital",))
        row[column] = to_float(value)
    return row


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _write_table(table_dir: Path, name: str, table: pa.Table) -> None:
    target = table_dir / name
    tmp = target.with_suffix(".tmp")
    pq.write_table(table, tmp)
    tmp.replace(target)


def filing_changed_companies(landing: Landing) -> set[str]:
    """Companies whose change events in this snapshot report a new annual accounts filing."""
    if not landing.table_exists("events_enheter"):
        return set()
    table = read_table(
        landing.root / "events_enheter", columns=["organisasjonsnummer", "changed_fields"]
    )
    needle = FILING_FIELD.lower()
    numbers = table["organisasjonsnummer"].to_pylist()
    changed = table["changed_fields"].to_pylist()
    return {
        orgnr
        for orgnr, fields in zip(numbers, changed, strict=True)
        if fields and needle in fields.lower()
    }


def _write(table_dir: Path, name: str, rows: list[dict], schema: pa.Schema) -> None:
    target = table_dir / name
    tmp = target.with_suffix(".parquet.tmp")
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), tmp)
    tmp.replace(target)


class RegnskapFetcher:
    """Fetch accounts per organisation number into batch files, skipping what is already done.

    A ledger file lists every organisation number that received a final answer (200 or 404).
    Rerunning continues after the ledger. A crash between writing a batch and its ledger entry
    can duplicate rows for that batch; the silver layer deduplicates on the accounts id.
    """

    def __init__(
        self,
        client: PoliteClient,
        landing: Landing,
        path_template: str = "/regnskapsregisteret/regnskap/{orgnr}",
        batch_size: int = 500,
        workers: int = 1,
    ) -> None:
        self.client = client
        self.landing = landing
        self.path_template = path_template
        self.batch_size = batch_size
        self.workers = max(1, workers)
        self.table_dir = landing.table_dir("regnskap")
        self.status_dir = landing.table_dir("regnskap_status")
        self.ledger_path = self.table_dir / "_fetched_orgnr.txt"

    def fetched(self) -> set[str]:
        if not self.ledger_path.exists():
            return set()
        return {
            line.strip()
            for line in self.ledger_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }

    def _fetch_one(self, orgnr: str):
        """One request through the shared, rate-limited client; None when retries are exhausted."""
        try:
            return self.client.get(self.path_template.format(orgnr=orgnr))
        except RetryError:
            return None

    def _next_batch_index(self) -> int:
        return len(list(self.status_dir.glob("batch-*.parquet")))

    def run(self, orgnrs: Iterable[str], limit: int | None = None) -> dict:
        done = self.fetched()
        todo = [o for o in orgnrs if o not in done]
        if limit is not None:
            todo = todo[:limit]
        log.info("regnskap: %d already fetched, %d to fetch", len(done), len(todo))
        totals = {"requested": len(todo), "ok": 0, "not_found": 0, "failed": 0, "rows": 0}
        for batch in _chunks(todo, self.batch_size):
            rows: list[dict] = []
            status_rows: list[dict] = []
            finished: list[str] = []
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                responses = list(pool.map(self._fetch_one, batch))
            for orgnr, response in zip(batch, responses, strict=True):
                if response is None:
                    status_rows.append(
                        {"organisasjonsnummer": orgnr, "http_status": 0, "n_regnskap": 0}
                    )
                    totals["failed"] += 1
                    continue
                if response.status_code == 200:
                    payload = response.json()
                    items = payload if isinstance(payload, list) else [payload]
                    rows.extend(flatten_regnskap(orgnr, item) for item in items)
                    status_rows.append(
                        {"organisasjonsnummer": orgnr, "http_status": 200, "n_regnskap": len(items)}
                    )
                    totals["ok"] += 1
                    finished.append(orgnr)
                elif response.status_code == 404:
                    status_rows.append(
                        {"organisasjonsnummer": orgnr, "http_status": 404, "n_regnskap": 0}
                    )
                    totals["not_found"] += 1
                    finished.append(orgnr)
                else:
                    status_rows.append(
                        {
                            "organisasjonsnummer": orgnr,
                            "http_status": response.status_code,
                            "n_regnskap": 0,
                        }
                    )
                    totals["failed"] += 1
            for row in status_rows:
                row["source_snapshot_id"] = self.landing.snapshot_id
            index = self._next_batch_index()
            name = f"batch-{index:05d}.parquet"
            if rows:
                _write(self.table_dir, name, rows, REGNSKAP_SCHEMA)
            _write(self.status_dir, name, status_rows, REGNSKAP_STATUS_SCHEMA)
            with self.ledger_path.open("a", encoding="utf-8") as ledger:
                ledger.write("".join(f"{o}\n" for o in finished))
            totals["rows"] += len(rows)
            log.info(
                "regnskap batch %d: %d ok, %d not found, %d failed so far",
                index,
                totals["ok"],
                totals["not_found"],
                totals["failed"],
            )
        summary = dict(totals)
        summary["fetched_total"] = len(self.fetched())
        self.landing.update_manifest("regnskap", summary)
        return summary

    def carry_forward(
        self, previous: Landing, kept: set[str], filing_changed: set[str], refresh_share: float
    ) -> dict:
        """Copy accounts from an earlier snapshot for companies that need no new request.

        Fetched again instead: companies without a final answer in the earlier snapshot, companies
        whose register entry reports a new annual accounts filing since then, and a rolling share
        chosen by a hash of the organisation number, so every company is refreshed within
        1/refresh_share snapshots. Copied rows keep the snapshot they were fetched in.
        """
        status = read_table(previous.root / "regnskap_status").to_pylist()
        final = {r["organisasjonsnummer"]: r for r in status if r["http_status"] in (200, 404)}
        buckets = int(round(1 / refresh_share)) if refresh_share > 0 else 0
        turn = self.landing.snapshot_id % buckets if buckets else -1

        def due(orgnr: str) -> bool:
            if buckets == 0:
                return False
            return int(hashlib.sha256(orgnr.encode("ascii")).hexdigest(), 16) % buckets == turn

        counts = {"new": 0, "filing_changed": 0, "refresh_due": 0, "carried_forward": 0}
        done = self.fetched()
        carry: list[str] = []
        for orgnr in sorted(kept):
            if orgnr in done:
                continue
            if orgnr not in final:
                counts["new"] += 1
            elif orgnr in filing_changed:
                counts["filing_changed"] += 1
            elif due(orgnr):
                counts["refresh_due"] += 1
            else:
                carry.append(orgnr)
        counts["carried_forward"] = len(carry)
        if carry:
            table = read_table(previous.root / "regnskap")
            mask = pc.is_in(table["organisasjonsnummer"], value_set=pa.array(carry, pa.string()))
            rows = table.filter(mask).select(REGNSKAP_SCHEMA.names).cast(REGNSKAP_SCHEMA)
            _write_table(self.table_dir, "carried-forward.parquet", rows)
            status_rows = [
                {
                    "organisasjonsnummer": orgnr,
                    "http_status": final[orgnr]["http_status"],
                    "n_regnskap": final[orgnr]["n_regnskap"],
                    "source_snapshot_id": final[orgnr].get("source_snapshot_id")
                    or previous.snapshot_id,
                }
                for orgnr in carry
            ]
            _write(self.status_dir, "carried-forward.parquet", status_rows, REGNSKAP_STATUS_SCHEMA)
            with self.ledger_path.open("a", encoding="utf-8") as ledger:
                ledger.write("".join(f"{o}\n" for o in carry))
        summary = {
            "previous_snapshot_id": previous.snapshot_id,
            "refresh_share": refresh_share,
            **counts,
        }
        log.info("regnskap carry-forward: %s", summary)
        earlier = self.landing.read_manifest().get("regnskap_carry_forward") or {}
        if done and earlier.get("previous_snapshot_id") == previous.snapshot_id:
            # A restart after an interruption plans only what is left. The plan from the first
            # start stays on record.
            log.info("regnskap carry-forward: resumed, the plan from the first start is kept")
        else:
            self.landing.update_manifest("regnskap_carry_forward", summary)
        return summary
