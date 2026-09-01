"""Typed loader for `config/config.yaml`.

Only the sections the pipeline consumes directly are modelled strictly; the rest of the
file is preserved verbatim so later tasks can add typed sections without breaking
existing local config.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from briefing_app.models.candidate import (
    DEFAULT_CLASS_INSTRUMENT_FIT,
    DEFAULT_LEVERAGED_INSTRUMENTS,
    Crowding,
    Direction,
    ExpressionClass,
    Geography,
    Instrument,
)

DEFAULT_CONFIG_PATHS: tuple[str, ...] = ("config/config.yaml", "config/config.example.yaml")

ProviderName = Literal[
    "alpha_vantage",
    "cboe",
    "fmp",
    "finnhub",
    "fred",
    "finra",
    "sec_edgar",
    "fca",
    "eurex",
    "bundesanzeiger",
    "eu_oam",
    "tiingo",
    "twelve_data",
    "quiver",
]


class ConfigError(RuntimeError):
    """Raised when the config file is missing or structurally unusable."""


class CandidateDefaults(BaseModel):
    """Applied to any candidate field a loaded record leaves unset."""

    model_config = ConfigDict(extra="forbid")

    venue: str = "NASDAQ"
    geography: Geography = Geography.US
    country: str | None = None
    currency: str | None = None
    sector: str | None = None
    # Set `thesis` to allow bare-ticker shorthand (`universe.fixed: [SPY, QQQ]`);
    # leave it unset to force every candidate to declare its own one-liner.
    thesis: str | None = None
    direction: Direction = Direction.LONG
    horizon_days: int = Field(default=10, gt=0)
    expression_class: ExpressionClass = ExpressionClass.E
    broker: str | None = None
    permitted_instruments: list[Instrument] = Field(
        default_factory=lambda: [Instrument.SHARES, Instrument.OPTIONS]
    )
    crowding: Crowding = Crowding.NEUTRAL


class UniverseSettings(BaseModel):
    """Where candidates come from, and how many of each kind are expected."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["fixed", "screen", "both"] = "both"
    fixed: list[Any] = Field(default_factory=list)
    fixed_files: list[str] = Field(default_factory=list)
    candidate_files: list[str] = Field(default_factory=list)
    fixed_min: int = Field(default=8, ge=0)
    fixed_max: int = Field(default=12, ge=0)
    screen_min: int = Field(default=15, ge=0)
    screen_max: int = Field(default=30, ge=0)


class GateSettings(BaseModel):
    """Thresholds and policy switches for the pre-scoring catalyst gate."""

    model_config = ConfigDict(extra="forbid")

    default_horizon_days: int = Field(default=10, gt=0)
    enabled_expression_classes: list[ExpressionClass] = Field(
        default_factory=lambda: list(ExpressionClass)
    )
    class_instrument_fit: dict[ExpressionClass, list[Instrument]] = Field(
        default_factory=lambda: {
            klass: list(instruments)
            for klass, instruments in DEFAULT_CLASS_INSTRUMENT_FIT.items()
        }
    )
    leveraged_instruments: list[Instrument] = Field(
        default_factory=lambda: list(DEFAULT_LEVERAGED_INSTRUMENTS)
    )
    allow_leverage_on_estimated_catalyst: bool = False
    # Which EU per-strike options track is actually available this run (Stage 3A):
    # A browser capture, B manual capture (caps at Tier B), C nothing -> S_O = n/a.
    eu_options_track: Literal["A", "B", "C"] = "C"
    require_borrow_source_for_shorts: bool = True
    require_thesis_source: bool = True
    unverified_thesis_action: Literal["flag", "watchlist"] = "flag"
    crowded_confidence_multiplier: float = Field(default=0.5, gt=0.0, le=1.0)
    rejection_cooldown_days: int = Field(default=30, ge=0)

    def instruments_for_class(self, expression_class: ExpressionClass) -> list[Instrument]:
        configured = self.class_instrument_fit.get(expression_class)
        if configured is not None:
            return configured
        return list(DEFAULT_CLASS_INSTRUMENT_FIT[expression_class])

    def is_leveraged(self, instrument: Instrument) -> bool:
        return instrument in self.leveraged_instruments

    def summary(self) -> dict[str, Any]:
        return {
            "default_horizon_days": self.default_horizon_days,
            "enabled_expression_classes": [c.value for c in self.enabled_expression_classes],
            "eu_options_track": self.eu_options_track,
            "allow_leverage_on_estimated_catalyst": self.allow_leverage_on_estimated_catalyst,
            "require_borrow_source_for_shorts": self.require_borrow_source_for_shorts,
            "unverified_thesis_action": self.unverified_thesis_action,
            "rejection_cooldown_days": self.rejection_cooldown_days,
        }


