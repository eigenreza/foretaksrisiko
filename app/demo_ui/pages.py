"""The six pages of the demo. Each function renders one page for one language."""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from demo_ui import charts, data
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
    return fmt_decimal(value, lang, 2)


def _interval(row, metric: str, lang: str) -> str:
    if row is None or pd.isna(row["ci_low"]) or pd.isna(row["ci_high"]):
        return ""
    joiner = " til " if lang == "no" else " to "
    return (
        _format_metric(metric, row["ci_low"], lang)
        + joiner
        + _format_metric(metric, row["ci_high"], lang)
    )


def _show(target, chart, lang: str) -> None:
    """Draw a chart with the number format of the chosen language."""
    target.altair_chart(charts.localized(chart, lang), width="stretch")


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
        columns = st.columns(len(HEADLINE_METRICS))
        for column, metric in zip(columns, HEADLINE_METRICS, strict=True):
            row = _metric_row(metrics, MAIN_MODEL, metric)
            if row is None:
                continue
            interval = _interval(row, metric, lang)
            column.metric(
                labels.metric(metric),
                _format_metric(metric, row["value"], lang),
                help=interval or None,
            )
        st.markdown(text("oversikt.results_text", lang))
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
        left, middle, right = st.columns(3)
        model = left.selectbox(
            text("modellen.fairness_model", lang),
            [m for m in charts.MODEL_ORDER if m in set(fairness["model"])],
            format_func=labels.model,
            key="fairness_model",
        )
        group_type = middle.selectbox(
            text("monstre.group_type", lang),
            [g for g in GROUP_TYPE_ORDER if g in set(fairness["group_type"])],
            format_func=labels.group_type,
            key="fairness_group_type",
        )
        mitigated = right.checkbox(text("modellen.fairness_threshold", lang), key="fairness_pgt")
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
        values["age_years"] = st.slider(
            label("age_years"), 0.0, 60.0, float(typical.age_years), 0.5, key="in_age_years"
        )
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
        values["equity_ratio"] = st.slider(
            label("equity_ratio"), -1.0, 1.0, float(typical.equity_ratio), 0.05, key="in_equity"
        )
        values["operating_margin"] = st.slider(
            label("operating_margin"),
            -1.0,
            1.0,
            float(typical.operating_margin),
            0.05,
            key="in_margin",
        )
        values["current_ratio"] = st.slider(
            label("current_ratio"), 0.0, 5.0, float(typical.current_ratio), 0.1, key="in_current"
        )
        values["cash_ratio"] = st.slider(
            label("cash_ratio"), 0.0, 3.0, float(typical.cash_ratio), 0.1, key="in_cash"
        )
        values["revenue_growth"] = st.slider(
            label("revenue_growth"), -1.0, 3.0, float(typical.revenue_growth), 0.05, key="in_rg"
        )
        values["asset_growth"] = st.slider(
            label("asset_growth"), -1.0, 3.0, float(typical.asset_growth), 0.05, key="in_ag"
        )
        values["acc_age_days"] = st.slider(
            label("acc_age_days"), 0, 2000, int(typical.acc_age_days), key="in_acc_age"
        )
        values["acc_filing_lag_days"] = st.slider(
            label("acc_filing_lag_days"),
            -200,
            600,
            int(typical.acc_filing_lag_days),
            key="in_acc_lag",
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

    form_column, result_column = st.columns([2, 3])
    with form_column:
        inputs = _inputs_form(art, typical, lang)
    features, context = build_features(inputs, art)
    result = score(features, art, reference)

    with result_column:
        st.caption(text("prov.disclaimer", lang))
        one, two = st.columns(2)
        one.metric(
            text("prov.out.probability", lang),
            fmt_percent(result.probability, lang, 2),
            help=text("prov.out.probability_help", lang),
        )
        if result.probability_percentile is not None:
            one.caption(
                text("prov.out.higher_than", lang).format(
                    pct=fmt_percent(result.probability_percentile, lang, 0)
                )
            )
        two.metric(
            text("prov.out.mahalanobis", lang),
            fmt_decimal(result.mahalanobis, lang, 2),
            help=text("prov.out.mahalanobis_help", lang),
        )
        if result.mahalanobis_percentile is not None:
            two.caption(
                text("prov.out.higher_than_reference", lang).format(
                    pct=fmt_percent(result.mahalanobis_percentile, lang, 0)
                )
            )
        three, four = st.columns(2)
        three.metric(
            text("prov.out.extreme", lang),
            str(result.n_extreme_z),
            help=text("prov.out.extreme_help", lang),
        )
        group_size = max(
            (s[0] for f in RATIO_FEATURES if (s := art.stats(context["peer_group"], f))),
            default=None,
        )
        four.metric(
            text("prov.out.peer_group", lang),
            fmt_number(group_size, lang) if group_size else "",
            help=text("prov.out.peer_group_help", lang),
        )
        four.caption(_peer_group_text(context["peer_group"], lang))

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
            table = drivers(inputs, art, typical, reference)
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
    scenario = st.selectbox(text("overvaking.scenario", lang), scenarios, key="monitoring_scenario")
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
            key="mon_metric",
        )
        subset = frame[(frame["snapshot_id"] == snapshot) & (frame["metric"] == metric)]
        subset = subset.sort_values("value", ascending=False).head(15)
        st.subheader(text("overvaking.drift_title", lang))
        if subset.empty:
            st.info(text("common.missing", lang))
        else:
            _show(st, charts.drift_chart(subset, labels, metric), lang)
        st.subheader(text("overvaking.events_title", lang))
        events = frame[frame["severity"].isin(["warn", "alert"])]
        if events.empty:
            st.info(text("overvaking.no_events", lang))
        else:
            shown = events.copy()
            shown["feature"] = shown["feature"].map(labels.feature)
            st.dataframe(
                shown[["snapshot_id", "feature", "metric", "value", "severity"]],
                hide_index=True,
                width="stretch",
            )

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
