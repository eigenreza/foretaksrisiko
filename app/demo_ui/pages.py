"""The six pages of the demo. Each function renders one page for one language."""

from __future__ import annotations

import dataclasses
import math

import pandas as pd
import streamlit as st

from demo_ui import assistant, charts, data
from demo_ui.texts import fmt_decimal, fmt_money, fmt_number, fmt_percent, text
from foretaksrisiko.demo.synthetic import (
    RATIO_FEATURES,
    Artefacts,
    Inputs,
    build_features,
    drivers,
    peer_position,
    score,
)
from foretaksrisiko.figures.labels import GROUP_TYPE_ORDER, Labels

MAIN_MODEL = "hgb_calibrated"
HEADLINE_METRICS = ("average_precision", "precision_top_1pct", "lift_top_1pct", "brier")
TABLE_METRICS = (
    "average_precision",
    "precision_top_1pct",
    "precision_top_5pct",
    "lift_top_1pct",
    "lift_top_5pct",
    "roc_auc",
    "brier",
    "expected_calibration_error",
)
PERCENT_INPUTS = ("equity_ratio", "operating_margin", "revenue_growth", "asset_growth")
MONEY_INPUTS = ("share_capital", "total_assets", "revenue")


def render(page: str, lang: str) -> None:
    {
        "oversikt": oversikt,
        "assistent": assistant.page,
        "monstre": monstre,
        "modellen": modellen,
        "prov_selv": prov_selv,
        "overvaking": overvaking,
        "personvern": personvern,
    }[page](lang)


# -- helpers ---------------------------------------------------------------------------------------


def _metric_row(frame: pd.DataFrame, model: str, metric: str, ablation: str = "all"):
    rows = frame[
        (frame["model"] == model)
        & (frame["ablation"] == ablation)
        & (frame["split"] == "test")
        & (frame["metric"] == metric)
    ]
    if rows.empty:
        return None
    with_interval = rows[rows["ci_low"].notna()]
    seed_one = rows[rows["seed"] == 1]
    chosen = with_interval if not with_interval.empty else seed_one if not seed_one.empty else rows
    return chosen.iloc[0]


def _format_metric(metric: str, value: float, lang: str) -> str:
    if metric.startswith("lift"):
        return fmt_decimal(value, lang, 1)
    if metric in ("brier", "expected_calibration_error"):
        return fmt_decimal(value, lang, 4)
    # Small values get a third decimal, so an interval does not read "0.01 to 0.01".
    return fmt_decimal(value, lang, 3 if abs(value) < 0.1 else 2)


def _interval(row, metric: str, lang: str) -> str:
    if row is None or pd.isna(row["ci_low"]) or pd.isna(row["ci_high"]):
        return ""
    joiner = " til " if lang == "no" else " to "
    return (
        _format_metric(metric, row["ci_low"], lang)
        + joiner
        + _format_metric(metric, row["ci_high"], lang)
    )


def _named(key: str, fallback: str, lang: str) -> str:
    """The text for ``key`` in the language, or the fallback when there is none."""
    try:
        return text(key, lang)
    except KeyError:
        return fallback


def _show(target, chart, lang: str) -> None:
    """Draw a chart with the number format of the chosen language."""
    target.altair_chart(charts.localized(chart, lang), width="stretch")


Tile = tuple[str, str, str | None, list[str]]


def _tiles(items: list[Tile]) -> None:
    """Metric tiles: label, value, help and captions, each kind in its own row.

    The label is text that wraps, because the metric's own label is cut off on narrow
    screens, and the separate rows keep the values level when one label needs two lines.
    """
    for column, (label, _, help_text, _) in zip(st.columns(len(items)), items, strict=True):
        column.markdown(f"**{label}**", help=help_text)
    for column, (label, value, _, _) in zip(st.columns(len(items)), items, strict=True):
        column.metric(label, value, label_visibility="collapsed")
    for column, (*_, captions) in zip(st.columns(len(items)), items, strict=True):
        for caption in captions:
            column.caption(caption)


def _table_toggle(frame: pd.DataFrame, lang: str, key: str) -> None:
    with st.expander(text("common.table", lang)):
        st.dataframe(frame, hide_index=True, width="stretch")


def _group_label(frame: pd.DataFrame, lang: str) -> str:
    return "group_label_no" if lang == "no" else "group_label_en"


# -- pages -----------------------------------------------------------------------------------------


def _go_to(page: str) -> None:
    """Button callback: open another page."""
    st.session_state["page"] = page