class ReportGradingSettings(BaseModel):
    """Weights and penalties used when grading the final trading ideas report."""

    model_config = ConfigDict(extra="forbid")

    probability_weight: float = Field(default=0.60, ge=0.0, le=1.0)
    alignment_weight: float = Field(default=0.40, ge=0.0, le=1.0)
    divergence_penalty: float = 10.0
    crowding_penalty_scale: float = 20.0

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> "ReportGradingSettings":
        total = self.probability_weight + self.alignment_weight
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                "probability_weight and alignment_weight must sum to 1.0"
            )
        return self


class ReportSettings(BaseModel):
    """Settings for the generated trading ideas report."""

    model_config = ConfigDict(extra="forbid")

    grading: ReportGradingSettings = Field(default_factory=ReportGradingSettings)


class OptionFilterSettings(BaseModel):
    """Per-contract quality bar. A quote failing these is not a tradeable strike."""

    model_config = ConfigDict(extra="forbid")

    min_open_interest: int = Field(default=10, ge=0)
    min_volume: int = Field(default=1, ge=0)
    max_bid_ask_width_pct: float = Field(default=0.25, gt=0.0)
    max_quote_age_minutes: int = Field(default=30, gt=0)


class StrategySettings(BaseModel):
    """Thresholds for the T8 rule engine, all boundary-tested.

    Defaults come from the plan's Phase 7 examples and the Score Interpretation table;
    anything the plan leaves open is set conservatively so a rule refuses rather than
    guesses when the supporting data is thin.
    """

    model_config = ConfigDict(extra="forbid")

    # Volatility rules.
    short_premium_iv_rank_min: float = Field(default=70.0, ge=0.0, le=100.0)
    long_premium_iv_rank_max: float = Field(default=25.0, ge=0.0, le=100.0)
    #: IV must exceed realized by this much before premium is worth selling.
    short_premium_min_vrp: float = 0.0
    #: A 25-delta risk reversal beyond this is too skewed for a symmetric condor.
    extreme_skew_rr: float = Field(default=0.05, gt=0.0)
    #: Percentile bands of a name's own risk-reversal history that count as "material".
    skew_percentile_low: float = Field(default=10.0, ge=0.0, le=100.0)
    skew_percentile_high: float = Field(default=90.0, ge=0.0, le=100.0)
    #: Tail-probability asymmetry the implied distribution must show to back the skew.
    skew_min_tail_edge: float = Field(default=0.02, ge=0.0)

    # Directional rules. The bands mirror the Score Interpretation table.
    neutral_score_band: float = Field(default=0.15, gt=0.0, le=1.0)
    strong_score_threshold: float = Field(default=0.60, gt=0.0, le=1.0)
    require_confirmed_catalyst_for_event: bool = True
    #: The plan authorises a short/put expression only with borrow evidence.
    require_borrow_for_bearish: bool = True

    # Chain liquidity, evaluated against `option_filters`.
    min_chain_quotes: int = Field(default=20, ge=1)
    min_liquid_strike_fraction: float = Field(default=0.30, ge=0.0, le=1.0)

    # Ranges and horizons.
    event_day_multiplier: float = Field(default=1.5, gt=0.0)
    #: Days between now and expiry inside which an unmodeled event blocks short premium.
    catalyst_window_days: int = Field(default=10, ge=0)

    # Leverage guard.
    default_leverage: float = Field(default=5.0, gt=0.0)
    leverage_knockout_buffer: float = Field(default=0.5, gt=0.0, le=1.0)
    max_window_drag_pct: float | None = Field(default=None, ge=0.0)

    max_setups_per_ticker: int = Field(default=3, ge=1)

    def summary(self) -> dict[str, Any]:
        return {
            "short_premium_iv_rank_min": self.short_premium_iv_rank_min,
            "long_premium_iv_rank_max": self.long_premium_iv_rank_max,
            "neutral_score_band": self.neutral_score_band,
            "strong_score_threshold": self.strong_score_threshold,
            "require_borrow_for_bearish": self.require_borrow_for_bearish,
            "default_leverage": self.default_leverage,
            "leverage_knockout_buffer": self.leverage_knockout_buffer,
            "max_window_drag_pct": self.max_window_drag_pct,
        }


