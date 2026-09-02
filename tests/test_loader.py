"""Universe loaders: YAML, CSV, defaults, and failure isolation."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from briefing_app.config import (
    AppConfig,
    CandidateDefaults,
    ConfigError,
    first_symbol_for_geography,
    load_config,
)
from briefing_app.models.candidate import CandidateSource, Geography, Instrument
from briefing_app.universe.loader import (
    UniverseLoadError,
    load_candidate_file,
    load_fixed_universe,
    load_screen_candidates,
    load_universe,
)

FIXED_YAML = """
source: fixed_universe
defaults:
  broker: Trade Republic
candidates:
  - NVDA
  - ticker: rhm.de
    venue: XETRA
    geography: Germany
    expression_class: E
    thesis: Budget cycle event.
    permitted_instruments: [shares, knock_out]
    catalysts:
      - name: Budget vote
        date: 2026-09-06
        status: confirmed
"""

CSV_TEXT = """ticker,venue,thesis,expression_class,permitted_instruments,catalyst_name,catalyst_date,catalyst_status,catalyst_kind
fdx,NYSE,Freight read.,V,shares|options,Quarterly results,2026-09-17,confirmed,earnings
fdx,NYSE,Freight read.,V,shares|options,US CPI,2026-09-10,confirmed,macro
gm,NYSE,Tariff ruling.,E,shares|options,Tariff ruling,2026-09-07,estimated,regulatory
"""


def write_config(tmp_path: Path, body: str) -> AppConfig:
    (tmp_path / "config.yaml").write_text(body, encoding="utf-8")
    return load_config(tmp_path / "config.yaml")


def test_load_config_exposes_report_grading_defaults(tmp_path: Path) -> None:
    config = write_config(tmp_path, "{}\n")

    assert config.report.grading.probability_weight == pytest.approx(0.60)
    assert config.report.grading.alignment_weight == pytest.approx(0.40)
    assert config.report.grading.divergence_penalty == pytest.approx(10.0)
    assert config.report.grading.crowding_penalty_scale == pytest.approx(20.0)


def test_load_config_rejects_report_grading_weights_that_do_not_sum_to_one(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.yaml").write_text(
        """
report:
  grading:
    probability_weight: 0.9
    alignment_weight: 0.4
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path / "config.yaml")

    message = str(excinfo.value)
    assert "probability_weight" in message
    assert "alignment_weight" in message


def test_load_config_rejects_report_grading_weights_outside_bounds(
    tmp_path: Path,
) -> None:
    (tmp_path / "config.yaml").write_text(
        """
report:
  grading:
    probability_weight: -0.1
    alignment_weight: 1.1
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path / "config.yaml")

    message = str(excinfo.value)
    assert "probability_weight" in message
    assert "alignment_weight" in message


def test_provider_chains_parse_strings_and_default_full_fallbacks(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
providers:
  news: alpha_vantage
""",
    )

    assert config.providers.news == ["alpha_vantage"]
    assert config.providers.options == ["cboe", "alpha_vantage"]
    assert config.providers.prices == ["fmp", "twelve_data", "alpha_vantage"]


