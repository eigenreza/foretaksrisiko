"""Build the aggregate-only figures from the demo data files.

Each figure function takes already-read pandas frames and a language code and returns a
matplotlib Figure. ``render_all`` reads the CSV files in a demo folder, renders every figure
whose inputs exist and saves each one as SVG and PNG under the output folder.
"""

from __future__ import annotations

import logging
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from matplotlib.ticker import FuncFormatter, NullFormatter

from foretaksrisiko.figures.style import (
    ABLATION_ORDER,
    GROUP_TYPE_ORDER,
    HATCHES,
    KIND_ORDER,
    LINESTYLES,
    MARKERS,
    MODEL_ORDER,
    OKABE_ITO,
    PALETTE,
    REFERENCE_COLOR,
    Labels,
    apply_style,
)

log = logging.getLogger(__name__)

PNG_DPI = 150
DEFAULT_FORMATS = ("svg", "png")
# Saved files carry no creation date. PNG writes none by default.
SAVE_METADATA: dict[str, dict[str, None]] = {
    "svg": {"Date": None},
    "pdf": {"CreationDate": None},
    "png": {},
}

ABLATION_METRICS = ("average_precision", "precision_top_1pct")
SHAP_TOP_N = 15
DRIFT_TOP_N = 10
PSI_WARN = 0.10
PSI_ALERT = 0.25
# Observed rates of zero cannot be drawn on a log axis, so they are clipped to this floor and
# drawn with a distinct marker (see ``calibration``).
RATE_FLOOR = 1e-4
ORDINAL_GROUP_TYPES = ("age_band", "size_band")


def _subplots(nrows: int = 1, ncols: int = 1, figsize=(9, 5), **kwargs) -> tuple[Figure, object]:
    apply_style()
    return plt.subplots(nrows, ncols, figsize=figsize, **kwargs)


def _wrap(text: str, width: int) -> str:
    return textwrap.fill(text, width=width)


def _percent_formatter(labels: Labels) -> FuncFormatter:
    return FuncFormatter(lambda value, _pos: labels.percent(value))


def _number_formatter(labels: Labels) -> FuncFormatter:
    return FuncFormatter(lambda value, _pos: labels.number(value))


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def _is_false(series: pd.Series) -> pd.Series:
    """True where a text or boolean column reads as false or is missing."""
    text = series.astype(str).str.strip().str.lower()
    return text.isin(["false", "0", "nan", "none", ""])


def _ordered(present: list[str], preferred: tuple[str, ...]) -> list[str]:
    """Preferred order first, then anything else in order of appearance."""
    head = [name for name in preferred if name in present]
    tail = [name for name in present if name not in preferred]
    return head + tail


def _latest_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    if "snapshot_id" not in frame.columns or frame.empty:
        return frame
    snapshot = _numeric(frame, "snapshot_id")
    return frame[snapshot == snapshot.max()]


