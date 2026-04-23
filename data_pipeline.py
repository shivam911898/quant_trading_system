"""
╔══════════════════════════════════════════════════════════════╗
║         QUANT TRADING SYSTEM — PHASE 1: DATA PIPELINE       ║
╚══════════════════════════════════════════════════════════════╝

This module handles everything data-related:
  1. Fetching OHLCV data (stocks & crypto)
  2. Cleaning & validating data
  3. Computing technical indicators
  4. Saving/loading from local storage (CSV)

Author: Your Trading System
"""

import os
import time
import warnings
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

# ── Optional imports (install if missing) ──────────────────────
try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False
    print("⚠️  yfinance not installed. Run: pip install yfinance")

try:
    import ccxt
    CCXT_AVAILABLE = True
except ImportError:
    CCXT_AVAILABLE = False
    print("⚠️  ccxt not installed. Run: pip install ccxt")

# ── Configuration ──────────────────────────────────────────────
DATA_DIR = Path("data")           # local folder to store CSVs
DATA_DIR.mkdir(exist_ok=True)

STOCK_INTERVALS  = ["1m", "5m", "15m", "30m", "1h", "1d", "1wk"]
CRYPTO_INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"]


# ══════════════════════════════════════════════════════════════
#  1.  STOCK DATA FETCHER  (via yfinance)
# ══════════════════════════════════════════════════════════════

