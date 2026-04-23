import { useState } from "react";

const metrics = [
  {
    name: "Total Return %",
    formula: "(Final Equity - Start) / Start × 100",
    good: "> 20%",
    great: "> 50%",
    color: "#22d3ee",
    desc: "Raw profit/loss as percentage of starting capital",
  },
  {
    name: "Sharpe Ratio",
    formula: "Mean Daily Return / Std Dev × √252",
    good: "> 1.0",
    great: "> 2.0",
    color: "#a78bfa",
    desc: "Risk-adjusted return. The most important metric. Higher = better returns per unit of risk.",
  },
  {
    name: "Max Drawdown %",
    formula: "(Trough - Peak) / Peak × 100",
    good: "> -20%",
    great: "> -10%",
    color: "#f87171",
    desc: "Worst peak-to-trough loss. How much pain could you handle? Smaller is better.",
  },
  {
    name: "Win Rate %",
    formula: "Winning Trades / Total Trades × 100",
    good: "> 50%",
    great: "> 60%",
    color: "#34d399",
    desc: "% of trades that were profitable. Means nothing alone — needs profit factor too.",
  },
  {
    name: "Profit Factor",
    formula: "Gross Profit / Gross Loss",
    good: "> 1.5",
    great: "> 2.0",
    color: "#fbbf24",
    desc: "Gross wins divided by gross losses. >1 means the system makes money overall.",
  },
  {
    name: "CAGR %",
    formula: "(Final / Initial)^(1/years) - 1",
    good: "> 15%",
    great: "> 30%",
    color: "#60a5fa",
    desc: "Compound Annual Growth Rate — annualised return, comparable across time periods.",
  },
  {
    name: "Calmar Ratio",
    formula: "CAGR / |Max Drawdown|",
    good: "> 0.5",
    great: "> 1.0",
    color: "#f472b6",
    desc: "Return vs drawdown tradeoff. Better than Sharpe for long-term strategies.",
  },
  {
    name: "Expectancy $",
    formula: "(Win Rate × Avg Win) + (Loss Rate × Avg Loss)",
    good: "> $0",
    great: "> $50",
    color: "#fb923c",
    desc: "Expected $ profit per trade on average. Positive means the edge is real.",
  },
];

const engineParams = [
  { name: "initial_capital", default: "10,000", desc: "Starting portfolio size in $" },
  { name: "position_size", default: "0.95", desc: "% of cash used per trade (0.95 = 95%)" },
  { name: "commission_pct", default: "0.001", desc: "0.1% commission per trade (realistic)" },
  { name: "slippage_pct", default: "0.0005", desc: "0.05% slippage on fills" },
  { name: "stop_loss_pct", default: "0.05", desc: "5% hard stop-loss per trade" },
  { name: "take_profit_pct", default: "0.10", desc: "10% take-profit target" },
  { name: "allow_short", default: "False", desc: "Allow shorting the market" },
  { name: "max_open_trades", default: "1", desc: "Max simultaneous positions" },
];

const classes = [
  {
    name: "BacktestEngine",
    color: "#22d3ee",
    icon: "⚙",
    desc: "Core simulation loop. Processes each candle, fills orders at next open, applies all costs.",
    key: "engine",
    code: `engine = BacktestEngine(\n    initial_capital=10_000,\n    stop_loss_pct=0.05\n)\nreport = engine.run(df_with_signals)`,
  },
  {
    name: "PerformanceMetrics",
    color: "#a78bfa",
    icon: "📊",
    desc: "Computes Sharpe, drawdown, win rate, CAGR, profit factor from trade log + equity curve.",
    key: "metrics",
    code: `# Called automatically inside BacktestReport\nm = report.get_metrics()\nprint(m["sharpe_ratio"])\nprint(m["max_drawdown_pct"])`,
  },
  {
    name: "BacktestReport",
    color: "#34d399",
    icon: "📋",
    desc: "Wraps all results. Print summary, trade log, grade the strategy, export metrics.",
    key: "report",
    code: `report.print_summary()    # full stats\nreport.print_trade_log()  # every trade\nm = report.get_metrics()  # dict of metrics`,
  },
  {
    name: "WalkForwardTest",
    color: "#fbbf24",
    icon: "🔄",
    desc: "Prevents overfitting. Tests strategy on unseen data multiple times to prove real edge.",
    key: "wft",
    code: `wf = WalkForwardTest(\n    train_pct=0.7,\n    n_splits=3\n)\nreports = wf.run(df, MeanReversionStrategy)`,
  },
];

const gradeRubric = [
  { grade: "⭐⭐⭐⭐⭐", label: "EXCEPTIONAL", score: "8–10", color: "#fbbf24" },
  { grade: "⭐⭐⭐⭐", label: "GREAT", score: "6–7", color: "#34d399" },
  { grade: "⭐⭐⭐", label: "GOOD", score: "4–5", color: "#22d3ee" },
  { grade: "⭐⭐", label: "AVERAGE", score: "2–3", color: "#94a3b8" },
  { grade: "⭐", label: "NEEDS WORK", score: "0–1", color: "#f87171" },
];

