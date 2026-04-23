import { useState } from "react";

const strategies = [
  {
    id: "mr",
    name: "Mean Reversion",
    tagline: "Buy the dip. Sell the rip.",
    color: "#22d3ee",
    accent: "#0891b2",
    icon: "↩",
    idea: "Prices always return to their average. When something is abnormally low, it bounces back. When abnormally high, it drops.",
    bestFor: ["Sideways markets", "Range-bound stocks", "Lower volatility assets", "Daily bars"],
    worstFor: ["Strong trending markets", "Crypto bull runs"],
    indicators: [
      { name: "RSI < 35", role: "BUY trigger", desc: "Momentum is oversold — exhausted sellers" },
      { name: "BB% < 0.15", role: "BUY confirm", desc: "Price near lower Bollinger Band — statistically cheap" },
      { name: "RSI > 65", role: "SELL trigger", desc: "Momentum is overbought — exhausted buyers" },
      { name: "BB% > 0.85", role: "SELL confirm", desc: "Price near upper Bollinger Band — statistically expensive" },
    ],
    logic: [
      { label: "BUY  (+1)", cond: "RSI < 35  AND  BB% < 0.15", color: "#22d3ee" },
      { label: "HOLD  (0)", cond: "Neither condition met", color: "#475569" },
      { label: "SELL (-1)", cond: "RSI > 65  AND  BB% > 0.85", color: "#f87171" },
    ],
    params: [
      { name: "rsi_low", default: "35", desc: "Lower RSI threshold (buy zone)" },
      { name: "rsi_high", default: "65", desc: "Upper RSI threshold (sell zone)" },
      { name: "bb_low", default: "0.15", desc: "BB% buy threshold (near lower band)" },
      { name: "bb_high", default: "0.85", desc: "BB% sell threshold (near upper band)" },
    ],
    code: `mr = MeanReversionStrategy(df,\n    rsi_low=35,\n    rsi_high=65\n)\ndf_signals = mr.generate()`,
  },
  {
    id: "mom",
    name: "Momentum",
    tagline: "The trend is your friend.",
    color: "#a78bfa",
    accent: "#7c3aed",
    icon: "→",
    idea: "Assets that move in one direction tend to keep moving that way. Ride the wave in, ride it out.",
    bestFor: ["Trending markets", "Crypto", "High-momentum growth stocks", "4h / Daily bars"],
    worstFor: ["Choppy / sideways markets", "Low-volume assets"],
    indicators: [
      { name: "EMA(9) > EMA(21)", role: "BUY trigger", desc: "Fast EMA crosses above slow — uptrend starting" },
      { name: "MACD Hist > 0", role: "BUY confirm", desc: "Positive momentum behind the move" },
      { name: "Close > SMA(200)", role: "BUY filter", desc: "Only buy in a long-term uptrend" },
      { name: "EMA(9) < EMA(21)", role: "SELL trigger", desc: "Fast EMA crosses below slow — downtrend starting" },
    ],
    logic: [
      { label: "BUY  (+1)", cond: "EMA cross UP + MACD > 0 + above SMA200", color: "#a78bfa" },
      { label: "HOLD  (0)", cond: "No crossover detected", color: "#475569" },
      { label: "SELL (-1)", cond: "EMA cross DOWN + MACD < 0", color: "#f87171" },
    ],
    params: [
      { name: "fast_ema", default: "9", desc: "Fast EMA period" },
      { name: "slow_ema", default: "21", desc: "Slow EMA period" },
      { name: "trend_sma", default: "200", desc: "Long-term trend filter" },
    ],
    code: `mom = MomentumStrategy(df,\n    fast_ema=9,\n    slow_ema=21\n)\ndf_signals = mom.generate()`,
  },
  {
    id: "combined",
    name: "Combined",
    tagline: "Only fire when both agree.",
    color: "#34d399",
    accent: "#059669",
    icon: "⊕",
    idea: "Mean reversion and momentum often conflict. Their overlap is rare but high-confidence — fewer signals, much better accuracy.",
    bestFor: ["Conservative traders", "Smaller accounts", "When you want quality > quantity"],
    worstFor: ["Traders wanting high signal frequency", "Scalping"],
    indicators: [
      { name: "MR signal = +1", role: "Required", desc: "Mean Reversion says oversold BUY" },
      { name: "Mom signal = +1", role: "Required", desc: "Momentum confirms upward trend" },
      { name: "MR signal = -1", role: "Required", desc: "Mean Reversion says overbought SELL" },
      { name: "Mom signal = -1", role: "Required", desc: "Momentum confirms downward trend" },
    ],
    logic: [
      { label: "BUY  (+1)", cond: "MR = BUY  AND  Momentum = BUY", color: "#34d399" },
      { label: "HOLD  (0)", cond: "Strategies disagree", color: "#475569" },
      { label: "SELL (-1)", cond: "MR = SELL AND  Momentum = SELL", color: "#f87171" },
    ],
    params: [
      { name: "No params", default: "—", desc: "Uses both sub-strategy defaults" },
    ],
    code: `combined = CombinedStrategy(df)\ndf_signals = combined.generate()\n\n# Fewer signals, higher confidence`,
  },
];