def _series_style(index: int) -> dict:
    return {
        "color": PALETTE[index % len(PALETTE)],
        "marker": MARKERS[index % len(MARKERS)],
        "linestyle": LINESTYLES[(index // len(PALETTE)) % len(LINESTYLES)],
    }


# Figures


def pipeline(lang: str) -> Figure:
    """Static diagram of the data flow from the laptop to the alerts, drawn with patches."""
    labels = Labels(lang)
    keys = ("acquire", "landing", "bronze", "silver", "gold", "models", "scoring", "alerts")
    laptop_boxes = 2
    width, gap, height = 1.0, 0.24, 0.95
    x0, y_center = 0.2, 1.8
    total_width = 10.0
    total_height = 3.4

    fig, ax = _subplots(figsize=(total_width, total_height))
    ax.set_xlim(0, total_width)
    ax.set_ylim(0, total_height)
    ax.set_aspect("equal")
    ax.grid(False)
    ax.set_axis_off()

    laptop_fill = to_rgba(OKABE_ITO["orange"], 0.25)
    cloud_fill = to_rgba(OKABE_ITO["sky"], 0.25)
    for index, key in enumerate(keys):
        x = x0 + index * (width + gap)
        fill = laptop_fill if index < laptop_boxes else cloud_fill
        box = FancyBboxPatch(
            (x, y_center - height / 2),
            width,
            height,
            boxstyle="round,pad=0,rounding_size=0.12",
            facecolor=fill,
            edgecolor="black",
            linewidth=0.9,
        )
        ax.add_patch(box)
        ax.text(
            x + width / 2,
            y_center,
            _wrap(labels(f"pipeline.{key}"), 14),
            ha="center",
            va="center",
            fontsize=8,
        )
        if index < len(keys) - 1:
            arrow = FancyArrowPatch(
                (x + width, y_center),
                (x + width + gap, y_center),
                arrowstyle="-|>",
                mutation_scale=11,
                color="black",
                linewidth=0.9,
                shrinkA=0,
                shrinkB=0,
            )
            ax.add_patch(arrow)

    boundary = x0 + laptop_boxes * (width + gap) - gap / 2
    ax.plot(
        [boundary, boundary],
        [0.3, total_height - 0.35],
        linestyle="--",
        color=REFERENCE_COLOR,
        linewidth=1.0,
    )
    label_y = total_height - 0.4
    ax.text(boundary - 0.1, label_y, labels("pipeline.laptop"), ha="right", va="top", fontsize=9)
    ax.text(boundary + 0.1, label_y, labels("pipeline.cloud"), ha="left", va="top", fontsize=9)
    ax.text(
        x0 + width / 2,
        y_center - height / 2 - 0.12,
        _wrap(labels("pipeline.note"), 24),
        ha="center",
        va="top",
        fontsize=7.5,
        style="italic",
    )
    ax.set_title(labels("pipeline.title"))
    fig.tight_layout()
    return fig


def _barh_counts(ax: Axes, names: list[str], counts: np.ndarray, color: str, labels: Labels):
    order = np.argsort(counts)
    positions = np.arange(len(order))
    ax.barh(
        positions,
        counts[order],
        color=color,
        edgecolor="black",
        linewidth=0.5,
    )
    ax.set_yticks(positions)
    ax.set_yticklabels([names[i] for i in order])
    ax.xaxis.set_major_formatter(_number_formatter(labels))
    ax.set_xlabel(labels("axis.companies"))
    ax.grid(False, axis="y")


def population_overview(by_section: pd.DataFrame, by_fylke: pd.DataFrame, lang: str) -> Figure:
    """Companies by industry section and by county for the latest snapshot, sorted descending."""
    labels = Labels(lang)
    fig, (ax_section, ax_fylke) = _subplots(1, 2, figsize=(10, 5.5))

    section = _latest_snapshot(by_section)
    section_label = f"section_label_{lang}"
    if section_label not in section.columns:
        section_label = "nace_section"
    _barh_counts(
        ax_section,
        section[section_label].astype(str).tolist(),
        _numeric(section, "n").to_numpy(dtype=float),
        OKABE_ITO["blue"],
        labels,
    )
    ax_section.set_title(labels("population.by_section"))

    fylke = _latest_snapshot(by_fylke)
    fylke_label = "fylke_name" if "fylke_name" in fylke.columns else "fylke_code"
    _barh_counts(
        ax_fylke,
        fylke[fylke_label].astype(str).tolist(),
        _numeric(fylke, "n").to_numpy(dtype=float),
        OKABE_ITO["orange"],
        labels,
    )
    ax_fylke.set_title(labels("population.by_fylke"))

    fig.suptitle(labels("population.title"))
    fig.tight_layout()
    return fig


def score_distributions(quantiles: pd.DataFrame, lang: str) -> Figure:
    """Score value by quantile on the test split, one panel per model."""
    labels = Labels(lang)
    fig, axes = _subplots(2, 2, figsize=(9, 6.5))
    test = quantiles[quantiles["split"].astype(str) == "test"]
    for index, model in enumerate(MODEL_ORDER):
        ax = axes.flat[index]
        sub = test[test["model"].astype(str) == model].sort_values("quantile")
        if sub.empty:
            ax.set_axis_off()
            continue
        ax.plot(
            _numeric(sub, "quantile"),
            _numeric(sub, "value"),
            color=PALETTE[index],
            marker=MARKERS[index],
            markersize=3.5,
            markevery=max(1, len(sub) // 10),
        )
        ax.set_xlim(0, 1)
        ax.set_title(labels.model(model))
        ax.set_xlabel(labels("axis.quantile"))
        ax.set_ylabel(labels("axis.score"))
    fig.suptitle(labels("scores.title"))
    fig.tight_layout()
    return fig


def topk(topk_table: pd.DataFrame, lang: str) -> Figure:
    """Precision and lift against the share flagged, one line per model, log scale on x."""
    labels = Labels(lang)
    fig, (ax_precision, ax_lift) = _subplots(1, 2, figsize=(10, 4.3))
    models = _ordered(topk_table["model"].astype(str).unique().tolist(), MODEL_ORDER)
    shares = set()
    for index, model in enumerate(models):
        sub = topk_table[topk_table["model"].astype(str) == model].sort_values("share")
        share_pct = _numeric(sub, "share").to_numpy(dtype=float) * 100
        shares.update(share_pct.tolist())
        style = _series_style(index)
        ax_precision.plot(
            share_pct, _numeric(sub, "precision") * 100, label=labels.model(model), **style
        )
        ax_lift.plot(share_pct, _numeric(sub, "lift"), label=labels.model(model), **style)

    ticks = sorted(shares)
    for ax in (ax_precision, ax_lift):
        ax.set_xscale("log")
        if ticks:
            ax.set_xticks(ticks)
        ax.xaxis.set_major_formatter(_percent_formatter(labels))
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.set_xlabel(labels("axis.share_flagged"))
    ax_precision.yaxis.set_major_formatter(_percent_formatter(labels))
    ax_precision.set_ylabel(labels("axis.precision"))
    ax_precision.set_ylim(bottom=0)
    ax_lift.set_ylabel(labels("axis.lift"))
    ax_lift.set_ylim(bottom=0)
    ax_precision.legend(loc="upper right")
    fig.suptitle(labels("topk.title"))
    fig.tight_layout()
    return fig


def calibration(bins: pd.DataFrame, lang: str) -> Figure:
    """Reliability diagram on log-log percent axes, point size by the number in each bin."""
    labels = Labels(lang)
    fig, ax = _subplots(figsize=(8, 6))
    predicted = _numeric(bins, "mean_predicted").to_numpy(dtype=float)
    observed = _numeric(bins, "observed_rate").to_numpy(dtype=float)
    counts = _numeric(bins, "n").fillna(0).to_numpy(dtype=float)
    keep = np.isfinite(predicted) & np.isfinite(observed) & (predicted > 0)
    predicted, observed, counts = predicted[keep], observed[keep], counts[keep]

    # Zero observed rates have no position on a log axis: clip them to RATE_FLOOR and mark them
    # with a downward triangle so the reader sees they sit at or below the floor.
    clipped = observed <= RATE_FLOOR
    x = predicted * 100
    y = np.clip(observed, RATE_FLOOR, None) * 100
    count_max = max(float(counts.max()) if len(counts) else 0.0, 1.0)
    size_base, size_span = 20.0, 230.0
    sizes = size_base + size_span * counts / count_max

    handles = []
    if len(x):
        low = min(x.min(), y.min()) / 1.5
        high = max(x.max(), y.max()) * 1.5
    else:
        low, high = RATE_FLOOR * 100, 100.0
    (diagonal,) = ax.plot(
        [low, high],
        [low, high],
        linestyle="--",
        color=REFERENCE_COLOR,
        label=labels("calibration.diagonal"),
    )
    handles.append(diagonal)
    scatter = ax.scatter(
        x[~clipped],
        y[~clipped],
        s=sizes[~clipped],
        color=OKABE_ITO["blue"],
        edgecolor="black",
        linewidth=0.5,
        alpha=0.85,
        label=labels("calibration.bins"),
        zorder=3,
    )
    handles.append(scatter)
    if clipped.any():
        floor_points = ax.scatter(
            x[clipped],
            y[clipped],
            s=sizes[clipped],
            marker="v",
            color=OKABE_ITO["vermilion"],
            edgecolor="black",
            linewidth=0.5,
            label=labels("calibration.floor"),
            zorder=3,
        )
        handles.append(floor_points)

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(low, high)
    ax.set_ylim(low, high)
    ax.set_aspect("equal", adjustable="box")
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_formatter(_percent_formatter(labels))
        axis.set_minor_formatter(NullFormatter())
    ax.set_xlabel(labels("axis.mean_predicted"))
    ax.set_ylabel(labels("axis.observed_rate"))
    ax.set_title(labels("calibration.title"))

    main_legend = ax.legend(handles=handles, loc="upper left")
    ax.add_artist(main_legend)
    if len(counts) and counts.max() > 0:
        size_handles, size_labels = scatter.legend_elements(
            prop="sizes",
            num=4,
            func=lambda s: (s - size_base) / size_span * count_max,
            fmt="{x:.0f}",
            color=OKABE_ITO["blue"],
        )
        ax.legend(
            size_handles,
            size_labels,
            loc="lower right",
            title=labels("calibration.size"),
            labelspacing=1.2,
        )
    fig.tight_layout()
    return fig


def shap_summary(explanations: pd.DataFrame, lang: str) -> Figure:
    """Top features of the calibrated model by mean absolute SHAP value."""
    labels = Labels(lang)
    fig, ax = _subplots(figsize=(9, 6))
    rows = explanations[explanations["model"].astype(str).isin(["hgb", "hgb_calibrated"])].copy()
    rows["mean_abs_shap"] = _numeric(rows, "mean_abs_shap")
    rows = rows.dropna(subset=["mean_abs_shap"]).nlargest(SHAP_TOP_N, "mean_abs_shap")
    rows = rows.sort_values("mean_abs_shap")
    positions = np.arange(len(rows))
    ax.barh(
        positions,
        rows["mean_abs_shap"].to_numpy(dtype=float),
        color=OKABE_ITO["green"],
        edgecolor="black",
        linewidth=0.5,
    )
    ax.set_yticks(positions)
    ax.set_yticklabels([labels.feature(str(name)) for name in rows["feature"]])
    ax.grid(False, axis="y")
    ax.set_xlabel(labels("axis.mean_abs_shap"))
    ax.set_title(labels("shap.title"))
    fig.tight_layout()
    return fig


def ablation(metrics: pd.DataFrame, lang: str) -> Figure:
    """Grouped bars per ablation for the calibrated model on the test split, with intervals."""
    labels = Labels(lang)
    fig, ax = _subplots(figsize=(9, 5))
    seed = _numeric(metrics, "seed")
    rows = metrics[
        (metrics["split"].astype(str) == "test")
        & (metrics["model"].astype(str) == "hgb_calibrated")
        & (seed.isna() | (seed == 1))
        & (metrics["metric"].astype(str).isin(ABLATION_METRICS))
    ].copy()
    rows["ablation"] = rows["ablation"].astype(str)
    rows["metric"] = rows["metric"].astype(str)
    rows = rows.drop_duplicates(subset=["ablation", "metric"], keep="first")
    ablations = _ordered(rows["ablation"].unique().tolist(), ABLATION_ORDER)
    x = np.arange(len(ablations))
    bar_width = 0.38
    for index, metric in enumerate(ABLATION_METRICS):
        sub = rows[rows["metric"] == metric].set_index("ablation").reindex(ablations)
        values = _numeric(sub, "value").to_numpy(dtype=float)
        ci_low = _numeric(sub, "ci_low").to_numpy(dtype=float)
        ci_high = _numeric(sub, "ci_high").to_numpy(dtype=float)
        lower = np.clip(values - ci_low, 0, None)
        upper = np.clip(ci_high - values, 0, None)
        has_interval = np.isfinite(lower) & np.isfinite(upper)
        yerr = np.vstack([lower, upper]) if has_interval.any() else None
        offset = (index - (len(ABLATION_METRICS) - 1) / 2) * bar_width
        ax.bar(
            x + offset,
            np.nan_to_num(values, nan=0.0),
            bar_width,
            yerr=yerr,
            color=PALETTE[index],
            hatch=HATCHES[index],
            edgecolor="black",
            linewidth=0.5,
            label=labels.metric(metric),
            error_kw={"capsize": 3, "elinewidth": 0.9, "ecolor": "black"},
        )
    ax.set_xticks(x)
    ax.set_xticklabels([_wrap(labels.ablation(name), 14) for name in ablations])
    ax.grid(False, axis="x")
    ax.set_xlabel(labels("axis.feature_set"))
    ax.set_ylabel(labels("axis.value"))
    ax.set_ylim(bottom=0)
    ax.legend(loc="upper right")
    ax.set_title(labels("ablation.title"))
    fig.tight_layout()
    return fig


def fairness(groups: pd.DataFrame, lang: str) -> Figure:
    """Flag rate and base rate per group, one panel per group type, in percent."""
    labels = Labels(lang)
    fig, axes = _subplots(2, 2, figsize=(10, 8))
    rows = groups[
        (groups["model"].astype(str) == "hgb_calibrated") & _is_false(groups["per_group_threshold"])
    ].copy()
    label_column = f"group_label_{lang}"
    if label_column not in rows.columns:
        label_column = "group_value"
    rows["flag_rate"] = _numeric(rows, "flag_rate")
    rows["base_rate"] = _numeric(rows, "base_rate")
    bar_height = 0.38
    legend_handles = None
    for index, group_type in enumerate(GROUP_TYPE_ORDER):
        ax = axes.flat[index]
        sub = rows[rows["group_type"].astype(str) == group_type]
        if sub.empty:
            ax.set_axis_off()
            continue
        if group_type in ORDINAL_GROUP_TYPES:
            # Bands in their natural order: by the number each band starts with.
            start = sub["group_value"].astype(str).str.extract(r"(\d+)")[0].astype(float)
            sub = sub.iloc[np.argsort(start.to_numpy(), kind="stable")]
        else:
            sub = sub.sort_values("flag_rate", ascending=False)
        names = sub[label_column].fillna(sub["group_value"]).astype(str).tolist()
        positions = np.arange(len(sub))
        flag_bars = ax.barh(
            positions - bar_height / 2,
            sub["flag_rate"].to_numpy(dtype=float) * 100,
            bar_height,
            color=OKABE_ITO["vermilion"],
            edgecolor="black",
            linewidth=0.5,
            label=labels("fairness.flag_rate"),
        )
        base_bars = ax.barh(
            positions + bar_height / 2,
            sub["base_rate"].to_numpy(dtype=float) * 100,
            bar_height,
            color=OKABE_ITO["sky"],
            hatch="//",
            edgecolor="black",
            linewidth=0.5,
            label=labels("fairness.base_rate"),
        )
        legend_handles = legend_handles or [flag_bars, base_bars]
        ax.set_yticks(positions)
        ax.set_yticklabels(names)
        ax.invert_yaxis()
        ax.grid(False, axis="y")
        ax.xaxis.set_major_formatter(_percent_formatter(labels))
        ax.set_xlabel(labels("axis.rate"))
        ax.set_title(labels.group_type(group_type))
    if legend_handles:
        fig.legend(handles=legend_handles, loc="lower center", ncol=2)
    fig.suptitle(labels("fairness.title"))
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    return fig


def drift(drift_table: pd.DataFrame, score_summary: pd.DataFrame, lang: str) -> Figure:
    """PSI per snapshot for the most shifted features, and the share flagged per snapshot."""
    labels = Labels(lang)
    fig, (ax_psi, ax_flag) = _subplots(1, 2, figsize=(10, 6), gridspec_kw={"width_ratios": [3, 2]})

    psi = drift_table[
        (drift_table["scenario"].astype(str) == "default")
        & (drift_table["metric"].astype(str) == "psi")
    ].copy()
    psi["snapshot_id"] = _numeric(psi, "snapshot_id")
    psi["value"] = _numeric(psi, "value")
    psi["feature"] = psi["feature"].astype(str)
    snapshots = sorted(psi["snapshot_id"].dropna().unique().tolist())
    handles = []
    if snapshots:
        latest = psi[psi["snapshot_id"] == snapshots[-1]]
        top = (
            latest.sort_values("value", ascending=False)["feature"]
            .drop_duplicates()
            .head(DRIFT_TOP_N)
            .tolist()
        )
        table = psi.pivot_table(index="snapshot_id", columns="feature", values="value")
        table = table.reindex(snapshots)
        for index, feature in enumerate(top):
            style = _series_style(index)
            if len(snapshots) == 1:
                style["linestyle"] = "none"
            (line,) = ax_psi.plot(
                snapshots,
                table[feature].to_numpy(dtype=float),
                label=labels.feature(feature),
                **style,
            )
            handles.append(line)
        ax_psi.set_xticks(snapshots)
    ax_psi.axhline(PSI_WARN, linestyle="--", color=REFERENCE_COLOR, linewidth=1)
    ax_psi.axhline(PSI_ALERT, linestyle="-.", color="black", linewidth=1)
    text_x = snapshots[-1] if snapshots else 1
    ax_psi.text(text_x, PSI_WARN, labels("drift.warn"), ha="right", va="bottom", fontsize=7.5)
    ax_psi.text(text_x, PSI_ALERT, labels("drift.alert"), ha="right", va="bottom", fontsize=7.5)
    ax_psi.set_ylim(bottom=0)
    ax_psi.margins(x=0.15)
    ax_psi.set_xlabel(labels("axis.snapshot"))
    ax_psi.set_ylabel(labels("axis.psi"))
    ax_psi.set_title(labels("drift.psi_panel"))

    current = score_summary[
        (score_summary["scenario"].astype(str) == "default")
        & (score_summary["side"].astype(str) == "current")
    ].copy()
    current["snapshot_id"] = _numeric(current, "snapshot_id")
    current["flag_share"] = _numeric(current, "flag_share")
    by_snapshot = current.groupby("snapshot_id")["flag_share"].mean().sort_index()
    flag_snapshots = by_snapshot.index.to_numpy(dtype=float)
    ax_flag.plot(
        flag_snapshots,
        by_snapshot.to_numpy(dtype=float) * 100,
        color=OKABE_ITO["blue"],
        marker="o",
        linestyle="-" if len(flag_snapshots) > 1 else "none",
    )
    if len(flag_snapshots):
        ax_flag.set_xticks(flag_snapshots)
    ax_flag.set_ylim(bottom=0)
    ax_flag.margins(x=0.15)
    ax_flag.yaxis.set_major_formatter(_percent_formatter(labels))
    ax_flag.set_xlabel(labels("axis.snapshot"))
    ax_flag.set_ylabel(labels("axis.share_flagged"))
    ax_flag.set_title(labels("drift.flag_panel"))

    if handles:
        fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=7.5)
    fig.suptitle(labels("drift.title"))
    fig.tight_layout(rect=(0, 0.17 if handles else 0, 1, 1))
    return fig


def network_degree(degree: pd.DataFrame, lang: str) -> Figure:
    """Companies by the portfolio size of their auditor and accountant, log scale on y."""
    labels = Labels(lang)
    fig, axes = _subplots(1, 2, figsize=(9, 4.8), sharey=True)
    positive_counts: list[float] = []
    for index, kind in enumerate(KIND_ORDER):
        ax = axes[index]
        sub = degree[degree["kind"].astype(str) == kind].copy()
        if sub.empty:
            ax.set_axis_off()
            continue
        sub["bin_order"] = _numeric(sub, "bin_order")
        sub = sub.sort_values("bin_order")
        positions = np.arange(len(sub))
        counts = _numeric(sub, "n_companies").fillna(0).to_numpy(dtype=float)
        positive_counts.extend(counts[counts > 0].tolist())
        ax.bar(
            positions,
            counts,
            color=PALETTE[index],
            hatch=HATCHES[index],
            edgecolor="black",
            linewidth=0.5,
            log=True,
        )
        ax.set_xticks(positions)
        ax.set_xticklabels(sub["size_bin"].astype(str).tolist(), rotation=45, ha="right")
        ax.grid(False, axis="x")
        ax.yaxis.set_major_formatter(_number_formatter(labels))
        ax.yaxis.set_minor_formatter(NullFormatter())
        ax.set_xlabel(labels("axis.clients"))
        ax.set_title(labels.kind(kind))
    if positive_counts:
        # Whole decades on the shared log axis, so that every labelled tick is a power of ten.
        low = 10 ** np.floor(np.log10(min(positive_counts)))
        high = 10 ** (np.floor(np.log10(max(positive_counts))) + 1)
        axes[0].set_ylim(low, high)
    axes[0].set_ylabel(labels("axis.companies"))
    fig.suptitle(labels("network.title"))
    fig.tight_layout()
    return fig


# Registry and rendering


@dataclass(frozen=True)
class FigureSpec:
    """Input file names under the demo folder and the function that draws the figure."""

    inputs: tuple[str, ...]
    build: Callable[..., Figure]


FIGURES: dict[str, FigureSpec] = {
    "pipeline": FigureSpec((), pipeline),
    "population_overview": FigureSpec(
        ("population_by_section.csv", "population_by_fylke.csv"), population_overview
    ),
    "score_distributions": FigureSpec(("score_quantiles.csv",), score_distributions),
    "topk": FigureSpec(("topk.csv",), topk),
    "calibration": FigureSpec(("calibration.csv",), calibration),
    "shap_summary": FigureSpec(("explanations.csv",), shap_summary),
    "ablation": FigureSpec(("evaluation_metrics.csv",), ablation),
    "fairness": FigureSpec(("fairness.csv",), fairness),
    "drift": FigureSpec(("drift.csv", "score_summary.csv"), drift),
    "network_degree": FigureSpec(("network_degree.csv",), network_degree),
}


def save_figure(
    fig: Figure, out_dir: Path, stem: str, lang: str, formats: tuple[str, ...] = DEFAULT_FORMATS
) -> list[Path]:
    """Save one figure as ``<stem>_<lang>.<format>`` for each format, without date metadata."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for fmt in formats:
        path = out_dir / f"{stem}_{lang}.{fmt}"
        kwargs = {"metadata": SAVE_METADATA.get(fmt, {})}
        if fmt == "png":
            kwargs["dpi"] = PNG_DPI
        fig.savefig(path, format=fmt, **kwargs)
        written.append(path)
    return written


def render_all(
    demo_dir: Path, out_dir: Path, lang: str, formats: tuple[str, ...] = DEFAULT_FORMATS
) -> list[Path]:
    """Render every figure whose input files exist in ``demo_dir`` and return the written paths.

    A folder that holds none of the known data files renders nothing, not even the data-free
    pipeline diagram, so an empty folder gives an empty list.
    """
    Labels(lang)
    apply_style()
    demo_dir = Path(demo_dir)
    out_dir = Path(out_dir)
    known = {file_name for spec in FIGURES.values() for file_name in spec.inputs}
    available = {file_name for file_name in known if (demo_dir / file_name).is_file()}
    if not available:
        log.info("no demo data files in %s, nothing to render", demo_dir)
        return []
    written: list[Path] = []
    for name, spec in FIGURES.items():
        missing = [file_name for file_name in spec.inputs if file_name not in available]
        if missing:
            log.info("skipping figure %s: missing %s", name, ", ".join(missing))
            continue
        frames = [pd.read_csv(demo_dir / file_name) for file_name in spec.inputs]
        fig = spec.build(*frames, lang=lang)
        try:
            written.extend(save_figure(fig, out_dir, name, lang, formats))
        finally:
            plt.close(fig)
        log.info("rendered figure %s (%s)", name, lang)
    return written
