"""Altair charts for the demo, in the figures' Okabe-Ito palette with fixed colours per series.

Every chart carries tooltips, uses one axis per measure and keeps the same colour for the same
model or series on every page.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

from foretaksrisiko.figures.labels import Labels

ORANGE = "#E69F00"
SKY = "#56B4E9"
GREEN = "#009E73"
BLUE = "#0072B2"
VERMILION = "#D55E00"
PURPLE = "#CC79A7"
GREY = "#777777"

MODEL_ORDER = ("rule", "isolation_forest", "mahalanobis", "hgb_calibrated")
MODEL_COLORS = {
    "rule": ORANGE,
    "isolation_forest": SKY,
    "mahalanobis": GREEN,
    "hgb_calibrated": BLUE,
}
STATUS_COLORS = {"ok": GREEN, "warn": ORANGE, "alert": VERMILION}
# Number format of the Norwegian view: decimal comma and a space between thousands.
NORWEGIAN_NUMBERS = {
    "decimal": ",",
    "thousands": " ",
    "grouping": [3],
    "currency": ["", " kr"],
    "percent": " %",
}


def localized(chart, lang: str):
    """The chart with the number format of the chosen language on axes and tooltips."""
    if lang != "no":
        return chart
    return chart.configure(locale={"number": NORWEGIAN_NUMBERS})


def _model_scale(df: pd.DataFrame, labels: Labels) -> tuple[pd.DataFrame, alt.Scale]:
    """Add a localised series column and return a colour scale in the fixed model order."""
    present = [m for m in MODEL_ORDER if m in set(df["model"])]
    frame = df.copy()
    frame["series"] = frame["model"].map(labels.model)
    scale = alt.Scale(
        domain=[labels.model(m) for m in present], range=[MODEL_COLORS[m] for m in present]
    )
    return frame, scale


def _bars_height(rows: int) -> int:
    return max(160, 24 * rows + 40)


def horizontal_bars(
    df: pd.DataFrame,
    category: str,
    value: str,
    label_category: str,
    label_value: str,
    color: str = BLUE,
    value_format: str = ",",
    sort: str | list[str] = "-x",
) -> alt.Chart:
    return (
        alt.Chart(df)
        .mark_bar(color=color, cornerRadiusEnd=3)
        .encode(
            y=alt.Y(f"{category}:N", sort=sort, title=None, axis=alt.Axis(labelLimit=260)),
            x=alt.X(f"{value}:Q", title=label_value),
            tooltip=[
                alt.Tooltip(f"{category}:N", title=label_category),
                alt.Tooltip(f"{value}:Q", title=label_value, format=value_format),
            ],
        )
        .properties(height=_bars_height(len(df)))
    )


def topk_charts(df: pd.DataFrame, labels: Labels) -> tuple[alt.Chart, alt.Chart]:
    frame, scale = _model_scale(df, labels)
    frame["share_pct"] = frame["share"] * 100
    base = alt.Chart(frame).encode(
        x=alt.X("share_pct:Q", title=labels.percent_axis(labels("axis.share_flagged"))),
        color=alt.Color("series:N", scale=scale, legend=alt.Legend(title=None, orient="bottom")),
    )
    precision = base.mark_line(point=True, strokeWidth=2).encode(
        y=alt.Y("precision:Q", title=labels("axis.precision")),
        tooltip=[
            alt.Tooltip("series:N", title=labels("axis.feature_set")),
            alt.Tooltip("share_pct:Q", title=labels("axis.share_flagged"), format=".1f"),
            alt.Tooltip("precision:Q", title=labels("axis.precision"), format=".3f"),
        ],
    )
    lift = base.mark_line(point=True, strokeWidth=2).encode(
        y=alt.Y("lift:Q", title=labels("axis.lift")),
        tooltip=[
            alt.Tooltip("series:N", title=labels("axis.feature_set")),
            alt.Tooltip("share_pct:Q", title=labels("axis.share_flagged"), format=".1f"),
            alt.Tooltip("lift:Q", title=labels("axis.lift"), format=".1f"),
        ],
    )
    return precision.properties(height=280), lift.properties(height=280)


def calibration_chart(df: pd.DataFrame, labels: Labels) -> alt.LayerChart:
    top = float(max(df["mean_predicted"].max(), df["observed_rate"].max())) * 1.05 or 0.01
    diagonal = (
        alt.Chart(pd.DataFrame({"x": [0.0, top], "y": [0.0, top]}))
        .mark_line(color=GREY, strokeDash=[4, 4])
        .encode(x="x:Q", y="y:Q")
    )
    points = (
        alt.Chart(df)
        .mark_point(filled=True, color=BLUE, size=90)
        .encode(
            x=alt.X("mean_predicted:Q", title=labels("axis.mean_predicted")),
            y=alt.Y("observed_rate:Q", title=labels("axis.observed_rate")),
            tooltip=[
                alt.Tooltip("bin:O", title=labels("calibration.bins")),
                alt.Tooltip("n:Q", title=labels("calibration.size"), format=","),
                alt.Tooltip("mean_predicted:Q", title=labels("axis.mean_predicted"), format=".4f"),
                alt.Tooltip("observed_rate:Q", title=labels("axis.observed_rate"), format=".4f"),
            ],
        )
    )
    return (diagonal + points).properties(height=320)


def feature_bars(
    df: pd.DataFrame, value: str, label_value: str, labels: Labels, color: str = BLUE
) -> alt.Chart:
    frame = df.copy()
    frame["label"] = frame["feature"].map(labels.feature)
    return horizontal_bars(
        frame, "label", value, labels("axis.feature_set"), label_value, color, ".4f"
    )


def ablation_chart(df: pd.DataFrame, labels: Labels) -> alt.Chart:
    frame = df.copy()
    frame["label"] = frame["ablation"].map(labels.ablation)
    return horizontal_bars(
        frame,
        "label",
        "value",
        labels("axis.feature_set"),
        labels.metric("average_precision"),
        BLUE,
        ".3f",
        sort=list(frame["label"]),
    )


def fairness_chart(df: pd.DataFrame, labels: Labels, label_column: str) -> alt.Chart:
    long = df.melt(
        id_vars=[label_column, "n"],
        value_vars=["flag_rate", "base_rate"],
        var_name="series",
        value_name="rate",
    )
    names = {
        "flag_rate": labels("fairness.flag_rate"),
        "base_rate": labels("fairness.base_rate"),
    }
    long["series"] = long["series"].map(names)
    scale = alt.Scale(domain=list(names.values()), range=[BLUE, ORANGE])
    return (
        alt.Chart(long)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y(
                f"{label_column}:N",
                sort=list(df[label_column]),
                title=None,
                axis=alt.Axis(labelLimit=260),
            ),
            x=alt.X("rate:Q", title=labels("axis.rate"), axis=alt.Axis(format="%")),
            yOffset="series:N",
            color=alt.Color(
                "series:N", scale=scale, legend=alt.Legend(title=None, orient="bottom")
            ),
            tooltip=[
                alt.Tooltip(f"{label_column}:N", title=labels("axis.feature_set")),
                alt.Tooltip("series:N", title=labels("axis.rate")),
                alt.Tooltip("rate:Q", title=labels("axis.rate"), format=".2%"),
                alt.Tooltip("n:Q", title=labels("axis.companies"), format=","),
            ],
        )
        .properties(height=_bars_height(len(df)) + 60)
    )


def score_quantile_chart(df: pd.DataFrame, labels: Labels) -> alt.FacetChart:
    frame, scale = _model_scale(df, labels)
    return (
        alt.Chart(frame)
        .mark_line(strokeWidth=2)
        .encode(
            x=alt.X("quantile:Q", title=labels("axis.quantile")),
            y=alt.Y("value:Q", title=labels("axis.score")),
            color=alt.Color("series:N", scale=scale, legend=None),
            tooltip=[
                alt.Tooltip("series:N", title=labels("axis.feature_set")),
                alt.Tooltip("quantile:Q", title=labels("axis.quantile"), format=".2f"),
                alt.Tooltip("value:Q", title=labels("axis.score"), format=".4f"),
            ],
        )
        .properties(height=200, width=220)
        .facet(column=alt.Column("series:N", title=None, sort=list(scale.domain)))
        .resolve_scale(y="independent")
    )


def network_chart(df: pd.DataFrame, labels: Labels) -> alt.Chart:
    frame = df.copy()
    frame["series"] = frame["kind"].map(labels.kind)
    order = list(frame.sort_values("bin_order")["size_bin"].drop_duplicates())
    scale = alt.Scale(
        domain=[labels.kind("auditor"), labels.kind("accountant")], range=[BLUE, ORANGE]
    )
    return (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            x=alt.X("size_bin:N", sort=order, title=labels("axis.clients")),
            y=alt.Y("n_companies:Q", title=labels("axis.companies")),
            xOffset="series:N",
            color=alt.Color(
                "series:N", scale=scale, legend=alt.Legend(title=None, orient="bottom")
            ),
            tooltip=[
                alt.Tooltip("series:N", title=labels("axis.feature_set")),
                alt.Tooltip("size_bin:N", title=labels("axis.clients")),
                alt.Tooltip("n_companies:Q", title=labels("axis.companies"), format=","),
            ],
        )
        .properties(height=300)
    )


def drift_chart(df: pd.DataFrame, labels: Labels, value_label: str) -> alt.Chart:
    frame = df.copy()
    frame["label"] = frame["feature"].map(labels.feature)
    frame["status"] = frame["severity"].fillna("ok").replace({"": "ok"})
    scale = alt.Scale(domain=list(STATUS_COLORS), range=list(STATUS_COLORS.values()))
    return (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y("label:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
            x=alt.X("value:Q", title=value_label),
            color=alt.Color("status:N", scale=scale, legend=alt.Legend(title=None)),
            tooltip=[
                alt.Tooltip("label:N", title=labels("axis.feature_set")),
                alt.Tooltip("value:Q", title=value_label, format=".4f"),
                alt.Tooltip("status:N", title=labels("drift.warn")),
            ],
        )
        .properties(height=_bars_height(len(frame)))
    )


def snapshot_line(df: pd.DataFrame, value: str, label_value: str, labels: Labels) -> alt.Chart:
    return (
        alt.Chart(df)
        .mark_line(point=True, color=BLUE, strokeWidth=2)
        .encode(
            x=alt.X("snapshot_id:O", title=labels("axis.snapshot")),
            y=alt.Y(f"{value}:Q", title=label_value),
            tooltip=[
                alt.Tooltip("snapshot_id:O", title=labels("axis.snapshot")),
                alt.Tooltip(f"{value}:Q", title=label_value, format=".4f"),
            ],
        )
        .properties(height=240)
    )


def z_chart(df: pd.DataFrame, labels: Labels, label_z: str, label_extreme: str) -> alt.LayerChart:
    frame = df.dropna(subset=["z"]).copy()
    frame["label"] = frame["feature"].map(labels.feature)
    frame["status"] = (frame["z"].abs() > 3).map({True: label_extreme, False: label_z})
    scale = alt.Scale(domain=[label_z, label_extreme], range=[BLUE, VERMILION])
    bars = (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y(
                "label:N", sort=list(frame["label"]), title=None, axis=alt.Axis(labelLimit=260)
            ),
            x=alt.X("z:Q", title=label_z),
            color=alt.Color("status:N", scale=scale, legend=alt.Legend(title=None)),
            tooltip=[
                alt.Tooltip("label:N", title=labels("axis.feature_set")),
                alt.Tooltip("z:Q", title=label_z, format=".2f"),
                alt.Tooltip("pct:Q", title=labels("axis.quantile"), format=".2f"),
            ],
        )
    )
    rules = (
        alt.Chart(pd.DataFrame({"x": [-3.0, 3.0]}))
        .mark_rule(color=GREY, strokeDash=[4, 4])
        .encode(x="x:Q")
    )
    return (bars + rules).properties(height=_bars_height(len(frame)))


def driver_chart(
    df: pd.DataFrame, labels: Labels, label_delta: str, label_up: str, label_down: str
) -> alt.Chart:
    frame = df.copy()
    frame["delta_pp"] = frame["delta_probability"] * 100
    frame["direction"] = (frame["delta_pp"] >= 0).map({True: label_up, False: label_down})
    scale = alt.Scale(domain=[label_up, label_down], range=[VERMILION, BLUE])
    return (
        alt.Chart(frame)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y(
                "label:N", sort=list(frame["label"]), title=None, axis=alt.Axis(labelLimit=260)
            ),
            x=alt.X("delta_pp:Q", title=label_delta),
            color=alt.Color("direction:N", scale=scale, legend=alt.Legend(title=None)),
            tooltip=[
                alt.Tooltip("label:N", title=labels("axis.feature_set")),
                alt.Tooltip("delta_pp:Q", title=label_delta, format=".2f"),
            ],
        )
        .properties(height=_bars_height(len(frame)))
    )