def oversikt(lang: str) -> None:
    labels = Labels(lang)
    st.title(text("oversikt.title", lang))
    st.markdown(text("oversikt.lead", lang))
    with st.container(border=True):
        st.subheader(text("oversikt.try_title", lang))
        st.markdown(text("oversikt.try_text", lang))
        st.button(
            text("oversikt.try_button", lang),
            type="primary",
            on_click=_go_to,
            args=("prov_selv",),
            key="open_try",
        )
    st.markdown(text("oversikt.pages", lang))
    st.subheader(text("oversikt.what_title", lang))
    st.markdown(text("oversikt.what", lang))

    metrics = data.table("evaluation_metrics")
    if metrics is not None:
        st.subheader(text("oversikt.results_title", lang))
        tiles = []
        for metric in HEADLINE_METRICS:
            row = _metric_row(metrics, MAIN_MODEL, metric)
            if row is None:
                continue
            interval = _interval(row, metric, lang)
            captions = (
                [text("oversikt.interval", lang).format(interval=interval)] if interval else []
            )
            tiles.append(
                (labels.metric(metric), _format_metric(metric, row["value"], lang), None, captions)
            )
        if tiles:
            _tiles(tiles)
        st.markdown(text("oversikt.results_text", lang))
        st.markdown(text("oversikt.accounts", lang))
        st.caption(text("oversikt.results_note", lang))

    pipeline = data.figure_path("pipeline", lang)
    st.subheader(text("oversikt.pipeline_title", lang))
    st.markdown(text("oversikt.pipeline", lang))
    if pipeline is not None:
        st.image(str(pipeline), width="stretch")

    st.subheader(text("oversikt.meaning_title", lang))
    st.markdown(text("oversikt.meaning", lang))
    st.caption(text("common.source", lang))


def monstre(lang: str) -> None:
    labels = Labels(lang)
    st.title(text("monstre.title", lang))
    st.markdown(text("monstre.lead", lang))

    by_section = data.table("population_by_section")
    by_fylke = data.table("population_by_fylke")
    left, right = st.columns(2)
    with left:
        st.subheader(text("monstre.section_title", lang))
        if by_section is None:
            st.info(text("common.missing", lang))
        else:
            column = "section_label_no" if lang == "no" else "section_label_en"
            frame = by_section.rename(columns={column: "label"})
            _show(
                st,
                charts.horizontal_bars(
                    frame,
                    "label",
                    "n",
                    labels.group_type("nace_section"),
                    labels("axis.companies"),
                ),
                lang,
            )
            unknown = frame.loc[frame["nace_section"] == "missing", "n"].sum()
            if unknown and frame["n"].sum():
                st.caption(
                    text("monstre.unknown", lang).format(
                        share=fmt_percent(unknown / frame["n"].sum(), lang, 1)
                    )
                )
            _table_toggle(frame[["label", "n"]], lang, "section")
    with right:
        st.subheader(text("monstre.fylke_title", lang))
        if by_fylke is None:
            st.info(text("common.missing", lang))
        else:
            frame = by_fylke.rename(columns={"fylke_name": "label"})
            _show(
                st,
                charts.horizontal_bars(
                    frame, "label", "n", labels.group_type("fylke"), labels("axis.companies")
                ),
                lang,
            )
            _table_toggle(frame[["label", "n"]], lang, "fylke")

    fairness = data.table("fairness")
    st.subheader(text("monstre.base_title", lang))
    st.markdown(text("monstre.base_text", lang))
    if fairness is None:
        st.info(text("common.missing", lang))
    else:
        rows = fairness[(fairness["model"] == MAIN_MODEL) & (~fairness["per_group_threshold"])]
        group_type = st.selectbox(
            text("monstre.group_type", lang),
            [g for g in GROUP_TYPE_ORDER if g in set(rows["group_type"])],
            format_func=labels.group_type,
            key="monstre_group_type",
        )
        subset = rows[rows["group_type"] == group_type].copy()
        label_column = _group_label(subset, lang)
        subset = subset.rename(columns={label_column: "label"}).sort_values("base_rate")
        chart = charts.horizontal_bars(
            subset,
            "label",
            "base_rate",
            labels.group_type(group_type),
            labels("fairness.base_rate"),
            charts.ORANGE,
            ".2%",
        )
        _show(st, chart, lang)
        _table_toggle(subset[["label", "n", "base_rate"]], lang, "base")

    network = data.table("network_degree")
    st.subheader(text("monstre.network_title", lang))
    st.markdown(text("monstre.network_text", lang))
    if network is None:
        st.info(text("common.missing", lang))
    else:
        _show(st, charts.network_chart(network, labels), lang)
        _table_toggle(network, lang, "network")

    quantiles = data.table("score_quantiles")
    st.subheader(text("monstre.scores_title", lang))
    st.markdown(text("monstre.scores_text", lang))
    if quantiles is None:
        st.info(text("common.missing", lang))
    else:
        test = quantiles[quantiles["split"] == "test"]
        _show(st, charts.score_quantile_chart(test, labels), lang)