class StockDataFetcher:
    """
    Fetches historical OHLCV data for US stocks using yfinance.

    Usage:
        fetcher = StockDataFetcher()
        df = fetcher.fetch("AAPL", interval="1d", period="1y")
    """

    def __init__(self):
        if not YF_AVAILABLE:
            raise ImportError("Install yfinance: pip install yfinance")

    def fetch(self, symbol: str, interval: str = "1d",
              period: str = "1y", save: bool = True) -> pd.DataFrame:
        """
        Fetch OHLCV data for a stock symbol.

        Args:
            symbol   : Ticker symbol e.g. "AAPL", "TSLA"
            interval : Time interval e.g. "1d", "1h", "15m"
            period   : How far back e.g. "1y", "6mo", "60d"
            save     : Save to CSV for offline use

        Returns:
            Clean pandas DataFrame with OHLCV columns
        """
        print(f"📥 Fetching {symbol} | interval={interval} | period={period}")

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)

        if df.empty:
            raise ValueError(f"No data returned for {symbol}")

        df = self._clean(df, symbol)

        if save:
            self._save(df, symbol, interval)

        print(f"✅ Got {len(df)} rows for {symbol}")
        return df

    def fetch_multiple(self, symbols: list, interval: str = "1d",
                       period: str = "1y") -> dict:
        """
        Fetch data for multiple symbols. Returns a dict of DataFrames.

        Args:
            symbols : List of tickers e.g. ["AAPL", "MSFT", "GOOG"]

        Returns:
            { "AAPL": df, "MSFT": df, ... }
        """
        results = {}
        for sym in symbols:
            try:
                results[sym] = self.fetch(sym, interval=interval, period=period)
                time.sleep(0.3)   # be polite to the API
            except Exception as e:
                print(f"❌ Failed {sym}: {e}")
        return results

    def _clean(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """Standardise and clean raw yfinance output."""
        df = df.copy()

        # Rename columns to lowercase standard
        df.columns = [c.lower() for c in df.columns]
        df = df.rename(columns={"stock splits": "splits"})

        # Keep only OHLCV
        keep = ["open", "high", "low", "close", "volume"]
        df = df[[c for c in keep if c in df.columns]]

        # Make index timezone-naive
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        df.index.name = "datetime"
        df["symbol"] = symbol

        # Drop rows with NaN prices
        df = df.dropna(subset=["open", "high", "low", "close"])

        # Remove zero-volume candles (market closed / bad data)
        df = df[df["volume"] > 0]

        return df

    def _save(self, df: pd.DataFrame, symbol: str, interval: str):
        path = DATA_DIR / f"{symbol}_{interval}.csv"
        df.to_csv(path)
        print(f"💾 Saved → {path}")


# ══════════════════════════════════════════════════════════════
#  2.  CRYPTO DATA FETCHER  (via ccxt)
# ══════════════════════════════════════════════════════════════

class CryptoDataFetcher:
    """
    Fetches historical OHLCV data for crypto pairs using ccxt.
    Supports Binance, Coinbase, Kraken, and more.

    Usage:
        fetcher = CryptoDataFetcher(exchange="binance")
        df = fetcher.fetch("BTC/USDT", interval="1h", days=90)
    """

    TIMEFRAME_MAP = {
        "1m": 60_000,
        "5m": 300_000,
        "15m": 900_000,
        "1h": 3_600_000,
        "4h": 14_400_000,
        "1d": 86_400_000,
    }

    def __init__(self, exchange: str = "binance"):
        if not CCXT_AVAILABLE:
            raise ImportError("Install ccxt: pip install ccxt")

        exchange_class = getattr(ccxt, exchange)
        self.exchange = exchange_class({
            "enableRateLimit": True,  # auto rate-limit
        })
        print(f"🔗 Connected to {exchange}")

    def fetch(self, symbol: str, interval: str = "1h",
              days: int = 90, save: bool = True) -> pd.DataFrame:
        """
        Fetch OHLCV data for a crypto pair.

        Args:
            symbol   : Pair e.g. "BTC/USDT", "ETH/USDT"
            interval : Timeframe e.g. "1h", "15m", "1d"
            days     : Number of days of history to fetch
            save     : Save to CSV

        Returns:
            Clean pandas DataFrame with OHLCV columns
        """
        print(f"📥 Fetching {symbol} | interval={interval} | days={days}")

        since_ms = self.exchange.parse8601(
            (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        all_candles = []
        while True:
            candles = self.exchange.fetch_ohlcv(symbol, interval, since=since_ms, limit=1000)
            if not candles:
                break
            all_candles.extend(candles)
            since_ms = candles[-1][0] + self.TIMEFRAME_MAP.get(interval, 3_600_000)
            if since_ms >= self.exchange.milliseconds():
                break
            time.sleep(self.exchange.rateLimit / 1000)

        df = self._to_dataframe(all_candles, symbol)

        if save:
            safe_symbol = symbol.replace("/", "-")
            path = DATA_DIR / f"{safe_symbol}_{interval}.csv"
            df.to_csv(path)
            print(f"💾 Saved → {path}")

        print(f"✅ Got {len(df)} rows for {symbol}")
        return df

    def _to_dataframe(self, candles: list, symbol: str) -> pd.DataFrame:
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("datetime").drop(columns=["timestamp"])
        df["symbol"] = symbol
        df = df.dropna()
        df = df[df["volume"] > 0]
        return df


# ══════════════════════════════════════════════════════════════
#  3.  TECHNICAL INDICATORS
# ══════════════════════════════════════════════════════════════

class TechnicalIndicators:
    """
    Adds common technical indicators to an OHLCV DataFrame.
    All methods return the DataFrame with new columns added.

    These indicators are the raw material for your trading signals.

    Usage:
        ti = TechnicalIndicators(df)
        df = ti.add_all()          # add everything
        df = ti.add_sma(20)        # just SMA-20
    """

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()

    # ── Trend Indicators ──────────────────────────────────────

    def add_sma(self, window: int = 20) -> "TechnicalIndicators":
        """Simple Moving Average — smooths out price noise."""
        self.df[f"sma_{window}"] = self.df["close"].rolling(window).mean()
        return self

    def add_ema(self, window: int = 20) -> "TechnicalIndicators":
        """Exponential Moving Average — weights recent prices more."""
        self.df[f"ema_{window}"] = self.df["close"].ewm(span=window, adjust=False).mean()
        return self

    def add_macd(self, fast: int = 12, slow: int = 26,
                 signal: int = 9) -> "TechnicalIndicators":
        """
        MACD — momentum indicator using two EMAs.
        Crossover of MACD line and signal line = trade signal.
        """
        ema_fast = self.df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = self.df["close"].ewm(span=slow, adjust=False).mean()
        self.df["macd"]        = ema_fast - ema_slow
        self.df["macd_signal"] = self.df["macd"].ewm(span=signal, adjust=False).mean()
        self.df["macd_hist"]   = self.df["macd"] - self.df["macd_signal"]
        return self

    # ── Momentum Indicators ───────────────────────────────────

    def add_rsi(self, window: int = 14) -> "TechnicalIndicators":
        """
        RSI — Relative Strength Index (0–100).
        > 70 = overbought, < 30 = oversold.
        """
        delta = self.df["close"].diff()
        gain  = delta.clip(lower=0).rolling(window).mean()
        loss  = (-delta.clip(upper=0)).rolling(window).mean()
        rs    = gain / loss.replace(0, np.nan)
        self.df[f"rsi_{window}"] = 100 - (100 / (1 + rs))
        return self

    def add_stochastic(self, k_window: int = 14,
                       d_window: int = 3) -> "TechnicalIndicators":
        """
        Stochastic Oscillator — compares close to high-low range.
        %K and %D lines; crossovers are signals.
        """
        low_min  = self.df["low"].rolling(k_window).min()
        high_max = self.df["high"].rolling(k_window).max()
        self.df["stoch_k"] = 100 * (self.df["close"] - low_min) / (high_max - low_min)
        self.df["stoch_d"] = self.df["stoch_k"].rolling(d_window).mean()
        return self

    # ── Volatility Indicators ─────────────────────────────────

    def add_bollinger_bands(self, window: int = 20,
                            num_std: float = 2.0) -> "TechnicalIndicators":
        """
        Bollinger Bands — price envelope based on volatility.
        Price touching upper band = overbought; lower = oversold.
        """
        sma = self.df["close"].rolling(window).mean()
        std = self.df["close"].rolling(window).std()
        self.df["bb_upper"]  = sma + num_std * std
        self.df["bb_middle"] = sma
        self.df["bb_lower"]  = sma - num_std * std
        self.df["bb_width"]  = (self.df["bb_upper"] - self.df["bb_lower"]) / sma
        self.df["bb_pct"]    = (self.df["close"] - self.df["bb_lower"]) / \
                               (self.df["bb_upper"] - self.df["bb_lower"])
        return self

    def add_atr(self, window: int = 14) -> "TechnicalIndicators":
        """
        ATR — Average True Range.
        Measures market volatility. Used heavily in position sizing.
        """
        hl  = self.df["high"] - self.df["low"]
        hpc = (self.df["high"] - self.df["close"].shift()).abs()
        lpc = (self.df["low"]  - self.df["close"].shift()).abs()
        tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        self.df[f"atr_{window}"] = tr.rolling(window).mean()
        return self

    # ── Volume Indicators ─────────────────────────────────────

    def add_vwap(self) -> "TechnicalIndicators":
        """
        VWAP — Volume Weighted Average Price.
        Institutional benchmark; price above VWAP = bullish.
        """
        tp = (self.df["high"] + self.df["low"] + self.df["close"]) / 3
        self.df["vwap"] = (tp * self.df["volume"]).cumsum() / self.df["volume"].cumsum()
        return self

    def add_obv(self) -> "TechnicalIndicators":
        """
        OBV — On Balance Volume.
        Tracks buying/selling pressure via volume direction.
        """
        direction = np.sign(self.df["close"].diff())
        self.df["obv"] = (self.df["volume"] * direction).fillna(0).cumsum()
        return self

    # ── Utility ───────────────────────────────────────────────

    def add_returns(self) -> "TechnicalIndicators":
        """Log returns and percentage returns — needed for backtesting."""
        self.df["pct_return"]  = self.df["close"].pct_change()
        self.df["log_return"]  = np.log(self.df["close"] / self.df["close"].shift())
        return self

    def add_all(self) -> pd.DataFrame:
        """Add all indicators at once. Returns the final DataFrame."""
        return (self
                .add_sma(20).add_sma(50).add_sma(200)
                .add_ema(12).add_ema(26)
                .add_macd()
                .add_rsi(14)
                .add_stochastic()
                .add_bollinger_bands()
                .add_atr(14)
                .add_vwap()
                .add_obv()
                .add_returns()
                ).df

    def get(self) -> pd.DataFrame:
        """Return current DataFrame."""
        return self.df


# ══════════════════════════════════════════════════════════════
#  4.  DATA LOADER  (load saved CSVs)
# ══════════════════════════════════════════════════════════════

class DataLoader:
    """
    Loads previously saved data from CSV files.
    Use this to avoid re-fetching data every time you run.

    Usage:
        loader = DataLoader()
        df = loader.load("AAPL", "1d")
        loader.list_available()
    """

    def load(self, symbol: str, interval: str) -> pd.DataFrame:
        """Load a saved CSV file for a symbol/interval pair."""
        safe = symbol.replace("/", "-")
        path = DATA_DIR / f"{safe}_{interval}.csv"
        if not path.exists():
            raise FileNotFoundError(f"No saved data at {path}. Fetch it first.")
        df = pd.read_csv(path, index_col="datetime", parse_dates=True)
        print(f"📂 Loaded {len(df)} rows from {path}")
        return df

    def list_available(self):
        """Print all locally saved datasets."""
        files = list(DATA_DIR.glob("*.csv"))
        if not files:
            print("No saved data found. Run a fetcher first.")
            return
        print(f"\n📁 Available datasets in '{DATA_DIR}/':")
        for f in sorted(files):
            df = pd.read_csv(f, nrows=1)
            size = f.stat().st_size // 1024
            print(f"   {f.name:<35} {size} KB")


# ══════════════════════════════════════════════════════════════
#  5.  MAIN — Demo / Quick Test
# ══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  QUANT TRADING SYSTEM — Phase 1: Data Pipeline")
    print("=" * 60)

    # ── Fetch stock data ──────────────────────────────────────
    if YF_AVAILABLE:
        stock_fetcher = StockDataFetcher()

        # Single stock
        df_aapl = stock_fetcher.fetch("AAPL", interval="1d", period="2y")

        # Multiple stocks (for portfolio strategies)
        portfolio = ["AAPL", "MSFT", "GOOGL", "TSLA", "SPY"]
        stock_data = stock_fetcher.fetch_multiple(portfolio, interval="1d", period="1y")

    # ── Fetch crypto data ─────────────────────────────────────
    if CCXT_AVAILABLE:
        crypto_fetcher = CryptoDataFetcher(exchange="binance")
        df_btc = crypto_fetcher.fetch("BTC/USDT", interval="1h", days=90)

    # ── Add technical indicators ──────────────────────────────
    if YF_AVAILABLE:
        print("\n📊 Adding technical indicators to AAPL...")
        ti = TechnicalIndicators(df_aapl)
        df_with_indicators = ti.add_all()

        print(f"\n✅ DataFrame shape: {df_with_indicators.shape}")
        print(f"\n📋 Columns available:")
        for col in df_with_indicators.columns:
            print(f"   {col}")

        print(f"\n🔍 Last 3 rows:")
        print(df_with_indicators.tail(3).to_string())

    # ── List saved data ───────────────────────────────────────
    loader = DataLoader()
    loader.list_available()

    print("\n✅ Phase 1 Complete! Data pipeline is ready.")
    print("   Next → Phase 2: Strategy & Signal Generation")


if __name__ == "__main__":
    main()
