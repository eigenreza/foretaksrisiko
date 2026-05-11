from __future__ import annotations

from typer.testing import CliRunner

from conftest import KEPT_UNITS
from foretaksrisiko import __version__
from foretaksrisiko.acquire.enheter import acquire_enheter
from foretaksrisiko.acquire.roller import acquire_roller
from foretaksrisiko.acquire.underenheter import acquire_underenheter
from foretaksrisiko.acquire.verify import verify_landing
from foretaksrisiko.cli import app


def test_verify_report_on_synthetic_landing(
    enheter_opener, underenheter_opener, roller_opener, landing, scope
) -> None:
    acquire_enheter(enheter_opener, landing, scope)
    acquire_underenheter(underenheter_opener, landing, set(KEPT_UNITS))
    acquire_roller(roller_opener, landing, set(KEPT_UNITS))
    report = verify_landing(landing, scope)
    enheter = report["tables"]["enheter"]
    assert enheter["rows"] == 4 and enheter["distinct_orgnr"] == 4
    assert enheter["forms"] == {"AS": 3, "ASA": 1}
    assert enheter["konkurs_true"] == 1
    assert report["tables"]["underenheter"]["distinct_parents"] == 1
    assert report["tables"]["roller_counts"]["share_ceo_is_chair"] == 0.5
    assert report["tables"]["roller_links"]["by_rolletype"] == {"REVI": 1}
    checks = report["checks"]
    assert checks["enheter_unique_orgnr"] and checks["enheter_forms_in_scope"]
    assert checks["underenheter_parents_in_population"]
    assert checks["roller_links_both_ends_in_population"]
    # Synthetic numbers deliberately fail MOD11, so this one check must fail on fixtures.
    assert checks["enheter_all_valid_mod11"] is False
    assert enheter["valid_mod11_share"] == 0.0
    assert report["all_checks_passed"] is False


def test_cli_version_and_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output
    result = runner.invoke(app, ["acquire", "--help"])
    assert result.exit_code == 0
    for command in ("enheter", "underenheter", "roller", "klass", "sample", "regnskap", "verify"):
        assert command in result.output