def modellen(lang: str) -> None:
    labels = Labels(lang)
    st.title(text("modellen.title", lang))
    st.markdown(text("modellen.lead", lang))

    metrics = data.table("evaluation_metrics")
    st.subheader(text("modellen.metrics_title", lang))
    if metrics is None:
        st.info(text("common.missing", lang))
    else:
        rows = []
        for model in charts.MODEL_ORDER:
            for metric in TABLE_METRICS:
                row = _metric_row(metrics, model, metric)
                if row is None or pd.isna(row["value"]):
                    continue
                rows.append(
                    {
                        text("modellen.col_model", lang): labels.model(model),
                        text("modellen.col_metric", lang): labels.metric(metric),
                        text("modellen.col_value", lang): _format_metric(
                            metric, row["value"], lang
                        ),
                        text("modellen.col_interval", lang): _interval(row, metric, lang),
                    }
                )
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.markdown(text("modellen.metrics_text", lang))

    topk = data.table("topk")
    st.subheader(text("modellen.topk_title", lang))
    st.markdown(text("modellen.topk_text", lang))
    if topk is None:
        st.info(text("common.missing", lang))
    else:
        precision, lift = charts.topk_charts(topk, labels)
        left, right = st.columns(2)
        _show(left, precision, lang)
        _show(right, lift, lang)
        _table_toggle(topk, lang, "topk")

    calibration = data.table("calibration")
    explanations = data.table("explanations")
    left, right = st.columns(2)
    with left:
        st.subheader(text("modellen.calibration_title", lang))
        st.markdown(text("modellen.calibration_text", lang))
        if calibration is None:
            st.info(text("common.missing", lang))
        else:
            _show(st, charts.calibration_chart(calibration, labels), lang)
            _table_toggle(calibration, lang, "calibration")
    with right:
        st.subheader(text("modellen.shap_title", lang))
        st.markdown(text("modellen.shap_text", lang))
        if explanations is None:
            st.info(text("common.missing", lang))
        else:
            shap = (
                explanations[explanations["model"] == "hgb"]
                .sort_values("mean_abs_shap", ascending=False)
                .head(15)
            )
            _show(
                st,
                charts.feature_bars(shap, "mean_abs_shap", labels("axis.mean_abs_shap"), labels),
                lang,
            )

    st.subheader(text("modellen.ablation_title", lang))
    st.markdown(text("modellen.ablation_text", lang))
    if metrics is None:
        st.info(text("common.missing", lang))
    else:
        rows = []
        for ablation in ("all", "no_network", "no_accounts", "no_text", "register_roles_only"):
            row = _metric_row(metrics, MAIN_MODEL, "average_precision", ablation)
            if row is not None:
                rows.append({"ablation": ablation, "value": float(row["value"])})
        if rows:
            _show(st, charts.ablation_chart(pd.DataFrame(rows), labels), lang)

    fairness = data.table("fairness")
    st.subheader(text("modellen.fairness_title", lang))
    st.markdown(text("modellen.fairness_text", lang))
    if fairness is None:
        st.info(text("common.missing", lang))
    else:
        left, right = st.columns(2)
        models = [m for m in charts.MODEL_ORDER if m in set(fairness["model"])]
        model = left.selectbox(
            text("modellen.fairness_model", lang),
            models,
            # The text above describes the calibrated probability, so the chart starts there.
            index=models.index(MAIN_MODEL) if MAIN_MODEL in models else 0,
            format_func=labels.model,
            key="fairness_model",
        )
        group_type = right.selectbox(
            text("monstre.group_type", lang),
            [g for g in GROUP_TYPE_ORDER if g in set(fairness["group_type"])],
            format_func=labels.group_type,
            key="fairness_group_type",
        )
        mitigated = st.checkbox(text("modellen.fairness_threshold", lang), key="fairness_pgt")
        subset = fairness[
            (fairness["model"] == model)
            & (fairness["group_type"] == group_type)
            & (fairness["per_group_threshold"] == mitigated)
        ].copy()
        label_column = _group_label(subset, lang)
        if subset.empty:
            st.info(text("common.missing", lang))
        else:
            _show(st, charts.fairness_chart(subset, labels, label_column), lang)
            _table_toggle(
                subset[[label_column, "n", "base_rate", "flag_rate", "precision"]], lang, "fair"
            )