const simulationSteps = [
  { step: "1", label: "Load signals", sub: "df with signal col", col: "#64748b" },
  { step: "2", label: "Candle loop", sub: "one by one, no peek", col: "#60a5fa" },
  { step: "3", label: "Check stops", sub: "SL / TP hit?", col: "#f87171" },
  { step: "4", label: "Fill orders", sub: "next open + slippage", col: "#a78bfa" },
  { step: "5", label: "Log equity", sub: "cash + positions", col: "#34d399" },
  { step: "6", label: "Report", sub: "metrics + grade", col: "#fbbf24" },
];

const commonMistakes = [
  { mistake: "Look-ahead bias", fix: "We fill at NEXT candle's open, never current close", icon: "👁" },
  { mistake: "Ignoring costs", fix: "Commission + slippage on every single trade", icon: "💸" },
  { mistake: "Overfitting", fix: "Walk-forward test validates on unseen data", icon: "🎯" },
  { mistake: "Too few trades", fix: "Need 30+ trades for statistically valid results", icon: "📉" },
];

export default function App() {
  const [activeClass, setActiveClass] = useState(0);
  const [activeMetric, setActiveMetric] = useState(0);
  const cls = classes[activeClass];
  const met = metrics[activeMetric];

  return (
    <div style={{
      fontFamily: "'JetBrains Mono', monospace",
      background: "#07090f",
      minHeight: "100vh",
      color: "#e2e8f0",
      padding: "24px",
    }}>
      {/* Header */}
      <div style={{ marginBottom: 22 }}>
        <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
          {["DATA PIPELINE ✓", "STRATEGY & SIGNALS ✓", "BACKTESTER ◀ ACTIVE", "RISK MGMT", "LIVE TRADING", "DASHBOARD"].map((p, i) => (
            <span key={i} style={{
              background: i < 2 ? "#0f1a0f" : i === 2 ? "#22d3ee15" : "#0a0c12",
              border: `1px solid ${i < 2 ? "#166534" : i === 2 ? "#22d3ee50" : "#1e293b"}`,
              borderRadius: 6, padding: "3px 8px", fontSize: 9,
              color: i < 2 ? "#4ade80" : i === 2 ? "#22d3ee" : "#1e293b",
              letterSpacing: 1, fontWeight: 700
            }}>{p}</span>
          ))}
        </div>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 900, letterSpacing: -1 }}>
          Backtester <span style={{ color: "#22d3ee" }}>— Phase 3</span>
        </h1>
        <p style={{ margin: "4px 0 0", color: "#475569", fontSize: 12 }}>
          Simulate your strategy on years of historical data before risking a single rupee
        </p>
      </div>

      {/* Simulation loop */}
      <div style={{
        background: "#0b101c", border: "1px solid #1e293b",
        borderRadius: 12, padding: "14px 18px", marginBottom: 18
      }}>
        <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 10 }}>
          HOW THE ENGINE WORKS — CANDLE BY CANDLE
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {simulationSteps.map((s, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{
                background: s.col + "15", border: `1px solid ${s.col}35`,
                borderRadius: 8, padding: "7px 12px", textAlign: "center"
              }}>
                <div style={{ fontSize: 10, color: s.col, fontWeight: 700 }}>{s.step}. {s.label}</div>
                <div style={{ fontSize: 9, color: "#475569", marginTop: 1 }}>{s.sub}</div>
              </div>
              {i < simulationSteps.length - 1 && (
                <div style={{ color: "#1e293b", fontSize: 14 }}>→</div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>

        {/* Classes panel */}
        <div>
          <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 8 }}>CLASSES</div>
          {classes.map((c, i) => (
            <button key={i} onClick={() => setActiveClass(i)} style={{
              width: "100%", marginBottom: 6,
              background: activeClass === i ? c.color + "10" : "#0b101c",
              border: `1px solid ${activeClass === i ? c.color + "50" : "#1e293b"}`,
              borderRadius: 9, padding: "10px 14px", cursor: "pointer", textAlign: "left"
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 18 }}>{c.icon}</span>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: activeClass === i ? c.color : "#cbd5e1" }}>
                    {c.name}
                  </div>
                  <div style={{ fontSize: 10, color: "#475569", marginTop: 1 }}>{c.desc}</div>
                </div>
              </div>
            </button>
          ))}

          {/* Code preview */}
          <div style={{
            background: "#050810", border: `1px solid ${cls.color}20`,
            borderRadius: 10, padding: 14, marginTop: 4
          }}>
            <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 8 }}>
              USAGE — {cls.name}
            </div>
            <pre style={{
              margin: 0, fontSize: 11, color: "#7dd3fc",
              lineHeight: 1.9, fontFamily: "monospace", whiteSpace: "pre"
            }}>{cls.code}</pre>
          </div>
        </div>

        {/* Metrics panel */}
        <div>
          <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 8 }}>
            PERFORMANCE METRICS
          </div>
          <div style={{
            display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5, marginBottom: 10
          }}>
            {metrics.map((m, i) => (
              <button key={i} onClick={() => setActiveMetric(i)} style={{
                background: activeMetric === i ? m.color + "12" : "#0b101c",
                border: `1px solid ${activeMetric === i ? m.color + "50" : "#1e293b"}`,
                borderRadius: 7, padding: "8px 10px", cursor: "pointer", textAlign: "left"
              }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: activeMetric === i ? m.color : "#94a3b8" }}>
                  {m.name}
                </div>
                <div style={{ fontSize: 9, color: "#475569", marginTop: 2 }}>
                  Good: {m.good}
                </div>
              </button>
            ))}
          </div>

          {/* Metric detail */}
          <div style={{
            background: "#0b101c", border: `1px solid ${met.color}30`,
            borderRadius: 10, padding: 14
          }}>
            <div style={{ fontSize: 14, fontWeight: 800, color: met.color, marginBottom: 6 }}>
              {met.name}
            </div>
            <div style={{ fontSize: 11, color: "#94a3b8", marginBottom: 10, lineHeight: 1.6 }}>
              {met.desc}
            </div>
            <div style={{
              background: "#060a10", borderRadius: 6, padding: "7px 12px",
              fontSize: 11, color: "#7dd3fc", fontFamily: "monospace", marginBottom: 8
            }}>
              {met.formula}
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <div style={{
                background: "#14532d20", border: "1px solid #14532d",
                borderRadius: 6, padding: "5px 10px", fontSize: 11, color: "#4ade80"
              }}>
                ✓ Good: {met.good}
              </div>
              <div style={{
                background: "#fbbf2420", border: "1px solid #92400e",
                borderRadius: 6, padding: "5px 10px", fontSize: 11, color: "#fbbf24"
              }}>
                ★ Great: {met.great}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom row */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>

        {/* Engine params */}
        <div style={{
          background: "#0b101c", border: "1px solid #1e293b",
          borderRadius: 12, padding: "14px 16px"
        }}>
          <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 10 }}>
            BACKTEST ENGINE PARAMETERS
          </div>
          {engineParams.map((p, i) => (
            <div key={i} style={{
              display: "flex", justifyContent: "space-between", alignItems: "flex-start",
              borderBottom: "1px solid #0f1623", paddingBottom: 6, marginBottom: 6
            }}>
              <div>
                <div style={{ fontSize: 11, color: "#22d3ee" }}>{p.name}</div>
                <div style={{ fontSize: 10, color: "#475569", marginTop: 1 }}>{p.desc}</div>
              </div>
              <span style={{
                background: "#111827", border: "1px solid #1e293b",
                borderRadius: 4, padding: "1px 7px", fontSize: 10, color: "#94a3b8",
                whiteSpace: "nowrap", marginLeft: 8, flexShrink: 0
              }}>{p.default}</span>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {/* Grading rubric */}
          <div style={{
            background: "#0b101c", border: "1px solid #1e293b",
            borderRadius: 12, padding: "14px 16px"
          }}>
            <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 10 }}>
              STRATEGY GRADING
            </div>
            {gradeRubric.map((g, i) => (
              <div key={i} style={{
                display: "flex", alignItems: "center", gap: 10, marginBottom: 6
              }}>
                <span style={{ fontSize: 12, minWidth: 80 }}>{g.grade}</span>
                <span style={{ fontSize: 11, color: g.color, fontWeight: 700, minWidth: 90 }}>
                  {g.label}
                </span>
                <span style={{ fontSize: 10, color: "#334155" }}>score {g.score}</span>
              </div>
            ))}
          </div>

          {/* Common mistakes */}
          <div style={{
            background: "#0b101c", border: "1px solid #1e293b",
            borderRadius: 12, padding: "14px 16px"
          }}>
            <div style={{ fontSize: 10, color: "#334155", letterSpacing: 2, marginBottom: 10 }}>
              COMMON BACKTEST MISTAKES — AND HOW WE HANDLE THEM
            </div>
            {commonMistakes.map((m, i) => (
              <div key={i} style={{ marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 14 }}>{m.icon}</span>
                  <span style={{ fontSize: 11, color: "#f87171", fontWeight: 700 }}>{m.mistake}</span>
                </div>
                <div style={{ fontSize: 10, color: "#4ade80", marginTop: 2, paddingLeft: 22 }}>
                  ✓ {m.fix}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Footer */}
      <div style={{
        marginTop: 16, padding: "10px 14px",
        background: "#0b101c", border: "1px solid #1e293b", borderRadius: 10,
        display: "flex", justifyContent: "space-between", alignItems: "center"
      }}>
        <span style={{ fontSize: 11, color: "#475569" }}>
          Run: <span style={{ color: "#7dd3fc" }}>python backtester.py</span> — see full trade log + metrics
        </span>
        <span style={{ fontSize: 11, color: "#334155" }}>
          Phase 3 ✓ → Next: Phase 4 — Risk Management
        </span>
      </div>
    </div>
  );
}
