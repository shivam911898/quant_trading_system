"""
╔══════════════════════════════════════════════════════════════╗
║     QUANT TRADING SYSTEM — PHASE 5: LIVE PAPER TRADING     ║
╚══════════════════════════════════════════════════════════════╝

This module simulates live trading logic without risking real money.
It is intentionally compatible with the earlier phases:

  • Phase 1: reads OHLCV-style bars
  • Phase 2: uses any strategy class that outputs signal / signal_strength
  • Phase 4: asks the RiskManager to approve and size each new trade
  • Phase 6: persists CSV / JSON state for the dashboard

Execution model:
  • Signals observed on bar[i] are NOT traded immediately.
  • They are queued as pending orders.
  • Pending orders are executed at bar[i+1] open.
  • After the open fill, stop-loss / take-profit are checked intrabar.

This matches the patched Phase 3 backtester semantics.

Contains:
  1. PaperOrder           — order request + fill details
  2. PaperPosition        — one open position
  3. PendingSignal        — queued signal waiting for next-bar-open execution
  4. SimulatedPaperBroker — tracks cash, fills, and mark-to-market equity
  5. PaperTradingEngine   — event loop that behaves like a live trader
  6. TradingSessionReport — summary + export locations
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional, Type
import json
import warnings
import io
import logging
import time
from contextlib import redirect_stdout

import pandas as pd
import requests

warnings.filterwarnings("ignore")
LOGGER = logging.getLogger(__name__)
CONTROL_COMMANDS_FILE = "control_commands.jsonl"

try:
    from risk_management import RiskConfig, RiskDecision, RiskManager, PortfolioSnapshot
except ImportError as exc:
    raise ImportError("Place live_paper_trading.py next to risk_management.py") from exc


# ══════════════════════════════════════════════════════════════
#  1.  DATACLASSES
# ══════════════════════════════════════════════════════════════

@dataclass
class PaperOrder:
    order_id: int
    timestamp: pd.Timestamp
    symbol: str
    side: str                       # buy / sell / short / cover
    quantity: int
    requested_price: float
    filled_price: float
    status: str                     # filled / rejected / cancelled
    reason: str = ""
    fees: float = 0.0

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["timestamp"] = str(self.timestamp)
        return payload


@dataclass
class PaperPosition:
    symbol: str
    side: str                       # long / short
    quantity: int
    entry_price: float
    entry_time: pd.Timestamp
    stop_price: Optional[float] = None
    target_price: Optional[float] = None
    current_price: Optional[float] = None
    unrealized_pnl: float = 0.0

    def mark(self, price: float):
        self.current_price = float(price)
        if self.side == "long":
            self.unrealized_pnl = (self.current_price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - self.current_price) * self.quantity

    def exposure(self) -> float:
        px = self.current_price if self.current_price is not None else self.entry_price
        return abs(self.quantity * px)

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload["entry_time"] = str(self.entry_time)
        return payload


@dataclass
class PendingSignal:
    symbol: str
    signal: int
    signal_time: pd.Timestamp
    signal_reason: str = ""
    row_payload: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "signal": int(self.signal),
            "signal_time": str(self.signal_time),
            "signal_reason": self.signal_reason,
            "row_payload": dict(self.row_payload),
        }


@dataclass
class TradingSessionReport:
    equity_curve: pd.DataFrame
    orders: pd.DataFrame
    positions_history: pd.DataFrame
    alerts: pd.DataFrame
    state_dir: Path

    def summary(self) -> dict:
        if self.equity_curve.empty:
            return {"error": "No session activity"}

        eq = self.equity_curve["equity"]
        start = float(eq.iloc[0])
        end = float(eq.iloc[-1])
        dd = ((eq - eq.cummax()) / eq.cummax() * 100).min()

        return {
            "start_equity": round(start, 2),
            "final_equity": round(end, 2),
            "total_return_pct": round((end - start) / start * 100, 2) if start else 0.0,
            "max_drawdown_pct": round(float(dd), 2),
            "total_orders": int(len(self.orders)),
            "alerts": int(len(self.alerts)),
            "state_dir": str(self.state_dir),
        }


# ══════════════════════════════════════════════════════════════
#  2.  BROKER SIMULATION
# ══════════════════════════════════════════════════════════════

class SimulatedPaperBroker:
    """
    Minimal broker that supports one position per symbol.
    Good enough for validating your live decision loop before any API integration.
    """

    def __init__(self, starting_cash: float = 10_000.0,
                 commission_pct: float = 0.001,
                 slippage_pct: float = 0.0005):
        self.starting_cash = float(starting_cash)
        self.cash = float(starting_cash)
        self.commission_pct = float(commission_pct)
        self.slippage_pct = float(slippage_pct)
        self.positions: Dict[str, PaperPosition] = {}
        self.orders: List[PaperOrder] = []
        self.order_counter = 0

    def _fill_price(self, price: float, side: str) -> float:
        slip = price * self.slippage_pct
        if side in {"buy", "cover"}:
            return price + slip
        return price - slip

    def _fees(self, notional: float) -> float:
        return notional * self.commission_pct

    def submit_order(
        self,
        timestamp,
        symbol: str,
        side: str,
        quantity: int,
        market_price: float,
        reason: str = "",
        stop_price: Optional[float] = None,
        target_price: Optional[float] = None,
    ) -> PaperOrder:
        timestamp = pd.Timestamp(timestamp)
        self.order_counter += 1
        filled_price = self._fill_price(float(market_price), side)
        notional = filled_price * quantity
        fees = self._fees(notional)
        status = "filled"

        if quantity <= 0:
            status = "rejected"
            order = PaperOrder(self.order_counter, timestamp, symbol, side, quantity,
                               market_price, market_price, status,
                               "quantity<=0", 0.0)
            self.orders.append(order)
            return order

        if side == "buy":
            total_cost = notional + fees
            if self.cash < total_cost:
                status = "rejected"
                order = PaperOrder(self.order_counter, timestamp, symbol, side, quantity,
                                   market_price, filled_price, status,
                                   "insufficient_cash", fees)
                self.orders.append(order)
                return order

            self.cash -= total_cost
            self.positions[symbol] = PaperPosition(
                symbol=symbol,
                side="long",
                quantity=quantity,
                entry_price=filled_price,
                entry_time=timestamp,
                stop_price=stop_price,
                target_price=target_price,
                current_price=filled_price,
            )

        elif side == "sell":
            pos = self.positions.get(symbol)
            if pos is None or pos.side != "long":
                status = "rejected"
                order = PaperOrder(self.order_counter, timestamp, symbol, side, quantity,
                                   market_price, filled_price, status,
                                   "no_long_position", fees)
                self.orders.append(order)
                return order
            sell_qty = min(quantity, pos.quantity)
            notional = filled_price * sell_qty
            fees = self._fees(notional)
            proceeds = notional - fees
            self.cash += proceeds
            pos.quantity -= sell_qty
            pos.mark(filled_price)
            quantity = sell_qty
            if pos.quantity == 0:
                self.positions.pop(symbol, None)

        elif side == "short":
            proceeds = notional - fees
            self.cash += proceeds
            self.positions[symbol] = PaperPosition(
                symbol=symbol,
                side="short",
                quantity=quantity,
                entry_price=filled_price,
                entry_time=timestamp,
                stop_price=stop_price,
                target_price=target_price,
                current_price=filled_price,
            )

        elif side == "cover":
            pos = self.positions.get(symbol)
            if pos is None or pos.side != "short":
                status = "rejected"
                order = PaperOrder(self.order_counter, timestamp, symbol, side, quantity,
                                   market_price, filled_price, status,
                                   "no_short_position", fees)
                self.orders.append(order)
                return order
            cover_qty = min(quantity, pos.quantity)
            notional = filled_price * cover_qty
            fees = self._fees(notional)
            buyback_cost = notional + fees
            self.cash -= buyback_cost
            pos.quantity -= cover_qty
            pos.mark(filled_price)
            quantity = cover_qty
            if pos.quantity == 0:
                self.positions.pop(symbol, None)
        else:
            status = "rejected"
            order = PaperOrder(self.order_counter, timestamp, symbol, side, quantity,
                               market_price, market_price, status,
                               f"unknown_side:{side}", 0.0)
            self.orders.append(order)
            return order

        order = PaperOrder(self.order_counter, timestamp, symbol, side, quantity,
                           market_price, filled_price, status, reason, fees)
        self.orders.append(order)
        return order

    def mark_to_market(self, price_map: Dict[str, float]):
        for symbol, pos in list(self.positions.items()):
            if symbol in price_map:
                pos.mark(float(price_map[symbol]))

    def gross_exposure(self) -> float:
        return float(sum(pos.exposure() for pos in self.positions.values()))

    def net_exposure(self) -> float:
        total = 0.0
        for pos in self.positions.values():
            sign = 1 if pos.side == "long" else -1
            total += sign * pos.exposure()
        return float(total)

    def equity(self) -> float:
        total = self.cash
        for pos in self.positions.values():
            px = pos.current_price if pos.current_price is not None else pos.entry_price
            if pos.side == "long":
                total += px * pos.quantity
            else:
                total -= px * pos.quantity
        return float(total)

    def snapshot(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            equity=self.equity(),
            cash=float(self.cash),
            gross_exposure=self.gross_exposure(),
            net_exposure=self.net_exposure(),
            open_positions=len(self.positions),
            symbol_exposure={s: p.exposure() for s, p in self.positions.items()},
        )


class AlpacaPaperBroker:
    """
    Alpaca paper trading adapter implementing the broker interface expected by PaperTradingEngine.
    """

    def __init__(self, api_key: str, secret_key: str, base_url: str = "https://paper-api.alpaca.markets"):
        if not api_key or not secret_key:
            raise ValueError("Alpaca API credentials are required for alpaca-paper broker")

        self.api_key = api_key.strip()
        self.secret_key = secret_key.strip()
        normalized_base = base_url.strip().rstrip("/")
        if normalized_base.endswith("/v2"):
            normalized_base = normalized_base[: -len("/v2")]
        self.base_url = normalized_base
        self.headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
            "Content-Type": "application/json",
        }

        self.cash = 0.0
        self.positions: Dict[str, PaperPosition] = {}
        self.orders: List[PaperOrder] = []
        self.order_counter = 0
        self._equity = 0.0
        self._position_risk: Dict[str, dict] = {}

        self._refresh_account()
        self._refresh_positions()

    def _request(self, method: str, path: str, payload: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        response = requests.request(method, url, headers=self.headers, json=payload, timeout=15)
        if response.status_code >= 400:
            raise RuntimeError(f"Alpaca API error {response.status_code}: {response.text}")
        if response.text.strip() == "":
            return {}
        return response.json()

    def _refresh_account(self) -> None:
        account = self._request("GET", "/v2/account")
        self.cash = float(account.get("cash", 0.0))
        self._equity = float(account.get("equity", self.cash))

    def _refresh_positions(self) -> None:
        raw_positions = self._request("GET", "/v2/positions")
        positions: Dict[str, PaperPosition] = {}
        if isinstance(raw_positions, list):
            for row in raw_positions:
                symbol = str(row.get("symbol", "")).upper()
                if not symbol:
                    continue

                qty_float = abs(float(row.get("qty", 0.0)))
                qty = int(round(qty_float))
                if qty <= 0:
                    continue

                side = str(row.get("side", "long")).lower()
                entry = float(row.get("avg_entry_price", 0.0))
                current = float(row.get("current_price", entry or 0.0))
                risk = self._position_risk.get(symbol, {})

                pos = PaperPosition(
                    symbol=symbol,
                    side="short" if side == "short" else "long",
                    quantity=qty,
                    entry_price=entry,
                    entry_time=pd.Timestamp.utcnow(),
                    stop_price=risk.get("stop_price"),
                    target_price=risk.get("target_price"),
                    current_price=current,
                    unrealized_pnl=float(row.get("unrealized_pl", 0.0)),
                )
                positions[symbol] = pos

        self.positions = positions

    def _poll_order_fill_price(self, order_id: str, fallback_price: float) -> float:
        filled_price = float(fallback_price)
        for _ in range(5):
            details = self._request("GET", f"/v2/orders/{order_id}")
            status = str(details.get("status", "")).lower()
            avg = details.get("filled_avg_price")
            if avg is not None:
                filled_price = float(avg)
            if status in {"filled", "partially_filled", "new", "accepted", "done_for_day"}:
                if status == "filled":
                    return filled_price
            time.sleep(0.4)
        return filled_price

    def submit_order(
        self,
        timestamp,
        symbol: str,
        side: str,
        quantity: int,
        market_price: float,
        reason: str = "",
        stop_price: Optional[float] = None,
        target_price: Optional[float] = None,
    ) -> PaperOrder:
        ts = pd.Timestamp(timestamp)
        self.order_counter += 1
        normalized_symbol = symbol.upper()

        if quantity <= 0:
            order = PaperOrder(
                self.order_counter,
                ts,
                normalized_symbol,
                side,
                quantity,
                float(market_price),
                float(market_price),
                "rejected",
                "quantity<=0",
                0.0,
            )
            self.orders.append(order)
            return order

        api_side = "buy" if side in {"buy", "cover"} else "sell"
        payload = {
            "symbol": normalized_symbol,
            "qty": str(int(quantity)),
            "side": api_side,
            "type": "market",
            "time_in_force": "day",
        }

        try:
            submitted = self._request("POST", "/v2/orders", payload)
            alpaca_order_id = str(submitted.get("id", ""))
            filled_price = float(market_price)
            if alpaca_order_id:
                filled_price = self._poll_order_fill_price(alpaca_order_id, fallback_price=float(market_price))

            status = "filled"
            if side in {"buy", "short"}:
                self._position_risk[normalized_symbol] = {
                    "stop_price": stop_price,
                    "target_price": target_price,
                }
            elif side in {"sell", "cover"}:
                self._position_risk.pop(normalized_symbol, None)

            self._refresh_account()
            self._refresh_positions()

            order = PaperOrder(
                self.order_counter,
                ts,
                normalized_symbol,
                side,
                int(quantity),
                float(market_price),
                filled_price,
                status,
                reason,
                0.0,
            )
        except Exception as exc:
            LOGGER.exception("Alpaca order failed")
            order = PaperOrder(
                self.order_counter,
                ts,
                normalized_symbol,
                side,
                int(quantity),
                float(market_price),
                float(market_price),
                "rejected",
                str(exc),
                0.0,
            )

        self.orders.append(order)
        return order

    def mark_to_market(self, price_map: Dict[str, float]):
        _ = price_map
        self._refresh_account()
        self._refresh_positions()

    def gross_exposure(self) -> float:
        return float(sum(pos.exposure() for pos in self.positions.values()))

    def net_exposure(self) -> float:
        total = 0.0
        for pos in self.positions.values():
            sign = 1 if pos.side == "long" else -1
            total += sign * pos.exposure()
        return float(total)

    def equity(self) -> float:
        self._refresh_account()
        return float(self._equity)

    def snapshot(self) -> PortfolioSnapshot:
        self._refresh_account()
        self._refresh_positions()
        return PortfolioSnapshot(
            equity=float(self._equity),
            cash=float(self.cash),
            gross_exposure=self.gross_exposure(),
            net_exposure=self.net_exposure(),
            open_positions=len(self.positions),
            symbol_exposure={s: p.exposure() for s, p in self.positions.items()},
        )


# ══════════════════════════════════════════════════════════════
#  3.  PAPER TRADING ENGINE
# ══════════════════════════════════════════════════════════════

class PaperTradingEngine:
    """
    Feeds bars one at a time into the strategy and broker.

    Signal semantics mirror the backtester:
      1. Execute previous bar's pending signal at current open.
      2. Check stop-loss / take-profit inside the current bar.
      3. Mark equity on the current close.
      4. Compute current bar signal and queue it for next bar open.
    """

    def __init__(self,
                 strategy_class: Type,
                 broker: SimulatedPaperBroker,
                 risk_manager: RiskManager,
                 allow_short: bool = False,
                 state_dir: str = "runtime_state"):
        self.strategy_class = strategy_class
        self.broker = broker
        self.risk_manager = risk_manager
        self.allow_short = allow_short
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.equity_points: List[dict] = []
        self.alerts: List[dict] = []
        self.position_snapshots: List[dict] = []
        self.pending_signals: Dict[str, PendingSignal] = {}
        self.trading_paused: bool = False

    def _log_alert(self, timestamp, level: str, message: str):
        self.alerts.append({
            "timestamp": str(pd.Timestamp(timestamp)),
            "level": level,
            "message": message,
        })

    def _serialize_signal_row(self, row: pd.Series) -> dict:
        payload = {}
        for key, value in row.to_dict().items():
            if pd.isna(value):
                payload[key] = None
            elif isinstance(value, pd.Timestamp):
                payload[key] = str(value)
            else:
                payload[key] = value
        return payload

    def _queue_signal_for_next_open(self, timestamp, signal_row: pd.Series):
        if self.trading_paused:
            return
        symbol = str(signal_row.get("symbol", "UNKNOWN"))
        signal = int(signal_row.get("signal", 0))
        if signal == 0:
            self.pending_signals.pop(symbol, None)
            return

        pending = PendingSignal(
            symbol=symbol,
            signal=signal,
            signal_time=pd.Timestamp(timestamp),
            signal_reason=str(signal_row.get("signal_reason", "")),
            row_payload=self._serialize_signal_row(signal_row),
        )
        self.pending_signals[symbol] = pending
        self._log_alert(
            timestamp,
            "INFO",
            f"{symbol}: queued signal {signal:+d} for next-bar-open execution"
            + (f" | {pending.signal_reason}" if pending.signal_reason else ""),
        )

    def _export_state(self):
        orders_df = pd.DataFrame([o.as_dict() for o in self.broker.orders])
        positions_df = pd.DataFrame(self.position_snapshots)
        alerts_df = pd.DataFrame(self.alerts)
        equity_df = pd.DataFrame(self.equity_points)

        if not orders_df.empty:
            orders_df.to_csv(self.state_dir / "orders.csv", index=False)
        if not positions_df.empty:
            positions_df.to_csv(self.state_dir / "positions_history.csv", index=False)
        if not alerts_df.empty:
            alerts_df.to_csv(self.state_dir / "alerts.csv", index=False)
        if not equity_df.empty:
            equity_df.to_csv(self.state_dir / "equity_curve.csv", index=False)

        state = {
            "broker": {
                "cash": round(self.broker.cash, 2),
                "equity": round(self.broker.equity(), 2),
                "gross_exposure": round(self.broker.gross_exposure(), 2),
                "net_exposure": round(self.broker.net_exposure(), 2),
                "open_positions": len(self.broker.positions),
                "trading_paused": self.trading_paused,
            },
            "risk": self.risk_manager.summary(),
            "positions": [pos.as_dict() for pos in self.broker.positions.values()],
            "pending_signals": [p.as_dict() for p in self.pending_signals.values()],
            "last_alert": self.alerts[-1] if self.alerts else None,
        }
        (self.state_dir / "system_state.json").write_text(json.dumps(state, indent=2))

    def _consume_control_commands(self) -> List[dict]:
        path = self.state_dir / CONTROL_COMMANDS_FILE
        if not path.exists():
            return []

        commands: List[dict] = []
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
                if isinstance(payload, dict):
                    commands.append(payload)
            except json.JSONDecodeError:
                self._log_alert(pd.Timestamp.utcnow(), "WARN", f"Invalid control command payload: {stripped[:80]}")

        path.write_text("")
        return commands

    def _flatten_all_positions(self, timestamp, row: pd.Series):
        execution_price = float(row.get("open", row["close"]))
        for symbol, pos in list(self.broker.positions.items()):
            side = "sell" if pos.side == "long" else "cover"
            self._submit_exit(timestamp, symbol, side, pos.quantity, execution_price, "manual_flatten_all")

    def _process_control_commands(self, timestamp, row: pd.Series):
        commands = self._consume_control_commands()
        for command in commands:
            cmd = str(command.get("command", "")).strip().upper()
            source = str(command.get("source", "unknown"))

            if cmd == "PAUSE_TRADING":
                self.trading_paused = True
                self._log_alert(timestamp, "WARN", f"Control command from {source}: trading paused")
            elif cmd == "RESUME_TRADING":
                self.trading_paused = False
                self._log_alert(timestamp, "INFO", f"Control command from {source}: trading resumed")
            elif cmd == "CANCEL_PENDING":
                dropped = len(self.pending_signals)
                self.pending_signals.clear()
                self._log_alert(timestamp, "INFO", f"Control command from {source}: cleared {dropped} pending signals")
            elif cmd == "FLATTEN_ALL":
                self._flatten_all_positions(timestamp, row)
                self._log_alert(timestamp, "WARN", f"Control command from {source}: flatten-all executed")
            else:
                self._log_alert(timestamp, "WARN", f"Unknown control command from {source}: {cmd}")

    def _submit_exit(self, timestamp, symbol: str, side: str, quantity: int, price: float, reason: str):
        order = self.broker.submit_order(timestamp, symbol, side, quantity, price, reason=reason)
        if order.status == "filled":
            self._log_alert(timestamp, "INFO", f"{symbol}: {side} x{quantity} @ {order.filled_price:.2f} [{reason}]")
        else:
            self._log_alert(timestamp, "WARN", f"{symbol}: {side} rejected — {order.reason}")
        return order

    def _check_exit_rules(self, timestamp, row: pd.Series):
        symbol = str(row.get("symbol", "UNKNOWN"))
        pos = self.broker.positions.get(symbol)
        if pos is None:
            return

        current_open = float(row.get("open", row["close"]))
        current_high = float(row.get("high", row["close"]))
        current_low = float(row.get("low", row["close"]))
        current_close = float(row.get("close", row["close"]))
        pos.mark(current_close)

        if pos.side == "long":
            if pos.stop_price is not None and current_open <= pos.stop_price:
                self._submit_exit(timestamp, symbol, "sell", pos.quantity, current_open, "gap_stop_loss")
                return
            if pos.target_price is not None and current_open >= pos.target_price:
                self._submit_exit(timestamp, symbol, "sell", pos.quantity, current_open, "gap_take_profit")
                return
            if pos.stop_price is not None and current_low <= pos.stop_price:
                self._submit_exit(timestamp, symbol, "sell", pos.quantity, pos.stop_price, "stop_loss")
                return
            if pos.target_price is not None and current_high >= pos.target_price:
                self._submit_exit(timestamp, symbol, "sell", pos.quantity, pos.target_price, "take_profit")
                return
        else:
            if pos.stop_price is not None and current_open >= pos.stop_price:
                self._submit_exit(timestamp, symbol, "cover", pos.quantity, current_open, "gap_stop_loss")
                return
            if pos.target_price is not None and current_open <= pos.target_price:
                self._submit_exit(timestamp, symbol, "cover", pos.quantity, current_open, "gap_take_profit")
                return
            if pos.stop_price is not None and current_high >= pos.stop_price:
                self._submit_exit(timestamp, symbol, "cover", pos.quantity, pos.stop_price, "stop_loss")
                return
            if pos.target_price is not None and current_low <= pos.target_price:
                self._submit_exit(timestamp, symbol, "cover", pos.quantity, pos.target_price, "take_profit")
                return

    def _latest_signal(self, history_df: pd.DataFrame) -> pd.Series:
        strategy = self.strategy_class(history_df)
        with io.StringIO() as buf, redirect_stdout(buf):
            enriched = strategy.generate()
        return enriched.iloc[-1]

    def _record_snapshot(self, timestamp, row: pd.Series):
        symbol = str(row.get("symbol", "UNKNOWN"))
        self.broker.mark_to_market({symbol: float(row["close"])})
        equity = self.broker.equity()
        cash = self.broker.cash
        gross = self.broker.gross_exposure()

        self.equity_points.append({
            "timestamp": str(pd.Timestamp(timestamp)),
            "price": float(row["close"]),
            "equity": round(equity, 4),
            "cash": round(cash, 4),
            "gross_exposure": round(gross, 4),
        })

        for pos in self.broker.positions.values():
            self.position_snapshots.append({
                "timestamp": str(pd.Timestamp(timestamp)),
                **pos.as_dict(),
            })

    def _execute_pending_signal_at_open(self, timestamp, row: pd.Series):
        symbol = str(row.get("symbol", "UNKNOWN"))
        pending = self.pending_signals.pop(symbol, None)
        if pending is None:
            return

        execution_open = float(row.get("open", row["close"]))
        signal_row = pd.Series(pending.row_payload, name=pending.signal_time)
        signal = int(pending.signal)
        current_pos = self.broker.positions.get(symbol)

        if signal == 1:
            for sym, pos in list(self.broker.positions.items()):
                if sym == symbol and pos.side == "short":
                    self._submit_exit(timestamp, symbol, "cover", pos.quantity, execution_open, "signal_reversal")
            if symbol in self.broker.positions and self.broker.positions[symbol].side == "long":
                return
            desired_side = "long"
        elif signal == -1 and self.allow_short:
            for sym, pos in list(self.broker.positions.items()):
                if sym == symbol and pos.side == "long":
                    self._submit_exit(timestamp, symbol, "sell", pos.quantity, execution_open, "signal_reversal")
            if symbol in self.broker.positions and self.broker.positions[symbol].side == "short":
                return
            desired_side = "short"
        elif signal == -1 and not self.allow_short:
            if current_pos and current_pos.side == "long":
                self._submit_exit(timestamp, symbol, "sell", current_pos.quantity, execution_open, "sell_signal")
            return
        else:
            return

        plan_row = signal_row.copy()
        plan_row["close"] = execution_open
        plan_row.name = pd.Timestamp(timestamp)
        portfolio = self.broker.snapshot()
        decision: RiskDecision = self.risk_manager.build_trade_plan(plan_row, portfolio, desired_side)
        if not decision.approved or decision.trade_plan is None:
            self._log_alert(timestamp, "WARN", f"{symbol}: pending entry rejected by risk manager — {decision.reason}")
            return

        plan = decision.trade_plan
        order_side = "buy" if desired_side == "long" else "short"
        order = self.broker.submit_order(
            timestamp,
            symbol,
            order_side,
            plan.quantity,
            execution_open,
            reason="signal_entry_next_open",
            stop_price=plan.stop_price,
            target_price=plan.take_profit_price,
        )
        if order.status == "filled":
            self._log_alert(
                timestamp,
                "INFO",
                f"{symbol}: executed queued {desired_side} x{plan.quantity} @ next open {order.filled_price:.2f} "
                f"| stop {plan.stop_price:.2f} | target {plan.take_profit_price:.2f}",
            )
        else:
            self._log_alert(timestamp, "WARN", f"{symbol}: broker rejected queued order — {order.reason}")

    def process_bar(self, history_df: pd.DataFrame):
        row = history_df.iloc[-1]
        timestamp = history_df.index[-1]

        self._process_control_commands(timestamp, row)

        if not self.trading_paused:
            self._execute_pending_signal_at_open(timestamp, row)
        self._check_exit_rules(timestamp, row)
        self._record_snapshot(timestamp, row)

        halted, reason = self.risk_manager.update_equity(timestamp, self.broker.equity())
        if halted:
            self._log_alert(timestamp, "ERROR", reason)
            self._export_state()
            return

        if self.trading_paused:
            self._export_state()
            return

        signal_row = self._latest_signal(history_df)
        self._queue_signal_for_next_open(timestamp, signal_row)
        self._export_state()

    def run_on_history(self, df: pd.DataFrame, warmup_bars: int = 220) -> TradingSessionReport:
        if len(df) <= warmup_bars:
            raise ValueError("Not enough rows for warm-up. Use more historical data.")

        for i in range(warmup_bars, len(df)):
            history = df.iloc[: i + 1]
            self.process_bar(history)

        self._export_state()

        equity_df = pd.read_csv(self.state_dir / "equity_curve.csv") if (self.state_dir / "equity_curve.csv").exists() else pd.DataFrame()
        orders_df = pd.read_csv(self.state_dir / "orders.csv") if (self.state_dir / "orders.csv").exists() else pd.DataFrame()
        positions_df = pd.read_csv(self.state_dir / "positions_history.csv") if (self.state_dir / "positions_history.csv").exists() else pd.DataFrame()
        alerts_df = pd.read_csv(self.state_dir / "alerts.csv") if (self.state_dir / "alerts.csv").exists() else pd.DataFrame()

        return TradingSessionReport(
            equity_curve=equity_df,
            orders=orders_df,
            positions_history=positions_df,
            alerts=alerts_df,
            state_dir=self.state_dir,
        )


# ══════════════════════════════════════════════════════════════
#  4.  MAIN — HISTORICAL PAPER MODE DEMO
# ══════════════════════════════════════════════════════════════


def main():
    print("=" * 60)
    print("  QUANT TRADING SYSTEM — Phase 5: Live Paper Trading")
    print("=" * 60)

    try:
        from strategy_signals import MomentumStrategy, generate_sample_data
    except ImportError as exc:
        raise SystemExit(f"Run this file from the same folder as strategy_signals.py: {exc}")

    df = generate_sample_data(420)
    broker = SimulatedPaperBroker(starting_cash=10_000, commission_pct=0.001, slippage_pct=0.0005)
    risk_manager = RiskManager(RiskConfig(
        risk_per_trade_pct=0.01,
        max_position_pct=0.20,
        max_total_exposure_pct=1.0,
        reward_to_risk=2.0,
        allow_short=False,
    ))

    engine = PaperTradingEngine(
        strategy_class=MomentumStrategy,
        broker=broker,
        risk_manager=risk_manager,
        allow_short=False,
        state_dir="paper_runtime",
    )
    report = engine.run_on_history(df, warmup_bars=220)

    print("\nSession summary:")
    print(report.summary())
    print(f"\nState exported to: {report.state_dir.resolve()}")
    print("Files written:")
    for name in ["equity_curve.csv", "orders.csv", "positions_history.csv", "alerts.csv", "system_state.json"]:
        path = report.state_dir / name
        if path.exists():
            print(f"  • {path}")

    print("\n✅ Phase 5 Complete! Paper trading engine is ready.")
    print("   Next → Phase 6: Monitoring Dashboard")
    return report


if __name__ == "__main__":
    main()
