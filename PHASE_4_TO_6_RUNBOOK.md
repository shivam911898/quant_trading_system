# Quant Trading System — Phase 4 to 6 Runbook

## What was added

### Phase 4 — `risk_management.py`
Builds trade plans from strategy signals.

Key pieces:
- `RiskConfig`
- `TradePlan`
- `RiskDecision`
- `CircuitBreaker`
- `RiskManager`

Main ideas:
- ATR-based stop distance if `atr_14` exists
- fallback fixed stop-loss if ATR is missing
- risk-per-trade sizing
- max position cap
- gross exposure cap
- daily loss halt
- drawdown halt

### Phase 5 — `live_paper_trading.py`
Runs a paper-trading loop on historical bars in a way that mimics live processing.

Key pieces:
- `PaperOrder`
- `PaperPosition`
- `SimulatedPaperBroker`
- `PaperTradingEngine`
- `TradingSessionReport`

Outputs written to `paper_runtime/`:
- `system_state.json`
- `equity_curve.csv`
- `orders.csv`
- `positions_history.csv`
- `alerts.csv`

### Phase 6 — `monitoring_dashboard.py`
Streamlit dashboard that reads the Phase 5 runtime files.

Displays:
- equity and exposure
- drawdown
- open positions
- recent orders
- recent alerts
- risk / system health

---

## How to run

### 1) Risk Management demo
```bash
python risk_management.py
```

### 2) Paper Trading demo
```bash
python live_paper_trading.py
```

### 3) Monitoring Dashboard
```bash
streamlit run monitoring_dashboard.py
```

If you want a different runtime folder:
```bash
streamlit run monitoring_dashboard.py -- --state-dir paper_runtime
```

---

## Integration flow

1. Phase 1 fetches OHLCV data and indicators
2. Phase 2 creates `signal`, `signal_reason`, `signal_strength`
3. Phase 4 sizes the position and creates stop/target levels
4. Phase 5 simulates execution and writes runtime state
5. Phase 6 visualizes runtime state

---

## Important note on existing Phase 3

Your current `backtester.py` docstring says:
- orders are filled at the **next candle open**

But the implementation currently uses the **current row's price path** for signal-based fills and stop logic.

That does **not** break the new phases, but it means:
- Phase 3 is not perfectly aligned with its own stated execution model
- if you want stricter realism, Phase 3 should be patched later to fill signal entries/exits on the next bar's open

---

## Suggested next upgrade

If you continue improving the system, the next highest-value changes are:
1. patch Phase 3 to use true next-bar execution
2. add broker adapters (Alpaca / Zerodha Kite / Binance testnet)
3. persist data to SQLite/Postgres instead of CSV
4. add multi-asset portfolio support
5. add walk-forward parameter optimization
