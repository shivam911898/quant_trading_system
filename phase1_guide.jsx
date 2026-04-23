import { useState } from "react";

const phases = [
  { id: 1, label: "Data Pipeline", active: true },
  { id: 2, label: "Strategy & Signals", active: false },
  { id: 3, label: "Backtester", active: false },
  { id: 4, label: "Risk Management", active: false },
  { id: 5, label: "Live Trading", active: false },
  { id: 6, label: "Dashboard", active: false },
];

const classes = [
  {
    name: "StockDataFetcher",
    color: "#00d4ff",
    icon: "📈",
    purpose: "Fetches US stock OHLCV data via yfinance",
    methods: [
      { name: "fetch(symbol, interval, period)", desc: 'Get data for one stock. e.g. fetch("AAPL", "1d", "2y")' },
      { name: "fetch_multiple(symbols)", desc: 'Batch fetch a list e.g. ["AAPL","MSFT","TSLA"]' },
    ],
    install: "pip install yfinance",
    example: 'fetcher = StockDataFetcher()\ndf = fetcher.fetch("AAPL", interval="1d", period="1y")',
  },
  {
    name: "CryptoDataFetcher",
    color: "#f7931a",
    icon: "₿",
    purpose: "Fetches crypto OHLCV data via ccxt (100+ exchanges)",
    methods: [
      { name: "fetch(symbol, interval, days)", desc: 'Get crypto data. e.g. fetch("BTC/USDT", "1h", 90)' },
    ],
    install: "pip install ccxt",
    example: 'fetcher = CryptoDataFetcher(exchange="binance")\ndf = fetcher.fetch("BTC/USDT", "1h", days=90)',
  },
  {
    name: "TechnicalIndicators",
    color: "#a78bfa",
    icon: "📊",
    purpose: "Adds indicators to your DataFrame — fuel for signals",
    methods: [
      { name: "add_sma(window)", desc: "Simple Moving Average — smooths price noise" },
      { name: "add_ema(window)", desc: "Exponential MA — weights recent prices more" },
      { name: "add_macd()", desc: "Momentum via two EMAs — crossover = signal" },
      { name: "add_rsi(window)", desc: "RSI 0–100. >70 overbought, <30 oversold" },
      { name: "add_bollinger_bands()", desc: "Volatility envelope around price" },
      { name: "add_atr(window)", desc: "Average True Range — used in position sizing" },
      { name: "add_vwap()", desc: "Volume Weighted Avg Price — institutional benchmark" },
      { name: "add_obv()", desc: "On Balance Volume — buying/selling pressure" },
      { name: "add_all()", desc: "⚡ Add ALL indicators at once" },
    ],
    install: "built-in (uses numpy + pandas)",
    example: 'ti = TechnicalIndicators(df)\ndf = ti.add_all()   # adds 20+ columns',
  },
  {
    name: "DataLoader",
    color: "#34d399",
    icon: "💾",
    purpose: "Load saved CSVs — avoids re-fetching every run",
    methods: [
      { name: "load(symbol, interval)", desc: 'Load saved data e.g. load("AAPL","1d")' },
      { name: "list_available()", desc: "Print all saved datasets in /data/" },
    ],
    install: "built-in",
    example: 'loader = DataLoader()\ndf = loader.load("AAPL", "1d")',
  },
];

const pipeline = [
  { step: "1", label: "Raw API", desc: "yfinance / ccxt", color: "#00d4ff" },
  { step: "2", label: "Clean & Validate", desc: "drop NaN, bad volume", color: "#60a5fa" },
  { step: "3", label: "Indicators", desc: "SMA, RSI, MACD...", color: "#a78bfa" },
  { step: "4", label: "Save CSV", desc: "/data/ folder", color: "#34d399" },
  { step: "5", label: "Load & Use", desc: "feed into strategy", color: "#f59e0b" },
];

const intervals = [
  { label: "1m", use: "HFT / scalping" },
  { label: "5m", use: "Scalping" },
  { label: "15m", use: "Day trading" },
  { label: "1h", use: "Swing trading" },
  { label: "4h", use: "Swing trading" },
  { label: "1d", use: "Position trading ← START HERE" },
  { label: "1wk", use: "Long-term" },
];

