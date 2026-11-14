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
import { Badge, Button, Panel, ProgressBar, Spinner } from "../components/ui";
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
                    className={`group flex items-center gap-2 border-l-2 px-2.5 py-2 transition-colors ${
                      active
                        ? "border-l-gold-500 bg-gold-500/[0.06]"
                        : "border-l-transparent hover:bg-ink-850/70"
                    }`}
                  >
                    <button
                      onClick={() => chooseSymbol(row.symbol)}
                      className="min-w-0 flex-1 text-left"
                    >
                      <div className="flex items-center justify-between">
                        <span
                          className={`text-[12px] font-semibold tracking-[0.02em] ${
                            active ? "text-gold-300" : "text-paper"
                          }`}
                        >
                          {row.symbol}
                        </span>
                        <span className="font-mono text-[10px] text-fog">
                          {row.spread_points !== null ? `${row.spread_points.toFixed(0)}p` : "—"}
                        </span>
                      </div>
                      <div className="mt-0.5 flex items-center justify-between font-mono text-[10px] text-text-faint">
                        <span>{row.bid !== null ? price(row.bid, row.digits) : "—"}</span>
                        <span>{row.ask !== null ? price(row.ask, row.digits) : "—"}</span>
                      </div>
                    </button>
                    <button
                      onClick={() => remove(row.symbol)}
                      className="p-0.5 text-fog/40 opacity-0 transition-opacity hover:text-short group-hover:opacity-100"
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
                    className={`border-l-2 px-2.5 py-1.5 ${
                      rowTone === "short"
                        ? "border-l-short bg-short/[0.06]"
                        : rowTone === "warn"
                          ? "border-l-warn bg-warn/[0.06]"
                          : "border-l-line/80 bg-ink-850/50"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span
                        className={`px-1.5 py-0.5 font-mono text-[9.5px] font-semibold uppercase tracking-[0.06em] ${
                          rowTone === "short"
                            ? "bg-short/15 text-short"
                            : rowTone === "warn"
                              ? "bg-warn/15 text-warn"
                              : "bg-ink-800 text-fog"
                        }`}
                      >
                        {window.currency}
                      </span>
                      <span className={`font-mono text-[10px] ${timeTone}`}>
                        {shortTime(window.start)}–{shortTime(window.end)}
                      </span>
                    </div>
                    <div className="mt-1 truncate text-[10.5px] text-paper/75" title={window.name}>
                      {window.name}
                      {isActive && (
                        <span className="ml-1.5 font-mono text-[9px] uppercase tracking-[0.06em] text-short">
                          active now
                        </span>
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
        {/* Below xl the watchlist rail is hidden, so symbol selection and the
            add form stay available in a compact strip above the chart. */}
        <div className="flex flex-wrap items-stretch gap-2 border border-line/80 bg-ink-900 p-2.5 xl:hidden">
          <label className="flex min-w-[160px] flex-1 items-center gap-2">
            <span className="eyebrow shrink-0">Symbol</span>
            <select
              value={symbol ?? ""}
              onChange={(event) => chooseSymbol(event.target.value)}
              className="field min-w-0 flex-1"
              disabled={symbols.length === 0}
              aria-label="Select instrument"
            >
              {symbols.length === 0 ? <option value="">No symbols</option> : null}
              {symbols.map((row) => (
                <option key={row.symbol} value={row.symbol}>
                  {row.symbol}
                </option>
              ))}
            </select>
          </label>
          <form onSubmit={submitSymbol} className="flex min-w-[200px] flex-1 items-center gap-1.5">
            <span className="eyebrow shrink-0">Add</span>
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
        </div>

        <div className="border border-line/80 bg-ink-900">
          {/* Identity + market data, with the primary action kept on the same line. */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
            <div className="min-w-0 flex-1 basis-[210px]">
              <div className="flex items-center gap-2.5">
                <span
                  data-testid="instrument-symbol"
                  className="truncate font-mono text-[20px] font-semibold leading-none tracking-[0.02em] text-paper"
                >
                  {symbol ?? "—"}
                </span>
                {selected ? (
                  <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-text-faint">
                    {selected.digits} digits
                  </span>
                ) : null}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[10px] uppercase tracking-[0.04em] text-text-faint">
                <span>
                  bid{" "}
                  <b className="font-medium text-paper">
                    {selected?.bid !== null && selected ? price(selected.bid, selected.digits) : "—"}
                  </b>
                </span>
                <span>
                  ask{" "}
                  <b className="font-medium text-paper">
                    {selected?.ask !== null && selected ? price(selected.ask, selected.digits) : "—"}
                  </b>
                </span>
                <span>
                  spread{" "}
                  <b className="font-medium text-paper">
                    {selected?.spread_points !== null && selected
                      ? `${selected.spread_points.toFixed(0)} pts`
                      : "—"}
                  </b>
                </span>
              </div>
            </div>

            <Button
              variant="primary"
              size="sm"
              className="ml-auto whitespace-nowrap"
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

          {/* Timeframe and review live on their own ruled band. */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-line/50 px-4 py-2">
            <div className="flex items-center gap-2">
              <span className="mr-1 text-[9px] font-semibold uppercase tracking-[0.1em] text-text-faint">
                TF
              </span>
              <div className="flex items-center gap-0.5 border border-line/70 bg-ink-950 p-0.5">
                {timeframes.map((item) => (
                  <button
                    key={item}
                    onClick={() => chooseTimeframe(item)}
                    className={`px-2 py-1 font-mono text-[10.5px] font-medium transition-colors ${
                      tf === item
                        ? "bg-gold-500/15 text-gold-300"
                        : "text-fog hover:bg-ink-850 hover:text-paper"
                    }`}
                  >
                    {item}
                  </button>
                ))}
              </div>
            </div>

            <div className="ml-auto">
              {analysis && !drawerOpen ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="whitespace-nowrap"
                  onClick={() => setDrawerOpen(true)}
                >
                  View analysis
                  <Badge
                    tone={
                      analysis.signal.side === "long"
                        ? "long"
                        : analysis.signal.side === "short"
                          ? "short"
                          : "neutral"
                    }
                  >
                    {analysis.signal.side === "none" ? "no trade" : analysis.signal.side}
                  </Badge>
                </Button>
              ) : null}
            </div>
          </div>
        </div>

        {running && job.data ? (
          <div className="border border-gold-500/25 border-l-2 border-l-gold-500 bg-gold-500/[0.05] px-4 py-2.5">
            <div className="mb-1.5 flex items-center justify-between text-[11px]">
              <span className="flex items-center gap-2 text-gold-300">
                <Spinner className="h-3 w-3" />
                {job.data.message}
              </span>
              <span className="font-mono tabular-nums text-gold-300">{job.data.pct}%</span>
            </div>
            <ProgressBar pct={job.data.pct} />
          </div>
        ) : null}

        {failed ? (
          <div className="flex items-start gap-2 border border-short/35 border-l-2 border-l-short bg-short/[0.06] px-4 py-2.5 text-[11.5px] text-short">
            <AlertIcon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <div>
              <div className="font-semibold uppercase tracking-[0.06em]">Analysis failed</div>
              <div className="mt-0.5 text-short/80">{job.data?.error}</div>
            </div>
          </div>
        ) : null}

        {latestProblem ? (
          <div className="flex items-center gap-2 border border-warn/30 border-l-2 border-l-warn bg-warn/[0.06] px-4 py-2 text-[11px] text-warn">
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
                <span className="mr-2 border border-gold-500/30 bg-gold-500/10 px-2 py-0.5 font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-gold-300">
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
          {!symbol ? (
            <div className="flex min-h-[360px] flex-col items-center justify-center px-6 text-center">
              <div className="eyebrow mb-2">No instrument selected</div>
              <p className="text-[12.5px] text-paper/80">Add a symbol to begin</p>
              <p className="mt-1.5 max-w-sm text-[11px] leading-relaxed text-fog">
                Adding a symbol calls MT5 Market Watch first, then stores the validated contract
                specification.
              </p>
            </div>
          ) : bars.isError ? (
            <div className="px-3 py-10 text-center text-[11.5px] text-short">
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
            <div className="flex min-h-[430px] items-center justify-center gap-2 text-[11.5px] text-fog">
              <Spinner className="h-4 w-4" /> Loading candles…
            </div>
          )}
        </Panel>

        {/* AgentPanel for mobile/tablet (stacked below chart) */}
        <div className="space-y-3 lg:hidden">
          <AgentPanel />
        </div>
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