def _peer_group_text(group: str, lang: str) -> str:
    kind, _, rest = group.partition(":")
    code, _, band = rest.partition("|")
    if kind == "division":
        head = text("prov.peer_division", lang).format(code=code)
    elif kind == "section":
        head = text("prov.peer_section", lang).format(code=code)
    else:
        head = text("prov.peer_all", lang)
        band = code
    return head + ", " + text("prov.peer_band", lang).format(band=band)


# Widget key for each input, so that an example company can fill the form in one click.
INPUT_KEYS = {
    "nace_division": "in_nace_division",
    "fylke_code": "in_fylke_code",
    "age_years": "in_age_years",
    "share_capital": "in_share_capital",
    "registered_employees": "in_employees",
    "registered_vat": "in_vat",
    "in_group": "in_group",
    "n_changes_12m": "in_changes",
    "board_size": "in_board",
    "has_ceo": "in_has_ceo",
    "ceo_is_chair": "in_ceo_chair",
    "has_auditor": "in_auditor",
    "has_accountant": "in_accountant",
    "n_role_events_12m": "in_roles",
    "days_since_board_change": "in_board_days",
    "days_since_ceo_change": "in_ceo_days",
    "has_accounts": "in_has_accounts",
    "total_assets": "in_assets",
    "revenue": "in_revenue",
    "equity_ratio": "in_equity",
    "operating_margin": "in_margin",
    "current_ratio": "in_current",
    "cash_ratio": "in_cash",
    "revenue_growth": "in_rg",
    "asset_growth": "in_ag",
    "acc_age_days": "in_acc_age",
    "acc_filing_lag_days": "in_acc_lag",
    "acc_n_statements_known": "in_acc_n",
}
# Inputs shown as whole numbers in the form.
INT_INPUTS = {
    "share_capital", "n_changes_12m", "board_size", "n_role_events_12m",
    "days_since_board_change", "days_since_ceo_change", "total_assets", "revenue",
    "acc_age_days", "acc_filing_lag_days", "acc_n_statements_known",
}  # fmt: skip
# Example companies: changes from the typical company, chosen to show how the scores react.
PRESETS = {
    "typical": {},
    "solid": {"age_years": 25.0, "total_assets": 50_000_000, "revenue": 80_000_000,
              "equity_ratio": 0.6, "operating_margin": 0.1, "has_auditor": True,
              "registered_employees": True, "board_size": 5, "acc_n_statements_known": 10},
    "late": {"acc_age_days": 900, "acc_filing_lag_days": 260},
    "weak": {"equity_ratio": -0.4, "operating_margin": -0.3, "current_ratio": 0.4,
             "cash_ratio": 0.05, "revenue_growth": -0.4},
    "unusual": {"operating_margin": 0.9, "revenue_growth": 2.5, "asset_growth": 2.0},
}  # fmt: skip


# Decimal inputs: low, high and step of the slider grid. Streamlit's slider shows decimal
# points, so these use a select slider with labels in the language's number format. The options
# are the grid plus the typical value and every example value, so no value is ever rounded.
DECIMAL_GRIDS = {
    "age_years": (0.0, 60.0, 0.5),
    "equity_ratio": (-1.0, 1.0, 0.05),
    "operating_margin": (-1.0, 1.0, 0.05),
    "current_ratio": (0.0, 5.0, 0.1),
    "cash_ratio": (0.0, 3.0, 0.05),
    "revenue_growth": (-1.0, 3.0, 0.05),
    "asset_growth": (-1.0, 3.0, 0.05),
}


def _decimal_options(name: str, typical: Inputs) -> list[float]:
    low, high, step = DECIMAL_GRIDS[name]
    grid = {round(low + i * step, 2) for i in range(int(round((high - low) / step)) + 1)}
    examples = {float(changes[name]) for changes in PRESETS.values() if name in changes}
    return sorted(grid | examples | {float(getattr(typical, name))})


