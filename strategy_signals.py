"""
╔══════════════════════════════════════════════════════════════╗
║     QUANT TRADING SYSTEM — PHASE 2: STRATEGY & SIGNALS      ║
╚══════════════════════════════════════════════════════════════╝

This module contains:
  1. SignalGenerator  — base class all strategies inherit from
  2. MeanReversionStrategy  — buy oversold, sell overbought (RSI + BB)
  3. MomentumStrategy       — ride trending moves (EMA crossover + MACD)
  4. CombinedStrategy       — blends both for higher-confidence signals
  5. SignalVisualizer        — prints signal summary to console

Every strategy outputs a standard signal column:
   +1  = BUY
    0  = HOLD / flat
   -1  = SELL / short

Author: Your Trading System
"""

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

# ── Try importing Phase 1 data pipeline ───────────────────────
try:
    from data_pipeline import StockDataFetcher, TechnicalIndicators, DataLoader
    PIPELINE_AVAILABLE = True
except ImportError:
    PIPELINE_AVAILABLE = False
    print("⚠️  data_pipeline.py not found. Using sample data mode.")


# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

def generate_sample_data(n: int = 500) -> pd.DataFrame:
    """
    Generate synthetic OHLCV data for testing without an API.
    Uses a random walk with realistic price dynamics.
    """
    np.random.seed(42)
    dates = pd.date_range("2022-01-01", periods=n, freq="B")

    # Geometric Brownian Motion — realistic price simulation
    returns = np.random.normal(0.0003, 0.015, n)
    close   = 150.0 * np.cumprod(1 + returns)
    high    = close * (1 + np.abs(np.random.normal(0, 0.008, n)))
    low     = close * (1 - np.abs(np.random.normal(0, 0.008, n)))
    open_   = close * (1 + np.random.normal(0, 0.005, n))
    volume  = np.random.randint(1_000_000, 10_000_000, n).astype(float)

    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume, "symbol": "SAMPLE"
    }, index=dates)


# ══════════════════════════════════════════════════════════════
#  1.  BASE SIGNAL GENERATOR
# ══════════════════════════════════════════════════════════════

