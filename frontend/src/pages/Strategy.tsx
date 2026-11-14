import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../lib/api";
import type { Strategy, StrategyBacktest } from "../lib/types";
import { Badge, Panel, Row } from "../components/ui";

const STATUS_COLOR: Record<string, "long" | "short" | "neutral" | "warn"> = {
  draft: "neutral",
  compiled: "neutral",
  backtested: "long",
  shadow: "long",
  demo: "long",
  live: "short",
  archived: "short",
};

export default function StrategyPage() {
  const { strategyId } = useParams<{ strategyId: string }>();
  const navigate = useNavigate();
  const [strategy, setStrategy] = useState<Strategy | null>(null);
  const [backtests, setBacktests] = useState<StrategyBacktest[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!strategyId) {
      navigate("/strategies");
      return;
    }
    loadStrategy();
  }, [strategyId, navigate]);

  async function loadStrategy() {
    if (!strategyId) return;
    try {
      setLoading(true);
      const data = await api.strategy(strategyId);
      setStrategy(data.strategy);
      setBacktests(data.backtests ?? []);
    } catch (exc: any) {
      setError(exc.message || "Failed to load strategy");
    } finally {
      setLoading(false);
    }
  }

  async function promote(target: string) {
    if (!strategyId) return;
    if (!window.confirm(`Promote strategy to ${target.toUpperCase()}?`)) return;
    try {
      await api.strategyPromote(strategyId, target, true);
      await loadStrategy();
    } catch (exc: any) {
      setError(exc.message || "Promotion failed");
    }
  }

  async function demote() {
    if (!strategyId) return;
    if (!window.confirm("Demote strategy to shadow?")) return;
    try {
      await api.strategyDemote(strategyId, true);
      await loadStrategy();
    } catch (exc: any) {
      setError(exc.message || "Demotion failed");
    }
  }

  if (loading) {
    return (
      <div className="p-5">
        <div className="text-[12px] text-fog">Loading strategy…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-5">
        <div className="text-[12px] text-short">{error}</div>
        <button
          onClick={() => navigate("/strategies")}
          className="mt-2 text-[10px] underline text-fog"
        >
          Back to strategies
        </button>
      </div>
    );
  }

  if (!strategy) {
    return (
      <div className="p-5">
        <div className="text-[12px] text-short">Strategy not found.</div>
      </div>
    );
  }

  const latestBacktest = backtests[0];
  const statusColor = STATUS_COLOR[strategy.status] ?? "neutral";

  return (
    <div className="p-5 space-y-4">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-[15px] font-semibold text-paper">{strategy.name}</h1>
            <Badge tone={statusColor}>{strategy.status.toUpperCase()}</Badge>
            <Badge tone="neutral">v{strategy.version}</Badge>
          </div>
          <div className="text-[10px] text-fog mt-1">{strategy.symbol} · {strategy.timeframe}</div>
          {strategy.description && (
            <p className="mt-1 text-[11px] text-fog">{strategy.description}</p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => navigate("/strategies")}
            className="text-[10px] underline text-fog hover:text-paper"
          >
            ← Back to strategies
          </button>
          {strategy.status === "draft" && (
            <button
              onClick={() => promote("compiled")}
              className="text-[10px] px-3 py-1.5 rounded border border-line/60 bg-ink-800/60 text-fog hover:text-gold-400 hover:border-gold-500/50"
            >
              Compile
            </button>
          )}
          {strategy.status === "compiled" && (
            <button
              onClick={() => promote("backtested")}
              className="text-[10px] px-3 py-1.5 rounded border border-line/60 bg-ink-800/60 text-fog hover:text-gold-400 hover:border-gold-500/50"
            >
              Backtest
            </button>
          )}
          {strategy.status === "backtested" && (
            <button
              onClick={() => promote("shadow")}
              className="text-[10px] px-3 py-1.5 rounded border border-line/60 bg-ink-800/60 text-fog hover:text-gold-400 hover:border-gold-500/50"
            >
              Shadow
            </button>
          )}
          {strategy.status === "shadow" && (
            <button
              onClick={() => promote("demo")}
              className="text-[10px] px-3 py-1.5 rounded border border-line/60 bg-ink-800/60 text-fog hover:text-gold-400 hover:border-gold-500/50"
            >
              Demo
            </button>
          )}
          {strategy.status === "demo" && (
            <button
              onClick={() => promote("live")}
              className="text-[10px] px-3 py-1.5 rounded border border-line/60 bg-ink-800/60 text-fog hover:text-gold-400 hover:border-gold-500/50"
            >
              Live
            </button>
          )}
          {(strategy.status === "demo" || strategy.status === "live") && (
            <button
              onClick={demote}
              className="text-[10px] px-3 py-1.5 rounded border border-short/30 bg-ink-800/60 text-short hover:text-short hover:border-short/50"
            >
              Demote
            </button>
          )}
        </div>
      </div>

      {/* Performance metrics */}
      {latestBacktest && (
        <Panel title="Backtest Performance">
          <div className="grid grid-cols-2 gap-4">
            <Row label="Net Profit" value={`${(latestBacktest.net_profit ?? 0).toFixed(2)}`} />
            <Row label="Win Rate" value={`${(latestBacktest.win_rate ?? 0).toFixed(1)}%`} />
            <Row label="Profit Factor" value={`${(latestBacktest.profit_factor ?? 0).toFixed(2)}`} />
            <Row label="Max Drawdown" value={`${(latestBacktest.max_drawdown ?? 0).toFixed(2)}`} />
            <Row label="Sharpe Ratio" value={`${(latestBacktest.sharpe_ratio ?? 0).toFixed(2)}`} />
            <Row label="Total Trades" value={`${latestBacktest.total_trades ?? 0}`} />
            <Row label="Period" value={`${latestBacktest.start_date} → ${latestBacktest.end_date}`} />
          </div>
        </Panel>
      )}

      {/* MQL5 Code */}
      <Panel title="MQL5 Source">
        <div className="overflow-x-auto font-mono text-[10px] leading-relaxed text-paper/80 bg-ink-950 p-3 rounded border border-line/60">
          {strategy.mql5_code}
        </div>
        <div className="mt-2 flex gap-2">
          <button
            onClick={() => {
              navigator.clipboard.writeText(strategy.mql5_code);
            }}
            className="text-[10px] underline text-fog hover:text-paper"
          >
            Copy Code
          </button>
        </div>
      </Panel>

      {/* Backtest History */}
      {backtests.length > 1 && (
        <Panel title="Backtest History">
          <div className="overflow-x-auto">
            <table className="w-full text-[10px] border-collapse">
              <thead>
                <tr className="border-b border-line/60">
                  <th className="text-left pb-2 text-fog">Period</th>
                  <th className="text-left pb-2 text-fog">Net Profit</th>
                  <th className="text-left pb-2 text-fog">Win Rate</th>
                  <th className="text-left pb-2 text-fog">Profit Factor</th>
                  <th className="text-left pb-2 text-fog">Max DD</th>
                  <th className="text-left pb-2 text-fog">Trades</th>
                </tr>
              </thead>
              <tbody>
                {backtests.map((bt) => (
                  <tr key={bt.id} className="border-b border-line/40 hover:bg-ink-850/40">
                    <td className="pb-1 text-fog">{bt.start_date} → {bt.end_date}</td>
                    <td className="pb-1 text-paper">
                      {(bt.net_profit ?? 0).toFixed(2)}
                    </td>
                    <td className="pb-1 text-paper">
                      {(bt.win_rate ?? 0).toFixed(1)}%
                    </td>
                    <td className="pb-1 text-paper">
                      {(bt.profit_factor ?? 0).toFixed(2)}
                    </td>
                    <td className="pb-1 text-short">
                      {(bt.max_drawdown ?? 0).toFixed(2)}
                    </td>
                    <td className="pb-1 text-paper">{bt.total_trades ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
}