class SectorExposureSettings(BaseModel):
    """How one sector responds to each macro factor.

    Declared in config before the data pull, never inferred at scoring time: rising
    rates are a tailwind for one sector and a headwind for another, and `S_M` refuses to
    guess which. A factor with no declared sensitivity is scored `n/a`, not neutral.
    """

    model_config = ConfigDict(extra="forbid")

    #: Factor name (see `components.macro.FACTOR_BUCKETS`) to sensitivity, -1.0..+1.0.
    sensitivities: dict[str, float] = Field(default_factory=dict)
    #: Standing regulatory or policy tailwind (+) or headwind (-) for the sector.
    policy_stance: float | None = Field(default=None, ge=-1.0, le=1.0)
    policy_note: str | None = None
    policy_source: str | None = None

    @field_validator("sensitivities")
    @classmethod
    def _bounded(cls, value: dict[str, float]) -> dict[str, float]:
        for factor, sensitivity in value.items():
            if not -1.0 <= float(sensitivity) <= 1.0:
                raise ValueError(f"sensitivity for {factor} must be -1.0..+1.0")
        return value


class ComponentSettings(BaseModel):
    """Staleness bounds and inputs for the T6 components."""

    model_config = ConfigDict(extra="forbid")

    #: Sector name to its declared macro exposure.
    sector_exposures: dict[str, SectorExposureSettings] = Field(default_factory=dict)
    #: Release-cadence-relative bounds, per the plan's staleness table.
    macro_max_age_days: int = Field(default=45, gt=0)
    sentiment_max_age_days: int = Field(default=7, gt=0)
    insider_window_days: int = Field(default=90, gt=0)
    institutional_max_age_days: int = Field(default=135, gt=0)
    eu_institutional_max_age_days: int = Field(default=90, gt=0)
    catalyst_calendar_days: int = Field(default=30, gt=0)

    def exposure_for(self, sector: str | None) -> SectorExposureSettings | None:
        if not sector:
            return None
        wanted = sector.strip().lower()
        for name, exposure in self.sector_exposures.items():
            if name.strip().lower() == wanted:
                return exposure
        return None


class PipelineSettings(BaseModel):
    """T10 orchestration switches."""

    model_config = ConfigDict(extra="forbid")

    data_mode: Literal["fixture", "live"] = "fixture"
    skip_non_market_days: bool = True
    max_tickers: int | None = Field(default=None, ge=1)


