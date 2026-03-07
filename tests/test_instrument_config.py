"""Tests for InstrumentConfig and MCX parameterization."""

from pathlib import Path
from unittest.mock import patch

import pytest

from nifty_trader.config import InstrumentConfig, AppConfig, load_config


class TestInstrumentConfigDefaults:
    def test_nifty_defaults(self):
        cfg = InstrumentConfig()
        assert cfg.name == "NIFTY"
        assert cfg.security_id == "13"
        assert cfg.exchange_segment == "NSE_FNO"
        assert cfg.spot_exchange_segment == "IDX_I"
        assert cfg.instrument_type == "INDEX"
        assert cfg.lot_size == 25
        assert cfg.feed_code == 0
        assert cfg.market_open == "09:15"
        assert cfg.market_close == "15:30"

    def test_frozen(self):
        cfg = InstrumentConfig()
        with pytest.raises(AttributeError):
            cfg.name = "GOLDM"


class TestMCXInstrumentConfig:
    def test_gold_mini(self):
        cfg = InstrumentConfig(
            name="GOLDM",
            security_id="999",
            exchange_segment="MCX_COMM",
            spot_exchange_segment="MCX_COMM",
            instrument_type="FUTCOM",
            lot_size=100,
            feed_code=5,
            market_open="09:00",
            market_close="23:30",
        )
        assert cfg.name == "GOLDM"
        assert cfg.lot_size == 100
        assert cfg.exchange_segment == "MCX_COMM"
        assert cfg.feed_code == 5

    def test_crude_oil_mini(self):
        cfg = InstrumentConfig(
            name="CRUDEOILM",
            security_id="888",
            exchange_segment="MCX_COMM",
            spot_exchange_segment="MCX_COMM",
            instrument_type="FUTCOM",
            lot_size=10,
            feed_code=5,
            market_open="09:00",
            market_close="23:30",
        )
        assert cfg.lot_size == 10

    def test_natural_gas(self):
        cfg = InstrumentConfig(
            name="NATURALGAS",
            security_id="777",
            exchange_segment="MCX_COMM",
            spot_exchange_segment="MCX_COMM",
            instrument_type="FUTCOM",
            lot_size=1250,
            feed_code=5,
            market_open="09:00",
            market_close="23:30",
        )
        assert cfg.lot_size == 1250


class TestAppConfigInstrument:
    def test_default_app_config_has_instrument(self):
        cfg = AppConfig()
        assert cfg.instrument.name == "NIFTY"
        assert cfg.instrument.lot_size == 25

    def test_load_config_defaults(self):
        """load_config with project YAML should load instrument section."""
        cfg = load_config()
        assert cfg.instrument.name == "NIFTY"
        assert cfg.instrument.security_id == "13"
        assert cfg.instrument.lot_size == 25

    def test_load_mcx_config_file(self):
        """load_config with MCX YAML should load CRUDEOILM instrument."""
        mcx_path = Path(__file__).resolve().parents[1] / "config" / "mcx-crudeoilm.yaml"
        cfg = load_config(yaml_path=mcx_path)
        assert cfg.instrument.name == "CRUDEOILM"
        assert cfg.instrument.lot_size == 10
        assert cfg.instrument.exchange_segment == "MCX_COMM"
        assert cfg.instrument.feed_code == 5
        assert cfg.instrument.market_open == "09:00"
        assert cfg.instrument.market_close == "23:30"


class TestValidatorMarketOpen:
    def test_mcx_market_open_time(self):
        """Validator uses configured market_open, not hardcoded 09:15."""
        from datetime import datetime, time
        from nifty_trader.risk.manager import RiskManager
        from nifty_trader.risk.validator import OrderValidator

        cfg = load_config()
        risk = RiskManager(cfg.risk)
        # MCX market open at 09:00
        validator = OrderValidator(cfg, risk, market_open="09:00")
        assert validator._market_open == "09:00"

        # Verify it parses correctly in the time check
        open_parts = validator._market_open.split(":")
        open_time = time(int(open_parts[0]), int(open_parts[1]))
        assert open_time == time(9, 0)

    def test_nse_market_open_default(self):
        """Default market_open is 09:15 (NSE)."""
        from nifty_trader.risk.manager import RiskManager
        from nifty_trader.risk.validator import OrderValidator

        cfg = load_config()
        risk = RiskManager(cfg.risk)
        validator = OrderValidator(cfg, risk)
        assert validator._market_open == "09:15"