def _decimal_label(name: str, value: float, lang: str) -> str:
    """A slider label: a percentage for shares and growth, otherwise up to two decimals."""
    if name in PERCENT_INPUTS:
        whole = abs(value * 100 - round(value * 100)) < 1e-9
        return fmt_percent(value, lang, 0 if whole else 1)
    shown = f"{value:.2f}".rstrip("0").rstrip(".")
    return shown.replace(".", ",") if lang == "no" else shown


def _apply_preset(name: str, typical: Inputs) -> None:
    """Fill every form field from the typical company, then apply the example's changes."""
    values = {**dataclasses.asdict(typical), **PRESETS[name]}
    for field, key in INPUT_KEYS.items():
        value = values[field]
        if isinstance(value, bool):
            st.session_state[key] = value
        elif field in INT_INPUTS:
            st.session_state[key] = int(value)
        elif isinstance(value, int | float):
            st.session_state[key] = float(value)
        else:
            st.session_state[key] = value


def _preset_buttons(typical: Inputs, lang: str) -> None:
    st.markdown(text("prov.presets_lead", lang))
    # A row that wraps, with each button as wide as its label, so no label is cut off.
    row = st.container(horizontal=True, gap="small")
    for name in PRESETS:
        row.button(
            text(f"prov.preset.{name}", lang),
            key=f"preset_{name}",
            on_click=_apply_preset,
            args=(name, typical),
            width="content",
        )


def _inputs_form(art: Artefacts, typical: Inputs, lang: str) -> Inputs:
    """Sliders and dropdowns for the synthetic company, starting from the typical company."""
    name_column = "name_no" if lang == "no" else "name_en"
    divisions = art.divisions.sort_values("code")
    division_names = dict(zip(divisions["code"], divisions[name_column], strict=True))
    fylker = art.fylker.sort_values("code")
    fylke_names = dict(zip(fylker["code"], fylker[name_column], strict=True))
    division_codes = list(division_names)
    fylke_codes = list(fylke_names)

    def label(name: str) -> str:
        return text(f"prov.in.{name}", lang)

    def decimal(name: str) -> float:
        """A slider for a decimal input, with labels in the language's number format."""
        return float(
            st.select_slider(
                label(name),
                options=_decimal_options(name, typical),
                value=float(getattr(typical, name)),
                format_func=lambda v: _decimal_label(name, v, lang),
                key=INPUT_KEYS[name],
            )
        )

    values: dict[str, object] = {}
    with st.expander(text("prov.group_register", lang), expanded=True):
        values["nace_division"] = st.selectbox(
            label("nace_division"),
            division_codes,
            index=division_codes.index(typical.nace_division)
            if typical.nace_division in division_codes
            else 0,
            format_func=lambda c: f"{c} {division_names[c]}",
            key="in_nace_division",
        )
        values["fylke_code"] = st.selectbox(
            label("fylke_code"),
            fylke_codes,
            index=fylke_codes.index(typical.fylke_code) if typical.fylke_code in fylke_codes else 0,
            format_func=lambda c: f"{c} {fylke_names[c]}",
            key="in_fylke_code",
        )
        values["age_years"] = decimal("age_years")
        values["share_capital"] = float(
            st.number_input(
                label("share_capital"),
                min_value=0,
                max_value=1_000_000_000,
                value=int(typical.share_capital),
                step=10_000,
                key="in_share_capital",
            )
        )
        values["registered_employees"] = st.checkbox(
            label("registered_employees"), typical.registered_employees, key="in_employees"
        )
        values["registered_vat"] = st.checkbox(
            label("registered_vat"), typical.registered_vat, key="in_vat"
        )
        values["in_group"] = st.checkbox(label("in_group"), typical.in_group, key="in_group")
        values["n_changes_12m"] = st.slider(
            label("n_changes_12m"), 0, 20, int(typical.n_changes_12m), key="in_changes"
        )
    with st.expander(text("prov.group_roles", lang)):
        values["board_size"] = st.slider(
            label("board_size"), 1, 10, max(int(typical.board_size), 1), key="in_board"
        )
        values["has_ceo"] = st.checkbox(label("has_ceo"), typical.has_ceo, key="in_has_ceo")
        values["ceo_is_chair"] = st.checkbox(
            label("ceo_is_chair"), typical.ceo_is_chair, key="in_ceo_chair"
        )
        values["has_auditor"] = st.checkbox(
            label("has_auditor"), typical.has_auditor, key="in_auditor"
        )
        values["has_accountant"] = st.checkbox(
            label("has_accountant"), typical.has_accountant, key="in_accountant"
        )
        values["n_role_events_12m"] = st.slider(
            label("n_role_events_12m"), 0, 20, int(typical.n_role_events_12m), key="in_roles"
        )
        values["days_since_board_change"] = st.slider(
            label("days_since_board_change"),
            0,
            3650,
            int(typical.days_since_board_change),
            key="in_board_days",
        )
        values["days_since_ceo_change"] = st.slider(
            label("days_since_ceo_change"),
            0,
            3650,
            int(typical.days_since_ceo_change),
            key="in_ceo_days",
        )
    with st.expander(text("prov.group_accounts", lang), expanded=True):
        values["has_accounts"] = st.checkbox(
            label("has_accounts"), typical.has_accounts, key="in_has_accounts"
        )
        values["total_assets"] = float(
            st.number_input(
                label("total_assets"),
                min_value=0,
                max_value=100_000_000_000,
                value=int(typical.total_assets),
                step=100_000,
                key="in_assets",
            )
        )
        values["revenue"] = float(
            st.number_input(
                label("revenue"),
                min_value=0,
                max_value=100_000_000_000,
                value=int(typical.revenue),
                step=100_000,
                key="in_revenue",
            )
        )
        for name in (
            "equity_ratio",
            "operating_margin",
            "current_ratio",
            "cash_ratio",
            "revenue_growth",
            "asset_growth",
        ):
            values[name] = decimal(name)
        values["acc_age_days"] = st.slider(
            label("acc_age_days"), 0, 2000, int(typical.acc_age_days), key="in_acc_age"
        )
        values["acc_filing_lag_days"] = st.slider(
            label("acc_filing_lag_days"),
            0,
            500,
            int(typical.acc_filing_lag_days),
            key="in_acc_lag",
            help=text("prov.help.acc_filing_lag_days", lang),
        )
        values["acc_n_statements_known"] = st.slider(
            label("acc_n_statements_known"),
            0,
            15,
            int(typical.acc_n_statements_known),
            key="in_acc_n",
        )
    return Inputs(**values)


