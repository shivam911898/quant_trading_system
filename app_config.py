from __future__ import annotations

import os
from dataclasses import dataclass


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 10_000.0
    position_size: float = 0.95
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10


@dataclass(frozen=True)
class PaperConfig:
    starting_cash: float = 10_000.0
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005
    warmup_bars: int = 220


@dataclass(frozen=True)
class RuntimeConfig:
    log_level: str = "INFO"
    log_file: str = "logs/system.log"
    default_state_dir: str = "paper_runtime"
    default_paper_broker: str = "simulated"
    server_port: int = 8501
    server_address: str = "127.0.0.1"


@dataclass(frozen=True)
class AlpacaConfig:
    api_key: str = ""
    secret_key: str = ""
    base_url: str = "https://paper-api.alpaca.markets"


@dataclass(frozen=True)
class TradingSystemConfig:
    runtime: RuntimeConfig
    backtest: BacktestConfig
    paper: PaperConfig
    alpaca: AlpacaConfig


def load_settings() -> TradingSystemConfig:
    runtime = RuntimeConfig(
        log_level=_env_str("QTS_LOG_LEVEL", "INFO").upper(),
        log_file=_env_str("QTS_LOG_FILE", "logs/system.log"),
        default_state_dir=_env_str("QTS_STATE_DIR", "paper_runtime"),
        default_paper_broker=_env_str("QTS_PAPER_BROKER", "simulated").lower(),
        server_port=_env_int("QTS_DASHBOARD_PORT", 8501),
        server_address=_env_str("QTS_DASHBOARD_HOST", "127.0.0.1"),
    )

    backtest = BacktestConfig(
        initial_capital=_env_float("QTS_INITIAL_CAPITAL", 10_000.0),
        position_size=_env_float("QTS_POSITION_SIZE", 0.95),
        commission_pct=_env_float("QTS_COMMISSION_PCT", 0.001),
        slippage_pct=_env_float("QTS_SLIPPAGE_PCT", 0.0005),
        stop_loss_pct=_env_float("QTS_STOP_LOSS_PCT", 0.05),
        take_profit_pct=_env_float("QTS_TAKE_PROFIT_PCT", 0.10),
    )

    paper = PaperConfig(
        starting_cash=_env_float("QTS_PAPER_STARTING_CASH", 10_000.0),
        commission_pct=_env_float("QTS_PAPER_COMMISSION_PCT", 0.001),
        slippage_pct=_env_float("QTS_PAPER_SLIPPAGE_PCT", 0.0005),
        warmup_bars=_env_int("QTS_PAPER_WARMUP_BARS", 220),
    )

    alpaca = AlpacaConfig(
        api_key=_env_str("ALPACA_API_KEY", ""),
        secret_key=_env_str("ALPACA_SECRET_KEY", ""),
        base_url=_env_str("ALPACA_BASE_URL", "https://paper-api.alpaca.markets"),
    )

    return TradingSystemConfig(runtime=runtime, backtest=backtest, paper=paper, alpaca=alpaca)
