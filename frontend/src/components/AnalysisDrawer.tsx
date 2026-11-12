import { useEffect, useState } from "react";

import { useDraft, useNarrative, useGenerateNarrative } from "../hooks/useApi";
import type { Analysis, Draft, Job, Narrative } from "../lib/types";
import { dateTime, money, number, percent, price } from "../lib/format";
import { Badge, Button, EmptyState, ProgressBar, Row, Spinner } from "./ui";
import { AlertIcon, BoltIcon, CheckIcon, RefreshIcon, XIcon, BrainIcon } from "./icons";

function signalTone(side: string): "long" | "short" | "neutral" {
  if (side === "long") return "long";
  if (side === "short") return "short";
  return "neutral";
}

export default function AnalysisDrawer({
  analysis,
  job,
  onClose,
  onExecute,
  onRefreshDraft,
  onReanalyse,
  refreshing,
  analysing,
}: {
  analysis: Analysis | null;
  job: Job | null;
  onClose: () => void;
  onExecute: (draftId: string) => void;
  onRefreshDraft: () => void;
  onReanalyse: () => void;
  refreshing: boolean;
  analysing: boolean;
}) {
  const draft: Draft | null = analysis?.draft ?? null;
  const live = useDraft(draft?.id ?? null, Boolean(draft));
  const narrative = useNarrative(analysis?.id ?? null);
  const generateNarrative = useGenerateNarrative();
  const active = live.data?.draft ?? draft;
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const remaining = active
    ? Math.max(0, Math.floor((new Date(active.expires_at).getTime() - now) / 1000))
    : 0;
  const running = job?.status === "running" || job?.status === "queued";
  const executable = Boolean(active?.executable && remaining > 0 && !active?.blocked);

  const handleGenerateNarrative = (refresh = false) => {
    if (!analysis?.id) return;
    generateNarrative.mutate({ analysisId: analysis.id, refresh });
  };

  return (
    <aside className="fixed right-0 top-[58px] z-50 flex h-[calc(100vh-58px)] w-[540px] max-w-full animate-slide-in flex-col border-l border-line bg-ink-900/95 shadow-drawer backdrop-blur">
      <header className="flex items-start justify-between gap-3 border-b border-line/70 px-5 py-4">
        <div>
          <div className="flex items-center gap-2">
            <BoltIcon className="h-4 w-4 text-gold-400" />
            <h2 className="text-[14px] font-semibold text-paper">
              {analysis ? `${analysis.symbol} · ${analysis.timeframe}` : "Analysis"}
            </h2>
            {analysis ? <Badge tone="gold">{analysis.signal.version}</Badge> : null}
          </div>
          <p className="mt-1 text-[11.5px] text-fog">
            {analysis
              ? `last closed bar ${dateTime(analysis.last_bar_time)} · ${analysis.samples} paths · horizon ${analysis.horizon}`
              : "Deterministic forecast, no LLM in the numbers."}
          </p>
        </div>
        <button
          onClick={onClose}
          className="rounded-md p-1.5 text-fog transition-colors hover:bg-ink-800 hover:text-paper"
          aria-label="Close analysis"
        >
          <XIcon className="h-4 w-4" />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {running ? (
          <RunningPanel job={job as Job} />
        ) : !analysis ? (
          <EmptyState
            title="No analysis for this bar"
            message="Pick a timeframe and press Analyse. The result is cached per closed bar."
          />
        ) : (
          <div className="space-y-5">
            <SignalHeader analysis={analysis} />

            <section>
              <SectionTitle>Forecast</SectionTitle>
              <div className="grid grid-cols-3 gap-2">
                <Mini label="p up" value={percent(analysis.signal.p_up)} tone={signalTone(analysis.signal.side)} />
                <Mini
                  label="expected"
                  value={`${analysis.signal.edge >= 0 ? "+" : "−"}${number(Math.abs(analysis.signal.edge), 2)}`}
                  hint="USD per ounce"
                />
                <Mini
                  label="edge"
                  value={`${number(analysis.signal.edge_atr, 2)} ATR`}
                  tone={signalTone(analysis.signal.side)}
                />
                <Mini label="dispersion" value={number(analysis.signal.dispersion, 2)} />
                <Mini label="ATR" value={number(analysis.features.atr, 2)} />
                <Mini label="spread" value={`${number(analysis.features.spread_points, 0)} pts`} />
              </div>
            </section>

            <section>
              <SectionTitle>Why</SectionTitle>
              <div className="space-y-1.5">
                {analysis.signal.reasons.map((reason) => (
                  <div
                    key={reason}
                    className="flex items-start gap-2 rounded-md border border-line/50 bg-ink-850/50 px-3 py-2 text-[12px] text-paper/80"
                  >
                    {analysis.signal.side === "none" ? (
                      <AlertIcon className="mt-0.5 h-3 w-3 shrink-0 text-warn" />
                    ) : (
                      <CheckIcon className="mt-0.5 h-3 w-3 shrink-0 text-long" />
                    )}
                    {reason}
                  </div>
                ))}
                {analysis.signal.reasons.length === 0 ? (
                  <div className="text-[12px] text-fog">No rule notes were recorded.</div>
                ) : null}
              </div>
            </section>

            {active ? (
              <DraftPanel
                draft={active}
                analysis={analysis}
                remaining={remaining}
                executable={executable}
                onExecute={() => onExecute(active.id)}
                onRefresh={onRefreshDraft}
                refreshing={refreshing}
              />
            ) : (
              <EmptyState
                title="No draft order"
                message="The rule returned NO TRADE for this bar. Nothing to size, nothing to send."
                action={
                  <Button variant="secondary" onClick={onReanalyse} loading={analysing}>
                    <RefreshIcon className="h-3.5 w-3.5" /> Re-analyse
                  </Button>
                }
              />
            )}

            <NarrativePanel
              analysis={analysis}
              narrative={narrative.data ?? null}
              loading={narrative.isLoading}
              generating={generateNarrative.isPending}
              onGenerate={handleGenerateNarrative}
            />

            <footer className="space-y-1 border-t border-line/60 pt-3">
              <Row label="Model" value={analysis.model_id} />
              <Row label="Inference" value={`${number(analysis.infer_s, 2)} s`} />
              <Row label="Signal / risk" value={`${analysis.signal.version} · ${analysis.risk_version}`} />
              <Row label="Analysed" value={dateTime(analysis.created_at)} />
              <div className="pt-2 text-[10.5px] leading-relaxed text-fog/70">
                Numbers come from the deterministic graph. Commentary, once enabled, is
                labelled separately and can never change an order.
              </div>
            </footer>
          </div>
        )}
      </div>
    </aside>
  );
}

