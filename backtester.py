"""
╔══════════════════════════════════════════════════════════════╗
║       QUANT TRADING SYSTEM — PHASE 3: BACKTESTER            ║
╚══════════════════════════════════════════════════════════════╝

This module simulates your strategies on historical data and
measures real performance metrics — before risking real money.

Contains:
  1. Trade            — dataclass representing a single trade
  2. BacktestEngine   — core simulation loop (next-bar-open execution)
  3. PerformanceMetrics — Sharpe, drawdown, win rate, etc.
  4. BacktestReport   — full results summary + trade log
  5. WalkForwardTest  — prevents overfitting via out-of-sample testing

Key concepts:
  • No look-ahead bias  — signals are generated on bar[i] and filled on bar[i+1] open
  • Realistic costs     — slippage + commission on every trade
  • Risk-aware sizing   — optional Phase 4 RiskManager integration
  • Event-driven loop   — processes each candle one by one

Author: Your Trading System
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

try:
    from data_pipeline import StockDataFetcher, DataLoader
    from strategy_signals import (
        MeanReversionStrategy,
        MomentumStrategy,
        CombinedStrategy,
        generate_sample_data,
    )
    MODULES_AVAILABLE = True
except ImportError:
    MODULES_AVAILABLE = False
    print("⚠️  Run from same folder as data_pipeline.py and strategy_signals.py")

    def generate_sample_data(n: int = 500) -> pd.DataFrame:
        np.random.seed(42)
        dates = pd.date_range("2022-01-01", periods=n, freq="B")
        returns = np.random.normal(0.0003, 0.015, n)
        close = 150.0 * np.cumprod(1 + returns)
        high = close * (1 + np.abs(np.random.normal(0, 0.008, n)))
        low = close * (1 - np.abs(np.random.normal(0, 0.008, n)))
        open_ = close * (1 + np.random.normal(0, 0.005, n))
        vol = np.random.randint(1_000_000, 10_000_000, n).astype(float)
        return pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": vol,
                "symbol": "SAMPLE",
            },
            index=dates,
        )

try:
    from risk_management import RiskConfig, RiskManager, PortfolioSnapshot
    RISK_AVAILABLE = True
except ImportError:
    RiskConfig = None  # type: ignore[assignment]
    RiskManager = None  # type: ignore[assignment]
    PortfolioSnapshot = None  # type: ignore[assignment]
    RISK_AVAILABLE = False


# ══════════════════════════════════════════════════════════════
#  1.  TRADE DATACLASS
# ══════════════════════════════════════════════════════════════

@dataclass
class Trade:
    """Represents a single completed round-trip trade."""

    trade_id: int
    symbol: str
    direction: str                # long / short
    entry_date: pd.Timestamp
    entry_price: float
    shares: float = 0.0
    entry_cost: float = 0.0
    signal_strength: float = 0.0
    stop_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    risk_budget: float = 0.0
    planned_max_loss: float = 0.0
    planned_notional: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    exit_date: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_cost: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    is_open: bool = True
    exit_reason: str = ""

    def close(self, exit_date, exit_price, exit_cost, reason="signal"):
        self.exit_date = pd.Timestamp(exit_date)
        self.exit_price = float(exit_price)
        self.exit_cost = float(exit_cost)
        self.exit_reason = str(reason)
        self.is_open = False

        if self.direction == "long":
            gross = (self.exit_price - self.entry_price) * self.shares
        else:
            gross = (self.entry_price - self.exit_price) * self.shares

        self.pnl = gross - self.entry_cost - self.exit_cost
        invested = max(self.entry_price * self.shares, 1e-12)
        self.pnl_pct = (self.pnl / invested) * 100


# ══════════════════════════════════════════════════════════════
#  2.  BACKTEST ENGINE
# ══════════════════════════════════════════════════════════════

class BacktestEngine:
    """
    Event-driven backtesting engine.

    Signals observed on bar[i] are executed at the next bar's open (bar[i+1]).
    After the open, stop-loss / take-profit levels are checked intrabar using
    the current bar's high/low range.
    """

    def __init__(
        self,
        initial_capital: float = 10_000.0,
        position_size: float = 0.95,
        commission_pct: float = 0.001,
        slippage_pct: float = 0.0005,
        stop_loss_pct: float = 0.05,
        take_profit_pct: float = 0.10,
        allow_short: bool = False,
        max_open_trades: int = 1,
        risk_manager: Optional[Any] = None,
        risk_config: Optional[Any] = None,
    ):
        self.initial_capital = float(initial_capital)
        self.position_size = float(position_size)
        self.commission_pct = float(commission_pct)
        self.slippage_pct = float(slippage_pct)
        self.stop_loss_pct = float(stop_loss_pct)
        self.take_profit_pct = float(take_profit_pct)
        self.allow_short = bool(allow_short)
        self.max_open_trades = int(max_open_trades)

        self._risk_config = None
        if RISK_AVAILABLE:
            if risk_config is not None:
                self._risk_config = risk_config
            elif risk_manager is not None and hasattr(risk_manager, "config"):
                self._risk_config = risk_manager.config

        self.cash = self.initial_capital
        self.trades: List[Trade] = []
        self.open_trades: List[Trade] = []
        self.equity_curve: List[dict] = []
        self.trade_counter = 0
        self.skipped_orders: List[dict] = []
        self.risk_manager = self._new_risk_manager()

    def _new_risk_manager(self):
        if RISK_AVAILABLE and self._risk_config is not None:
            return RiskManager(self._risk_config)
        return None

    def _execution_price(self, price: float, direction: str) -> float:
        slip = float(price) * self.slippage_pct
        return float(price + slip) if direction == "long" else float(price - slip)

    def _commission(self, price: float, shares: float) -> float:
        return float(price) * float(shares) * self.commission_pct

    def _portfolio_value(self, mark_price: float) -> float:
        open_value = 0.0
        for t in self.open_trades:
            if t.direction == "long":
                open_value += t.shares * mark_price
            else:
                open_value += (t.entry_price - mark_price) * t.shares + t.entry_price * t.shares
        return float(self.cash + open_value)

    def _portfolio_snapshot(self, mark_price: float):
        equity = self._portfolio_value(mark_price)
        gross = 0.0
        net = 0.0
        symbol_exposure: Dict[str, float] = {}
        for t in self.open_trades:
            exposure = abs(t.shares * mark_price)
            gross += exposure
            net += exposure if t.direction == "long" else -exposure
            symbol_exposure[t.symbol] = symbol_exposure.get(t.symbol, 0.0) + exposure
        if RISK_AVAILABLE and PortfolioSnapshot is not None:
            return PortfolioSnapshot(
                equity=equity,
                cash=float(self.cash),
                gross_exposure=float(gross),
                net_exposure=float(net),
                open_positions=len(self.open_trades),
                symbol_exposure=symbol_exposure,
            )
        return {
            "equity": equity,
            "cash": float(self.cash),
            "gross_exposure": float(gross),
            "net_exposure": float(net),
            "open_positions": len(self.open_trades),
            "symbol_exposure": symbol_exposure,
        }

    def _fixed_plan(self, symbol: str, direction: str, date, execution_price: float, signal_strength: float) -> Optional[dict]:
        if len(self.open_trades) >= self.max_open_trades:
            self.skipped_orders.append({"date": str(pd.Timestamp(date)), "symbol": symbol, "reason": "max_open_trades"})
            return None

        capital = self.cash * self.position_size
        shares = capital / max(execution_price, 1e-12)
        cost = self._commission(execution_price, shares)
        total_cost = execution_price * shares + cost if direction == "long" else cost
        if self.cash < total_cost and direction == "long":
            self.skipped_orders.append({"date": str(pd.Timestamp(date)), "symbol": symbol, "reason": "insufficient_cash"})
            return None

        stop_price = None
        target_price = None
        if direction == "long":
            stop_price = execution_price * (1 - self.stop_loss_pct)
            target_price = execution_price * (1 + self.take_profit_pct) if self.take_profit_pct > 0 else None
        else:
            stop_price = execution_price * (1 + self.stop_loss_pct)
            target_price = execution_price * (1 - self.take_profit_pct) if self.take_profit_pct > 0 else None

        return {
            "symbol": symbol,
            "direction": direction,
            "date": pd.Timestamp(date),
            "execution_price": float(execution_price),
            "shares": float(shares),
            "signal_strength": float(signal_strength),
            "stop_price": None if stop_price is None else float(stop_price),
            "take_profit_price": None if target_price is None else float(target_price),
            "risk_budget": float(self.cash * self.position_size * self.stop_loss_pct),
            "planned_max_loss": float((execution_price - stop_price) * shares) if direction == "long" else float((stop_price - execution_price) * shares),
            "planned_notional": float(execution_price * shares),
            "metadata": {"source": "fixed_fractional"},
        }

    def _risk_managed_plan(self, signal_row: pd.Series, symbol: str, direction: str, date, execution_price: float) -> Optional[dict]:
        if self.risk_manager is None:
            return None
        plan_row = signal_row.copy()
        plan_row["close"] = float(execution_price)
        plan_row.name = pd.Timestamp(date)
        snapshot = self._portfolio_snapshot(execution_price)
        decision = self.risk_manager.build_trade_plan(plan_row, snapshot, direction)
        if not decision.approved or decision.trade_plan is None:
            self.skipped_orders.append({
                "date": str(pd.Timestamp(date)),
                "symbol": symbol,
                "reason": getattr(decision, "reason", "risk_rejected"),
            })
            return None
        tp = decision.trade_plan
        return {
            "symbol": tp.symbol,
            "direction": tp.side,
            "date": pd.Timestamp(date),
            "execution_price": float(execution_price),
            "shares": float(tp.quantity),
            "signal_strength": float(tp.signal_strength),
            "stop_price": float(tp.stop_price),
            "take_profit_price": float(tp.take_profit_price),
            "risk_budget": float(tp.risk_budget),
            "planned_max_loss": float(tp.max_loss),
            "planned_notional": float(tp.notional),
            "metadata": {"source": "risk_manager", **dict(tp.metadata)},
        }

    def _open_position_from_plan(self, plan: dict):
        direction = plan["direction"]
        fill_price = self._execution_price(plan["execution_price"], direction)
        shares = float(plan["shares"])
        cost = self._commission(fill_price, shares)

        if direction == "long":
            total_cost = fill_price * shares + cost
            if self.cash < total_cost:
                self.skipped_orders.append({
                    "date": str(plan["date"]),
                    "symbol": plan["symbol"],
                    "reason": "insufficient_cash_after_slippage",
                })
                return None
            self.cash -= total_cost
        else:
            proceeds = fill_price * shares - cost
            self.cash += proceeds

        self.trade_counter += 1
        trade = Trade(
            trade_id=self.trade_counter,
            symbol=str(plan["symbol"]),
            direction=direction,
            entry_date=pd.Timestamp(plan["date"]),
            entry_price=float(fill_price),
            shares=shares,
            entry_cost=float(cost),
            signal_strength=float(plan["signal_strength"]),
            stop_price=plan.get("stop_price"),
            take_profit_price=plan.get("take_profit_price"),
            risk_budget=float(plan.get("risk_budget", 0.0)),
            planned_max_loss=float(plan.get("planned_max_loss", 0.0)),
            planned_notional=float(plan.get("planned_notional", fill_price * shares)),
            metadata=dict(plan.get("metadata", {})),
        )
        self.open_trades.append(trade)
        return trade

    def _close_position(self, trade: Trade, date, price: float, reason: str = "signal"):
        fill_price = self._execution_price(price, "short" if trade.direction == "long" else "long")
        cost = self._commission(fill_price, trade.shares)
        trade.close(date, fill_price, cost, reason)

        if trade.direction == "long":
            self.cash += fill_price * trade.shares - cost
        else:
            # Short entry already credited sale proceeds to cash. Closing uses buyback cost.
            self.cash -= fill_price * trade.shares + cost

        self.trades.append(trade)
        self.open_trades.remove(trade)

    def _trade_exit_price(self, trade: Trade, row: pd.Series) -> Optional[tuple]:
        current_open = float(row.get("open", row["close"]))
        current_high = float(row.get("high", row["close"]))
        current_low = float(row.get("low", row["close"]))

        stop_price = trade.stop_price
        target_price = trade.take_profit_price

        if trade.direction == "long":
            if stop_price is not None and current_open <= stop_price:
                return current_open, "gap_stop_loss"
            if target_price is not None and current_open >= target_price:
                return current_open, "gap_take_profit"
            if stop_price is not None and current_low <= stop_price:
                return float(stop_price), "stop_loss"
            if target_price is not None and current_high >= target_price:
                return float(target_price), "take_profit"
        else:
            if stop_price is not None and current_open >= stop_price:
                return current_open, "gap_stop_loss"
            if target_price is not None and current_open <= target_price:
                return current_open, "gap_take_profit"
            if stop_price is not None and current_high >= stop_price:
                return float(stop_price), "stop_loss"
            if target_price is not None and current_low <= target_price:
                return float(target_price), "take_profit"
        return None

    def _execute_signal_at_open(self, signal_row: pd.Series, execution_date, execution_row: pd.Series, symbol: str):
        signal = int(signal_row.get("signal", 0))
        if signal == 0:
            return

        execution_open = float(execution_row.get("open", execution_row["close"]))
        signal_strength = float(signal_row.get("signal_strength", 0.5))

        if signal == 1:
            for trade in [t for t in list(self.open_trades) if t.direction == "short"]:
                self._close_position(trade, execution_date, execution_open, "signal_reversal")
            if any(t.direction == "long" for t in self.open_trades):
                return
            direction = "long"
        elif signal == -1 and self.allow_short:
            for trade in [t for t in list(self.open_trades) if t.direction == "long"]:
                self._close_position(trade, execution_date, execution_open, "signal_reversal")
            if any(t.direction == "short" for t in self.open_trades):
                return
            direction = "short"
        elif signal == -1 and not self.allow_short:
            for trade in [t for t in list(self.open_trades) if t.direction == "long"]:
                self._close_position(trade, execution_date, execution_open, "sell_signal")
            return
        else:
            return

        plan = self._risk_managed_plan(signal_row, symbol, direction, execution_date, execution_open)
        if plan is None:
            plan = self._fixed_plan(symbol, direction, execution_date, execution_open, signal_strength)
        if plan is not None:
            self._open_position_from_plan(plan)

    def run(self, df: pd.DataFrame) -> "BacktestReport":
        required = {"open", "high", "low", "close", "signal"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {sorted(missing)}")
        if len(df) < 2:
            raise ValueError("Need at least 2 rows to backtest next-bar-open execution")

        self.cash = self.initial_capital
        self.trades = []
        self.open_trades = []
        self.equity_curve = []
        self.trade_counter = 0
        self.skipped_orders = []
        self.risk_manager = self._new_risk_manager()

        df = df.copy().sort_index()
        symbol = str(df["symbol"].iloc[0]) if "symbol" in df.columns else "UNKNOWN"
        rows = list(df.iterrows())

        first_date, first_row = rows[0]
        self.equity_curve.append({
            "date": pd.Timestamp(first_date),
            "equity": round(self.initial_capital, 6),
            "price": float(first_row["close"]),
            "cash": round(self.cash, 6),
            "open_positions": 0,
        })

        for i in range(1, len(rows)):
            prev_date, prev_row = rows[i - 1]
            current_date, current_row = rows[i]

            self._execute_signal_at_open(prev_row, current_date, current_row, symbol)

            for trade in list(self.open_trades):
                exit_decision = self._trade_exit_price(trade, current_row)
                if exit_decision is not None:
                    exit_price, exit_reason = exit_decision
                    self._close_position(trade, current_date, exit_price, exit_reason)

            close_price = float(current_row["close"])
            equity = self._portfolio_value(close_price)
            self.equity_curve.append({
                "date": pd.Timestamp(current_date),
                "equity": round(equity, 6),
                "price": close_price,
                "cash": round(self.cash, 6),
                "open_positions": len(self.open_trades),
            })

        last_date, last_row = rows[-1]
        last_close = float(last_row["close"])
        for trade in list(self.open_trades):
            self._close_position(trade, last_date, last_close, "end_of_data")

        equity_df = pd.DataFrame(self.equity_curve).drop_duplicates(subset=["date"], keep="last").set_index("date")
        if not equity_df.empty:
            final_equity = self._portfolio_value(last_close)
            equity_df.iloc[-1, equity_df.columns.get_loc("equity")] = round(final_equity, 6)
            equity_df.iloc[-1, equity_df.columns.get_loc("cash")] = round(self.cash, 6)
            equity_df.iloc[-1, equity_df.columns.get_loc("open_positions")] = len(self.open_trades)

        config = {
            "position_size": self.position_size,
            "commission_pct": self.commission_pct,
            "slippage_pct": self.slippage_pct,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "allow_short": self.allow_short,
            "max_open_trades": self.max_open_trades,
            "execution_model": "signal_on_bar_i_fill_on_bar_i_plus_1_open",
            "risk_manager_enabled": self.risk_manager is not None,
            "skipped_orders": self.skipped_orders,
        }
        if self.risk_manager is not None and hasattr(self.risk_manager, "summary"):
            config["risk_summary"] = self.risk_manager.summary()

        return BacktestReport(
            trades=self.trades,
            equity_curve=equity_df,
            initial_capital=self.initial_capital,
            config=config,
        )


# ══════════════════════════════════════════════════════════════
#  3.  PERFORMANCE METRICS
# ══════════════════════════════════════════════════════════════

class PerformanceMetrics:
    """Calculates industry-standard performance metrics."""

    @staticmethod
    def compute(trades: list, equity_curve: pd.DataFrame, initial_capital: float) -> dict:
        if not trades:
            return {"error": "No trades executed"}

        closed = [t for t in trades if not t.is_open]
        if not closed:
            return {"error": "No closed trades"}

        pnls = [t.pnl for t in closed]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p <= 0]

        total_pnl = float(sum(pnls))
        win_rate = len(winners) / len(closed) * 100
        avg_win = np.mean(winners) if winners else 0.0
        avg_loss = np.mean(losers) if losers else 0.0
        gross_loss = abs(sum(losers))
        profit_factor = abs(sum(winners) / sum(losers)) if gross_loss > 0 else float("inf")
        expectancy = np.mean(pnls) if pnls else 0.0
        payoff_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

        eq = equity_curve["equity"].astype(float)
        final_equity = float(eq.iloc[-1])
        total_return = (final_equity - initial_capital) / initial_capital * 100
        n_years = max(len(eq) / 252, 1 / 252)
        cagr = ((final_equity / initial_capital) ** (1 / n_years) - 1) * 100 if initial_capital > 0 and final_equity > 0 else -100.0

        daily_returns = eq.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        sharpe_ratio = (daily_returns.mean() / daily_returns.std() * np.sqrt(252)) if daily_returns.std() and daily_returns.std() > 0 else 0.0

        rolling_max = eq.cummax()
        drawdown = (eq - rolling_max) / rolling_max * 100
        max_drawdown = float(drawdown.min()) if not drawdown.empty else 0.0
        calmar = cagr / abs(max_drawdown) if max_drawdown != 0 else 0.0

        durations = []
        for t in closed:
            if t.exit_date is not None and t.entry_date is not None:
                durations.append((pd.Timestamp(t.exit_date) - pd.Timestamp(t.entry_date)).days)
        avg_holding_days = float(np.mean(durations)) if durations else 0.0

        exit_reasons: Dict[str, int] = {}
        for t in closed:
            exit_reasons[t.exit_reason] = exit_reasons.get(t.exit_reason, 0) + 1

        return {
            "total_return_pct": round(total_return, 2),
            "cagr_pct": round(cagr, 2),
            "total_pnl": round(total_pnl, 2),
            "final_equity": round(final_equity, 2),
            "sharpe_ratio": round(float(sharpe_ratio), 3),
            "calmar_ratio": round(float(calmar), 3),
            "max_drawdown_pct": round(max_drawdown, 2),
            "total_trades": len(closed),
            "win_rate_pct": round(win_rate, 1),
            "profit_factor": round(float(profit_factor), 2),
            "payoff_ratio": round(float(payoff_ratio), 2),
            "expectancy": round(float(expectancy), 2),
            "avg_win": round(float(avg_win), 2),
            "avg_loss": round(float(avg_loss), 2),
            "avg_holding_days": round(avg_holding_days, 1),
            "exit_reasons": exit_reasons,
        }


# ══════════════════════════════════════════════════════════════
#  4.  BACKTEST REPORT
# ══════════════════════════════════════════════════════════════

class BacktestReport:
    """Wraps all backtest results and provides display methods."""

    def __init__(self, trades, equity_curve, initial_capital, config):
        self.trades = trades
        self.equity_curve = equity_curve
        self.initial_capital = initial_capital
        self.config = config
        self.metrics = PerformanceMetrics.compute(trades, equity_curve, initial_capital)

    def print_summary(self):
        m = self.metrics
        if "error" in m:
            print(f"❌ {m['error']}")
            return

        grade = self._grade(m)
        print(f"\n{'╔' + '═'*54 + '╗'}")
        print(f"  {'BACKTEST RESULTS':^52}")
        print(f"{'╠' + '═'*54 + '╣'}")
        print("  RETURNS")
        print(f"    Total Return     : {m['total_return_pct']:>+8.2f}%")
        print(f"    CAGR             : {m['cagr_pct']:>+8.2f}%  (annualised)")
        print(f"    Final Equity     : ${m['final_equity']:>10,.2f}  (started ${self.initial_capital:,.0f})")
        print(f"{'─'*56}")
        print("  RISK")
        print(f"    Sharpe Ratio     : {m['sharpe_ratio']:>8.3f}  (>1.0 = good, >2.0 = great)")
        print(f"    Calmar Ratio     : {m['calmar_ratio']:>8.3f}")
        print(f"    Max Drawdown     : {m['max_drawdown_pct']:>+8.2f}%")
        print(f"{'─'*56}")
        print("  TRADES")
        print(f"    Total Trades     : {m['total_trades']:>8}")
        print(f"    Win Rate         : {m['win_rate_pct']:>8.1f}%")
        print(f"    Profit Factor    : {m['profit_factor']:>8.2f}  (>1.5 = good)")
        print(f"    Payoff Ratio     : {m['payoff_ratio']:>8.2f}  (avg win / avg loss)")
        print(f"    Expectancy       : ${m['expectancy']:>8.2f}  per trade")
        print(f"    Avg Holding Days : {m['avg_holding_days']:>8.1f}")
        print(f"{'─'*56}")
        print(f"  Exit Reasons: {m['exit_reasons']}")
        skipped = self.config.get("skipped_orders", [])
        if skipped:
            print(f"  Skipped Orders: {len(skipped)}")
        print(f"{'─'*56}")
        print(f"  Overall Grade: {grade}")
        print(f"{'╚' + '═'*54 + '╝'}")

    def print_trade_log(self, last_n: int = 20):
        closed = [t for t in self.trades if not t.is_open]
        if not closed:
            print("No closed trades.")
            return

        print(
            f"\n  {'#':>3} {'ENTRY DATE':<12} {'EXIT DATE':<12} "
            f"{'ENTRY':>8} {'EXIT':>8} {'SHARES':>8} {'P&L':>9} {'%':>7}  {'REASON'}"
        )
        print("  " + "─" * 90)
        for t in closed[-last_n:]:
            pnl_col = "+" if t.pnl >= 0 else ""
            print(
                f"  {t.trade_id:>3} {str(t.entry_date)[:10]:<12} {str(t.exit_date)[:10]:<12} "
                f"${t.entry_price:>7.2f} ${t.exit_price:>7.2f} {t.shares:>8.2f} "
                f"{pnl_col}${t.pnl:>7.2f} {pnl_col}{t.pnl_pct:>6.1f}%  {t.exit_reason}"
            )

    def _grade(self, m: dict) -> str:
        score = 0
        if m["total_return_pct"] > 20:
            score += 2
        if m["sharpe_ratio"] > 1.0:
            score += 2
        if m["sharpe_ratio"] > 2.0:
            score += 1
        if m["win_rate_pct"] > 50:
            score += 1
        if m["profit_factor"] > 1.5:
            score += 2
        if m["max_drawdown_pct"] > -20:
            score += 1
        if m["max_drawdown_pct"] > -10:
            score += 1
        if score >= 8:
            return "⭐⭐⭐⭐⭐ EXCEPTIONAL"
        if score >= 6:
            return "⭐⭐⭐⭐   GREAT"
        if score >= 4:
            return "⭐⭐⭐     GOOD"
        if score >= 2:
            return "⭐⭐       AVERAGE"
        return "⭐         NEEDS WORK"

    def get_metrics(self) -> dict:
        return self.metrics

    def get_equity_curve(self) -> pd.DataFrame:
        return self.equity_curve


# ══════════════════════════════════════════════════════════════
#  5.  WALK-FORWARD TEST
# ══════════════════════════════════════════════════════════════

class WalkForwardTest:
    """Rolling out-of-sample validation."""

    def __init__(self, train_pct: float = 0.7, n_splits: int = 3):
        self.train_pct = float(train_pct)
        self.n_splits = int(n_splits)

    def run(self, df: pd.DataFrame, strategy_class, engine_kwargs: Optional[dict] = None) -> list:
        engine_kwargs = dict(engine_kwargs or {})
        n = len(df)
        reports = []
        step = (1 - self.train_pct) / max(self.n_splits, 1)

        print(f"\n🔄 Walk-Forward Test: {self.n_splits} splits")
        print(f"   Train: {self.train_pct*100:.0f}%  |  Test window: {step*100:.1f}% each")

        for i in range(self.n_splits):
            train_end = int(n * (self.train_pct + i * step))
            test_end = int(n * (self.train_pct + (i + 1) * step))
            test_start = train_end
            if test_end > n or test_start >= test_end:
                break

            train_df = df.iloc[:train_end]
            test_df = df.iloc[test_start:test_end]
            print(
                f"\n  Fold {i+1}: Train {train_df.index[0].date()}→{train_df.index[-1].date()} "
                f"| Test {test_df.index[0].date()}→{test_df.index[-1].date()}"
            )

            strategy = strategy_class(test_df)
            df_sig = strategy.generate()
            engine = BacktestEngine(**engine_kwargs)
            report = engine.run(df_sig)
            report.print_summary()
            reports.append(report)

        print(f"\n{'═'*55}")
        print("  WALK-FORWARD SUMMARY")
        print(f"{'─'*55}")
        for i, r in enumerate(reports):
            m = r.metrics
            if "error" not in m:
                print(
                    f"  Fold {i+1}: Return={m['total_return_pct']:+.1f}%  "
                    f"Sharpe={m['sharpe_ratio']:.2f}  "
                    f"WinRate={m['win_rate_pct']:.1f}%  "
                    f"MaxDD={m['max_drawdown_pct']:.1f}%"
                )
        print(f"{'═'*55}")
        return reports


# ══════════════════════════════════════════════════════════════
#  6.  STRATEGY COMPARISON
# ══════════════════════════════════════════════════════════════

def compare_strategies(df: pd.DataFrame, initial_capital: float = 10_000, engine_kwargs: Optional[dict] = None) -> pd.DataFrame:
    """Run all strategies and compare metrics side by side."""
    print("\n" + "=" * 60)
    print("  STRATEGY COMPARISON")
    print("=" * 60)

    if not MODULES_AVAILABLE:
        print("⚠️  strategy_signals.py not available. Run full system for comparison.")
        return pd.DataFrame()

    engine_kwargs = dict(engine_kwargs or {})
    engine_kwargs.setdefault("initial_capital", initial_capital)
    results = {}
    strategies = {
        "Mean Reversion": MeanReversionStrategy,
        "Momentum": MomentumStrategy,
        "Combined": CombinedStrategy,
    }

    for name, strat_class in strategies.items():
        print(f"\n▶ Running {name}...")
        strategy = strat_class(df)
        df_sig = strategy.generate()
        engine = BacktestEngine(**engine_kwargs)
        report = engine.run(df_sig)
        m = report.metrics
        if "error" not in m:
            results[name] = {
                "Return %": m["total_return_pct"],
                "CAGR %": m["cagr_pct"],
                "Sharpe": m["sharpe_ratio"],
                "Max DD %": m["max_drawdown_pct"],
                "Win Rate %": m["win_rate_pct"],
                "Profit Factor": m["profit_factor"],
                "Trades": m["total_trades"],
                "Expectancy $": m["expectancy"],
            }

    comparison = pd.DataFrame(results).T
    print("\n" + "=" * 60)
    print("  SIDE-BY-SIDE COMPARISON")
    print("=" * 60)
    if not comparison.empty:
        print(comparison.to_string())
    return comparison


# ══════════════════════════════════════════════════════════════
#  7.  MAIN
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  QUANT TRADING SYSTEM — Phase 3: Backtester")
    print("=" * 60)

    if MODULES_AVAILABLE:
        try:
            loader = DataLoader()
            df = loader.load("AAPL", "1d")
            print("✅ Loaded saved AAPL data from Phase 1")
        except Exception:
            try:
                fetcher = StockDataFetcher()
                df = fetcher.fetch("AAPL", interval="1d", period="2y")
                print("✅ Fetched fresh AAPL data")
            except Exception:
                print("🔧 Falling back to synthetic sample data for demo")
                df = generate_sample_data(500)
    else:
        print("🔧 Using synthetic sample data (modules unavailable)")
        df = generate_sample_data(500)

    print("\n▶ Backtesting: Mean Reversion Strategy")
    if MODULES_AVAILABLE:
        strategy = MeanReversionStrategy(df)
        df_sig = strategy.generate()
    else:
        df_sig = df.copy()
        close = df_sig["close"]
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
        sma = close.rolling(20).mean()
        std = close.rolling(20).std()
        bb_pct = (close - (sma - 2 * std)) / ((sma + 2 * std) - (sma - 2 * std))
        df_sig["signal"] = 0
        df_sig.loc[(rsi < 35) & (bb_pct < 0.15), "signal"] = 1
        df_sig.loc[(rsi > 65) & (bb_pct > 0.85), "signal"] = -1
        df_sig["signal_reason"] = ""
        df_sig["signal_strength"] = 0.5

    engine_kwargs = {
        "initial_capital": 10_000,
        "position_size": 0.95,
        "commission_pct": 0.001,
        "slippage_pct": 0.0005,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.10,
    }
    if RISK_AVAILABLE:
        engine_kwargs["risk_config"] = RiskConfig(
            risk_per_trade_pct=0.01,
            max_position_pct=0.20,
            max_total_exposure_pct=1.0,
            atr_stop_multiple=2.0,
            reward_to_risk=2.0,
            allow_short=False,
            max_open_positions=1,
        )

    engine = BacktestEngine(**engine_kwargs)
    report = engine.run(df_sig)
    report.print_summary()
    report.print_trade_log(last_n=15)

    if MODULES_AVAILABLE:
        compare_strategies(df, initial_capital=10_000, engine_kwargs=engine_kwargs)
        print("\n▶ Walk-Forward Validation (Mean Reversion)...")
        wf = WalkForwardTest(train_pct=0.7, n_splits=3)
        wf.run(df, MeanReversionStrategy, engine_kwargs=engine_kwargs)

    print("\n✅ Phase 3 Complete! Backtester is ready.")
    print("   Next → Phase 4: Risk Management")
    return report


if __name__ == "__main__":
    main()