def _format_input(name: str, value, lang: str) -> str:
    if isinstance(value, bool):
        return ("ja" if value else "nei") if lang == "no" else ("yes" if value else "no")
    if name in PERCENT_INPUTS:
        return fmt_percent(float(value), lang, 0)
    if name in MONEY_INPUTS:
        return fmt_money(float(value), lang)
    if isinstance(value, float):
        return fmt_decimal(value, lang, 1)
    return str(value)


def _comparison(reference: dict[str, float] | None, lang: str) -> str:
    """The median company and the base rate, so a single probability can be read in context."""
    metrics = data.table("evaluation_metrics")
    if not reference or "0.50" not in reference or metrics is None:
        return ""
    row = _metric_row(metrics, MAIN_MODEL, "base_rate")
    if row is None:
        return ""
    return text("prov.out.comparison", lang).format(
        median=fmt_percent(reference["0.50"], lang, 2), base=fmt_percent(row["value"], lang, 2)
    )


def prov_selv(lang: str) -> None:
    labels = Labels(lang)
    st.title(text("prov.title", lang))
    st.markdown(text("prov.lead", lang))
    with st.expander(text("prov.how_title", lang), expanded=True):
        st.markdown(text("prov.how", lang))
    art = data.artefacts()
    if art is None:
        st.warning(text("prov.missing", lang))
        return
    typical = art.typical_inputs()
    reference = data.probability_quantiles()
    _preset_buttons(typical, lang)

    form_column, result_column = st.columns([2, 3])
    with form_column:
        inputs = _inputs_form(art, typical, lang)
    features, context = build_features(inputs, art)
    result = score(features, art, reference)

    with result_column:
        st.caption(text("prov.disclaimer", lang))
        if not inputs.has_accounts and inputs.age_years >= 2:
            st.info(text("prov.note_no_accounts", lang))
        elif result.probability >= 0.2:
            st.info(text("prov.note_high", lang))
        probability_notes = []
        if result.probability_percentile is not None:
            probability_notes.append(
                text("prov.out.higher_than", lang).format(
                    pct=fmt_percent(result.probability_percentile, lang, 0)
                )
            )
        comparison = _comparison(reference, lang)
        if comparison:
            probability_notes.append(comparison)
        anomaly_notes = []
        if result.mahalanobis_percentile is not None:
            anomaly_notes.append(
                text("prov.out.higher_than_reference", lang).format(
                    pct=fmt_percent(result.mahalanobis_percentile, lang, 0)
                )
            )
        _tiles(
            [
                (
                    text("prov.out.probability", lang),
                    fmt_percent(result.probability, lang, 2),
                    text("prov.out.probability_help", lang),
                    probability_notes,
                ),
                (
                    text("prov.out.mahalanobis", lang),
                    fmt_decimal(result.mahalanobis, lang, 2),
                    text("prov.out.mahalanobis_help", lang),
                    anomaly_notes,
                ),
            ]
        )
        group_size = max(
            (s[0] for f in RATIO_FEATURES if (s := art.stats(context["peer_group"], f))),
            default=None,
        )
        _tiles(
            [
                (
                    text("prov.out.extreme", lang),
                    str(result.n_extreme_z),
                    text("prov.out.extreme_help", lang),
                    [],
                ),
                (
                    text("prov.out.peer_group", lang),
                    fmt_number(group_size, lang) if group_size else "",
                    text("prov.out.peer_group_help", lang),
                    [_peer_group_text(context["peer_group"], lang)],
                ),
            ]
        )

        peers_tab, drivers_tab, features_tab = st.tabs(
            [
                text("prov.tab_peers", lang),
                text("prov.tab_drivers", lang),
                text("prov.tab_features", lang),
            ]
        )
        with peers_tab:
            st.markdown(text("prov.peers_text", lang))
            position = peer_position(features, context["peer_group"], art)
            if position["z"].notna().sum() == 0:
                st.info(text("prov.peers_none", lang))
            else:
                if not inputs.has_accounts:
                    st.info(text("prov.peers_none", lang))
                _show(
                    st,
                    charts.z_chart(
                        position, labels, text("prov.z_label", lang), text("prov.z_extreme", lang)
                    ),
                    lang,
                )
                table = position.dropna(subset=["z"]).copy()
                table["feature"] = table["feature"].map(labels.feature)
                table = table.rename(
                    columns={
                        "feature": text("prov.col_feature", lang),
                        "value": text("prov.col_value", lang),
                        "median": text("prov.col_median", lang),
                        "z": text("prov.col_z", lang),
                        "pct": text("prov.col_pct", lang),
                        "n": text("prov.col_n", lang),
                    }
                ).drop(columns=["mad"])
                _table_toggle(table, lang, "peers")
        with drivers_tab:
            st.markdown(text("prov.drivers_text", lang))
            table = drivers(inputs, art, typical)
            if table.empty:
                st.info(text("prov.drivers_none", lang))
            else:
                table["label"] = table["input"].map(lambda n: text(f"prov.in.{n}", lang))
                _show(
                    st,
                    charts.driver_chart(
                        table.head(10),
                        labels,
                        text("prov.delta_label", lang),
                        text("prov.delta_up", lang),
                        text("prov.delta_down", lang),
                    ),
                    lang,
                )
                typical_result = score(build_features(typical, art)[0], art)
                st.caption(
                    text("prov.drivers_sum", lang).format(
                        total=fmt_decimal(table["delta_probability"].sum() * 100, lang, 2),
                        company=fmt_percent(result.probability, lang, 2),
                        typical=fmt_percent(typical_result.probability, lang, 2),
                    )
                )
                shown = pd.DataFrame(
                    {
                        text("prov.col_input", lang): table["label"],
                        text("prov.col_value", lang): [
                            _format_input(n, v, lang)
                            for n, v in zip(table["input"], table["value"], strict=True)
                        ],
                        text("prov.col_typical", lang): [
                            _format_input(n, v, lang)
                            for n, v in zip(table["input"], table["typical"], strict=True)
                        ],
                        text("prov.col_delta", lang): [
                            fmt_decimal(d * 100, lang, 2) for d in table["delta_probability"]
                        ],
                    }
                )
                _table_toggle(shown, lang, "drivers")
        with features_tab:
            st.markdown(text("prov.features_text", lang))
            rows = [
                {
                    text("prov.col_feature", lang): labels.feature(name),
                    "id": name,
                    text("prov.col_value", lang): ""
                    if value is None or (isinstance(value, float) and math.isnan(value))
                    else (fmt_decimal(value, lang, 3) if isinstance(value, float) else str(value)),
                }
                for name, value in ((n, features.get(n)) for n in art.meta["features"])
            ]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def overvaking(lang: str) -> None:
    labels = Labels(lang)
    st.title(text("overvaking.title", lang))
    st.markdown(text("overvaking.lead", lang))
    drift = data.table("drift")
    summary = data.table("score_summary")
    if drift is None and summary is None:
        st.info(text("overvaking.missing", lang))
        return
    scenarios = sorted(
        set(drift["scenario"].fillna("default")) if drift is not None else set()
    ) or ["default"]
    scenario = st.selectbox(
        text("overvaking.scenario", lang),
        scenarios,
        format_func=lambda key: _named(f"overvaking.scenario.{key}", key, lang),
        key="monitoring_scenario",
    )
    st.caption(text("overvaking.scenario_text", lang))

    if drift is not None:
        frame = drift.copy()
        frame["scenario"] = frame["scenario"].fillna("default")
        frame = frame[frame["scenario"] == scenario]
        snapshots = sorted(frame["snapshot_id"].unique())
        metrics = sorted(frame["metric"].unique())
        left, right = st.columns(2)
        snapshot = left.selectbox(
            text("overvaking.snapshot", lang), snapshots, index=len(snapshots) - 1, key="mon_snap"
        )
        metric = right.selectbox(
            text("overvaking.metric", lang),
            metrics,
            index=metrics.index("psi") if "psi" in metrics else 0,
            format_func=lambda key: _named(f"overvaking.metric.{key}", key, lang),
            key="mon_metric",
        )
        subset = frame[(frame["snapshot_id"] == snapshot) & (frame["metric"] == metric)]
        subset = subset.sort_values("value", ascending=False).head(15)
        st.subheader(text("overvaking.drift_title", lang))
        if subset.empty:
            st.info(text("common.missing", lang))
        else:
            statuses = {k: text(f"overvaking.status.{k}", lang) for k in ("ok", "warn", "alert")}
            metric_name = _named(f"overvaking.metric.{metric}", metric, lang)
            _show(st, charts.drift_chart(subset, labels, metric_name, statuses), lang)
        st.subheader(text("overvaking.events_title", lang))
        events = frame[frame["severity"].isin(["warn", "alert"])]
        if events.empty:
            st.info(text("overvaking.no_events", lang))
        else:
            shown = events.copy()
            shown["feature"] = shown["feature"].map(labels.feature)
            shown["metric"] = shown["metric"].map(
                lambda key: _named(f"overvaking.metric.{key}", key, lang)
            )
            shown["severity"] = shown["severity"].map(
                lambda key: _named(f"overvaking.status.{key}", key, lang)
            )
            shown["value"] = shown["value"].map(lambda v: fmt_decimal(float(v), lang, 4))
            columns = ["snapshot_id", "feature", "metric", "value", "severity"]
            if shown["snapshot_id"].nunique() == 1:
                # One snapshot only: the column adds nothing and pushes the table wide.
                columns.remove("snapshot_id")
            names = {c: text(f"overvaking.col.{c}", lang) for c in columns}
            shown = shown[columns].rename(columns=names)
            # Narrow columns for the short values, so the whole table fits the page.
            small = {
                names[c]: st.column_config.Column(width="small") for c in ("value", "severity")
            }
            st.dataframe(shown, hide_index=True, width="stretch", column_config=small)

    if summary is not None:
        st.subheader(text("overvaking.scores_title", lang))
        frame = summary.copy()
        frame["scenario"] = frame["scenario"].fillna("default")
        frame = frame[frame["scenario"] == scenario]
        if "side" in frame.columns:
            frame = frame[frame["side"].isin(["current", "", "nan"]) | frame["side"].isna()]
        if frame.empty:
            st.info(text("common.missing", lang))
        else:
            left, right = st.columns(2)
            _show(
                left,
                charts.snapshot_line(
                    frame, "flag_share", text("overvaking.flag_share", lang), labels
                ),
                lang,
            )
            _show(
                right,
                charts.snapshot_line(frame, "p50", text("overvaking.p50", lang), labels),
                lang,
            )
            _table_toggle(frame, lang, "summary")


def personvern(lang: str) -> None:
    st.title(text("personvern.title", lang))
    st.subheader(text("personvern.privacy_title", lang))
    st.markdown(text("personvern.privacy", lang))
    st.subheader(text("personvern.method_title", lang))
    st.markdown(text("personvern.method", lang))
    st.markdown(text("personvern.docs", lang))
    st.caption(text("common.source", lang))
