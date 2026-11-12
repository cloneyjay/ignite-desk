import { useMemo, useState } from "react";

import { useStats, useSymbols, useTrades } from "../hooks/useApi";
import { dateTime, daysAgo, duration, localDateInput, money, number, price, signedMoney } from "../lib/format";
import { Badge, Button, EmptyState, Metric, Panel } from "../components/ui";
import { RefreshIcon } from "../components/icons";

const TODAY = localDateInput(new Date());

export default function History() {
  const [from, setFrom] = useState(() => daysAgo(30));
  const [to, setTo] = useState(TODAY);
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState("");
  const [result, setResult] = useState("");
  const symbols = useSymbols();

  const range = useMemo(() => {
    const start = new Date(`${from}T00:00:00`);
    const end = new Date(`${to}T23:59:59.999`);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || start >= end) {
      return null;
    }
    return { from: start.toISOString(), to: end.toISOString() };
  }, [from, to]);

  const filters = {
    from: range?.from,
    to: range?.to,
    symbol: symbol || undefined,
    side: side || undefined,
    result: result || undefined,
  };

  const trades = useTrades(filters, { enabled: Boolean(range) });
  const stats = useStats(range ?? {});

  const rows = trades.data?.trades ?? [];

  const reset = () => {
    setFrom(daysAgo(30));
    setTo(TODAY);
    setSymbol("");
    setSide("");
    setResult("");
  };

  return (
    <div className="space-y-4">
      <Panel bodyClassName="p-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-[0.14em] text-fog">From</span>
            <input type="date" value={from} onChange={(event) => setFrom(event.target.value)} className="field" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-[0.14em] text-fog">To</span>
            <input type="date" value={to} onChange={(event) => setTo(event.target.value)} className="field" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-[0.14em] text-fog">Symbol</span>
            <select value={symbol} onChange={(event) => setSymbol(event.target.value)} className="field min-w-[130px]">
              <option value="">All symbols</option>
              {(symbols.data?.symbols ?? []).map((row) => (
                <option key={row.symbol} value={row.symbol}>
                  {row.symbol}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-[0.14em] text-fog">Side</span>
            <select value={side} onChange={(event) => setSide(event.target.value)} className="field min-w-[110px]">
              <option value="">All sides</option>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] uppercase tracking-[0.14em] text-fog">Result</span>
            <select value={result} onChange={(event) => setResult(event.target.value)} className="field min-w-[110px]">
              <option value="">All results</option>
              <option value="win">Wins</option>
              <option value="loss">Losses</option>
            </select>
          </label>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={reset}>
              Reset
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => trades.refetch()}
              loading={trades.isFetching}
            >
              <RefreshIcon className="h-3.5 w-3.5" />
              Refresh
            </Button>
          </div>
        </div>
        {!range ? (
          <div className="mt-2 text-[11.5px] text-short">From must be earlier than to.</div>
        ) : null}
      </Panel>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
        <Metric
          label="Net P/L"
          value={signedMoney(stats.data?.net_usd)}
          tone={(stats.data?.net_usd ?? 0) >= 0 ? "long" : "short"}
          sub={`${stats.data?.trades ?? 0} closed trades`}
        />
        <Metric
          label="Win rate"
          value={stats.data?.win_rate !== null && stats.data?.win_rate !== undefined ? `${(stats.data.win_rate * 100).toFixed(1)}%` : "—"}
          sub={`${stats.data?.wins ?? 0}W / ${stats.data?.losses ?? 0}L`}
        />
        <Metric
          label="Profit factor"
          value={number(stats.data?.profit_factor, 2)}
          tone={(stats.data?.profit_factor ?? 0) >= 1 ? "long" : "short"}
          sub={`gross ${money(stats.data?.gross_win_usd)} / ${money(stats.data?.gross_loss_usd)}`}
        />
        <Metric
          label="Expectancy"
          value={signedMoney(stats.data?.expectancy_usd)}
          sub="per trade"
        />
        <Metric
          label="Average R"
          value={stats.data?.average_r !== null && stats.data?.average_r !== undefined ? `${stats.data.average_r.toFixed(2)}R` : "—"}
          tone={(stats.data?.average_r ?? 0) >= 0 ? "long" : "short"}
          sub="planned risk basis"
        />
        <Metric
          label="Max drawdown"
          value={money(stats.data?.max_drawdown_usd)}
          tone="warn"
          sub={`avg hold ${duration(stats.data?.average_hold_s)}`}
        />
      </div>

      <Panel
        title="Closed trades"
        subtitle={
          trades.data
            ? `${rows.length} trade(s) · ${dateTime(trades.data.from)} → ${dateTime(trades.data.to)} · local time`
            : "Terminal deal history"
        }
        bodyClassName="p-0"
      >
        {trades.isError ? (
          <div className="px-5 py-8 text-center text-[12px] text-short">
            Could not load trade history. The MT5 terminal may be unreachable.
          </div>
        ) : rows.length === 0 ? (
          <div className="px-5 py-6">
            <EmptyState
              title="No closed trades in this range"
              message="Trades appear here once a position is closed in the terminal. Ignite drafts and rejected orders stay in the audit log."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] border-collapse">
              <thead>
                <tr className="border-b border-line/60">
                  <th className="th">Closed</th>
                  <th className="th">Symbol</th>
                  <th className="th">Side</th>
                  <th className="th text-right">Lots</th>
                  <th className="th text-right">Entry</th>
                  <th className="th text-right">Exit</th>
                  <th className="th text-right">Net P/L</th>
                  <th className="th text-right">R</th>
                  <th className="th text-right">Risk</th>
                  <th className="th text-right">Hold</th>
                  <th className="th">Ticket</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((trade) => {
                  const win = trade.net >= 0;
                  return (
                    <tr
                      key={trade.ticket}
                      className="border-b border-line/30 last:border-0 hover:bg-ink-800/40"
                    >
                      <td className="td text-fog">{dateTime(trade.close_time)}</td>
                      <td className="td font-semibold">{trade.symbol}</td>
                      <td className="td">
                        <Badge tone={trade.side === "buy" ? "long" : "short"}>
                          {trade.side ?? "—"}
                        </Badge>
                      </td>
                      <td className="td text-right font-mono">{trade.lots.toFixed(2)}</td>
                      <td className="td text-right font-mono">{price(trade.entry)}</td>
                      <td className="td text-right font-mono">{price(trade.exit)}</td>
                      <td className={`td text-right font-mono ${win ? "text-long" : "text-short"}`}>
                        {signedMoney(trade.net)}
                      </td>
                      <td className={`td text-right font-mono ${win ? "text-long" : "text-short"}`}>
                        {trade.r_multiple !== null ? `${trade.r_multiple.toFixed(2)}R` : "—"}
                      </td>
                      <td className="td text-right font-mono">{money(trade.risk_usd)}</td>
                      <td className="td text-right font-mono text-fog">{duration(trade.duration_s)}</td>
                      <td className="td font-mono text-[11px] text-fog">{trade.ticket}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <div className="flex flex-wrap items-center gap-3 text-[10.5px] text-fog/70">
        <span>Deal history comes from MT5; risk and R multiples come from Ignite drafts.</span>
        <span>·</span>
        <span>Timestamps rendered in your local timezone.</span>
      </div>
    </div>
  );
}
