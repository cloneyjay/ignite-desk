import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useBlackouts, useCalendar, useNews } from "../hooks/useApi";
import { api } from "../lib/api";
import { dayLabel, dateTime, shortTime } from "../lib/format";
import type { CalendarEvent } from "../lib/types";
import { Badge, Button, EmptyState, Panel, Spinner } from "../components/ui";
import { ClockIcon, NewsIcon, XIcon } from "../components/icons";

const CURRENCIES = ["USD", "EUR", "CNH", "JPY"];
const IMPACTS = [
  { value: "high,medium", label: "High + medium" },
  { value: "high", label: "High only" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
  { value: "high,medium,low", label: "All impacts" },
];

function impactTone(impact: string): "short" | "warn" | "info" | "neutral" {
  if (impact === "high") return "short";
  if (impact === "medium") return "warn";
  if (impact === "low") return "info";
  return "neutral";
}

export default function News() {
  const [impact, setImpact] = useState("high,medium");
  const [currencies, setCurrencies] = useState<string[]>(CURRENCIES);
  const [selectedNews, setSelectedNews] = useState<string | null>(null);

  const currencyQuery =
    currencies.length === 0 || currencies.length === CURRENCIES.length
      ? ""
      : currencies.join(",");

  const calendar = useCalendar(impact, currencyQuery);
  const blackouts = useBlackouts();
  const news = useNews();

  const detail = useQuery({
    queryKey: ["newsItem", selectedNews],
    queryFn: () => api.newsItem(selectedNews as string),
    enabled: Boolean(selectedNews),
  });

  const groups = useMemo(() => {
    const buckets = new Map<string, CalendarEvent[]>();
    for (const event of calendar.data?.events ?? []) {
      const key = event.time ? new Date(event.time).toDateString() : "unknown";
      const list = buckets.get(key) ?? [];
      list.push(event);
      buckets.set(key, list);
    }
    return [...buckets.entries()];
  }, [calendar.data]);

  const highCount = (calendar.data?.events ?? []).filter((event) => event.impact === "high").length;

  const toggleCurrency = (code: string) => {
    setCurrencies((current) =>
      current.includes(code) ? current.filter((item) => item !== code) : [...current, code],
    );
  };

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_368px]">
      <Panel
        title="Economic calendar"
        subtitle={
          calendar.data
            ? `${calendar.data.events.length} events · ${highCount} high impact · local time`
            : "Loading MT5 calendar…"
        }
        actions={
          <div className="flex flex-wrap items-center gap-1.5">
            <select
              value={impact}
              onChange={(event) => setImpact(event.target.value)}
              className="field w-[136px]"
            >
              {IMPACTS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <div className="flex items-center gap-1 rounded-md border border-line/70 bg-ink-900/60 p-0.5">
              {CURRENCIES.map((code) => {
                const active = currencies.includes(code);
                return (
                  <button
                    key={code}
                    onClick={() => toggleCurrency(code)}
                    className={`rounded px-1.5 py-1 text-[10.5px] font-semibold transition-colors ${
                      active ? "bg-gold-500/15 text-gold-300" : "text-fog hover:text-paper"
                    }`}
                  >
                    {code}
                  </button>
                );
              })}
            </div>
          </div>
        }
        bodyClassName="p-0"
      >
        {calendar.isError ? (
          <div className="px-5 py-8 text-center text-[12px] text-short">
            Calendar unavailable. Execution will fail closed until it recovers.
          </div>
        ) : calendar.isLoading ? (
          <div className="flex items-center justify-center gap-2 py-10 text-[12px] text-fog">
            <Spinner className="h-4 w-4" /> Loading calendar…
          </div>
        ) : groups.length === 0 ? (
          <div className="px-5 py-6">
            <EmptyState
              title="No matching events"
              message="Widen the impact filter or re-enable a currency. Blackout logic still uses high-impact USD/EUR/CNH/JPY events."
            />
          </div>
        ) : (
          <div className="max-h-[calc(100vh-230px)] overflow-y-auto">
            {groups.map(([day, events]) => (
              <div key={day}>
                <div className="sticky top-0 z-10 flex items-center justify-between border-y border-line/60 bg-ink-900/95 px-4 py-1.5 backdrop-blur">
                  <span className="text-[10.5px] font-semibold uppercase tracking-[0.16em] text-gold-300/90">
                    {dayLabel(events[0]?.time)}
                  </span>
                  <span className="font-mono text-[10px] text-fog">{events.length} events</span>
                </div>
                <table className="w-full border-collapse">
                  <thead>
                    <tr className="border-b border-line/40">
                      <th className="th w-[70px]">Time</th>
                      <th className="th w-[56px]">Ccy</th>
                      <th className="th w-[80px]">Impact</th>
                      <th className="th">Event</th>
                      <th className="th w-[72px] text-right">Actual</th>
                      <th className="th w-[72px] text-right">Forecast</th>
                      <th className="th w-[72px] text-right">Previous</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((event) => (
                      <tr
                        key={event.id}
                        className={`border-b border-line/20 last:border-0 hover:bg-ink-800/40 ${
                          event.impact === "high" ? "bg-short/[0.03]" : ""
                        }`}
                      >
                        <td className="td font-mono text-[11px] text-fog">
                          {event.time_unknown ? "tbd" : shortTime(event.time)}
                        </td>
                        <td className="td">
                          <span className="font-mono text-[11px] font-semibold text-paper/80">
                            {event.currency || "—"}
                          </span>
                        </td>
                        <td className="td">
                          <Badge tone={impactTone(event.impact)}>{event.impact}</Badge>
                        </td>
                        <td className="td">
                          <div className="truncate text-[12.5px] text-paper/90" title={event.name}>
                            {event.name}
                          </div>
                          {event.country ? (
                            <div className="text-[10px] text-fog/70">{event.country}</div>
                          ) : null}
                        </td>
                        <td className="td text-right font-mono text-[11.5px]">
                          {event.actual ?? "—"}
                        </td>
                        <td className="td text-right font-mono text-[11.5px] text-fog">
                          {event.forecast ?? "—"}
                        </td>
                        <td className="td text-right font-mono text-[11.5px] text-fog">
                          {event.previous ?? "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <div className="space-y-3">
        <Panel
          title="Blackout windows"
          subtitle={
            blackouts.data
              ? `${blackouts.data.blackouts.length} windows · ${blackouts.data.pre_minutes}m before / ${blackouts.data.post_minutes}m after`
              : "Deterministic, from the calendar"
          }
          bodyClassName="p-3"
        >
          {blackouts.isError ? (
            <div className="text-[11.5px] text-short">
              Calendar unavailable — orders fail closed.
            </div>
          ) : (blackouts.data?.blackouts ?? []).length === 0 ? (
            <div className="text-[11.5px] text-fog">No blackout windows in the next 48 hours.</div>
          ) : (
            <div className="max-h-[320px] space-y-1.5 overflow-y-auto pr-1">
              {(blackouts.data?.blackouts ?? []).map((window) => (
                <div
                  key={`${window.event_id}-${window.start}`}
                  className="rounded-md border border-short/25 bg-short/[0.06] px-2.5 py-1.5"
                >
                  <div className="flex items-center justify-between text-[10.5px]">
                    <Badge tone="short">{window.currency}</Badge>
                    <span className="font-mono text-fog">
                      {shortTime(window.start)} – {shortTime(window.end)}
                    </span>
                  </div>
                  <div className="mt-1 text-[11.5px] leading-snug text-paper/80">{window.name}</div>
                  <div className="mt-0.5 font-mono text-[10px] text-fog/70">
                    event {shortTime(window.event_time)} · {dayLabel(window.event_time)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel
          title="Terminal news"
          subtitle={news.data ? `${news.data.count} items` : "Highest priority first"}
          bodyClassName="p-0"
        >
          {news.isError ? (
            <div className="px-4 py-4 text-[11.5px] text-short">News feed unavailable.</div>
          ) : (news.data?.news ?? []).length === 0 ? (
            <div className="px-4 py-5 text-[11.5px] text-fog">No news in the last 48 hours.</div>
          ) : (
            <div className="max-h-[340px] overflow-y-auto">
              {(news.data?.news ?? []).map((item) => {
                const active = selectedNews === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => setSelectedNews(active ? null : item.id)}
                    className={`flex w-full items-start gap-2 border-b border-line/30 px-3.5 py-2.5 text-left transition-colors last:border-0 ${
                      active ? "bg-gold-500/[0.07]" : "hover:bg-ink-800/50"
                    }`}
                  >
                    <NewsIcon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fog/70" />
                    <div className="min-w-0">
                      <div className="truncate text-[12px] text-paper/90" title={item.subject}>
                        {item.subject}
                      </div>
                      <div className="mt-0.5 flex items-center gap-2 text-[10px] text-fog">
                        <span className="font-mono">{shortTime(item.time)}</span>
                        {item.category ? <span>{item.category}</span> : null}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </Panel>

        {selectedNews ? (
          <Panel
            title="Article"
            subtitle={detail.data?.subject ?? undefined}
            actions={
              <Button variant="ghost" size="sm" onClick={() => setSelectedNews(null)}>
                <XIcon className="h-3.5 w-3.5" />
              </Button>
            }
          >
            {detail.isLoading ? (
              <div className="flex items-center gap-2 text-[12px] text-fog">
                <Spinner className="h-3.5 w-3.5" /> Loading article…
              </div>
            ) : detail.isError ? (
              <div className="text-[12px] text-short">Could not load the article.</div>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center gap-2 text-[10.5px] text-fog">
                  <ClockIcon className="h-3 w-3" />
                  <span className="font-mono">{dateTime(detail.data?.time)}</span>
                  {detail.data?.category ? <Badge tone="neutral">{detail.data.category}</Badge> : null}
                </div>
                <div className="max-h-[260px] overflow-y-auto whitespace-pre-wrap text-[11.5px] leading-relaxed text-paper/80">
                  {detail.data?.body || "No body available."}
                </div>
              </div>
            )}
          </Panel>
        ) : null}

        <div className="rounded-lg border border-line/50 bg-ink-850/40 px-3 py-2 text-[10.5px] leading-relaxed text-fog/70">
          Blackouts are computed from high-impact USD, EUR, CNH and JPY events. The model never
          decides whether trading is allowed.
        </div>
      </div>
    </div>
  );
}