class SignalGenerator:
    """
    Base class for all strategies.
    Handles data loading, indicator computation, and signal validation.

    Every strategy:
      1. Takes OHLCV data
      2. Computes indicators (from Phase 1)
      3. Generates a signal column: +1, 0, -1
      4. Optionally filters signals by confidence
    """

    def __init__(self, df: pd.DataFrame):
        """
        Args:
            df : OHLCV DataFrame (from Phase 1 DataFetcher)
        """
        self.raw_df = df.copy()
        self.df     = None   # will hold df + indicators + signals
        self.name   = "Base"

    def _add_indicators(self) -> pd.DataFrame:
        """Add all technical indicators via Phase 1 TechnicalIndicators."""
        if PIPELINE_AVAILABLE:
            ti = TechnicalIndicators(self.raw_df)
            return ti.add_all()
        else:
            # Minimal indicator computation if pipeline not available
            df = self.raw_df.copy()
            close = df["close"]
            for w in [9, 20, 50, 200]:
                df[f"sma_{w}"]  = close.rolling(w).mean()
                df[f"ema_{w}"]  = close.ewm(span=w, adjust=False).mean()
            # RSI
            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            df["rsi_14"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))
            # Bollinger Bands
            sma = close.rolling(20).mean()
            std = close.rolling(20).std()
            df["bb_upper"]  = sma + 2 * std
            df["bb_lower"]  = sma - 2 * std
            df["bb_middle"] = sma
            df["bb_pct"]    = (close - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
            # MACD
            df["macd"]        = close.ewm(12).mean() - close.ewm(26).mean()
            df["macd_signal"] = df["macd"].ewm(9).mean()
            df["macd_hist"]   = df["macd"] - df["macd_signal"]
            # ATR
            hl  = df["high"] - df["low"]
            hpc = (df["high"] - close.shift()).abs()
            lpc = (df["low"]  - close.shift()).abs()
            df["atr_14"] = pd.concat([hl, hpc, lpc], axis=1).max(axis=1).rolling(14).mean()
            # Returns
            df["pct_return"] = close.pct_change()
            df["log_return"] = np.log(close / close.shift())
            return df

    def generate(self) -> pd.DataFrame:
        """Override in subclasses. Must set self.df with a 'signal' column."""
        raise NotImplementedError

    def _validate_signals(self):
        """Ensure signal column is clean: only -1, 0, +1."""
        self.df["signal"] = self.df["signal"].fillna(0)
        self.df["signal"] = self.df["signal"].clip(-1, 1).round()

    def get_signals(self) -> pd.DataFrame:
        """Return only rows where a signal was generated (non-zero)."""
        return self.df[self.df["signal"] != 0][["close", "signal", "signal_reason"]]

    def summary(self):
        """Print a quick signal summary."""
        if self.df is None:
            print("Run .generate() first.")
            return
        sigs = self.df[self.df["signal"] != 0]
        buys  = (sigs["signal"] == 1).sum()
        sells = (sigs["signal"] == -1).sum()
        total = len(self.df)
        print(f"\n{'─'*50}")
        print(f"  Strategy  : {self.name}")
        print(f"  Rows      : {total}")
        print(f"  BUY  (+1) : {buys} signals")
        print(f"  SELL (-1) : {sells} signals")
        print(f"  Signal %  : {100*(buys+sells)/total:.1f}% of candles have a signal")
        print(f"{'─'*50}")
        if len(sigs) > 0:
            print("\n  Last 5 signals:")
            print(sigs.tail(5).to_string())


# ══════════════════════════════════════════════════════════════
#  2.  MEAN REVERSION STRATEGY
# ══════════════════════════════════════════════════════════════

class MeanReversionStrategy(SignalGenerator):
    """
    MEAN REVERSION — "What goes down must come back up."

    Core idea:
      Prices tend to revert to their average. When a stock is
      unusually oversold, we buy expecting it to bounce back.
      When unusually overbought, we sell/short expecting a pullback.

    Indicators used:
      • RSI   — measures overbought/oversold momentum
      • Bollinger Bands — measures price deviation from mean

    Signal logic:
      BUY  when: RSI < rsi_low  AND  price < BB lower band
      SELL when: RSI > rsi_high AND  price > BB upper band

    Best for:
      • Sideways/ranging markets
      • Stocks that don't trend strongly
      • Lower frequency (daily bars)

    Parameters:
        rsi_low   : RSI buy threshold (default 35)
        rsi_high  : RSI sell threshold (default 65)
        bb_low    : BB% buy threshold (default 0.15 = near lower band)
        bb_high   : BB% sell threshold (default 0.85 = near upper band)
    """

    def __init__(self, df: pd.DataFrame,
                 rsi_low: float  = 35.0,
                 rsi_high: float = 65.0,
                 bb_low: float   = 0.15,
                 bb_high: float  = 0.85):
        super().__init__(df)
        self.name     = "Mean Reversion (RSI + Bollinger Bands)"
        self.rsi_low  = rsi_low
        self.rsi_high = rsi_high
        self.bb_low   = bb_low
        self.bb_high  = bb_high

    def generate(self) -> pd.DataFrame:
        """
        Compute indicators and generate buy/sell signals.
        Returns full DataFrame with signal column.
        """
        print(f"🔄 Running {self.name}...")
        self.df = self._add_indicators()

        rsi  = self.df["rsi_14"]
        bb   = self.df["bb_pct"]

        # ── Core signal conditions ────────────────────────────

        # BUY: RSI oversold AND price near lower Bollinger Band
        buy_condition = (rsi < self.rsi_low) & (bb < self.bb_low)

        # SELL: RSI overbought AND price near upper Bollinger Band
        sell_condition = (rsi > self.rsi_high) & (bb > self.bb_high)

        # ── Assign signals ────────────────────────────────────
        self.df["signal"] = 0
        self.df.loc[buy_condition,  "signal"] = 1
        self.df.loc[sell_condition, "signal"] = -1

        # ── Reason labels (useful for debugging) ─────────────
        self.df["signal_reason"] = ""
        self.df.loc[buy_condition,  "signal_reason"] = (
            f"RSI<{self.rsi_low} & BB%<{self.bb_low}"
        )
        self.df.loc[sell_condition, "signal_reason"] = (
            f"RSI>{self.rsi_high} & BB%>{self.bb_high}"
        )

        # ── Signal strength: how extreme is the oversold? ─────
        # Useful for position sizing in Phase 4
        self.df["signal_strength"] = 0.0
        self.df.loc[buy_condition,  "signal_strength"] = (
            (self.rsi_low - rsi[buy_condition])  / self.rsi_low
        ).clip(0, 1)
        self.df.loc[sell_condition, "signal_strength"] = (
            (rsi[sell_condition] - self.rsi_high) / (100 - self.rsi_high)
        ).clip(0, 1)

        self._validate_signals()
        self.summary()
        return self.df


# ══════════════════════════════════════════════════════════════
#  3.  MOMENTUM / TREND-FOLLOWING STRATEGY
# ══════════════════════════════════════════════════════════════

class MomentumStrategy(SignalGenerator):
    """
    MOMENTUM — "The trend is your friend."

    Core idea:
      Assets that have been rising tend to keep rising.
      We enter when a trend is confirmed and exit when it reverses.

    Indicators used:
      • EMA crossover  — fast EMA crossing slow EMA = trend change
      • MACD histogram — confirms momentum direction
      • Price vs SMA200 — only trade in direction of long-term trend

    Signal logic:
      BUY  when: fast_ema > slow_ema (crossover up)
                 AND macd_hist > 0
                 AND close > sma_200 (uptrend filter)

      SELL when: fast_ema < slow_ema (crossover down)
                 AND macd_hist < 0

    Best for:
      • Trending markets (bull runs, strong sectors)
      • Crypto (tends to trend more than stocks)
      • Medium frequency (daily / 4h bars)

    Parameters:
        fast_ema  : Fast EMA period (default 9)
        slow_ema  : Slow EMA period (default 21)
        trend_sma : Long-term trend filter SMA (default 200)
    """

    def __init__(self, df: pd.DataFrame,
                 fast_ema: int  = 9,
                 slow_ema: int  = 21,
                 trend_sma: int = 200):
        super().__init__(df)
        self.name      = "Momentum (EMA Crossover + MACD)"
        self.fast_ema  = fast_ema
        self.slow_ema  = slow_ema
        self.trend_sma = trend_sma

    def generate(self) -> pd.DataFrame:
        print(f"🔄 Running {self.name}...")
        self.df = self._add_indicators()

        close = self.df["close"]

        # Recompute EMAs with our custom periods (Phase 1 uses fixed ones)
        fast = close.ewm(span=self.fast_ema, adjust=False).mean()
        slow = close.ewm(span=self.slow_ema, adjust=False).mean()
        self.df["ema_fast"] = fast
        self.df["ema_slow"] = slow

        macd_hist = self.df["macd_hist"]

        # Long-term trend filter (only go long above SMA200)
        above_trend = close > self.df.get(f"sma_{self.trend_sma}", close)

        # ── EMA crossover detection ───────────────────────────
        ema_diff     = fast - slow
        cross_up     = (ema_diff > 0) & (ema_diff.shift(1) <= 0)   # just crossed up
        cross_down   = (ema_diff < 0) & (ema_diff.shift(1) >= 0)   # just crossed down

        # ── Core signal conditions ────────────────────────────
        buy_condition  = cross_up   & (macd_hist > 0) & above_trend
        sell_condition = cross_down & (macd_hist < 0)

        # ── Also catch sustained momentum (not just crossovers) ──
        momentum_buy  = (ema_diff > 0) & (macd_hist > macd_hist.shift(1)) & above_trend
        momentum_sell = (ema_diff < 0) & (macd_hist < macd_hist.shift(1))

        # Crossover signals are stronger; momentum signals fill the gaps
        self.df["signal"] = 0
        self.df.loc[momentum_buy,   "signal"] = 1
        self.df.loc[momentum_sell,  "signal"] = -1
        self.df.loc[buy_condition,  "signal"] = 1    # overwrite with confirmed crossover
        self.df.loc[sell_condition, "signal"] = -1

        # ── Reason labels ─────────────────────────────────────
        self.df["signal_reason"] = ""
        self.df.loc[buy_condition,  "signal_reason"] = "EMA cross UP + MACD confirm"
        self.df.loc[sell_condition, "signal_reason"] = "EMA cross DOWN + MACD confirm"
        self.df.loc[momentum_buy & ~buy_condition,  "signal_reason"] = "Momentum continuation BUY"
        self.df.loc[momentum_sell & ~sell_condition,"signal_reason"] = "Momentum continuation SELL"

        # ── Signal strength based on EMA separation ───────────
        self.df["signal_strength"] = (ema_diff.abs() / close * 100).clip(0, 1)

        self._validate_signals()
        self.summary()
        return self.df


# ══════════════════════════════════════════════════════════════
#  4.  COMBINED STRATEGY (Mean Reversion + Momentum)
# ══════════════════════════════════════════════════════════════

class CombinedStrategy(SignalGenerator):
    """
    COMBINED — Only trade when BOTH strategies agree.

    Core idea:
      Mean reversion and momentum often conflict. When they
      AGREE on a signal direction, confidence is much higher.
      This filters out noise and reduces false positives.

    Logic:
      BUY  only when MeanReversion=BUY  AND Momentum=BUY
      SELL only when MeanReversion=SELL AND Momentum=SELL

    Trade-off:
      Fewer signals, but much higher win rate.
      Best for risk-averse traders or smaller accounts.
    """

    def __init__(self, df: pd.DataFrame):
        super().__init__(df)
        self.name = "Combined (Mean Reversion + Momentum consensus)"

    def generate(self) -> pd.DataFrame:
        print(f"🔄 Running {self.name}...")

        # Run both sub-strategies
        mr  = MeanReversionStrategy(self.raw_df)
        mom = MomentumStrategy(self.raw_df)

        df_mr  = mr.generate()
        df_mom = mom.generate()

        self.df = self._add_indicators()

        # Merge signals
        self.df["signal_mr"]  = df_mr["signal"]
        self.df["signal_mom"] = df_mom["signal"]

        # Only fire when both agree
        self.df["signal"] = 0
        both_buy  = (self.df["signal_mr"] == 1)  & (self.df["signal_mom"] == 1)
        both_sell = (self.df["signal_mr"] == -1) & (self.df["signal_mom"] == -1)

        self.df.loc[both_buy,  "signal"] = 1
        self.df.loc[both_sell, "signal"] = -1

        self.df["signal_reason"] = ""
        self.df.loc[both_buy,  "signal_reason"] = "CONSENSUS BUY  (MR + Mom agree)"
        self.df.loc[both_sell, "signal_reason"] = "CONSENSUS SELL (MR + Mom agree)"

        # Strength = average of both
        self.df["signal_strength"] = (
            df_mr["signal_strength"] + df_mom["signal_strength"]
        ) / 2

        self._validate_signals()
        self.summary()
        return self.df


# ══════════════════════════════════════════════════════════════
#  5.  SIGNAL VISUALIZER  (console output)
# ══════════════════════════════════════════════════════════════

class SignalVisualizer:
    """
    Prints a visual summary of signals to the console.
    (A proper chart dashboard comes in Phase 6.)
    """

    @staticmethod
    def print_signal_table(df: pd.DataFrame, last_n: int = 20):
        """Print last N rows with signal annotations."""
        print(f"\n{'═'*65}")
        print(f"  {'DATE':<20} {'CLOSE':>10} {'RSI':>6} {'SIGNAL':>8}  REASON")
        print(f"{'─'*65}")

        tail = df.tail(last_n)
        for idx, row in tail.iterrows():
            date   = str(idx)[:10]
            close  = f"${row['close']:.2f}"
            rsi    = f"{row.get('rsi_14', 0):.1f}" if 'rsi_14' in row else "  —"
            sig    = row.get("signal", 0)
            reason = row.get("signal_reason", "")

            if sig == 1:
                sig_str = "  🟢 BUY "
            elif sig == -1:
                sig_str = "  🔴 SELL"
            else:
                sig_str = "  ·  —  "

            print(f"  {date:<20} {close:>10} {rsi:>6} {sig_str}  {reason}")

        print(f"{'═'*65}\n")

    @staticmethod
    def print_stats(df: pd.DataFrame, strategy_name: str):
        """Print key signal statistics."""
        signals = df[df["signal"] != 0]
        total   = len(df)
        n_buy   = (signals["signal"] == 1).sum()
        n_sell  = (signals["signal"] == -1).sum()

        # Signal clustering check
        consecutive = (df["signal"] != df["signal"].shift()).astype(int)

        print(f"\n{'╔'+'═'*48+'╗'}")
        print(f"  SIGNAL STATS — {strategy_name[:30]}")
        print(f"{'╠'+'═'*48+'╣'}")
        print(f"  Total candles       : {total:>6}")
        print(f"  BUY  signals        : {n_buy:>6}  ({100*n_buy/total:.1f}%)")
        print(f"  SELL signals        : {n_sell:>6}  ({100*n_sell/total:.1f}%)")
        print(f"  Signal changes      : {consecutive.sum():>6}")
        if len(signals) > 0:
            avg_strength = signals.get("signal_strength", pd.Series([0])).mean()
            print(f"  Avg signal strength : {avg_strength:>6.3f}")
        print(f"{'╚'+'═'*48+'╝'}")


# ══════════════════════════════════════════════════════════════
#  6.  MAIN — Demo
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  QUANT TRADING SYSTEM — Phase 2: Strategy & Signals")
    print("=" * 60)

    # ── Load or fetch data ────────────────────────────────────
    if PIPELINE_AVAILABLE:
        try:
            loader = DataLoader()
            df = loader.load("AAPL", "1d")
            print("✅ Loaded saved AAPL data from Phase 1")
        except Exception:
            try:
                print("📥 Fetching fresh AAPL data...")
                fetcher = StockDataFetcher()
                df = fetcher.fetch("AAPL", interval="1d", period="2y")
                print("✅ Fresh market data fetched")
            except Exception:
                print("🔧 Falling back to synthetic sample data for demo")
                df = generate_sample_data(500)
    else:
        print("🔧 Using synthetic sample data (install yfinance for real data)")
        df = generate_sample_data(500)

    viz = SignalVisualizer()

    # ── Strategy 1: Mean Reversion ────────────────────────────
    print("\n" + "━"*60)
    print("  STRATEGY 1: MEAN REVERSION")
    print("━"*60)
    mr_strategy = MeanReversionStrategy(df, rsi_low=35, rsi_high=65)
    df_mr = mr_strategy.generate()
    viz.print_stats(df_mr, mr_strategy.name)
    viz.print_signal_table(df_mr, last_n=15)

    # ── Strategy 2: Momentum ──────────────────────────────────
    print("\n" + "━"*60)
    print("  STRATEGY 2: MOMENTUM")
    print("━"*60)
    mom_strategy = MomentumStrategy(df, fast_ema=9, slow_ema=21)
    df_mom = mom_strategy.generate()
    viz.print_stats(df_mom, mom_strategy.name)
    viz.print_signal_table(df_mom, last_n=15)

    # ── Strategy 3: Combined ──────────────────────────────────
    print("\n" + "━"*60)
    print("  STRATEGY 3: COMBINED (consensus)")
    print("━"*60)
    combined = CombinedStrategy(df)
    df_combined = combined.generate()
    viz.print_stats(df_combined, combined.name)
    viz.print_signal_table(df_combined, last_n=15)

    print("\n✅ Phase 2 Complete! Signal generation is ready.")
    print("   Next → Phase 3: Backtester (simulate strategies on history)")

    return df_mr, df_mom, df_combined


if __name__ == "__main__":
    df_mr, df_mom, df_combined = main()