class ProvidersSettings(BaseModel):
    """Ordered provider fallback chains for each live data leg."""

    model_config = ConfigDict(extra="forbid")

    options: list[ProviderName] = Field(
        default_factory=lambda: ["cboe", "alpha_vantage"]
    )
    quotes: list[ProviderName] = Field(default_factory=lambda: ["alpha_vantage"])
    prices: list[ProviderName] = Field(
        default_factory=lambda: ["fmp", "alpha_vantage"]
    )
    news: list[ProviderName] = Field(
        default_factory=lambda: ["alpha_vantage", "fmp"]
    )
    earnings: list[ProviderName] = Field(
        default_factory=lambda: ["alpha_vantage", "fmp"]
    )
    macro: list[ProviderName] = Field(default_factory=lambda: ["fmp"])
    analyst: list[ProviderName] = Field(default_factory=lambda: ["fmp"])
    #: SEC EDGAR leads: Form 4 is the primary record, free and unmetered, while the two
    #: aggregators behind it are a spent key and a plan-gated endpoint.
    insider: list[ProviderName] = Field(
        default_factory=lambda: ["sec_edgar", "alpha_vantage", "fmp"]
    )
    institutional: list[ProviderName] = Field(
        default_factory=lambda: ["alpha_vantage", "fmp"]
    )
    put_call: list[ProviderName] = Field(default_factory=lambda: ["alpha_vantage"])
    political: list[ProviderName] = Field(default_factory=list)
    retail: list[ProviderName] = Field(default_factory=list)
    #: FINRA's consolidated file is free, unmetered and needs no key, so it leads by
    #: default. It carries daily short *volume* only - see `docs/alternatives/pa1-borrow.md`.
    short_interest: list[ProviderName] = Field(default_factory=lambda: ["finra"])

    @field_validator("*", mode="before")
    @classmethod
    def _coerce_chain(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [value.strip().lower()]
        if isinstance(value, list):
            return [
                item.strip().lower() if isinstance(item, str) else item
                for item in value
            ]
        return value


class AppConfig(BaseModel):
    """Whole-file view of `config.yaml`. Unknown top-level keys are kept as-is."""

    model_config = ConfigDict(extra="allow")

    timezone: str = "Europe/Lisbon"
    universe: UniverseSettings = Field(default_factory=UniverseSettings)
    candidate_defaults: CandidateDefaults = Field(default_factory=CandidateDefaults)
    gate: GateSettings = Field(default_factory=GateSettings)
    components: ComponentSettings = Field(default_factory=ComponentSettings)
    option_filters: OptionFilterSettings = Field(default_factory=OptionFilterSettings)
    report: ReportSettings = Field(default_factory=ReportSettings)
    strategy: StrategySettings = Field(default_factory=StrategySettings)
    pipeline: PipelineSettings = Field(default_factory=PipelineSettings)
    providers: ProvidersSettings = Field(default_factory=ProvidersSettings)

    _config_path: Path | None = None

    @property
    def config_path(self) -> Path | None:
        return self._config_path

    @property
    def base_dir(self) -> Path:
        return self._config_path.parent if self._config_path else Path.cwd()

    def resolve_path(self, value: str | Path) -> Path:
        """Resolve a config-relative path: next to the config file first, then CWD."""
        path = Path(value)
        if path.is_absolute():
            return path
        for base in (self.base_dir, Path.cwd(), self.base_dir.parent):
            candidate = base / path
            if candidate.exists():
                return candidate
        return self.base_dir / path


def find_config_path(explicit: str | Path | None = None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")
        return path

    env_path = os.getenv("BRIEFING_CONFIG_PATH")
    if env_path:
        path = Path(env_path)
        if not path.exists():
            raise ConfigError(f"BRIEFING_CONFIG_PATH points at a missing file: {path}")
        return path

    for default in DEFAULT_CONFIG_PATHS:
        path = Path(default)
        if path.exists():
            return path

    raise ConfigError(
        "No config file found. Set BRIEFING_CONFIG_PATH or create "
        f"one of: {', '.join(DEFAULT_CONFIG_PATHS)}"
    )


def load_yaml(path: str | Path) -> dict[str, Any]:
    yaml_path = Path(path)
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {yaml_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Could not parse {yaml_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"{yaml_path} must contain a YAML mapping at the top level.")
    return raw


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = find_config_path(path)
    try:
        config = AppConfig.model_validate(load_yaml(config_path))
    except ValidationError as exc:
        raise ConfigError(f"Invalid config {config_path}: {exc}") from exc
    config._config_path = config_path.resolve()
    return config


def load_app_config(settings: Any | None = None) -> AppConfig:
    """Load config from an `AppSettings`-like object or the default search path."""

    config_path = getattr(settings, "config_path", None)
    return load_config(config_path)


def first_symbol_for_geography(
    config: AppConfig,
    geography: str,
    fallback: str | None = None,
) -> str | None:
    """Return the first configured fixed-universe ticker for a geography.

    Looks at the inline `universe.fixed` entries first, then the candidates declared in
    `universe.fixed_files`, then `preflight.default_probe_symbols`, then the fallback.
    """

    target = geography.strip().upper()
    default_geography = str(config.candidate_defaults.geography.value).upper()
    for raw in config.universe.fixed:
        if isinstance(raw, str):
            if default_geography == target:
                return raw.strip().upper()
            continue
        if not isinstance(raw, dict):
            continue
        ticker = raw.get("ticker")
        candidate_geography = str(raw.get("geography") or default_geography).upper()
        if ticker and candidate_geography == target:
            return str(ticker).strip().upper()

    for ticker in _fixed_file_symbols(config, target):
        return ticker

    preflight = getattr(config, "preflight", None)
    if isinstance(preflight, dict):
        default_symbols = preflight.get("default_probe_symbols") or {}
        configured = default_symbols.get(target) or default_symbols.get(target.lower())
        if configured:
            return str(configured).strip().upper()
    return fallback


def _fixed_file_symbols(config: AppConfig, target_geography: str) -> list[str]:
    """Tickers declared in `universe.fixed_files`, matching one geography.

    Imported lazily because the universe loader depends on this module. A broken
    candidate file must not take preflight down, so a load failure yields no symbols.
    """

    if not config.universe.fixed_files:
        return []
    try:
        from briefing_app.universe.loader import load_fixed_universe

        loaded = load_fixed_universe(config)
    except Exception:  # noqa: BLE001 - probe symbols are best-effort
        return []
    return [
        candidate.ticker
        for candidate in loaded.candidates
        if candidate.geography.value.upper() == target_geography
    ]
