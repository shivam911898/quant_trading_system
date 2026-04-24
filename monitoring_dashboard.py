"""
╔══════════════════════════════════════════════════════════════╗
║    QUANT TRADING SYSTEM — PHASE 6: MONITORING DASHBOARD    ║
╚══════════════════════════════════════════════════════════════╝

Streamlit dashboard for the paper-trading runtime state produced by
live_paper_trading.py.

Features:
  • Account overview (equity, cash, exposure, drawdown)
  • Equity curve and drawdown visualization
  • Recent orders and alerts
  • Open positions and latest system health
  • Auto-refresh option for near-live monitoring

Usage:
    streamlit run monitoring_dashboard.py

Optional:
    streamlit run monitoring_dashboard.py -- --state-dir paper_runtime
"""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import sys
import time
from datetime import datetime, timezone

import pandas as pd

try:
    import streamlit as st
except ImportError as exc:
    raise SystemExit(
        "Streamlit is required for Phase 6. Install it with: pip install streamlit"
    ) from exc


# ══════════════════════════════════════════════════════════════
#  1.  DATA LOADING
# ══════════════════════════════════════════════════════════════

CONTROL_COMMANDS_FILE = "control_commands.jsonl"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--state-dir", default="paper_runtime")
    known, _ = parser.parse_known_args(sys.argv[1:])
    return known


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def compute_drawdown(equity_df: pd.DataFrame) -> pd.DataFrame:
    if equity_df.empty or "equity" not in equity_df.columns:
        return pd.DataFrame()
    out = equity_df.copy()
    out["rolling_peak"] = out["equity"].cummax()
    out["drawdown_pct"] = (out["equity"] - out["rolling_peak"]) / out["rolling_peak"] * 100
    return out


def enqueue_control_command(state_dir: Path, command: str, note: str = "") -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "dashboard",
        "command": command,
        "note": note.strip(),
    }
    line = json.dumps(payload, separators=(",", ":")) + "\n"
    with (state_dir / CONTROL_COMMANDS_FILE).open("a", encoding="utf-8") as fh:
        fh.write(line)


# ══════════════════════════════════════════════════════════════
#  2.  UI HELPERS
# ══════════════════════════════════════════════════════════════


def metric_card(label: str, value, delta=None):
    st.metric(label, value, delta=delta)


def render_health(state: dict):
    broker = state.get("broker", {})
    risk = state.get("risk", {})
    breaker = risk.get("circuit_breaker", {})

    st.subheader("System Health")
    c1, c2, c3 = st.columns(3)
    c1.metric("Open Positions", broker.get("open_positions", 0))
    c2.metric("Gross Exposure", f"${broker.get('gross_exposure', 0):,.2f}")
    c3.metric("Current Drawdown", f"{breaker.get('current_drawdown_pct', 0):.2f}%")

    if breaker.get("halted"):
        st.error(f"Trading halted: {breaker.get('halt_reason', 'unknown reason')}")
    else:
        st.success("Risk engine status: ACTIVE")

    if state.get("last_alert"):
        last = state["last_alert"]
        st.info(f"Last alert [{last.get('level', 'INFO')}]: {last.get('message', '')}")


def render_positions(state: dict, positions_df: pd.DataFrame):
    st.subheader("Positions")
    positions = state.get("positions", [])
    if positions:
        st.dataframe(pd.DataFrame(positions), use_container_width=True)
    elif not positions_df.empty:
        latest = positions_df.sort_values("timestamp").groupby("symbol", as_index=False).tail(1)
        st.dataframe(latest, use_container_width=True)
    else:
        st.caption("No open positions right now.")


def render_pending_signals(state: dict):
    st.subheader("Pending Next-Open Orders")
    pending = state.get("pending_signals", [])
    if not pending:
        st.caption("No queued signals waiting for the next bar open.")
        return

    pending_df = pd.DataFrame(pending)
    if "queued_at" in pending_df.columns:
        pending_df = pending_df.sort_values("queued_at", ascending=False)
    elif "signal_time" in pending_df.columns:
        pending_df = pending_df.sort_values("signal_time", ascending=False)

    preferred_cols = [
        "symbol", "signal", "side", "queued_at", "signal_time",
        "expected_fill_bar", "signal_strength", "signal_reason"
    ]
    show_cols = [c for c in preferred_cols if c in pending_df.columns]
    if show_cols:
        pending_df = pending_df[show_cols]

    st.dataframe(pending_df, use_container_width=True)


def render_orders(orders_df: pd.DataFrame):
    st.subheader("Recent Filled / Rejected Orders")
    if orders_df.empty:
        st.caption("No orders have been written yet.")
        return
    show = orders_df.sort_values("timestamp", ascending=False).head(25)
    st.dataframe(show, use_container_width=True)