function NarrativePanel({
  analysis,
  narrative,
  loading,
  generating,
  onGenerate,
}: {
  analysis: Analysis;
  narrative: Narrative | null;
  loading: boolean;
  generating: boolean;
  onGenerate: (refresh?: boolean) => void;
}) {
  if (!analysis) return null;

  const notGenerated = narrative?.status === "not_generated" || narrative?.narrative === null;

  if (notGenerated && !loading && !generating) {
    return (
      <section>
        <SectionTitle>AI commentary — non-binding</SectionTitle>
        <div className="rounded-xl border border-line/50 bg-ink-850/40 p-4">
          <p className="text-[12px] text-fog mb-3">
            The deterministic engine has produced the forecast, signal and draft above.
            This section adds a short desk note written by the LLM — it cannot change any
            number, override a block, or execute a trade.
          </p>
          <Button
            variant="secondary"
            onClick={() => onGenerate(false)}
            loading={generating}
            className="w-full"
          >
            <BrainIcon className="h-3.5 w-3.5 mr-2" />
            Generate commentary
          </Button>
        </div>
      </section>
    );
  }

  if (loading || generating) {
    return (
      <section>
        <SectionTitle>AI commentary — non-binding</SectionTitle>
        <div className="rounded-xl border border-gold-500/25 bg-gold-500/[0.06] p-4">
          <div className="flex items-center gap-2">
            <Spinner className="h-4 w-4" />
            <span className="text-[12px] text-gold-300">
              {loading ? "Loading commentary…" : "Generating commentary…"}
            </span>
          </div>
        </div>
      </section>
    );
  }

  if (narrative && narrative.narrative) {
    const isFallback = narrative.provider === "template" || narrative.fallback;
    const cards = narrative.cards ?? [];
    const checks = narrative.checks ?? {};

    return (
      <section>
        <SectionTitle>AI commentary — non-binding</SectionTitle>
        <div className="rounded-xl border border-line/50 bg-ink-850/40 p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <BrainIcon className="h-4 w-4 text-gold-400" />
              <span className="text-[11px] font-medium text-paper">Commentary</span>
              {isFallback && (
                <Badge tone="warn" className="text-[9px]">
                  Template (model unavailable)
                </Badge>
              )}
              {!isFallback && (
                <Badge tone="gold" className="text-[9px]">
                  {narrative.provider}
                </Badge>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onGenerate(true)}
                loading={generating}
              >
                <RefreshIcon className="h-3.5 w-3.5" />
                Regenerate
              </Button>
            </div>
          </div>

          <p className="text-[12px] text-paper/90 leading-relaxed mb-3 whitespace-pre-wrap">
            {narrative.narrative}
          </p>

          {isFallback && (
            <p className="text-[10.5px] text-fog/70 mb-3">
              The model was unavailable or its output failed numeric validation. A
              deterministic template was used instead.
            </p>
          )}

          <div className="space-y-1 text-[10.5px] text-fog/60">
            <Row
              label="Provider"
              value={
                narrative.provider === "template"
                  ? "deterministic template"
                  : `${narrative.provider} · ${narrative.model ?? "?"}`
              }
            />
            <Row label="Generated" value={dateTime(narrative.created_at)} />
            {narrative.latency_ms && (
              <Row label="Latency" value={`${narrative.latency_ms} ms`} />
            )}
            {cards.length > 0 && (
              <Row
                label="Desk notes"
                value={cards.map((c) => c.id).join(", ")}
              />
            )}
            {checks.numbers_checked && (
              <Row label="Numbers checked" value={checks.numbers_checked.toString()} />
            )}
          </div>
        </div>
      </section>
    );
  }

  return null;
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-2 text-[10.5px] font-semibold uppercase tracking-[0.16em] text-fog">
      {children}
    </h3>
  );
}

