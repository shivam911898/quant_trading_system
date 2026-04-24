from __future__ import annotations

import json

import pandas as pd

from live_paper_trading import (
    CONTROL_COMMANDS_FILE,
    PaperTradingEngine,
    PendingSignal,
    SimulatedPaperBroker,
)
from risk_management import RiskConfig, RiskManager


class NoSignalStrategy:
    def __init__(self, df: pd.DataFrame):
        self.df = df

    def generate(self) -> pd.DataFrame:
        out = self.df.copy()
        out["signal"] = 0
        out["signal_reason"] = ""
        out["signal_strength"] = 0.0
        return out


def _history_df() -> pd.DataFrame:
    idx = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"])
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0],
            "low": [99.0, 100.0, 101.0],
            "close": [100.5, 101.5, 102.5],
            "symbol": ["TEST", "TEST", "TEST"],
        },
        index=idx,
    )


def _write_command(state_dir, command: str) -> None:
    payload = {"timestamp": "2026-01-01T00:00:00Z", "source": "test", "command": command}
    (state_dir / CONTROL_COMMANDS_FILE).write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _engine(tmp_path) -> PaperTradingEngine:
    broker = SimulatedPaperBroker(starting_cash=10_000, commission_pct=0.0, slippage_pct=0.0)
    risk_manager = RiskManager(RiskConfig(allow_short=False))
    return PaperTradingEngine(
        strategy_class=NoSignalStrategy,
        broker=broker,
        risk_manager=risk_manager,
        allow_short=False,
        state_dir=str(tmp_path),
    )


def test_pause_and_resume_commands_toggle_state(tmp_path) -> None:
    engine = _engine(tmp_path)
    df = _history_df()

    _write_command(tmp_path, "PAUSE_TRADING")
    engine.process_bar(df.iloc[:1])
    assert engine.trading_paused is True

    _write_command(tmp_path, "RESUME_TRADING")
    engine.process_bar(df.iloc[:2])
    assert engine.trading_paused is False


def test_cancel_pending_command_clears_queue(tmp_path) -> None:
    engine = _engine(tmp_path)
    df = _history_df()

    engine.pending_signals["TEST"] = PendingSignal(
        symbol="TEST",
        signal=1,
        signal_time=df.index[0],
        signal_reason="test",
        row_payload={"symbol": "TEST", "signal": 1, "signal_strength": 0.9},
    )

    _write_command(tmp_path, "CANCEL_PENDING")
    engine.process_bar(df.iloc[:1])

    assert len(engine.pending_signals) == 0


def test_flatten_all_command_closes_open_positions(tmp_path) -> None:
    engine = _engine(tmp_path)
    df = _history_df()

    engine.broker.submit_order(df.index[0], "TEST", "buy", 10, 100.0, reason="setup")
    assert "TEST" in engine.broker.positions

    _write_command(tmp_path, "FLATTEN_ALL")
    engine.process_bar(df.iloc[:2])

    assert "TEST" not in engine.broker.positions
    assert any(order.reason == "manual_flatten_all" for order in engine.broker.orders)
