from __future__ import annotations

import pandas as pd

from backtester import BacktestEngine
from risk_management import PortfolioSnapshot, RiskConfig, RiskManager


def _minimal_signal_frame() -> pd.DataFrame:
    idx = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 100.0],
            "high": [101.0, 102.0, 101.0],
            "low": [99.0, 100.0, 99.0],
            "close": [100.0, 101.0, 100.0],
            "signal": [1, 0, 0],
            "signal_strength": [0.9, 0.0, 0.0],
            "symbol": ["TEST", "TEST", "TEST"],
        },
        index=idx,
    )


def test_backtester_uses_next_bar_open_for_entry() -> None:
    df = _minimal_signal_frame()
    engine = BacktestEngine(
        initial_capital=10_000,
        position_size=0.10,
        commission_pct=0.0,
        slippage_pct=0.0,
        stop_loss_pct=0.5,
        take_profit_pct=0.0,
        allow_short=False,
    )

    report = engine.run(df)
    assert report.trades, "Expected at least one closed trade"
    first_trade = report.trades[0]
    assert first_trade.entry_price == 101.0
    assert str(first_trade.entry_date.date()) == "2026-01-02"


def test_risk_manager_builds_trade_plan_for_strong_signal() -> None:
    manager = RiskManager(RiskConfig(allow_short=False))
    row = pd.Series(
        {
            "symbol": "TEST",
            "close": 100.0,
            "atr_14": 2.0,
            "signal_strength": 0.8,
        },
        name=pd.Timestamp("2026-01-10"),
    )
    snapshot = PortfolioSnapshot(equity=10_000, cash=10_000, gross_exposure=0, open_positions=0)

    decision = manager.build_trade_plan(row, snapshot, "long")

    assert decision.approved is True
    assert decision.trade_plan is not None
    assert decision.trade_plan.quantity > 0


def test_risk_manager_rejects_weak_signal() -> None:
    manager = RiskManager(RiskConfig(min_signal_strength=0.3))
    row = pd.Series(
        {
            "symbol": "TEST",
            "close": 100.0,
            "atr_14": 2.0,
            "signal_strength": 0.1,
        },
        name=pd.Timestamp("2026-01-10"),
    )
    snapshot = PortfolioSnapshot(equity=10_000, cash=10_000, gross_exposure=0, open_positions=0)

    decision = manager.build_trade_plan(row, snapshot, "long")

    assert decision.approved is False
    assert "Signal too weak" in decision.reason