def test_load_config_rejects_unknown_provider_names(tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(
        """
providers:
  news: [finnhub, not_a_provider]
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as excinfo:
        load_config(tmp_path / "config.yaml")

    message = str(excinfo.value)
    assert "providers" in message
    assert "news" in message
    assert "not_a_provider" in message


def test_yaml_loader_applies_config_defaults_and_file_defaults(tmp_path: Path) -> None:
    (tmp_path / "fixed.yaml").write_text(FIXED_YAML, encoding="utf-8")
    defaults = CandidateDefaults(venue="NASDAQ", broker="IBKR", thesis="Watched name.")

    result = load_candidate_file(
        tmp_path / "fixed.yaml", defaults=defaults, source=CandidateSource.SCREEN
    )
    assert result.errors == []
    nvda, rhm = result.candidates

    # A bare ticker string inherits every default...
    assert nvda.ticker == "NVDA"
    assert nvda.venue == "NASDAQ"
    assert nvda.thesis == "Watched name."
    assert nvda.expression_class.value == "E"
    # ...but the file-level default overrides only the key it names.
    assert nvda.broker == "Trade Republic"
    # The file declares its own source, overriding the caller's.
    assert nvda.source is CandidateSource.FIXED_UNIVERSE
    assert nvda.origin == str(tmp_path / "fixed.yaml")

    assert rhm.ticker == "RHM.DE"
    assert rhm.geography is Geography.EU
    assert rhm.permitted_instruments == [Instrument.SHARES, Instrument.KNOCK_OUT]
    assert rhm.catalysts[0].event_date == date(2026, 9, 6)


def test_csv_loader_merges_repeated_tickers_into_one_candidate(tmp_path: Path) -> None:
    (tmp_path / "watchlist.csv").write_text(CSV_TEXT, encoding="utf-8")
    result = load_candidate_file(
        tmp_path / "watchlist.csv",
        defaults=CandidateDefaults(),
        source=CandidateSource.WATCHLIST,
    )
    assert result.errors == []
    assert [c.ticker for c in result.candidates] == ["FDX", "GM"]

    fdx = result.candidates[0]
    assert [c.name for c in fdx.catalysts] == ["US CPI", "Quarterly results"]
    assert fdx.permitted_instruments == [Instrument.SHARES, Instrument.OPTIONS]
    assert fdx.source is CandidateSource.WATCHLIST


def test_a_bad_record_is_collected_as_an_error_without_killing_the_load(
    tmp_path: Path,
) -> None:
    (tmp_path / "bad.yaml").write_text(
        """
candidates:
  - ticker: GOOD
    thesis: Fine.
    catalysts: []
  - ticker: BAD
    thesis: Typo in a field name.
    expresion_class: E
  - ticker: WORSE
    thesis: Unknown instrument.
    permitted_instruments: [perpetual_swap]
""",
        encoding="utf-8",
    )
    result = load_candidate_file(
        tmp_path / "bad.yaml", defaults=CandidateDefaults(), source=CandidateSource.SCREEN
    )
    assert [c.ticker for c in result.candidates] == ["GOOD"]
    assert len(result.errors) == 2
    assert "BAD" in result.errors[0] and "expresion_class" in result.errors[0]
    assert "WORSE" in result.errors[1]


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(UniverseLoadError):
        load_candidate_file(
            tmp_path / "nope.yaml",
            defaults=CandidateDefaults(),
            source=CandidateSource.SCREEN,
        )


def test_unusable_yaml_structure_raises(tmp_path: Path) -> None:
    (tmp_path / "odd.yaml").write_text("names:\n  - AAA\n", encoding="utf-8")
    with pytest.raises(UniverseLoadError):
        load_candidate_file(
            tmp_path / "odd.yaml",
            defaults=CandidateDefaults(),
            source=CandidateSource.SCREEN,
        )


def test_fixed_universe_count_outside_the_expected_band_warns_but_loads(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        """
universe:
  mode: fixed
  fixed: [AAA, BBB]
  fixed_min: 8
  fixed_max: 12
candidate_defaults:
  venue: NASDAQ
  thesis: Watched name.
""",
    )
    result = load_fixed_universe(config)
    assert [c.ticker for c in result.candidates] == ["AAA", "BBB"]
    assert "expected at least 8" in result.warnings[0]


def test_screen_universe_upper_bound_warns(tmp_path: Path) -> None:
    tickers = "\n".join(f"  - T{i}" for i in range(35))
    (tmp_path / "screen.yaml").write_text(f"candidates:\n{tickers}\n", encoding="utf-8")
    config = write_config(
        tmp_path,
        """
universe:
  mode: screen
  candidate_files: [screen.yaml]
candidate_defaults:
  thesis: Watched name.
""",
    )
    result = load_screen_candidates(config)
    assert len(result.candidates) == 35
    assert "expected at most 30" in result.warnings[0]


def test_load_universe_combines_both_sources_and_keeps_duplicates_for_the_gate(
    tmp_path: Path,
) -> None:
    (tmp_path / "screen.yaml").write_text("candidates: [NVDA, AMD]\n", encoding="utf-8")
    config = write_config(
        tmp_path,
        """
universe:
  mode: both
  fixed: [NVDA]
  candidate_files: [screen.yaml]
  fixed_min: 0
  screen_min: 0
candidate_defaults:
  thesis: Watched name.
""",
    )
    result = load_universe(config)
    assert [c.ticker for c in result.candidates] == ["NVDA", "NVDA", "AMD"]
    assert result.candidates[0].source is CandidateSource.FIXED_UNIVERSE
    assert result.candidates[1].source is CandidateSource.SCREEN


def test_mode_override_beats_the_configured_mode(tmp_path: Path) -> None:
    (tmp_path / "screen.yaml").write_text("candidates: [AMD]\n", encoding="utf-8")
    config = write_config(
        tmp_path,
        """
universe:
  mode: both
  fixed: [NVDA]
  candidate_files: [screen.yaml]
  fixed_min: 0
  screen_min: 0
candidate_defaults:
  thesis: Watched name.
""",
    )
    assert [c.ticker for c in load_universe(config, "fixed").candidates] == ["NVDA"]
    assert [c.ticker for c in load_universe(config, "screen").candidates] == ["AMD"]
    with pytest.raises(UniverseLoadError):
        load_universe(config, "everything")


def test_empty_universe_warns_rather_than_failing_silently(tmp_path: Path) -> None:
    config = write_config(tmp_path, "universe:\n  mode: both\n")
    result = load_universe(config)
    assert result.candidates == []
    assert "produced no candidates" in result.warnings[0]


def test_bare_ticker_shorthand_needs_a_default_thesis(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        """
universe:
  mode: fixed
  fixed: [AAA]
  fixed_min: 0
""",
    )
    result = load_fixed_universe(config)
    assert result.candidates == []
    assert "thesis: Field required" in result.errors[0]


def test_probe_symbol_resolution_order(tmp_path: Path) -> None:
    """Probe symbols come from the universe first, config defaults only as a backstop."""
    (tmp_path / "fixed.yaml").write_text(
        """
candidates:
  - ticker: NVDA
    thesis: Watched US name.
    catalysts: []
  - ticker: RHM.DE
    venue: XETRA
    geography: EU
    thesis: Watched EU name.
    catalysts: []
""",
        encoding="utf-8",
    )
    config = write_config(
        tmp_path,
        """
universe:
  mode: fixed
  fixed_files: [fixed.yaml]
  fixed_min: 0
preflight:
  default_probe_symbols:
    US: SPY
    UK: VOD
""",
    )
    # Declared in universe.fixed_files, which the inline-only scan used to miss.
    assert first_symbol_for_geography(config, "US", "FALLBACK") == "NVDA"
    assert first_symbol_for_geography(config, "EU", "FALLBACK") == "RHM.DE"
    # No universe name for that geography: fall through to the configured default.
    assert first_symbol_for_geography(config, "UK", "FALLBACK") == "VOD"
    # Nothing configured at all: the caller's fallback.
    assert first_symbol_for_geography(config, "OTHER", "FALLBACK") == "FALLBACK"


def test_probe_symbol_lookup_survives_a_broken_candidate_file(tmp_path: Path) -> None:
    (tmp_path / "fixed.yaml").write_text("candidates: {not: a list}\n", encoding="utf-8")
    config = write_config(
        tmp_path,
        """
universe:
  mode: fixed
  fixed_files: [fixed.yaml]
preflight:
  default_probe_symbols:
    US: SPY
""",
    )
    assert first_symbol_for_geography(config, "US", "FALLBACK") == "SPY"