def render_alerts(alerts_df: pd.DataFrame):
    st.subheader("Recent Alerts")
    if alerts_df.empty:
        st.caption("No alerts yet.")
        return
    show = alerts_df.sort_values("timestamp", ascending=False).head(25)
    st.dataframe(show, use_container_width=True)


def render_equity(equity_df: pd.DataFrame):
    st.subheader("Equity Curve")
    if equity_df.empty:
        st.caption("No equity data found yet.")
        return

    eq = equity_df.copy()
    if "timestamp" in eq.columns:
        eq["timestamp"] = pd.to_datetime(eq["timestamp"])
        eq = eq.sort_values("timestamp")
        eq = eq.set_index("timestamp")

    st.line_chart(eq[["equity"]], use_container_width=True)

    dd = compute_drawdown(eq.reset_index())
    if not dd.empty:
        dd = dd.set_index("timestamp") if "timestamp" in dd.columns else dd
        st.subheader("Drawdown %")
        st.line_chart(dd[["drawdown_pct"]], use_container_width=True)


def render_runtime_files(state_dir: Path):
    st.subheader("Runtime Files")
    rows = []
    for name in ["system_state.json", "equity_curve.csv", "orders.csv", "positions_history.csv", "alerts.csv"]:
        path = state_dir / name
        rows.append({
            "file": name,
            "exists": path.exists(),
            "size_kb": round(path.stat().st_size / 1024, 1) if path.exists() else 0.0,
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True)


# ══════════════════════════════════════════════════════════════
#  3.  MAIN APP
# ══════════════════════════════════════════════════════════════


def main():
    args = _parse_args()
    state_dir = Path(args.state_dir)

    st.set_page_config(page_title="Quant Monitor", page_icon="📈", layout="wide")
    st.title("Quant Trading System — Monitoring Dashboard")
    st.caption(f"Watching runtime state in: {state_dir.resolve()}")

    with st.sidebar:
        st.header("Controls")
        refresh = st.checkbox("Auto-refresh every 5 seconds", value=False)
        st.caption("Turn this on after Phase 5 is writing files continuously.")

        st.divider()
        st.subheader("Trading Controls")
        armed = st.checkbox("Enable control actions", value=False)
        note = st.text_input("Operator note (optional)", value="")
        if not armed:
            st.caption("Enable control actions to send commands to the trading engine.")

        c1, c2 = st.columns(2)
        if c1.button("⏸ Pause", use_container_width=True, disabled=not armed):
            enqueue_control_command(state_dir, "PAUSE_TRADING", note=note)
            st.success("Pause command queued")
        if c2.button("▶ Resume", use_container_width=True, disabled=not armed):
            enqueue_control_command(state_dir, "RESUME_TRADING", note=note)
            st.success("Resume command queued")

        c3, c4 = st.columns(2)
        if c3.button("🧹 Cancel Pending", use_container_width=True, disabled=not armed):
            enqueue_control_command(state_dir, "CANCEL_PENDING", note=note)
            st.success("Cancel-pending command queued")
        if c4.button("🛑 Flatten All", use_container_width=True, disabled=not armed):
            enqueue_control_command(state_dir, "FLATTEN_ALL", note=note)
            st.warning("Flatten-all command queued")

        st.divider()
        st.write("Expected producer:")
        st.code("python live_paper_trading.py")
        st.write("Launch dashboard:")
        st.code("streamlit run monitoring_dashboard.py")

    state = load_json(state_dir / "system_state.json")
    equity_df = load_csv(state_dir / "equity_curve.csv")
    orders_df = load_csv(state_dir / "orders.csv")
    positions_df = load_csv(state_dir / "positions_history.csv")
    alerts_df = load_csv(state_dir / "alerts.csv")

    broker = state.get("broker", {})
    pending_signals = state.get("pending_signals", [])
    start_equity = None
    if not equity_df.empty and "equity" in equity_df.columns:
        start_equity = float(equity_df["equity"].iloc[0])
        end_equity = float(equity_df["equity"].iloc[-1])
        ret = ((end_equity - start_equity) / start_equity * 100) if start_equity else 0.0
    else:
        end_equity = broker.get("equity", 0.0)
        ret = 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Equity", f"${end_equity:,.2f}")
    c2.metric("Cash", f"${broker.get('cash', 0):,.2f}")
    c3.metric("Gross Exposure", f"${broker.get('gross_exposure', 0):,.2f}")
    c4.metric("Return %", f"{ret:.2f}%")
    c5.metric("Pending Orders", len(pending_signals))

    render_health(state)

    left, right = st.columns([1.6, 1.0])
    with left:
        render_equity(equity_df)
        render_orders(orders_df)
    with right:
        render_positions(state, positions_df)
        render_pending_signals(state)
        render_alerts(alerts_df)
        render_runtime_files(state_dir)

    if refresh:
        time.sleep(5)
        st.rerun()


if __name__ == "__main__":
    main()