const signalFlow = [
  { label: "OHLCV Data", sub: "from Phase 1", col: "#64748b" },
  { label: "Indicators", sub: "RSI, EMA, MACD, BB", col: "#60a5fa" },
  { label: "Conditions", sub: "threshold checks", col: "#a78bfa" },
  { label: "Signal", sub: "+1 / 0 / -1", col: "#34d399" },
  { label: "Strength", sub: "0.0 → 1.0", col: "#f59e0b" },
];

const rsiZones = [
  { range: "70–100", label: "Overbought", action: "SELL zone", col: "#f87171", pct: 30 },
  { range: "40–70", label: "Neutral", action: "Hold", col: "#475569", pct: 30 },
  { range: "30–40", label: "Borderline", action: "Watch", col: "#fbbf24", pct: 10 },
  { range: "0–30", label: "Oversold", action: "BUY zone", col: "#22d3ee", pct: 30 },
];

export default function App() {
  const [active, setActive] = useState(0);
  const s = strategies[active];

  return (
    <div style={{
      fontFamily: "'JetBrains Mono', monospace",
      background: "#080c14",
      minHeight: "100vh",
      color: "#e2e8f0",
      padding: "24px",
    }}>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 8 }}>
          <span style={{
            background: "#0f1623", border: "1px solid #1e293b",
            borderRadius: 6, padding: "4px 10px", fontSize: 10,
            color: "#64748b", letterSpacing: 2
          }}>PHASE 1 ✓</span>
          <span style={{ color: "#1e293b" }}>→</span>
          <span style={{
            background: `linear-gradient(135deg, ${s.color}22, ${s.accent}22)`,
            border: `1px solid ${s.color}55`,
            borderRadius: 6, padding: "4px 10px", fontSize: 10,
            color: s.color, letterSpacing: 2, fontWeight: 700
          }}>PHASE 2 — ACTIVE</span>
          <span style={{ color: "#1e293b" }}>→</span>
          {["PHASE 3","PHASE 4","PHASE 5","PHASE 6"].map(p => (
            <span key={p} style={{
              background: "#0f1623", border: "1px solid #1e293b",
              borderRadius: 6, padding: "4px 10px", fontSize: 10, color: "#1e293b", letterSpacing: 2
            }}>{p}</span>
          ))}
        </div>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 900, letterSpacing: -1 }}>
          Strategy <span style={{ color: s.color }}>&</span> Signal Generation
        </h1>
        <p style={{ margin: "4px 0 0", color: "#475569", fontSize: 12 }}>
          The brain of the system — translating data into actionable trade signals
        </p>
      </div>

      {/* Signal flow */}
      <div style={{
        background: "#0b101c", border: "1px solid #1e293b",
        borderRadius: 12, padding: "14px 20px", marginBottom: 20
      }}>
        <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 10 }}>SIGNAL PIPELINE</div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {signalFlow.map((f, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{
                background: f.col + "15", border: `1px solid ${f.col}35`,
                borderRadius: 8, padding: "7px 14px", textAlign: "center"
              }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: f.col }}>{f.label}</div>
                <div style={{ fontSize: 10, color: "#475569", marginTop: 1 }}>{f.sub}</div>
              </div>
              {i < signalFlow.length - 1 && <div style={{ color: "#1e293b", fontSize: 16 }}>→</div>}
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 16 }}>
        {/* Strategy selector */}
        <div>
          <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 10 }}>STRATEGIES</div>
          {strategies.map((st, i) => (
            <button key={i} onClick={() => setActive(i)} style={{
              width: "100%", marginBottom: 8,
              background: active === i ? st.color + "12" : "#0b101c",
              border: `1px solid ${active === i ? st.color + "50" : "#1e293b"}`,
              borderRadius: 10, padding: "12px 14px", cursor: "pointer",
              textAlign: "left", transition: "all 0.15s"
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{
                  fontSize: 20, color: st.color,
                  fontWeight: 900, lineHeight: 1
                }}>{st.icon}</span>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: active === i ? st.color : "#cbd5e1" }}>
                    {st.name}
                  </div>
                  <div style={{ fontSize: 10, color: "#475569", marginTop: 2 }}>{st.tagline}</div>
                </div>
              </div>
            </button>
          ))}

          {/* RSI cheatsheet */}
          <div style={{
            background: "#0b101c", border: "1px solid #1e293b",
            borderRadius: 10, padding: "12px 14px", marginTop: 8
          }}>
            <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 8 }}>RSI ZONES</div>
            {rsiZones.map((z, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                <div style={{
                  width: 8, height: 8, borderRadius: "50%", background: z.col, flexShrink: 0
                }} />
                <div>
                  <div style={{ fontSize: 10, color: z.col, fontWeight: 700 }}>{z.range}</div>
                  <div style={{ fontSize: 10, color: "#475569" }}>{z.action}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Strategy detail */}
        <div>
          <div style={{
            background: "#0b101c", border: `1px solid ${s.color}30`,
            borderRadius: 12, padding: 18, marginBottom: 16
          }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
              <div>
                <div style={{ fontSize: 20, fontWeight: 900, color: s.color }}>{s.name}</div>
                <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>{s.idea}</div>
              </div>
            </div>

            {/* Signal logic table */}
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 8 }}>SIGNAL LOGIC</div>
              {s.logic.map((l, i) => (
                <div key={i} style={{
                  display: "flex", alignItems: "center", gap: 12,
                  background: l.col + "10", border: `1px solid ${l.col}25`,
                  borderRadius: 6, padding: "8px 12px", marginBottom: 5
                }}>
                  <span style={{ fontSize: 12, fontWeight: 900, color: l.col, minWidth: 60 }}>{l.label}</span>
                  <span style={{ fontSize: 11, color: "#94a3b8", fontFamily: "monospace" }}>{l.cond}</span>
                </div>
              ))}
            </div>

            {/* Indicators */}
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 8 }}>INDICATORS USED</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                {s.indicators.map((ind, i) => (
                  <div key={i} style={{
                    background: "#111827", borderRadius: 8, padding: "8px 10px",
                    borderLeft: `3px solid ${s.color}60`
                  }}>
                    <div style={{ fontSize: 11, color: s.color, fontWeight: 700 }}>{ind.name}</div>
                    <div style={{ fontSize: 10, color: "#f59e0b", marginTop: 1 }}>{ind.role}</div>
                    <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>{ind.desc}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Best / Worst for */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 6 }}>✅ BEST FOR</div>
                {s.bestFor.map((b, i) => (
                  <div key={i} style={{ fontSize: 11, color: "#34d399", marginBottom: 3 }}>• {b}</div>
                ))}
              </div>
              <div>
                <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 6 }}>⚠️ AVOID WHEN</div>
                {s.worstFor.map((w, i) => (
                  <div key={i} style={{ fontSize: 11, color: "#f87171", marginBottom: 3 }}>• {w}</div>
                ))}
              </div>
            </div>
          </div>

          {/* Code + params */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <div style={{
              background: "#060a10", border: `1px solid ${s.color}20`,
              borderRadius: 10, padding: 14
            }}>
              <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 8 }}>USAGE</div>
              <pre style={{
                margin: 0, fontSize: 11, color: "#7dd3fc",
                lineHeight: 1.8, fontFamily: "monospace"
              }}>{s.code}</pre>
            </div>

            <div style={{
              background: "#0b101c", border: "1px solid #1e293b",
              borderRadius: 10, padding: 14
            }}>
              <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 8 }}>PARAMETERS</div>
              {s.params.map((p, i) => (
                <div key={i} style={{ marginBottom: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <span style={{ fontSize: 11, color: s.color }}>{p.name}</span>
                    <span style={{
                      fontSize: 10, color: "#334155", background: "#111827",
                      padding: "1px 6px", borderRadius: 4
                    }}>default: {p.default}</span>
                  </div>
                  <div style={{ fontSize: 10, color: "#64748b", marginTop: 2 }}>{p.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Footer hint */}
      <div style={{
        marginTop: 20, padding: "12px 16px",
        background: "#0b101c", border: "1px solid #1e293b", borderRadius: 10,
        display: "flex", justifyContent: "space-between", alignItems: "center"
      }}>
        <div style={{ fontSize: 11, color: "#475569" }}>
          ⚡ Run <span style={{ color: "#7dd3fc" }}>python strategy_signals.py</span> to see live signals on your data
        </div>
        <div style={{ fontSize: 11, color: "#334155" }}>
          Phase 2 complete → Next: Phase 3 — Backtester
        </div>
      </div>
    </div>
  );
}