export default function App() {
  const [activeClass, setActiveClass] = useState(0);
  const cls = classes[activeClass];

  return (
    <div style={{
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      background: "#0a0e1a",
      minHeight: "100vh",
      color: "#e2e8f0",
      padding: "24px",
    }}>
      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
          <div style={{
            background: "linear-gradient(135deg, #00d4ff, #a78bfa)",
            borderRadius: 8, padding: "6px 14px",
            fontSize: 11, fontWeight: 700, letterSpacing: 2, color: "#0a0e1a"
          }}>QUANT SYSTEM</div>
          <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1 }}>v1.0 — PHASE 1 OF 6</div>
        </div>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800, letterSpacing: -0.5 }}>
          Data Pipeline <span style={{ color: "#00d4ff" }}>✦</span>
        </h1>
        <p style={{ margin: "4px 0 0", color: "#64748b", fontSize: 13 }}>
          The foundation of every quant system — getting clean, indicator-rich data
        </p>
      </div>

      {/* Phase roadmap */}
      <div style={{
        display: "flex", gap: 4, marginBottom: 28, overflowX: "auto", paddingBottom: 4
      }}>
        {phases.map((p, i) => (
          <div key={p.id} style={{
            display: "flex", alignItems: "center", gap: 4, flexShrink: 0
          }}>
            <div style={{
              padding: "6px 12px", borderRadius: 6, fontSize: 11, fontWeight: 600,
              background: p.active ? "linear-gradient(135deg,#00d4ff22,#a78bfa22)" : "#111827",
              border: p.active ? "1px solid #00d4ff55" : "1px solid #1f2937",
              color: p.active ? "#00d4ff" : "#4b5563",
              whiteSpace: "nowrap"
            }}>
              {p.id}. {p.label}
            </div>
            {i < phases.length - 1 && (
              <div style={{ color: "#1f2937", fontSize: 14 }}>→</div>
            )}
          </div>
        ))}
      </div>

      {/* Data flow pipeline */}
      <div style={{
        background: "#0f1623", border: "1px solid #1f2937", borderRadius: 12,
        padding: "16px 20px", marginBottom: 24
      }}>
        <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 12 }}>
          DATA FLOW
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {pipeline.map((p, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{
                background: p.color + "15", border: `1px solid ${p.color}40`,
                borderRadius: 8, padding: "8px 14px", textAlign: "center"
              }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: p.color }}>{p.label}</div>
                <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>{p.desc}</div>
              </div>
              {i < pipeline.length - 1 && (
                <div style={{ color: "#334155", fontSize: 18 }}>→</div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 24 }}>
        {/* Class selector */}
        <div>
          <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 10 }}>
            CLASSES
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {classes.map((c, i) => (
              <button key={i} onClick={() => setActiveClass(i)} style={{
                background: activeClass === i ? c.color + "15" : "#0f1623",
                border: `1px solid ${activeClass === i ? c.color + "60" : "#1f2937"}`,
                borderRadius: 8, padding: "10px 14px", cursor: "pointer",
                display: "flex", alignItems: "center", gap: 10, textAlign: "left",
                transition: "all 0.15s"
              }}>
                <span style={{ fontSize: 18 }}>{c.icon}</span>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: activeClass === i ? c.color : "#e2e8f0" }}>
                    {c.name}
                  </div>
                  <div style={{ fontSize: 11, color: "#64748b", marginTop: 1 }}>{c.purpose}</div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Class detail */}
        <div>
          <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 10 }}>
            DETAIL — <span style={{ color: cls.color }}>{cls.name}</span>
          </div>
          <div style={{
            background: "#0f1623", border: `1px solid ${cls.color}30`,
            borderRadius: 10, padding: 16, height: "calc(100% - 26px)"
          }}>
            {/* Install */}
            <div style={{
              background: "#1a2235", borderRadius: 6, padding: "6px 10px",
              fontSize: 11, color: "#94a3b8", marginBottom: 14, fontFamily: "monospace"
            }}>
              $ {cls.install}
            </div>

            {/* Methods */}
            <div style={{ marginBottom: 14 }}>
              {cls.methods.map((m, i) => (
                <div key={i} style={{
                  borderLeft: `2px solid ${cls.color}50`, paddingLeft: 10, marginBottom: 10
                }}>
                  <div style={{ fontSize: 12, color: cls.color, fontWeight: 600 }}>
                    .{m.name}
                  </div>
                  <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>{m.desc}</div>
                </div>
              ))}
            </div>

            {/* Example */}
            <div style={{
              background: "#070d18", borderRadius: 6, padding: "10px 12px",
              fontSize: 11, color: "#a5f3fc", lineHeight: 1.7,
              fontFamily: "monospace", whiteSpace: "pre"
            }}>
              {cls.example}
            </div>
          </div>
        </div>
      </div>

      {/* Intervals guide */}
      <div style={{
        background: "#0f1623", border: "1px solid #1f2937", borderRadius: 12, padding: "16px 20px"
      }}>
        <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 12 }}>
          INTERVALS GUIDE — WHICH TO USE?
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {intervals.map((iv, i) => (
            <div key={i} style={{
              background: iv.use.includes("START") ? "#00d4ff12" : "#111827",
              border: iv.use.includes("START") ? "1px solid #00d4ff50" : "1px solid #1f2937",
              borderRadius: 8, padding: "8px 14px"
            }}>
              <div style={{
                fontSize: 14, fontWeight: 700,
                color: iv.use.includes("START") ? "#00d4ff" : "#e2e8f0"
              }}>{iv.label}</div>
              <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>{iv.use}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div style={{
        marginTop: 20, fontSize: 11, color: "#334155", textAlign: "center"
      }}>
        Phase 1 complete → Next: Phase 2 — Strategy & Signal Generation
      </div>
    </div>
  );
}
