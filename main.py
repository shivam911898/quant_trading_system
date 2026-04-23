from __future__ import annotations

"""
Single entry-point runner for the Quant Trading System.

Usage:
    python main.py backtest
    python main.py backtest --strategy momentum
    python main.py paper
    python main.py paper --strategy combined
    python main.py dashboard
    python main.py smoke-test
"""

import argparse
import logging
import subprocess
import sys
from pathlib import Path
from typing import Sequence, Type

from app_config import TradingSystemConfig, load_settings
from app_logging import setup_logging

BASE_DIR = Path(__file__).resolve().parent
STRATEGY_CHOICES = ("mean_reversion", "momentum", "combined")
SETTINGS: TradingSystemConfig = load_settings()
setup_logging(level=SETTINGS.runtime.log_level, log_file=SETTINGS.runtime.log_file)
LOGGER = logging.getLogger(__name__)


def _print_banner() -> None:
    print("=" * 68)
    print("  QUANT TRADING SYSTEM — UNIFIED RUNNER")
    print("=" * 68)


def _resolve_path(name: str) -> Path:
    return BASE_DIR / name


def _strategy_label(strategy_name: str) -> str:
    return strategy_name.replace("_", " ").title()


def _get_strategy_class(strategy_name: str) -> Type:
    from strategy_signals import CombinedStrategy, MeanReversionStrategy, MomentumStrategy

    mapping = {
        "mean_reversion": MeanReversionStrategy,
        "momentum": MomentumStrategy,
        "combined": CombinedStrategy,
    }
    if strategy_name not in mapping:
        raise ValueError(f"Unknown strategy: {strategy_name}")
    return mapping[strategy_name]


def _load_demo_data():
    from strategy_signals import generate_sample_data

    try:
        from data_pipeline import DataLoader, StockDataFetcher
    except Exception:
        print("🔧 Using synthetic sample data (modules unavailable)")
        return generate_sample_data(500)

    try:
        loader = DataLoader()
        df = loader.load("AAPL", "1d")
        print("✅ Loaded saved AAPL data from Phase 1")
        return df
    except Exception:
        pass

    try:
        fetcher = StockDataFetcher()
        df = fetcher.fetch("AAPL", interval="1d", period="2y")
        print("✅ Fetched fresh AAPL data")
        return df
    except Exception:
        print("🔧 Falling back to synthetic sample data for demo")
        return generate_sample_data(500)


def _default_engine_kwargs() -> dict:
    bcfg = SETTINGS.backtest
    kwargs: dict[str, object] = {
        "initial_capital": bcfg.initial_capital,
        "position_size": bcfg.position_size,
        "commission_pct": bcfg.commission_pct,
        "slippage_pct": bcfg.slippage_pct,
        "stop_loss_pct": bcfg.stop_loss_pct,
        "take_profit_pct": bcfg.take_profit_pct,
    }
    try:
        from risk_management import RiskConfig

        kwargs["risk_config"] = RiskConfig(
            risk_per_trade_pct=0.01,
            max_position_pct=0.20,
            max_total_exposure_pct=1.0,
            atr_stop_multiple=2.0,
            reward_to_risk=2.0,
            allow_short=False,
            max_open_positions=1,
        )
    except Exception:
        pass
    return kwargs


def run_backtest(strategy_name: str) -> int:
    from backtester import BacktestEngine

    _print_banner()
    print("▶ Mode: BACKTEST")
    print(f"▶ Strategy: {_strategy_label(strategy_name)}\n")
    LOGGER.info("Starting backtest for strategy=%s", strategy_name)

    df = _load_demo_data()
    strategy_class = _get_strategy_class(strategy_name)
    strategy = strategy_class(df)
    df_sig = strategy.generate()

    engine = BacktestEngine(**_default_engine_kwargs())
    report = engine.run(df_sig)
    report.print_summary()
    report.print_trade_log(last_n=15)
    LOGGER.info("Backtest complete | strategy=%s", strategy_name)
    return 0


def run_paper(
    state_dir: str,
    strategy_name: str,
    broker_name: str,
    alpaca_api_key: str,
    alpaca_secret_key: str,
    alpaca_base_url: str,
) -> int:
    from live_paper_trading import AlpacaPaperBroker, PaperTradingEngine, SimulatedPaperBroker
    from risk_management import RiskConfig, RiskManager
    from strategy_signals import generate_sample_data

    _print_banner()
    print("▶ Mode: PAPER TRADING")
    print(f"▶ Strategy: {_strategy_label(strategy_name)}")
    print(f"▶ Broker: {broker_name}\n")
    LOGGER.info(
        "Starting paper trading | strategy=%s | broker=%s | state_dir=%s",
        strategy_name,
        broker_name,
        state_dir,
    )

    df = generate_sample_data(420)
    pcfg = SETTINGS.paper
    if broker_name == "alpaca-paper":
        broker = AlpacaPaperBroker(
            api_key=alpaca_api_key,
            secret_key=alpaca_secret_key,
            base_url=alpaca_base_url,
        )
    else:
        broker = SimulatedPaperBroker(
            starting_cash=pcfg.starting_cash,
            commission_pct=pcfg.commission_pct,
            slippage_pct=pcfg.slippage_pct,
        )
    risk_manager = RiskManager(
        RiskConfig(
            risk_per_trade_pct=0.01,
            max_position_pct=0.20,
            max_total_exposure_pct=1.0,
            reward_to_risk=2.0,
            allow_short=False,
        )
    )

    strategy_class = _get_strategy_class(strategy_name)
    engine = PaperTradingEngine(
        strategy_class=strategy_class,
        broker=broker,
        risk_manager=risk_manager,
        allow_short=False,
        state_dir=state_dir,
    )
    report = engine.run_on_history(df, warmup_bars=pcfg.warmup_bars)

    print("\nSession summary:")
    print(report.summary())
    print(f"\nState exported to: {report.state_dir.resolve()}")
    print("Files written:")
    for name in ["equity_curve.csv", "orders.csv", "positions_history.csv", "alerts.csv", "system_state.json"]:
        path = report.state_dir / name
        if path.exists():
            print(f"  • {path}")
    LOGGER.info(
        "Paper trading complete | strategy=%s | broker=%s | state_dir=%s",
        strategy_name,
        broker_name,
        state_dir,
    )
    return 0


