"""Model data preparation: feature groups, masked-value imputation, company splits.

Identifier columns and every ``masked_*`` column are never model inputs. Masked values are filled
with training statistics so that the pattern of masking cannot be learned.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from foretaksrisiko.config import ModelConfig

ID_COLUMNS = [
    "design",
    "reference_snapshot_id",
    "reference_date",
    "organisasjonsnummer",
    "peer_group",
]
NEVER_FEATURES = {
    "any_change_after_t",
    "nace_sn2025",
    "kommunenummer",
    "acc_fiscal_year",
    "acc_prev_fiscal_year",
}
CATEGORICAL = [
    "nace_section",
    "nace_division",
    "fylke_code",
    "size_band",
    "institusjonell_sektorkode",
    "acc_oppstillingsplan",
    "acc_regnskapsregler",
]
LABEL_COLUMNS = ["label_strict", "label_broad", "eligible"]
RETRO_EXCLUDED = {"antall_ansatte"}

# Masked flag -> the feature columns it governs.
MASK_GOVERNS = {
    "masked_kapital": ["kapital_belop", "log_kapital"],
    "masked_antall_ansatte": ["antall_ansatte", "har_registrert_antall_ansatte"],
    "masked_naeringskode1": ["nace_section", "nace_division", "nace_missing"],
    "masked_adresse": ["fylke_code", "post_address_other_municipality"],
    "masked_mva": ["registrert_i_mvaregisteret"],
    "masked_er_i_konsern": ["er_i_konsern"],
    "masked_text": [
        "text_chars",
        "text_sim_own_code",
        "text_sim_best",
        "text_rank_own_code",
        "text_sim_section",
    ],
    "masked_board": [
        "board_size",
        "n_board_chair",
        "n_board_deputy_chair",
        "n_board_members",
        "n_deputy_members",
        "n_observers",
        "has_chair",
        "n_roles_valgt_av",
        "days_since_board_change",
    ],
    "masked_ceo": ["n_ceo", "has_ceo", "ceo_is_chair", "days_since_ceo_change"],
    "masked_auditor": [
        "has_auditor",
        "auditor_portfolio_size",
        "auditor_other_clients_adverse_share",
        "auditor_outside_population",
    ],
    "masked_accountant": [
        "has_accountant",
        "accountant_portfolio_size",
        "accountant_other_clients_adverse_share",
    ],
    "masked_roles_any": [
        "n_person_roleholders",
        "n_distinct_persons",
        "n_deceased_roleholders",
        "n_org_roleholders",
        "n_deregistered_roles",
    ],
}


def feature_group(column: str) -> str:
    """Assign a feature column to one of the ablation groups."""
    if column.startswith("text_"):
        return "text"
    if column.startswith(("auditor_", "accountant_")):
        return "network"
    base = (
        column[2:]
        if column.startswith("z_")
        else column[4:]
        if column.startswith("pct_")
        else column
    )
    if base.startswith("acc_") or base in {
        "equity_ratio",
        "debt_ratio",
        "operating_margin",
        "return_on_assets",
        "current_ratio",
        "cash_ratio",
        "interest_burden",
        "log_revenue",
        "log_assets",
        "revenue_growth",
        "asset_growth",
        "negative_equity",
        "zero_revenue",
        "loss",
        "has_accounts",
        "size_band",
    }:
        return "accounts"
    if column.startswith(("z_", "pct_")) or column == "n_extreme_z":
        return "peer"
    if column in {
        "board_size",
        "n_board_chair",
        "n_board_deputy_chair",
        "n_board_members",
        "n_deputy_members",
        "n_observers",
        "has_chair",
        "n_roles_valgt_av",
        "n_ceo",
        "has_ceo",
        "ceo_is_chair",
        "has_auditor",
        "has_accountant",
        "has_contact_person",
        "n_person_roleholders",
        "n_distinct_persons",
        "n_deceased_roleholders",
        "n_org_roleholders",
        "n_deregistered_roles",
        "days_since_board_change",
        "days_since_ceo_change",
        "n_role_events_6m",
        "n_role_events_12m",
    }:
        return "roles"
    return "register"


@dataclass
class Prepared:
    """Model-ready frame plus metadata."""

    frame: pd.DataFrame
    features: list[str]
    categorical: list[str]
    groups: dict[str, list[str]] = field(default_factory=dict)
    fill_values: dict[str, object] = field(default_factory=dict)
    dropped_constant: list[str] = field(default_factory=list)

    def matrix(
        self, rows: pd.Series | None = None, drop_groups: tuple[str, ...] = ()
    ) -> pd.DataFrame:
        columns = [c for c in self.features if feature_group(c) not in drop_groups]
        frame = self.frame if rows is None else self.frame[rows]
        return frame[columns]


def select_features(columns: list[str], design: str) -> list[str]:
    excluded = NEVER_FEATURES | set(ID_COLUMNS) | set(LABEL_COLUMNS)
    if design == "retro":
        excluded |= RETRO_EXCLUDED
    return [
        c for c in columns if not c.startswith("masked_") and c not in excluded and c != "split"
    ]


def split_companies(orgnr: pd.Series, cfg: ModelConfig) -> pd.Series:
    """Deterministic train/valid/test assignment from a salted hash of the organisation number."""
    salt = f"foretaksrisiko-split-{cfg.split_seed}".encode()

    def bucket(value: str) -> int:
        digest = hashlib.sha256(salt + str(value).encode()).digest()
        return int.from_bytes(digest[:4], "big") % 10_000

    buckets = orgnr.map(bucket)
    train_cut = int(cfg.train_share * 10_000)
    valid_cut = int((cfg.train_share + cfg.valid_share) * 10_000)
    return pd.Series(
        np.where(buckets < train_cut, "train", np.where(buckets < valid_cut, "valid", "test")),
        index=orgnr.index,
        dtype="object",
    )


def _fill_value(series: pd.Series):
    clean = series.dropna()
    if clean.empty:
        return None
    if pd.api.types.is_bool_dtype(series) or clean.isin([True, False]).all():
        return bool(clean.mode().iloc[0])
    if pd.api.types.is_numeric_dtype(series):
        return float(clean.median())
    return clean.mode().iloc[0]


def prepare(frame: pd.DataFrame, design: str, cfg: ModelConfig) -> Prepared:
    """Select features, impute masked values from training rows, encode categoricals, add split."""
    frame = frame.copy()
    frame["split"] = split_companies(frame["organisasjonsnummer"], cfg)
    features = select_features(list(frame.columns), design)
    train_rows = frame["split"] == "train"
    fill_values: dict[str, object] = {}
    for flag, governed in MASK_GOVERNS.items():
        if flag not in frame.columns:
            continue
        masked = frame[flag].fillna(False).astype(bool)
        for column in governed:
            if column not in frame.columns or column not in features:
                continue
            value = _fill_value(frame.loc[train_rows & ~masked, column])
            fill_values[column] = value
            if value is not None:
                frame.loc[masked, column] = value
    for column in features:
        if (
            pd.api.types.is_bool_dtype(frame[column])
            or frame[column].dropna().isin([True, False]).all()
        ):
            frame[column] = frame[column].map({True: 1.0, False: 0.0}).astype("float32")
    # Drop features that are constant on the training rows; they carry nothing and some
    # learners cannot bin a single distinct value.
    constant = [
        c
        for c in features
        if frame.loc[train_rows, c].dropna().nunique() <= 1 and c != "nace_missing"
    ]
    features = [c for c in features if c not in constant]
    categorical = [c for c in CATEGORICAL if c in features]
    for column in categorical:
        frame[column] = frame[column].astype("string").fillna("missing").astype("category")
    for column in features:
        if column not in categorical and pd.api.types.is_numeric_dtype(frame[column]):
            frame[column] = frame[column].astype("float32")
    groups: dict[str, list[str]] = {}
    for column in features:
        groups.setdefault(feature_group(column), []).append(column)
    return Prepared(
        frame=frame,
        features=features,
        categorical=categorical,
        groups=groups,
        fill_values=fill_values,
        dropped_constant=constant,
    )


def numeric_matrix(
    prepared: Prepared, rows: pd.Series | None = None, drop_groups: tuple[str, ...] = ()
) -> pd.DataFrame:
    """Numeric features only, median-imputed, for the anomaly models."""
    matrix = prepared.matrix(rows, drop_groups)
    numeric = [c for c in matrix.columns if c not in prepared.categorical]
    matrix = matrix[numeric].astype("float32")
    medians = matrix.median()
    return matrix.fillna(medians).fillna(0.0)
