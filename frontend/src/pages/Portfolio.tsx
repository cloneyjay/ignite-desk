import { useState } from "react";

import { useAccount, useEquity } from "../hooks/useApi";
import { dateTime, money, number, percent, price, signedMoney } from "../lib/format";
import EquityChart from "../components/EquityChart";
import { Badge, EmptyState, Metric, Panel, Row } from "../components/ui";
import { AlertIcon } from "../components/icons";

const RANGES = ["1d", "1w", "1m", "all"] as const;

export default function Portfolio() {
  const [range, setRange] = useState<string>("1d");
  const account = useAccount();
  const equity = useEquity(range);

  const data = account.data;
  const info = data?.account;
  const today = data?.today;
  const risk = data?.risk;
  const positions = data?.positions ?? [];

  const todayTone =
    today?.realised_usd === null || today?.realised_usd === undefined
      ? "neutral"
      : today.realised_usd > 0
        ? "long"
        : today.realised_usd < 0
          ? "short"
          : "neutral";

  const riskTone =
    risk?.open_risk_pct !== null && risk?.open_risk_pct !== undefined
      ? risk.open_risk_pct > risk.cap_pct
        ? "short"
        : risk.open_risk_pct > risk.cap_pct * 0.6
          ? "warn"
          : "long"
      : "neutral";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Metric
          label="Equity"
          value={money(info?.equity)}
          tone="gold"
          sub={
            info
              ? `${info.currency} · ${info.margin_mode} · ${info.type}`
              : account.isError
                ? "terminal unreachable"
                : "loading…"
          }
        />
        <Metric
          label="Balance"
          value={money(info?.balance)}
          sub={info ? `free margin ${money(info.margin_free)}` : undefined}
        />
        <Metric
          label="Today realised"
          value={signedMoney(today?.realised_usd)}
          tone={todayTone}
          sub={
            today?.trades !== null && today?.trades !== undefined
              ? `${today.trades} closed · ${today.wins ?? 0} wins`
              : "closed trades since local midnight"
          }
        />
        <Metric
          label="Open risk"
          value={money(risk?.open_risk_usd)}
          tone={riskTone}
          sub={
            risk
              ? `${percent(risk.open_risk_pct)} of equity · cap ${percent(risk.cap_pct)}`
              : undefined
          }
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_320px]">
        <Panel
          title="Equity growth"
          subtitle="Hourly snapshots, local time axis"
          actions={
            <div className="flex items-center gap-px border border-line/70 p-0.5">
              {RANGES.map((item) => (
                <button
                  key={item}
                  onClick={() => setRange(item)}
                  className={`px-2 py-1 font-mono text-[9.5px] font-semibold uppercase tracking-[0.08em] transition-colors ${
                    range === item
                      ? "bg-gold-500/15 text-gold-300"
                      : "text-text-faint hover:bg-ink-850 hover:text-fog"
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>
          }
          className="flex h-full flex-col"
          bodyClassName="min-h-[260px] flex-1 px-3 pb-2 pt-3"
        >
          <EquityChart points={equity.data?.points ?? []} fill />
        </Panel>

        <Panel title="Account" subtitle={info?.server}>
          {info ? (
            <div className="space-y-0.5">
              <Row label="Login" value={info.login} />
              <Row label="Account" value={info.name} />
              <Row
                label="Type"
                value={
                  <Badge tone={info.type === "demo" ? "gold" : "short"}>{info.type}</Badge>
                }
              />
              <Row label="Leverage margin used" value={money(info.margin)} />
              <Row label="Free margin" value={money(info.margin_free)} />
              <Row
                label="Margin level"
                value={info.margin_level ? `${number(info.margin_level, 0)}%` : "—"}
              />
              <Row
                label="Floating P/L"
                value={signedMoney(info.profit)}
                tone={info.profit >= 0 ? "long" : "short"}
              />
              <Row label="Swaps" value={signedMoney(info.swaps)} />
              <Row label="Build" value={String(info.terminal.build ?? "—")} />
              <Row
                label="Terminal"
                value={
                  <span className={info.terminal.connected ? "text-long" : "text-short"}>
                    {info.terminal.state ?? "unknown"}
                  </span>
                }
              />
              <Row
                label="Server time"
                value={dateTime(info.terminal.server_time_utc)}
              />
            </div>
          ) : (
            <div className="py-6 text-center text-[11px] uppercase tracking-[0.08em] text-text-faint">
              {account.isError ? "Could not read the account." : "Loading account…"}
            </div>
          )}
        </Panel>
      </div>

      <Panel
        title="Open positions"
        subtitle={
          positions.length
            ? `${positions.length} position(s) · risk at stop ${money(risk?.open_risk_usd)}`
            : "Nothing open"
        }
        bodyClassName="p-0"
      >
        {positions.length === 0 ? (
          <div className="px-5 py-6">
            <EmptyState
              title="No open positions"
              message="Orders placed from the Watchlist will appear here with live P/L and distance to stop."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] border-collapse">
              <thead>
                <tr className="border-b border-line/60">
                  <th className="th">Symbol</th>
                  <th className="th">Side</th>
                  <th className="th text-right">Lots</th>
                  <th className="th text-right">Entry</th>
                  <th className="th text-right">Current</th>
                  <th className="th text-right">Stop</th>
                  <th className="th text-right">Target</th>
                  <th className="th text-right">P/L</th>
                  <th className="th text-right">Risk</th>
                  <th className="th text-right">To stop</th>
                  <th className="th">Opened</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((position) => {
                  const unprotected = risk?.unprotected_tickets.includes(position.ticket);
                  return (
                    <tr
                      key={position.ticket}
                      className="border-b border-line/30 last:border-0 hover:bg-ink-800/40"
                    >
                      <td className="td font-semibold">
                        {position.symbol}
                        {unprotected ? (
                          <span className="ml-2 inline-flex items-center gap-1 text-[10px] text-warn">
                            <AlertIcon className="h-3 w-3" /> no stop
                          </span>
                        ) : null}
                      </td>
                      <td className="td">
                        <Badge tone={position.side === "buy" ? "long" : "short"}>
                          {position.side}
                        </Badge>
                      </td>
                      <td className="td text-right font-mono">{position.lots.toFixed(2)}</td>
                      <td className="td text-right font-mono">{price(position.price_open)}</td>
                      <td className="td text-right font-mono">{price(position.price_current)}</td>
                      <td className="td text-right font-mono">
                        {position.sl ? price(position.sl) : "—"}
                      </td>
                      <td className="td text-right font-mono">
                        {position.tp ? price(position.tp) : "—"}
                      </td>
                      <td
                        className={`td text-right font-mono ${
                          position.profit >= 0 ? "text-long" : "text-short"
                        }`}
                      >
                        {signedMoney(position.profit)}
                      </td>
                      <td className="td text-right font-mono">
                        {money(position.risk_at_stop_usd)}
                      </td>
                      <td className="td text-right font-mono">
                        {position.distance_to_stop_atr !== null
                          ? `${position.distance_to_stop_atr.toFixed(2)} ATR`
                          : "—"}
                      </td>
                      <td className="td text-fog">{dateTime(position.open_time)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
