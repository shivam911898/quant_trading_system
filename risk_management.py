"""
╔══════════════════════════════════════════════════════════════╗
║      QUANT TRADING SYSTEM — PHASE 4: RISK MANAGEMENT       ║
╚══════════════════════════════════════════════════════════════╝

This module turns raw strategy signals into executable trade plans.
It answers the most important question in trading:

    "How much should I trade, and when should I stop?"

Contains:
  1. RiskConfig        — central risk parameters
  2. TradePlan         — entry / stop / target / size for one trade
  3. RiskDecision      — approve / reject decision with reasons
  4. CircuitBreaker    — halts trading after large losses / drawdown
  5. RiskManager       — ATR stops, position sizing, exposure checks

Designed to plug into:
  • Phase 2 signals: expects signal, signal_strength, atr_14 if available
  • Phase 3 backtester: can annotate a DataFrame with risk columns
  • Phase 5 paper trader: can approve/reject each new order in real time
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Dict, Optional, Tuple
import math
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ══════════════════════════════════════════════════════════════
#  1.  CONFIG & DATACLASSES
# ══════════════════════════════════════════════════════════════

@dataclass
class RiskConfig:
    """Central risk configuration for the system."""

    risk_per_trade_pct: float = 0.01           # 1% of equity at risk per trade
    max_position_pct: float = 0.20             # max 20% of equity in one position
    max_total_exposure_pct: float = 1.00       # gross exposure cap (100% of equity)
    atr_stop_multiple: float = 2.0             # stop distance = 2 x ATR
    fallback_stop_loss_pct: float = 0.05       # use if ATR unavailable
    reward_to_risk: float = 2.0                # take-profit = 2R by default
    min_signal_strength: float = 0.10          # ignore weak signals
    max_open_positions: int = 5
    daily_loss_limit_pct: float = 0.03         # halt if down 3% in a day
    max_drawdown_limit_pct: float = 0.12       # halt if down 12% from peak
    allow_short: bool = False
    lot_size: int = 1                          # useful for integer-share assets
    slippage_buffer_pct: float = 0.0005        # reserve tiny extra margin
    stop_price_rounding: int = 4


@dataclass
class TradePlan:
    """Fully specified trade plan emitted by the risk engine."""

    symbol: str
    side: str                                  # long or short
    entry_price: float
    stop_price: float
    take_profit_price: float
    quantity: int
    notional: float
    risk_budget: float
    max_loss: float
    signal_strength: float
    atr: Optional[float] = None
    risk_per_share: float = 0.0
    metadata: Dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["metadata"] = dict(self.metadata)
        return payload


@dataclass
class RiskDecision:
    """Risk approval or rejection wrapper."""

    approved: bool
    reason: str
    trade_plan: Optional[TradePlan] = None


@dataclass
class PortfolioSnapshot:
    """Minimal portfolio snapshot used by RiskManager checks."""

    equity: float
    cash: float
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    open_positions: int = 0
    symbol_exposure: Dict[str, float] = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════
#  2.  CIRCUIT BREAKER
# ══════════════════════════════════════════════════════════════

class CircuitBreaker:
    """
    Tracks equity over time and halts trading when losses become too large.
    """

    def __init__(self, config: RiskConfig):
        self.config = config
        self.peak_equity: Optional[float] = None
        self.current_day: Optional[pd.Timestamp] = None
        self.day_start_equity: Optional[float] = None
        self.last_equity: Optional[float] = None
        self.halt_reason: str = ""

    def update(self, timestamp, equity: float) -> Tuple[bool, str]:
        ts = pd.Timestamp(timestamp)
        day = ts.normalize()

        if self.peak_equity is None:
            self.peak_equity = equity
        else:
            self.peak_equity = max(self.peak_equity, equity)

        if self.current_day is None or day != self.current_day:
            self.current_day = day
            self.day_start_equity = equity
            self.halt_reason = ""

        self.last_equity = equity

        if self.day_start_equity and self.day_start_equity > 0:
            daily_pnl_pct = (equity - self.day_start_equity) / self.day_start_equity
            if daily_pnl_pct <= -self.config.daily_loss_limit_pct:
                self.halt_reason = (
                    f"Daily loss limit hit ({daily_pnl_pct:.2%} <= "
                    f"-{self.config.daily_loss_limit_pct:.2%})"
                )
                return True, self.halt_reason

        if self.peak_equity and self.peak_equity > 0:
            dd = (equity - self.peak_equity) / self.peak_equity
            if dd <= -self.config.max_drawdown_limit_pct:
                self.halt_reason = (
                    f"Max drawdown limit hit ({dd:.2%} <= "
                    f"-{self.config.max_drawdown_limit_pct:.2%})"
                )
                return True, self.halt_reason

        return False, ""

    def status(self) -> dict:
        if self.last_equity is None:
            return {
                "peak_equity": None,
                "current_drawdown_pct": 0.0,
                "halted": False,
                "halt_reason": "",
            }

        current_dd = 0.0
        if self.peak_equity:
            current_dd = (self.last_equity - self.peak_equity) / self.peak_equity * 100

        return {
            "peak_equity": self.peak_equity,
            "current_drawdown_pct": round(current_dd, 2),
            "halted": bool(self.halt_reason),
            "halt_reason": self.halt_reason,
        }


# ══════════════════════════════════════════════════════════════
#  3.  RISK MANAGER
# ══════════════════════════════════════════════════════════════

class RiskManager:
    """
    Converts a signal into a trade plan with size, stop, target, and checks.
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        self.config = config or RiskConfig()
        self.circuit_breaker = CircuitBreaker(self.config)

    @staticmethod
    def _safe_float(value, default=np.nan) -> float:
        try:
            if value is None:
                return float(default)
            if pd.isna(value):
                return float(default)
            return float(value)
        except Exception:
            return float(default)

    def _signal_strength(self, row: pd.Series) -> float:
        strength = self._safe_float(row.get("signal_strength", 1.0), 1.0)
        return float(np.clip(strength, 0.0, 1.0))

    def _symbol(self, row: pd.Series) -> str:
        symbol = row.get("symbol", "UNKNOWN")
        return str(symbol)

    def _get_stop_distance(self, row: pd.Series, entry_price: float) -> Tuple[float, Optional[float]]:
        atr = self._safe_float(row.get("atr_14", np.nan), np.nan)
        if not np.isnan(atr) and atr > 0:
            stop_distance = atr * self.config.atr_stop_multiple
            return max(stop_distance, entry_price * 0.001), atr
        fallback = entry_price * self.config.fallback_stop_loss_pct
        return max(fallback, entry_price * 0.001), None

    def _round_quantity(self, qty: float) -> int:
        if self.config.lot_size <= 1:
            return max(0, int(math.floor(qty)))
        lots = math.floor(qty / self.config.lot_size)
        return max(0, lots * self.config.lot_size)

    def update_equity(self, timestamp, equity: float) -> Tuple[bool, str]:
        """Update risk state and return whether trading should halt."""
        return self.circuit_breaker.update(timestamp, equity)

    def build_trade_plan(
        self,
        row: pd.Series,
        portfolio: PortfolioSnapshot,
        side: str,
    ) -> RiskDecision:
        """
        Build a trade plan from the latest market row and portfolio state.
        """
        symbol = self._symbol(row)
        side = str(side).lower()

        if side not in {"long", "short"}:
            return RiskDecision(False, f"Invalid side: {side}")

        if side == "short" and not self.config.allow_short:
            return RiskDecision(False, "Short selling disabled in RiskConfig")

        halted, reason = self.circuit_breaker.update(row.name, portfolio.equity)
        if halted:
            return RiskDecision(False, reason)

        strength = self._signal_strength(row)
        if strength < self.config.min_signal_strength:
            return RiskDecision(False, f"Signal too weak ({strength:.2f} < {self.config.min_signal_strength:.2f})")

        if portfolio.open_positions >= self.config.max_open_positions:
            return RiskDecision(False, "Max open positions reached")

        entry_price = self._safe_float(row.get("close", np.nan), np.nan)
        if np.isnan(entry_price) or entry_price <= 0:
            return RiskDecision(False, "Invalid entry price")

        gross_after = portfolio.gross_exposure / max(portfolio.equity, 1e-9)
        if gross_after >= self.config.max_total_exposure_pct:
            return RiskDecision(False, "Portfolio gross exposure cap already reached")

        stop_distance, atr = self._get_stop_distance(row, entry_price)
        if stop_distance <= 0:
            return RiskDecision(False, "Stop distance could not be computed")

        stop_price = entry_price - stop_distance if side == "long" else entry_price + stop_distance
        target_price = (
            entry_price + stop_distance * self.config.reward_to_risk
            if side == "long"
            else entry_price - stop_distance * self.config.reward_to_risk
        )

        # Scale risk budget by signal strength, but do not reduce below 50% of base risk.
        base_risk_budget = portfolio.equity * self.config.risk_per_trade_pct
        scaled_risk_budget = base_risk_budget * (0.5 + 0.5 * strength)

        qty_by_risk = scaled_risk_budget / stop_distance
        alloc_cap = portfolio.equity * self.config.max_position_pct
        qty_by_alloc = alloc_cap / (entry_price * (1 + self.config.slippage_buffer_pct))
        qty_by_cash = portfolio.cash / (entry_price * (1 + self.config.slippage_buffer_pct)) if side == "long" else qty_by_alloc
        raw_qty = min(qty_by_risk, qty_by_alloc, qty_by_cash)
        quantity = self._round_quantity(raw_qty)

        if quantity <= 0:
            return RiskDecision(False, "Position size rounded to zero — account too small or stop too wide")

        notional = quantity * entry_price
        max_loss = quantity * stop_distance
        gross_exposure_pct_after = (portfolio.gross_exposure + notional) / max(portfolio.equity, 1e-9)
        if gross_exposure_pct_after > self.config.max_total_exposure_pct:
            return RiskDecision(False, "Trade would breach portfolio gross exposure cap")

        plan = TradePlan(
            symbol=symbol,
            side=side,
            entry_price=round(entry_price, 4),
            stop_price=round(stop_price, self.config.stop_price_rounding),
            take_profit_price=round(target_price, self.config.stop_price_rounding),
            quantity=quantity,
            notional=round(notional, 2),
            risk_budget=round(scaled_risk_budget, 2),
            max_loss=round(max_loss, 2),
            signal_strength=round(strength, 4),
            atr=None if atr is None else round(float(atr), 4),
            risk_per_share=round(stop_distance, 4),
            metadata={
                "gross_exposure_pct_after": round(gross_exposure_pct_after * 100, 2),
                "position_pct_of_equity": round(notional / max(portfolio.equity, 1e-9) * 100, 2),
                "base_risk_budget": round(base_risk_budget, 2),
            },
        )
        return RiskDecision(True, "approved", plan)

    def annotate_signal_frame(
        self,
        df: pd.DataFrame,
        starting_equity: float = 10_000.0,
        starting_cash: Optional[float] = None,
    ) -> pd.DataFrame:
        """
        Add risk columns to a signal DataFrame for inspection / debugging.

        This does not simulate fills. It simply shows what the risk engine would
        *want* to do if a signal appears at each row.
        """
        out = df.copy()
        out["trade_side"] = np.where(out.get("signal", 0) > 0, "long",
                              np.where(out.get("signal", 0) < 0, "short", "flat"))
        out["approved"] = False
        out["risk_reason"] = "no_signal"
        out["planned_qty"] = 0
        out["planned_stop"] = np.nan
        out["planned_target"] = np.nan
        out["planned_max_loss"] = 0.0
        out["planned_notional"] = 0.0

        portfolio = PortfolioSnapshot(
            equity=float(starting_equity),
            cash=float(starting_equity if starting_cash is None else starting_cash),
            gross_exposure=0.0,
            net_exposure=0.0,
            open_positions=0,
        )

        for idx, row in out.iterrows():
            signal = int(row.get("signal", 0))
            if signal == 0:
                continue
            side = "long" if signal > 0 else "short"
            decision = self.build_trade_plan(row, portfolio, side)
            out.at[idx, "approved"] = decision.approved
            out.at[idx, "risk_reason"] = decision.reason
            if decision.trade_plan:
                tp = decision.trade_plan
                out.at[idx, "planned_qty"] = tp.quantity
                out.at[idx, "planned_stop"] = tp.stop_price
                out.at[idx, "planned_target"] = tp.take_profit_price
                out.at[idx, "planned_max_loss"] = tp.max_loss
                out.at[idx, "planned_notional"] = tp.notional

        return out

    def summary(self) -> dict:
        payload = {"config": asdict(self.config)}
        payload.update({"circuit_breaker": self.circuit_breaker.status()})
        return payload


