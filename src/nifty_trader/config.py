"""Configuration loader — YAML + .env → frozen dataclass."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass(frozen=True)
class StrategyConfig:
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_bullish_entry: float = 35.0
    rsi_bearish_entry: float = 65.0
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    vwap_confirm_candles: int = 3
    volume_spike_multiplier: float = 1.5
    volume_sma_period: int = 20
    level_proximity_pct: float = 0.3
    confluence_min_score: float = 2.0
    signal_weights: dict = field(default_factory=lambda: {
        "ema": 1.0, "vwap": 0.8, "rsi": 0.7, "volume": 0.5, "levels": 0.5,
    })


@dataclass(frozen=True)
class RiskConfig:
    capital: float = 100_000.0
    risk_per_trade_pct: float = 2.0
    daily_loss_limit_pct: float = 3.0
    max_positions: int = 1
    sl_pct: float = 35.0
    reward_risk_ratio: float = 2.0
    trailing_breakeven_pct: float = 50.0
    trailing_advance_pct: float = 75.0
    time_stop_minutes: int = 45
    max_single_loss_pct: float = 5.0


@dataclass(frozen=True)
class StrikeConfig:
    delta_min: float = 0.30
    delta_max: float = 0.50
    delta_target: float = 0.40
    iv_rank_max: float = 80.0
    min_volume: int = 1000
    min_oi: int = 10000
    max_spread_pct: float = 2.0


@dataclass(frozen=True)
class TimingConfig:
    scan_start: str = "09:20"
    no_entry_after: str = "14:30"
    force_exit: str = "15:15"
    reconcile: str = "15:35"
    candle_interval_min: int = 5
    tick_interval_sec: int = 10


@dataclass(frozen=True)
class DataConfig:
    intraday_lookback_days: int = 5
    daily_lookback_days: int = 60
    ws_heartbeat_timeout_sec: int = 15
    rate_limit_data_per_sec: int = 5
    rate_limit_option_chain_sec: int = 3


@dataclass(frozen=True)
class NotificationConfig:
    telegram_enabled: bool = False
    console_enabled: bool = True


@dataclass(frozen=True)
class SpreadConfig:
    short_delta_min: float = 0.15
    short_delta_max: float = 0.30
    short_delta_target: float = 0.20
    spread_width_points: float = 100.0
    min_credit: float = 5.0
    profit_target_pct: float = 50.0
    loss_threshold_multiplier: float = 2.0
    min_volume: int = 500
    min_oi: int = 5000
    max_spread_pct: float = 3.0
    iv_rank_min: float = 30.0


@dataclass(frozen=True)
class AppConfig:
    dhan_client_id: str = ""
    dhan_access_token: str = ""
    dhan_base_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    paper_mode: bool = True
    strategy_mode: str = "directional"
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    strike: StrikeConfig = field(default_factory=StrikeConfig)
    spread: SpreadConfig = field(default_factory=SpreadConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    data: DataConfig = field(default_factory=DataConfig)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)


def _make_sub(cls, raw: dict | None):
    if not raw:
        return cls()
    # Filter to only keys the dataclass accepts
    valid = {f.name for f in cls.__dataclass_fields__.values()}
    return cls(**{k: v for k, v in raw.items() if k in valid})


def load_config(
    yaml_path: str | Path | None = None,
    env_path: str | Path | None = None,
) -> AppConfig:
    """Load configuration from YAML file and environment variables."""
    # Load .env
    if env_path:
        load_dotenv(env_path)
    else:
        # Try project root .env
        project_root = Path(__file__).resolve().parents[2]
        load_dotenv(project_root / ".env")

    # Load YAML
    if yaml_path is None:
        yaml_path = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"
    yaml_path = Path(yaml_path)

    raw: dict = {}
    if yaml_path.exists():
        with open(yaml_path) as f:
            raw = yaml.safe_load(f) or {}

    return AppConfig(
        dhan_client_id=os.getenv("DHAN_CLIENT_ID", ""),
        dhan_access_token=os.getenv("DHAN_ACCESS_TOKEN", ""),
        dhan_base_url=os.getenv("DHAN_BASE_URL", ""),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        paper_mode=os.getenv("PAPER_MODE", "true").lower() == "true",
        strategy_mode=raw.get("strategy_mode", "directional"),
        strategy=_make_sub(StrategyConfig, raw.get("strategy")),
        risk=_make_sub(RiskConfig, raw.get("risk")),
        strike=_make_sub(StrikeConfig, raw.get("strike")),
        spread=_make_sub(SpreadConfig, raw.get("spread")),
        timing=_make_sub(TimingConfig, raw.get("timing")),
        data=_make_sub(DataConfig, raw.get("data")),
        notifications=_make_sub(NotificationConfig, raw.get("notifications")),
    )