function SignalHeader({ analysis }: { analysis: Analysis }) {
  const tone = signalTone(analysis.signal.side);
  const label =
    analysis.signal.side === "long"
      ? "LONG"
      : analysis.signal.side === "short"
        ? "SHORT"
        : "NO TRADE";
  return (
    <div
      className={`flex items-center justify-between rounded-xl border px-4 py-3.5 ${
        tone === "long"
          ? "border-long/35 bg-long/[0.08]"
          : tone === "short"
            ? "border-short/35 bg-short/[0.08]"
            : "border-line bg-ink-850/60"
      }`}
    >
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fog">
          Signal
        </div>
        <div
          className={`mt-0.5 font-mono text-[24px] font-bold leading-none ${
            tone === "long" ? "text-long" : tone === "short" ? "text-short" : "text-paper/70"
          }`}
        >
          {label}
        </div>
      </div>
      <div className="text-right">
        <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fog">
          Confidence
        </div>
        <div className="mt-0.5 font-mono text-[18px] tabular-nums text-paper">
          {percent(analysis.signal.p_up, 0)}
        </div>
      </div>
    </div>
  );
}

function Mini({
  label,
  value,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: string;
  tone?: "neutral" | "long" | "short";
  hint?: string;
}) {
  const color =
    tone === "long" ? "text-long" : tone === "short" ? "text-short" : "text-paper";
  return (
    <div className="rounded-lg border border-line/60 bg-ink-850/60 px-3 py-2" title={hint}>
      <div className="text-[10px] uppercase tracking-[0.12em] text-fog">{label}</div>
      <div className={`mt-0.5 font-mono text-[13.5px] tabular-nums ${color}`}>{value}</div>
    </div>
  );
}