def run_dashboard(state_dir: str, server_port: int, server_address: str, headless: bool) -> int:
    dashboard_path = _resolve_path("monitoring_dashboard.py")
    if not dashboard_path.exists():
        print(f"❌ Dashboard file not found: {dashboard_path}")
        return 1

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(dashboard_path),
        "--server.port",
        str(server_port),
        "--server.address",
        server_address,
        "--server.headless",
        "true" if headless else "false",
        "--",
        "--state-dir",
        state_dir,
    ]

    _print_banner()
    print("▶ Mode: DASHBOARD\n")
    print("Launching Streamlit dashboard with command:")
    print(" ".join(cmd))
    print()
    LOGGER.info(
        "Launching dashboard | state_dir=%s | host=%s | port=%s | headless=%s",
        state_dir,
        server_address,
        server_port,
        headless,
    )

    try:
        completed = subprocess.run(cmd, cwd=str(BASE_DIR))
        return int(completed.returncode)
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
        return 130


def run_smoke_test() -> int:
    smoke_path = _resolve_path("integration_smoke_test.py")
    if not smoke_path.exists():
        print(f"❌ Smoke test file not found: {smoke_path}")
        return 1

    _print_banner()
    print("▶ Mode: SMOKE TEST\n")
    LOGGER.info("Running integration smoke test")
    completed = subprocess.run([sys.executable, str(smoke_path)], cwd=str(BASE_DIR))
    return int(completed.returncode)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Unified runner for the quant trading system",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    backtest = sub.add_parser("backtest", help="Run the Phase 3 backtester demo")
    backtest.add_argument(
        "--strategy",
        choices=STRATEGY_CHOICES,
        default="mean_reversion",
        help="Strategy to run in backtest mode",
    )

    paper = sub.add_parser("paper", help="Run the Phase 5 paper-trading demo")
    paper.add_argument(
        "--state-dir",
        default=SETTINGS.runtime.default_state_dir,
        help="Directory to write runtime state files",
    )
    paper.add_argument(
        "--strategy",
        choices=STRATEGY_CHOICES,
        default="momentum",
        help="Strategy to run in paper mode",
    )
    paper.add_argument(
        "--broker",
        choices=("simulated", "alpaca-paper"),
        default=SETTINGS.runtime.default_paper_broker,
        help="Broker adapter for paper trading",
    )
    paper.add_argument(
        "--alpaca-api-key",
        default=SETTINGS.alpaca.api_key,
        help="Alpaca API key (or set ALPACA_API_KEY env var)",
    )
    paper.add_argument(
        "--alpaca-secret-key",
        default=SETTINGS.alpaca.secret_key,
        help="Alpaca secret key (or set ALPACA_SECRET_KEY env var)",
    )
    paper.add_argument(
        "--alpaca-base-url",
        default=SETTINGS.alpaca.base_url,
        help="Alpaca API base URL",
    )

    dashboard = sub.add_parser("dashboard", help="Launch the Phase 6 Streamlit dashboard")
    dashboard.add_argument(
        "--state-dir",
        default=SETTINGS.runtime.default_state_dir,
        help="Directory to read runtime state files from",
    )
    dashboard.add_argument(
        "--server-port",
        type=int,
        default=SETTINGS.runtime.server_port,
        help="Streamlit server port",
    )
    dashboard.add_argument(
        "--server-address",
        default=SETTINGS.runtime.server_address,
        help="Streamlit bind address",
    )
    dashboard.add_argument("--headless", action="store_true", help="Run Streamlit in headless mode")

    sub.add_parser("smoke-test", help="Run the cross-phase integration smoke test")
    return parser


def choose_interactively() -> str:
    print("No mode was provided. Choose one:")
    print("  1) backtest")
    print("  2) paper")
    print("  3) dashboard")
    print("  4) smoke-test")
    try:
        choice = input("Enter choice [1-4]: ").strip()
    except EOFError:
        return ""
    mapping = {"1": "backtest", "2": "paper", "3": "dashboard", "4": "smoke-test"}
    return mapping.get(choice, "")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    command = args.command
    if command is None:
        command = choose_interactively()
        if not command:
            parser.print_help()
            return 1

    if command == "backtest":
        return run_backtest(args.strategy)
    if command == "paper":
        return run_paper(
            args.state_dir,
            args.strategy,
            args.broker,
            args.alpaca_api_key,
            args.alpaca_secret_key,
            args.alpaca_base_url,
        )
    if command == "dashboard":
        return run_dashboard(args.state_dir, args.server_port, args.server_address, args.headless)
    if command == "smoke-test":
        return run_smoke_test()

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
