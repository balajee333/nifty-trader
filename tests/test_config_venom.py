"""Tests for VenomConfig integration into AppConfig / load_config."""

import tempfile
import textwrap
from pathlib import Path

import pytest

from nifty_trader.config import AppConfig, VenomConfig, load_config, _make_sub


class TestVenomConfigDefaults:
    """VenomConfig with no overrides should carry sensible defaults."""

    def test_defaults(self):
        vc = VenomConfig()
        assert vc.ohlc_tolerance_index_pct == 0.05
        assert vc.ohlc_tolerance_option_abs == 0.50
        assert vc.min_confirmations == 3
        assert vc.vix_full == 13.0
        assert vc.vix_selective == 18.0
        assert vc.vix_caution == 23.0
        assert vc.vix_restricted == 30.0
        assert vc.vix_blocked == 30.0
        assert vc.entry_window_start == "09:16"
        assert vc.entry_window_end == "14:30"
        assert vc.sl_percent == 30.0
        assert vc.trail_activation_pct == 20.0
        assert vc.trail_distance_pct == 15.0
        assert vc.max_profit_pct == 100.0
        assert vc.time_stop_minutes == 20
        assert vc.max_trades_per_day == 3
        assert vc.max_daily_loss == 3000.0
        assert vc.max_weekly_loss == 8000.0
        assert vc.consecutive_loss_limit == 3
        assert vc.mtd_protection_threshold == 12000.0
        assert vc.mtd_stop_threshold == -5000.0

    def test_frozen(self):
        vc = VenomConfig()
        with pytest.raises(AttributeError):
            vc.sl_percent = 50.0  # type: ignore[misc]


class TestMakeSubVenom:
    """_make_sub should parse VenomConfig from a dict."""

    def test_empty_dict(self):
        vc = _make_sub(VenomConfig, {})
        assert vc == VenomConfig()

    def test_none(self):
        vc = _make_sub(VenomConfig, None)
        assert vc == VenomConfig()

    def test_partial_override(self):
        vc = _make_sub(VenomConfig, {"sl_percent": 25.0, "max_trades_per_day": 5})
        assert vc.sl_percent == 25.0
        assert vc.max_trades_per_day == 5
        assert vc.vix_full == 13.0  # unchanged default

    def test_unknown_keys_ignored(self):
        vc = _make_sub(VenomConfig, {"does_not_exist": 42})
        assert vc == VenomConfig()


class TestAppConfigHasVenom:
    """AppConfig should contain a VenomConfig member."""

    def test_default_app_config(self):
        cfg = AppConfig()
        assert isinstance(cfg.venom, VenomConfig)

    def test_venom_in_fields(self):
        assert "venom" in {f.name for f in AppConfig.__dataclass_fields__.values()}


class TestLoadConfigVenom:
    """load_config should parse a venom: section from YAML."""

    def test_load_with_venom_section(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            venom:
              sl_percent: 40.0
              max_trades_per_day: 5
              vix_blocked: 35.0
        """)
        yaml_file = tmp_path / "settings.yaml"
        yaml_file.write_text(yaml_content)

        cfg = load_config(yaml_path=yaml_file)
        assert cfg.venom.sl_percent == 40.0
        assert cfg.venom.max_trades_per_day == 5
        assert cfg.venom.vix_blocked == 35.0
        # defaults preserved
        assert cfg.venom.vix_full == 13.0

    def test_load_without_venom_section(self, tmp_path):
        yaml_file = tmp_path / "settings.yaml"
        yaml_file.write_text("strategy_mode: directional\n")

        cfg = load_config(yaml_path=yaml_file)
        assert cfg.venom == VenomConfig()
