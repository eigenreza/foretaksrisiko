"""Checks on one snapshot's landing zone. Produces counts and shares only, never records."""

from __future__ import annotations

from collections import Counter

import pyarrow.compute as pc

from foretaksrisiko.acquire.landing import Landing, read_table
from foretaksrisiko.config import ScopeConfig
from foretaksrisiko.orgnr import is_valid_orgnr


def _share(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _non_null(table, column: str) -> int:
    return int(pc.sum(pc.is_valid(table.column(column))).as_py() or 0)


def _true_count(table, column: str) -> int:
    values = table.column(column).to_pylist()
    return sum(1 for v in values if v is True)


def verify_landing(landing: Landing, scope: ScopeConfig | None = None) -> dict:
    """Return a report with counts, shares and pass/fail checks for the landing tables."""
    scope = scope or ScopeConfig()
    report: dict = {"snapshot_id": landing.snapshot_id, "tables": {}, "checks": {}}
    checks = report["checks"]

    enheter = read_table(landing.root / "enheter")
    orgnrs = enheter.column("organisasjonsnummer").to_pylist()
    kept = set(orgnrs)
    forms = Counter(enheter.column("organisasjonsform").to_pylist())
    valid = sum(1 for o in orgnrs if is_valid_orgnr(o))
    report["tables"]["enheter"] = {
        "rows": len(orgnrs),
        "distinct_orgnr": len(kept),
        "valid_mod11_share": _share(valid, len(orgnrs)),
        "forms": dict(forms),
        "frivillighetsregisteret_true": _true_count(
            enheter, "registrert_i_frivillighetsregisteret"
        ),
        "share_with_naeringskode1": _share(_non_null(enheter, "naeringskode1"), len(orgnrs)),
        "share_with_kommunenummer": _share(
            _non_null(enheter, "forretningsadresse_kommunenummer"), len(orgnrs)
        ),
        "share_with_antall_ansatte": _share(_non_null(enheter, "antall_ansatte"), len(orgnrs)),
        "share_with_siste_innsendte_aarsregnskap": _share(
            _non_null(enheter, "siste_innsendte_aarsregnskap"), len(orgnrs)
        ),
        "share_with_kapital": _share(_non_null(enheter, "kapital_belop"), len(orgnrs)),
        "konkurs_true": _true_count(enheter, "konkurs"),
        "under_avvikling_true": _true_count(enheter, "under_avvikling"),
        "under_tvang_true": _true_count(enheter, "under_tvangsavvikling_eller_tvangsopplosning"),
        "er_i_konsern_true": _true_count(enheter, "er_i_konsern"),
    }
    checks["enheter_unique_orgnr"] = len(kept) == len(orgnrs)
    checks["enheter_forms_in_scope"] = set(forms) <= set(scope.organisasjonsformer)
    checks["enheter_no_frivillighetsregisteret"] = (
        report["tables"]["enheter"]["frivillighetsregisteret_true"] == 0
    )
    checks["enheter_all_valid_mod11"] = valid == len(orgnrs)

    if landing.table_exists("enheter_tekst"):
        text = read_table(landing.root / "enheter_tekst", columns=["organisasjonsnummer"])
        text_orgnr = text.column("organisasjonsnummer").to_pylist()
        report["tables"]["enheter_tekst"] = {"rows": len(text_orgnr)}
        checks["enheter_tekst_in_population"] = set(text_orgnr) <= kept

    if landing.table_exists("underenheter"):
        sub = read_table(
            landing.root / "underenheter", columns=["organisasjonsnummer", "overordnet_enhet"]
        )
        parents = sub.column("overordnet_enhet").to_pylist()
        sub_orgnr = sub.column("organisasjonsnummer").to_pylist()
        report["tables"]["underenheter"] = {
            "rows": len(sub_orgnr),
            "distinct_orgnr": len(set(sub_orgnr)),
            "distinct_parents": len(set(parents)),
            "share_of_population_with_sub_units": _share(len(set(parents)), len(kept)),
        }
        checks["underenheter_parents_in_population"] = set(parents) <= kept
        checks["underenheter_unique_orgnr"] = len(set(sub_orgnr)) == len(sub_orgnr)

    if landing.table_exists("roller_counts"):
        roles = read_table(landing.root / "roller_counts")
        role_orgnr = roles.column("organisasjonsnummer").to_pylist()
        n = len(role_orgnr)
        board = roles.column("board_size").to_pylist()
        report["tables"]["roller_counts"] = {
            "rows": n,
            "distinct_orgnr": len(set(role_orgnr)),
            "share_of_population_with_roles": _share(len(set(role_orgnr)), len(kept)),
            "share_has_ceo": _share(_true_count(roles, "has_ceo"), n),
            "share_has_chair": _share(_true_count(roles, "has_chair"), n),
            "share_ceo_is_chair": _share(_true_count(roles, "ceo_is_chair"), n),
            "share_has_auditor": _share(_true_count(roles, "has_auditor"), n),
            "share_has_accountant": _share(_true_count(roles, "has_accountant"), n),
            "mean_board_size": round(sum(board) / n, 3) if n else None,
            "board_size_distribution": dict(sorted(Counter(min(b, 10) for b in board).items())),
        }
        checks["roller_counts_in_population"] = set(role_orgnr) <= kept
        checks["roller_counts_unique_orgnr"] = len(set(role_orgnr)) == n

    if landing.table_exists("roller_links"):
        links = read_table(landing.root / "roller_links")
        focal = links.column("organisasjonsnummer").to_pylist()
        holders = links.column("rolleholder_organisasjonsnummer").to_pylist()
        report["tables"]["roller_links"] = {
            "rows": len(focal),
            "distinct_focal": len(set(focal)),
            "distinct_holders": len(set(holders)),
            "by_rolletype": dict(Counter(links.column("rolletype").to_pylist())),
        }
        checks["roller_links_both_ends_in_population"] = set(focal) <= kept and set(holders) <= kept

    if landing.table_exists("sample"):
        sample = read_table(landing.root / "sample")
        sample_orgnr = sample.column("organisasjonsnummer").to_pylist()
        strata = Counter(
            zip(
                sample.column("stratum_section").to_pylist(),
                sample.column("stratum_county").to_pylist(),
                strict=True,
            )
        )
        report["tables"]["sample"] = {
            "rows": len(sample_orgnr),
            "distinct_orgnr": len(set(sample_orgnr)),
            "n_strata": len(strata),
            "sections": dict(sorted(Counter(s for s, _ in strata.elements()).items())),
        }
        checks["sample_in_population"] = set(sample_orgnr) <= kept
        checks["sample_unique_orgnr"] = len(set(sample_orgnr)) == len(sample_orgnr)

    klass_dir = landing.root / "klass"
    if klass_dir.is_dir():
        report["tables"]["klass"] = {
            sub.name: read_table(sub).num_rows
            for sub in sorted(klass_dir.iterdir())
            if sub.is_dir()
        }

    if landing.table_exists("regnskap_status"):
        status = read_table(landing.root / "regnskap_status")
        codes = Counter(status.column("http_status").to_pylist())
        report["tables"]["regnskap_status"] = {
            "rows": status.num_rows,
            "by_http_status": dict(codes),
        }
    if landing.table_exists("regnskap"):
        regnskap = read_table(
            landing.root / "regnskap",
            columns=["organisasjonsnummer", "regnskapstype", "regnskap_id"],
        )
        reg_orgnr = regnskap.column("organisasjonsnummer").to_pylist()
        report["tables"]["regnskap"] = {
            "rows": regnskap.num_rows,
            "distinct_orgnr": len(set(reg_orgnr)),
            "by_regnskapstype": dict(Counter(regnskap.column("regnskapstype").to_pylist())),
            "years_per_company": dict(sorted(Counter(Counter(reg_orgnr).values()).items())),
        }
        checks["regnskap_in_population"] = set(reg_orgnr) <= kept

    report["all_checks_passed"] = all(checks.values())
    return report
