"""Configuration loaded from YAML, with environment variable overrides."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_PATH = Path("configs/default.yaml")


class PathsConfig(BaseModel):
    data_dir: Path = Path("data")
    landing_dir: Path = Path("data/landing")
    logs_dir: Path = Path("logs")


class HttpConfig(BaseModel):
    user_agent: str = "foretaksrisiko/0.1 (research)"
    requests_per_second: float = 4.0
    max_retries: int = 5
    timeout_seconds: float = 60.0
    backoff_base_seconds: float = 1.0
    backoff_cap_seconds: float = 60.0
    workers: int = 3


class BrregConfig(BaseModel):
    base_url: str = "https://data.brreg.no"
    enheter_bulk_path: str = "/enhetsregisteret/api/enheter/lastned"
    enheter_bulk_accept: str = "application/vnd.brreg.enhetsregisteret.enhet.v2+gzip;charset=UTF-8"
    underenheter_bulk_path: str = "/enhetsregisteret/api/underenheter/lastned"
    underenheter_bulk_accept: str = (
        "application/vnd.brreg.enhetsregisteret.underenhet.v2+gzip;charset=UTF-8"
    )
    roller_bulk_path: str = "/enhetsregisteret/api/roller/totalbestand"
    roller_bulk_accept: str = "application/gzip"
    regnskap_path: str = "/regnskapsregisteret/regnskap/{orgnr}"
    oppdateringer_enheter_path: str = "/enhetsregisteret/api/oppdateringer/enheter"
    oppdateringer_underenheter_path: str = "/enhetsregisteret/api/oppdateringer/underenheter"
    oppdateringer_roller_path: str = "/enhetsregisteret/api/oppdateringer/roller"


class ScopeConfig(BaseModel):
    organisasjonsformer: list[str] = Field(default_factory=lambda: ["AS", "ASA"])
    drop_frivillighetsregisteret: bool = True


class SampleConfig(BaseModel):
    size: int = 50_000
    seed: int = 42


class KlassConfig(BaseModel):
    base_url: str = "https://data.ssb.no/api/klass/v1"
    sn2025_version: int = 3218
    sn2007_version: int = 30
    sn_correspondence_table: int = 2919
    fylke_version: int = 3315
    kommune_version: int = 3262
    fylke_correspondence_table: int = 2799
    kommune_correspondence_table: int = 2774


class LandingConfig(BaseModel):
    rows_per_file: int = 50_000
    regnskap_batch_size: int = 500
    # Share of the population whose accounts are fetched again in each later snapshot, chosen by
    # a hash of the organisation number, so every company is refreshed within 1/share snapshots.
    # Companies with a reported new filing and new companies are always fetched.
    regnskap_refresh_share: float = 0.1


class LakehouseConfig(BaseModel):
    catalog: str = "workspace"
    local_catalog: str = "spark_catalog"
    schema_prefix: str = "foretaksrisiko_"
    volume_name: str = "snapshots"
    local_warehouse_dir: Path = Path("data/warehouse")
    upload_exclude: list[str] = Field(default_factory=lambda: ["enheter_tekst"])
    bronze_tables: list[str] = Field(
        default_factory=lambda: [
            "enheter",
            "underenheter",
            "roller_counts",
            "roller_links",
            "sample",
            "regnskap",
            "regnskap_status",
            "oppdateringer_enheter",
            "oppdateringer_underenheter",
            "oppdateringer_roller",
            "events_enheter",
            "events_roller",
            "events_monthly_all",
            "text_features",
        ]
    )
    klass_tables: list[str] = Field(
        default_factory=lambda: [
            "sn2025",
            "sn2007",
            "sn_corr_2025_2007",
            "fylke",
            "kommune",
            "fylke_corr_2026_2024",
            "kommune_corr_2026_2024",
        ]
    )


class DesignConfig(BaseModel):
    """Label and feature design. Reference times are offsets from the snapshot date, never dates."""

    horizon_months: int = 6
    retro_offset_months: int = 6
    change_windows_months: list[int] = Field(default_factory=lambda: [6, 12])
    adverse_lookback_months: int = 24
    peer_min_size: int = 20
    size_band_quantiles: list[float] = Field(default_factory=lambda: [0.25, 0.5, 0.75, 0.9])
    extreme_z: float = 3.0
    filing_deadline_month: int = 8
    filing_deadline_day: int = 1


class ModelConfig(BaseModel):
    """Modelling and evaluation settings. Mirrors the pre-registered plan."""

    split_seed: int = 42
    train_share: float = 0.6
    valid_share: float = 0.2
    seeds: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5])
    top_shares: list[float] = Field(default_factory=lambda: [0.01, 0.05])
    bootstrap_samples: int = 1000
    calibration_bins: int = 10
    min_group_size: int = 20
    iforest_estimators: int = 300
    iforest_max_samples: int = 50_000
    mahalanobis_fit_rows: int = 20_000
    hgb_grid_learning_rate: list[float] = Field(default_factory=lambda: [0.05, 0.1])
    hgb_grid_max_leaf_nodes: list[int] = Field(default_factory=lambda: [15, 31])
    hgb_grid_min_samples_leaf: list[int] = Field(default_factory=lambda: [50, 200])
    hgb_max_iter: int = 400
    shap_rows: int = 1000
    experiment_name: str = "foretaksrisiko"


class QualityConfig(BaseModel):
    # Severity of the organisation number checksum check. Tests lower it to "warn" because
    # synthetic fixtures use numbers that fail the checksum on purpose (brief rule L7).
    mod11_severity: str = "error"
    min_nace_section_share: float = 0.85
    min_fylke_coverage: float = 0.99
    min_kommune_coverage: float = 0.99
    max_future_date_share: float = 0.0


class PromotionConfig(BaseModel):
    """Pre-set thresholds a challenger must meet on the frozen validation split before promotion.

    Promotion itself is a manual step (Reza approves); these rules only decide eligibility.
    """

    min_average_precision: float = 0.10
    min_precision_top_1pct: float = 0.05
    max_brier: float = 0.02
    max_expected_calibration_error: float = 0.02
    min_positives_valid: int = 30
    # A challenger may not be worse than the current champion by more than this relative margin
    # on validation average precision. Ignored when there is no champion yet.
    require_not_worse_than_champion: bool = True
    relative_tolerance: float = 0.05


class RegistryConfig(BaseModel):
    """Unity Catalog model registry: one registered model with champion and challenger aliases."""

    model_name: str = "proxy_outcome_hgb"
    layer: str = "gold"
    artifact_path: str = "hgb_calibrated"
    champion_alias: str = "champion"
    challenger_alias: str = "challenger"
    promotion: PromotionConfig = PromotionConfig()


class MonitoringConfig(BaseModel):
    """Drift thresholds and retraining trigger rules. A scenario overrides thresholds by name."""

    design: str = "prospective"
    psi_bins: int = 10
    # Band around each bin edge in which a value counts on both sides, as a share of the
    # reference's inter-decile range. Zero gives hard edges.
    psi_edge_smoothing: float = 0.02
    psi_warn: float = 0.10
    psi_alert: float = 0.25
    missingness_delta_warn: float = 0.02
    missingness_delta_alert: float = 0.05
    category_share_delta_warn: float = 0.05
    category_share_delta_alert: float = 0.10
    score_psi_warn: float = 0.10
    score_psi_alert: float = 0.25
    flag_share: float = 0.05
    flag_share_relative_warn: float = 0.25
    flag_share_relative_alert: float = 0.50
    min_rows: int = 1000
    retrain_min_alert_features: int = 3
    retrain_max_champion_age_snapshots: int = 26
    retrain_min_new_positives: int = 200
    scenarios: dict[str, dict[str, float]] = Field(default_factory=dict)

    def with_scenario(self, name: str | None) -> MonitoringConfig:
        """Return a copy with the named scenario's threshold overrides applied."""
        if not name or name == "default":
            return self
        if name not in self.scenarios:
            raise KeyError(f"unknown monitoring scenario: {name}")
        return self.model_copy(update=self.scenarios[name])


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORETAKSRISIKO_", env_nested_delimiter="__")

    paths: PathsConfig = PathsConfig()
    http: HttpConfig = HttpConfig()
    brreg: BrregConfig = BrregConfig()
    scope: ScopeConfig = ScopeConfig()
    sample: SampleConfig = SampleConfig()
    klass: KlassConfig = KlassConfig()
    landing: LandingConfig = LandingConfig()
    lakehouse: LakehouseConfig = LakehouseConfig()
    quality: QualityConfig = QualityConfig()
    design: DesignConfig = DesignConfig()
    model: ModelConfig = ModelConfig()
    registry: RegistryConfig = RegistryConfig()
    monitoring: MonitoringConfig = MonitoringConfig()


PACKAGED_CONFIG_PATH = Path(__file__).parent / "configs" / "default.yaml"


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from a YAML file: the given path, the repo default, or the packaged copy."""
    candidates = [config_path] if config_path else [DEFAULT_CONFIG_PATH, PACKAGED_CONFIG_PATH]
    data: dict = {}
    for path in candidates:
        if path is not None and path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            break
    return Settings(**data)
