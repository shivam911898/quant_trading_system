from pathlib import Path
import importlib.util
import sys

BASE = Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, BASE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main():
    data_pipeline = load_module("data_pipeline", "data_pipeline.py")
    strategy_signals = load_module("strategy_signals", "strategy_signals.py")
    risk_management = load_module("risk_management", "risk_management.py")
    backtester = load_module("backtester", "backtester.py")
    live = load_module("live_paper_trading", "live_paper_trading.py")

    df = strategy_signals.generate_sample_data(320)
    strat = strategy_signals.MeanReversionStrategy(df)
    df_sig = strat.generate()

    risk_config = risk_management.RiskConfig(max_open_positions=1, allow_short=False)
    report = backtester.BacktestEngine(
        initial_capital=10_000,
        commission_pct=0.001,
        slippage_pct=0.0005,
        risk_config=risk_config,
    ).run(df_sig)
    assert "equity" in report.get_equity_curve().columns

    broker = live.SimulatedPaperBroker(starting_cash=10_000)
    live_engine = live.PaperTradingEngine(
        strategy_class=strategy_signals.MomentumStrategy,
        broker=broker,
        risk_manager=risk_management.RiskManager(risk_config),
        allow_short=False,
        state_dir="paper_runtime_test",
    )
    session = live_engine.run_on_history(df, warmup_bars=220)
    assert session.state_dir.exists()
    print("ALL_SMOKE_TESTS_PASSED")


if __name__ == "__main__":
    main()
