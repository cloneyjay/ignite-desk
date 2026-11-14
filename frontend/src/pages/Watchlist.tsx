import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  isNoAnalysis,
  useAddSymbol,
  useAnalysis,
  useBars,
  useBlackouts,
  useHealth,
  useJob,
  useLatestAnalysis,
  useRefreshDraft,
  useRemoveSymbol,
  useSettings,
  useStartAnalysis,
  useSymbols,
} from "../hooks/useApi";
import { ApiError } from "../lib/api";
import { dateTime, price, shortTime } from "../lib/format";
import type { Analysis } from "../lib/types";
import CandleChart from "../components/CandleChart";
import AnalysisDrawer from "../components/AnalysisDrawer";
import ExecutionDialog from "../components/ExecutionDialog";
import AgentPanel from "../components/AgentPanel";
import { useToast } from "../components/Toast";
import { Badge, Button, EmptyState, Panel, ProgressBar, Spinner } from "../components/ui";
import { AlertIcon, BoltIcon, PlusIcon, RefreshIcon, XIcon } from "../components/icons";

export default function Watchlist() {
  const { push } = useToast();
  const [params, setParams] = useSearchParams();
  const symbolsQuery = useSymbols();
  const settings = useSettings();
  const health = useHealth();

  const [symbol, setSymbol] = useState<string | null>(null);
  const [tf, setTf] = useState("M15");
  const [jobId, setJobId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [execDraftId, setExecDraftId] = useState<string | null>(null);
  const [addValue, setAddValue] = useState("");
  // ?analysis=<id> pins a stored analysis for review (audit / deep link).
  const pinnedId = params.get("analysis");
  const pinned = useAnalysis(pinnedId);
  const clearPinned = () => {
    if (pinnedId) setParams({}, { replace: true });
  };

  const symbols = symbolsQuery.data?.symbols ?? [];
  const selected = symbols.find((row) => row.symbol === symbol) ?? null;

  useEffect(() => {
    if (!symbol && symbols.length) setSymbol(symbols[0].symbol);
  }, [symbol, symbols]);

  useEffect(() => {
    if (symbol && symbols.length && !symbols.some((row) => row.symbol === symbol)) {
      setSymbol(symbols[0].symbol);
      setJobId(null);
      setDrawerOpen(false);
    }
  }, [symbol, symbols]);

  const bars = useBars(symbol, tf, 200);
  const latest = useLatestAnalysis(symbol, tf);
  const blackouts = useBlackouts();
  const job = useJob(jobId);
  const jobAnalysis = useAnalysis(job.data?.analysis_id ?? null);

  const start = useStartAnalysis();
  const refresh = useRefreshDraft();
  const addSymbol = useAddSymbol();
  const removeSymbol = useRemoveSymbol();

  const timeframes = settings.data?.timeframes ?? ["M5", "M15", "M30", "H1"];
  const running = job.data?.status === "running" || job.data?.status === "queued";
  const stored = latest.data ?? null;
  const analysis: Analysis | null =
    jobAnalysis.data ??
    pinned.data ??
    (stored && stored.symbol === symbol && stored.timeframe === tf ? stored : null);
  const failed = job.data?.status === "failed";

  const chooseSymbol = (next: string) => {
    if (next === symbol) return;
    clearPinned();
    setSymbol(next);
    setJobId(null);
    setDrawerOpen(false);
  };

  const chooseTimeframe = (next: string) => {
    if (next === tf) return;
    clearPinned();
    setTf(next);
    setJobId(null);
    setDrawerOpen(false);
  };

  const analyse = () => {
    if (!symbol) return;
    start.mutate(
      { symbol, timeframe: tf, samples: 25 },
      {
        onSuccess: (response) => {
          clearPinned();
          setJobId(response.job.job_id);
          setDrawerOpen(true);
        },
        onError: (error) =>
          push({
            tone: "danger",
            title: "Could not start analysis",
            message: error instanceof ApiError ? error.message : String(error),
          }),
      },
    );
  };

  const submitSymbol = (event: React.FormEvent) => {
    event.preventDefault();
    const value = addValue.trim().toUpperCase();
    if (!value) return;
    addSymbol.mutate(value, {
      onSuccess: (response) => {
        setAddValue("");
        setSymbol(response.symbol.symbol);
        setJobId(null);
        setDrawerOpen(false);
        push({
          tone: "ok",
          title: `${response.symbol.symbol} added`,
          message: "Mirrored to MT5 Market Watch and stored locally.",
        });
      },
      onError: (error) =>
        push({
          tone: "danger",
          title: "Could not add symbol",
          message: error instanceof ApiError ? error.message : String(error),
        }),
    });
  };

  const remove = (value: string) => {
    if (!window.confirm(`Remove ${value} from the watchlist and MT5 Market Watch?`)) return;
    removeSymbol.mutate(value, {
      onSuccess: () =>
        push({ tone: "info", title: `${value} removed`, message: "Watchlist updated." }),
      onError: (error) =>
        push({
          tone: "danger",
          title: "Could not remove symbol",
          message: error instanceof ApiError ? error.message : String(error),
        }),
    });
  };

  const blackoutList = blackouts.data?.blackouts ?? [];
  // Sort blackouts by next occurrence (soonest first)
  const sortedBlackouts = [...blackoutList].sort((a, b) => new Date(a.start).getTime() - new Date(b.start).getTime());

  const latestError = latest.error;
  const latestProblem = latest.isError && !isNoAnalysis(latestError) ? latestError : null;

  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_300px] xl:grid-cols-[280px_minmax(0,1fr)_300px]">
        {/* Left column: Watchlist + Blackouts */}
        <div className="hidden space-y-3 xl:block">
          <Panel title="Watchlist" subtitle="Mirrors MT5 Market Watch" bodyClassName="p-2">
          {symbols.length === 0 ? (
            <div className="px-2 py-3 text-[12px] text-fog">
              {symbolsQuery.isLoading ? "Loading…" : "No symbols yet. Add one below."}
            </div>
          ) : (
            <div className="space-y-1">
              {symbols.map((row) => {
                const active = row.symbol === symbol;
                return (
                  <div
                    key={row.symbol}
                    className={`group flex items-center gap-2 rounded-lg border px-2.5 py-2 transition-colors ${
                      active
                        ? "border-gold-500/40 bg-gold-500/[0.08]"
                        : "border-transparent hover:border-line/70 hover:bg-ink-800/50"
                    }`}
                  >
                    <button
                      onClick={() => chooseSymbol(row.symbol)}
                      className="min-w-0 flex-1 text-left"
                    >
                      <div className="flex items-center justify-between">
                        <span
                          className={`text-[12.5px] font-semibold ${
                            active ? "text-gold-300" : "text-paper"
                          }`}
                        >
                          {row.symbol}
                        </span>
                        <span className="font-mono text-[11px] text-fog">
                          {row.spread_points !== null ? `${row.spread_points.toFixed(0)}p` : "—"}
                        </span>
                      </div>
                      <div className="mt-0.5 flex items-center justify-between font-mono text-[10.5px] text-fog">
                        <span>{row.bid !== null ? price(row.bid, row.digits) : "—"}</span>
                        <span>{row.ask !== null ? price(row.ask, row.digits) : "—"}</span>
                      </div>
                    </button>
                    <button
                      onClick={() => remove(row.symbol)}
                      className="rounded p-0.5 text-fog/40 opacity-0 transition-opacity hover:text-short group-hover:opacity-100"
                      aria-label={`Remove ${row.symbol}`}
                    >
                      <XIcon className="h-3 w-3" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          <form onSubmit={submitSymbol} className="mt-2 flex gap-1.5 border-t border-line/60 px-1 pt-2">
            <input
              value={addValue}
              onChange={(event) => setAddValue(event.target.value.toUpperCase())}
              placeholder="EURUSD"
              className="field min-w-0 flex-1 uppercase"
              maxLength={32}
            />
            <Button
              type="submit"
              variant="secondary"
              size="sm"
              loading={addSymbol.isPending}
              disabled={!addValue.trim()}
            >
              <PlusIcon className="h-3.5 w-3.5" />
              Add
            </Button>
          </form>
        </Panel>

        <Panel title="Blackouts" subtitle="High-impact windows · deterministic" bodyClassName="p-3">
          {blackouts.isError ? (
            <div className="text-[11.5px] text-short">
              Calendar unavailable — execution will fail closed.
            </div>
          ) : sortedBlackouts.length === 0 ? (
            <div className="text-[11.5px] text-fog">No blackout windows in range.</div>
          ) : (
            <div className="space-y-1.5">
              {sortedBlackouts.slice(0, 5).map((window) => {
                const startTime = new Date(window.start).getTime();
                const now = Date.now();
                const isActive = startTime <= now && new Date(window.end).getTime() >= now;
                const isUpcoming = startTime > now && startTime - now <= 60 * 60 * 1000; // within 60 min
                const rowTone = isActive ? "short" : isUpcoming ? "warn" : "neutral";
                const timeTone = isActive ? "short" : isUpcoming ? "warn" : "fog";
                return (
                  <div
                    key={`${window.event_id}-${window.start}`}
                    className={`rounded-md border px-2.5 py-1.5 ${
                      rowTone === "short"
                        ? "border-short/30 bg-short/10"
                        : rowTone === "warn"
                        ? "border-warn/30 bg-warn/10"
                        : "border-line/60 bg-ink-800/50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span
                        className={`font-mono text-[10.5px] px-1.5 py-0.5 rounded text-[10px] ${
                          rowTone === "short"
                            ? "bg-short/20 text-short"
                            : rowTone === "warn"
                            ? "bg-warn/20 text-warn"
                            : "bg-ink-800 text-fog"
                        }`}
                      >
                        {window.currency}
                      </span>
                      <span className={`font-mono text-[10.5px] ${timeTone}`}>
                        {shortTime(window.start)}–{shortTime(window.end)}
                      </span>
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-paper/75" title={window.name}>
                      {window.name}
                      {isActive && (
                        <span className="ml-1.5 font-mono text-[9px] text-short">ACTIVE NOW</span>
                      )}
                    </div>
                  </div>
                );
              })}
              {blackouts.data ? (
                <div className="pt-1 text-[11px] text-fog">
                  {blackouts.data.pre_minutes}m before / {blackouts.data.post_minutes}m after
                </div>
              ) : null}
            </div>
          )}
        </Panel>
        </div>

      {/* Main column: Symbol header + Candles */}
      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line/80 bg-ink-850/70 px-4 py-3 shadow-panel">
          <div className="flex items-center gap-4 min-w-0">
            <div>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[18px] font-bold tracking-wide text-paper">
                  {symbol ?? "—"}
                </span>
                {selected ? <Badge tone="neutral">{selected.digits} digits</Badge> : null}
              </div>
              <div className="mt-0.5 flex items-center gap-3 font-mono text-[11px] text-fog">
                <span>bid {selected?.bid !== null && selected ? price(selected.bid, selected.digits) : "—"}</span>
                <span>ask {selected?.ask !== null && selected ? price(selected.ask, selected.digits) : "—"}</span>
                <span>
                  spread{" "}
                  {selected?.spread_points !== null && selected
                    ? `${selected.spread_points.toFixed(0)} pts`
                    : "—"}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-0.5 rounded-lg border border-line/70 bg-ink-900/60 p-0.5">
              {timeframes.map((item) => (
                <button
                  key={item}
                  onClick={() => chooseTimeframe(item)}
                  className={`rounded-md px-2.5 py-1 text-[11.5px] font-semibold transition-colors ${
                    tf === item
                      ? "bg-gold-500/15 text-gold-300"
                      : "text-fog hover:bg-ink-800 hover:text-paper"
                  }`}
                >
                  {item}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {analysis && !drawerOpen ? (
              <Button variant="ghost" size="sm" onClick={() => setDrawerOpen(true)}>
                View analysis
                <Badge tone={analysis.signal.side === "long" ? "long" : analysis.signal.side === "short" ? "short" : "neutral"}>
                  {analysis.signal.side === "none" ? "no trade" : analysis.signal.side}
                </Badge>
              </Button>
            ) : null}
            <Button
              variant="primary"
              onClick={analyse}
              loading={start.isPending || running}
              disabled={!symbol || !health.data?.kronos.ready}
              title={
                health.data?.kronos.ready
                  ? "Run the deterministic analysis graph"
                  : "Kronos worker is offline"
              }
            >
              <BoltIcon className="h-3.5 w-3.5" />
              {running ? "Analysing" : "Analyse"}
            </Button>
          </div>
        </div>

        {running && job.data ? (
          <div className="rounded-lg border border-gold-500/25 bg-gold-500/[0.06] px-4 py-2.5">
            <div className="mb-1.5 flex items-center justify-between text-[11.5px]">
              <span className="flex items-center gap-2 text-gold-300">
                <Spinner className="h-3 w-3" />
                {job.data.message}
              </span>
              <span className="font-mono text-gold-300">{job.data.pct}%</span>
            </div>
            <ProgressBar pct={job.data.pct} />
          </div>
        ) : null}

        {failed ? (
          <div className="flex items-start gap-2 rounded-lg border border-short/40 bg-short/10 px-4 py-2.5 text-[12px] text-short">
            <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <div className="font-semibold">Analysis failed</div>
              <div className="text-short/80">{job.data?.error}</div>
            </div>
          </div>
        ) : null}

        {latestProblem ? (
          <div className="flex items-center gap-2 rounded-lg border border-warn/35 bg-warn/10 px-4 py-2 text-[11.5px] text-warn">
            <AlertIcon className="h-3.5 w-3.5" />
            Could not load the stored analysis:{" "}
            {latestProblem instanceof ApiError ? latestProblem.message : String(latestProblem)}
          </div>
        ) : null}

        <Panel
          title="Candles"
          subtitle={
            bars.data
              ? `${bars.data.count} closed bars · last ${dateTime(bars.data.last_bar_time)} · blackout windows shaded`
              : "Loading closed bars…"
          }
          actions={
            <>
              {analysis ? (
                <span className="rounded border border-gold-500/30 bg-gold-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-gold-300 mr-2">
                  Forecast overlay
                </span>
              ) : null}
              <Button
                variant="ghost"
                size="sm"
                onClick={() => bars.refetch()}
                loading={bars.isFetching}
                title="Reload bars"
              >
                <RefreshIcon className="h-3.5 w-3.5" />
              </Button>
            </>
          }
          bodyClassName="p-2"
        >
          {bars.isError ? (
            <div className="px-3 py-10 text-center text-[12px] text-short">
              Bars unavailable: {bars.error instanceof ApiError ? bars.error.message : "terminal error"}
            </div>
          ) : bars.data ? (
            <CandleChart
              bars={bars.data.bars}
              blackouts={sortedBlackouts}
              analysis={analysis}
              timeframe={tf}
              digits={selected?.digits ?? 2}
              height={430}
            />
          ) : (
            <div className="flex items-center justify-center gap-2 py-10 text-[12px] text-fog">
              <Spinner className="h-4 w-4" /> Loading candles…
            </div>
          )}
        </Panel>

        {/* AgentPanel for mobile/tablet (stacked below chart) */}
        <div className="lg:hidden space-y-3">
          <AgentPanel />
        </div>

        {!symbol ? (
          <EmptyState
            title="Add a symbol to begin"
            message="Adding a symbol calls MT5 Market Watch first, then stores the validated contract specification."
          />
        ) : null}
      </div>

      {/* Right column: AgentPanel */}
      <div className="hidden min-w-0 space-y-3 lg:block xl:sticky xl:top-20">
        <AgentPanel />
      </div>

      {drawerOpen ? (
        <AnalysisDrawer
          analysis={analysis}
          job={job.data ?? null}
          onClose={() => setDrawerOpen(false)}
          onExecute={(draftId) => setExecDraftId(draftId)}
          onRefreshDraft={() => {
            if (!analysis) return;
            refresh.mutate(analysis.id, {
              onError: (error) =>
                push({
                  tone: "danger",
                  title: "Could not refresh the draft",
                  message: error instanceof ApiError ? error.message : String(error),
                }),
            });
          }}
          onReanalyse={analyse}
          refreshing={refresh.isPending}
          analysing={start.isPending || running}
        />
      ) : null}

      {execDraftId ? (
        <ExecutionDialog
          draftId={execDraftId}
          onClose={() => setExecDraftId(null)}
          onFilled={() => {
            latest.refetch();
          }}
        />
      ) : null}
    </div>
  );
}
