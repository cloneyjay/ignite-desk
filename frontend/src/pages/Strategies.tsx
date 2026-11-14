import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import type { Strategy } from "../lib/types";
import { Badge, Panel } from "../components/ui";
import { PlusIcon, RefreshIcon } from "../components/icons";

const STATUS_COLOR: Record<string, "long" | "short" | "neutral" | "warn"> = {
  draft: "neutral",
  compiled: "neutral",
  backtested: "long",
  shadow: "long",
  demo: "long",
  live: "short",
  archived: "short",
};

export default function StrategiesPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadStrategies();
  }, []);

  async function loadStrategies() {
    try {
      setLoading(true);
      const data = await api.strategies();
      setStrategies(data.strategies ?? []);
    } catch (exc: any) {
      setError(exc.message || "Failed to load strategies");
    } finally {
      setLoading(false);
    }
  }

  async function createStrategy() {
    const name = window.prompt("Strategy name (e.g. 'EMA Crossover XAUUSD M15'):");
    if (!name) return;
    const symbol = window.prompt("Symbol (e.g. XAUUSD):", "XAUUSD");
    if (!symbol) return;
    const timeframe = window.prompt("Timeframe (M5/M15/M30/H1):", "M15");
    if (!timeframe) return;

    // Generate a simple EMA crossover strategy via chat
    const fastEma = 20;
    const slowEma = 50;
    try {
      await api.agentChat(`Create a strategy for ${symbol} ${timeframe}: EMA crossover with fast=${fastEma}, slow=${slowEma}`, undefined);
      // Note: This goes through the chat agent which will create the strategy
      await loadStrategies();
    } catch (exc: any) {
      setError(exc.message || "Failed to create strategy");
    }
  }

  if (loading) {
    return (
      <div className="p-5">
        <div className="text-[12px] text-fog">Loading strategies…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-5">
        <div className="text-[12px] text-short">{error}</div>
      </div>
    );
  }

  return (
    <div className="p-5 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[15px] font-semibold text-paper">Strategies</h1>
          <p className="text-[11px] text-fog">Manage your trading strategies and EAs</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={createStrategy}
            className="flex items-center gap-2 text-[10px] px-3 py-1.5 rounded border border-line/60 bg-ink-800/60 text-fog hover:text-gold-400 hover:border-gold-500/50"
          >
            <PlusIcon className="h-3 w-3" /> Create Strategy
          </button>
          <button
            onClick={() => loadStrategies()}
            className="text-[10px] px-3 py-1.5 rounded border border-line/60 bg-ink-800/60 text-fog hover:text-gold-400 hover:border-gold-500/50"
          >
            <RefreshIcon className="h-3 w-3" /> Refresh
          </button>
        </div>
      </div>

      {strategies.length === 0 && (
        <Panel title="Strategies">
          <div className="p-5 text-center">
            <div className="text-[12px] text-fog">No strategies yet.</div>
            <button
              onClick={createStrategy}
              className="mt-3 text-[10px] underline text-gold-400 hover:text-gold-300"
            >
              Create your first strategy
            </button>
          </div>
        </Panel>
      )}

      {strategies.length > 0 && (
        <Panel title="Strategies">
          <div className="overflow-x-auto">
            <table className="w-full text-[10px] border-collapse">
              <thead>
                <tr className="border-b border-line/60">
                  <th className="text-left pb-2 text-fog w-1/3">Name</th>
                  <th className="text-left pb-2 text-fog">Symbol · TF</th>
                  <th className="text-left pb-2 text-fog">Status</th>
                  <th className="text-left pb-2 text-fog">Win Rate</th>
                  <th className="text-left pb-2 text-fog">Profit Factor</th>
                  <th className="text-left pb-2 text-fog">Trades</th>
                  <th className="text-left pb-2 text-fog">Actions</th>
                </tr>
              </thead>
              <tbody>
                {strategies.map((s) => (
                  <tr key={s.id} className="border-b border-line/40 hover:bg-ink-850/40 group">
                    <td className="pb-1">
                      <div className="text-paper font-medium">{s.name}</div>
                      <div className="text-[9px] text-fog">v{s.version}</div>
                    </td>
                    <td className="pb-1 text-fog font-mono">
                      {s.symbol} · {s.timeframe}
                    </td>
                    <td className="pb-1">
                      <Badge
                        tone={STATUS_COLOR[s.status] ?? "neutral"}
                        className="text-[9px] px-2 py-0.5"
                      >
                        {s.status}
                      </Badge>
                    </td>
                    <td className="pb-1 text-paper">
                      {(s.win_rate ?? 0).toFixed(1)}%
                    </td>
                    <td className="pb-1 text-paper">
                      {(s.profit_factor ?? 0).toFixed(2)}
                    </td>
                    <td className="pb-1 text-paper">{s.total_trades ?? 0}</td>
                    <td className="pb-1">
                      <Link
                        to={`/strategies/${s.id}`}
                        className="text-[10px] underline text-fog hover:text-paper"
                      >
                        View
                      </Link>
                    </td>
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