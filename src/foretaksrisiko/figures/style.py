"""Shared figure style: Agg backend, rcParams and a colourblind-safe palette.

The bilingual label tables live in ``foretaksrisiko.figures.labels`` and are re-exported here so
that figure code and tests can import everything from one place.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from cycler import cycler

from foretaksrisiko.figures.labels import (  # noqa: F401 - re-exported for callers
    ABLATION_NAMES,
    ABLATION_ORDER,
    FEATURE_NAMES,
    GROUP_TYPE_NAMES,
    GROUP_TYPE_ORDER,
    KIND_NAMES,
    KIND_ORDER,
    LABELS,
    LANGUAGES,
    METRIC_NAMES,
    MODEL_NAMES,
    MODEL_ORDER,
    Labels,
)

# Okabe-Ito palette, readable with the common forms of colour vision deficiency.
OKABE_ITO = {
    "orange": "#E69F00",
    "sky": "#56B4E9",
    "green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermilion": "#D55E00",
    "purple": "#CC79A7",
    "black": "#000000",
}
PALETTE = tuple(OKABE_ITO.values())
# Series that share an axis also get distinct markers, hatches or line styles, so that the
# figures stay readable when printed in grey scale.
MARKERS = ("o", "s", "^", "D", "v", "P", "X", "*")
HATCHES = ("", "//", "\\\\", "xx", "..", "++", "oo", "--")
LINESTYLES = ("-", "--", "-.", ":")
GRID_COLOR = "#CCCCCC"
REFERENCE_COLOR = "#777777"

RC_PARAMS = {
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.titleweight": "bold",
    "axes.labelsize": 9,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
    "legend.fontsize": 8,
    "legend.title_fontsize": 8,
    "legend.frameon": False,
    "figure.titlesize": 11,
    "figure.titleweight": "bold",
    "figure.dpi": 100,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "axes.axisbelow": True,
    "grid.color": GRID_COLOR,
    "grid.linestyle": ":",
    "grid.linewidth": 0.6,
    "axes.prop_cycle": cycler(color=list(PALETTE)),
    "lines.linewidth": 1.4,
    "lines.markersize": 5,
    "hatch.linewidth": 0.6,
    "patch.linewidth": 0.5,
    "svg.fonttype": "none",
    "pdf.fonttype": 42,
}


def apply_style() -> None:
    """Install the shared rcParams for the current process."""
    matplotlib.rcParams.update(RC_PARAMS)