# ══════════════════════════════════════════════════════════════
#  4.  MAIN — QUICK DEMO
# ══════════════════════════════════════════════════════════════


def main():
    print("=" * 60)
    print("  QUANT TRADING SYSTEM — Phase 4: Risk Management")
    print("=" * 60)

    try:
        from strategy_signals import MeanReversionStrategy, generate_sample_data
    except ImportError as exc:
        raise SystemExit(f"Run this file from the same folder as strategy_signals.py: {exc}")

    df = generate_sample_data(350)
    strategy = MeanReversionStrategy(df)
    df_sig = strategy.generate()

    manager = RiskManager(
        RiskConfig(
            risk_per_trade_pct=0.01,
            max_position_pct=0.20,
            atr_stop_multiple=2.0,
            reward_to_risk=2.0,
            allow_short=False,
        )
    )

    annotated = manager.annotate_signal_frame(df_sig, starting_equity=10_000)
    preview = annotated[annotated["signal"] != 0][[
        "close", "signal", "signal_strength", "approved", "planned_qty",
        "planned_stop", "planned_target", "planned_max_loss", "risk_reason"
    ]].tail(10)

    print("\nLast 10 risk-reviewed signals:")
    print(preview.to_string())

    print("\nRisk manager status:")
    print(manager.summary())
    print("\n✅ Phase 4 Complete! Risk manager is ready.")
    print("   Next → Phase 5: Live Paper Trading")

    return annotated


if __name__ == "__main__":
    main()