function RunningPanel({ job }: { job: Job }) {
  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-gold-500/25 bg-gold-500/[0.06] px-4 py-4">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2 text-[12.5px] font-semibold text-gold-300">
            <Spinner className="h-3.5 w-3.5" />
            {job.symbol} · {job.timeframe}
          </div>
          <span className="font-mono text-[12px] text-gold-300">{job.pct}%</span>
        </div>
        <ProgressBar pct={job.pct} />
        <div className="mt-2 text-[11.5px] text-fog">{job.message}</div>
      </div>

      <div className="space-y-1.5">
        {job.progress.map((step, index) => (
          <div
            key={`${step.step}-${index}`}
            className="flex items-center justify-between rounded-md border border-line/40 bg-ink-850/40 px-3 py-1.5 font-mono text-[11px]"
          >
            <span className="text-fog">{step.step}</span>
            <span className="text-paper/70">{step.message}</span>
            <span className="text-fog/60">{step.pct}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function DraftPanel({
  draft,
  analysis,
  remaining,
  executable,
  onExecute,
  onRefresh,
  refreshing,
}: {
  draft: Draft;
  analysis: Analysis;
  remaining: number;
  executable: boolean;
  onExecute: () => void;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const atr = analysis.features.atr || 1;
  const checks = draft.checks ?? [];
  const failures = checks.filter((check) => !check.ok);

  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <SectionTitle>Draft order</SectionTitle>
        <span
          className={`font-mono text-[11px] ${
            remaining <= 0 ? "text-short" : remaining < 20 ? "text-warn" : "text-fog"
          }`}
        >
          {remaining > 0 ? `expires in ${remaining}s` : "expired"}
        </span>
      </div>

      <div className="rounded-xl border border-line/70 bg-ink-850/70 p-4">
        <div className="mb-3 flex items-center justify-between">
          <Badge tone={draft.side === "long" ? "long" : "short"}>
            {draft.side} {draft.lots} lots
          </Badge>
          <span className="text-[11px] text-fog">
            R:R <b className="font-mono text-paper/80">{number(draft.rr, 2)}</b>
          </span>
        </div>

        <div className="grid grid-cols-2 gap-x-6">
          <Row label="Entry" value={price(draft.reference_price)} />
          <Row label="Risk" value={money(draft.risk_usd)} />
          <Row label="Stop loss" value={`${price(draft.sl)} · ${number(Math.abs(draft.reference_price - draft.sl) / atr, 2)} ATR`} tone="short" />
          <Row label="Take profit" value={`${price(draft.tp)} · ${number(Math.abs(draft.tp - draft.reference_price) / atr, 2)} ATR`} tone="long" />
          <Row label="Risk %" value={percent(draft.risk_pct)} />
          <Row label="Margin" value={money(draft.margin)} />
          <Row label="Worst case" value={money(draft.worst_case_usd)} tone="short" />
          <Row label="State" value={draft.state} />
        </div>

        {draft.blocked ? (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-short/40 bg-short/10 px-3 py-2.5 text-[12px] text-short">
            <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{draft.block_reason ?? "This draft is blocked."}</span>
          </div>
        ) : null}

        {!draft.blocked && checks.length > 0 ? (
          <div className="mt-3 space-y-1">
            {checks.map((check) => (
              <div
                key={check.code}
                className={`flex items-start gap-2 text-[11.5px] ${
                  check.ok ? "text-fog" : "text-short"
                }`}
              >
                {check.ok ? (
                  <CheckIcon className="mt-0.5 h-3 w-3 shrink-0 text-long" />
                ) : (
                  <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
                )}
                <span className="text-paper/70">{check.message}</span>
              </div>
            ))}
          </div>
        ) : null}

        <div className="mt-4 flex items-center gap-2">
          <Button
            variant={draft.side === "long" ? "long" : "short"}
            onClick={onExecute}
            disabled={!executable}
            className="flex-1"
          >
            Execute {draft.side === "long" ? "buy" : "sell"}
          </Button>
          <Button variant="secondary" onClick={onRefresh} loading={refreshing}>
            <RefreshIcon className="h-3.5 w-3.5" />
            Refresh
          </Button>
        </div>
        {!executable && !draft.blocked ? (
          <div className="mt-2 text-[11px] leading-snug text-short">
            {remaining <= 0
              ? "The draft expired. Refresh to re-price it against the live market."
              : failures.length
                ? `Blocked by: ${failures.map((check) => check.code.replace(/_/g, " ")).join(", ")}.`
                : "Not executable right now."}
          </div>
        ) : null}
      </div>
    </section>
  );
}
