import { useState } from "react";

import AgentChat from "../components/AgentChat";
import {
  useAgentChat,
  useAgentOverview,
  useAgentRuns,
  useAgentStatus,
  useAgentToggle,
} from "../hooks/useAgent";
import { useAccount, useHealth } from "../hooks/useApi";
import { useToast } from "../components/Toast";
import { ApiError } from "../lib/api";
import { dateTime, money, percent, signedMoney } from "../lib/format";
import { Badge, Button, Panel, Row } from "../components/ui";

export default function Agent() {
  const { push } = useToast();
  const status = useAgentStatus();
  const overview = useAgentOverview();
  const runs = useAgentRuns();
  const account = useAccount();
  const health = useHealth();
  const chat = useAgentChat();
  const toggle = useAgentToggle();
  const [lastRequest, setLastRequest] = useState<string | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);

  const submit = (text: string) => {
    setLastRequest(text);
    setRequestError(null);
    chat.mutate(text, {
      onError: (error) =>
        (() => {
          const message = error instanceof ApiError ? error.message : String(error);
          setRequestError(message);
          push({ tone: "danger", title: "Agent request failed", message });
        })(),
    });
  };

  const enabled = status.data?.enabled ?? false;
  const connected = health.data?.terminal.connected ?? false;
  const state = status.isLoading ? "LOADING" : enabled ? (connected ? "RUNNING" : "ERROR") : "OFF";
  const stateTone = state === "RUNNING" ? "long" : state === "ERROR" ? "short" : "neutral";
  const latestRun = runs.data?.runs[0];
  const latestDecision = overview.data?.decisions[0];
  const info = account.data?.account;
  const risk = account.data?.risk;

  return (
    <div className="space-y-4">
      <Panel
        title="Agent console"
        subtitle="Observe, explain, and prepare the next safe action"
        actions={
          <div className="flex items-center gap-2">
            <Badge tone={stateTone} dot>{state}</Badge>
            <Button
              size="sm"
              variant={enabled ? "danger-outline" : "primary"}
              loading={toggle.isPending}
              onClick={() => {
                const isDemo = (health.data?.terminal.server ?? "").toLowerCase().includes("demo");
                if (!enabled && !isDemo && !window.confirm("Enable autonomous trading on the LIVE account?")) {
                  return;
                }
                if (enabled && !window.confirm("Disable autonomous trading? Existing positions stay open.")) {
                  return;
                }
                toggle.mutate(!enabled);
              }}
            >
              {enabled ? "Disable autonomous" : "Enable autonomous"}
            </Button>
          </div>
        }
        bodyClassName="p-4"
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <StatusTile label="Last cycle" value={dateTime(status.data?.last_cycle)} />
          <StatusTile label="Next cycle" value={dateTime(status.data?.next_cycle)} />
          <StatusTile label="Decisions today" value={String(status.data?.decisions_today ?? 0)} />
          <StatusTile label="Open positions" value={String(status.data?.positions_open ?? 0)} />
        </div>
      </Panel>

      <Panel
        title="Latest decision"
        subtitle="Structured agent conclusion and execution state"
        actions={
          latestDecision ? (
            <Badge tone={latestDecision.executed ? "long" : "neutral"}>
              {latestDecision.executed ? "EXECUTED" : latestDecision.decision}
            </Badge>
          ) : null
        }
      >
        {latestDecision ? (
          <div className="space-y-2 text-[12px]">
            <div className="flex flex-wrap items-center gap-2 font-mono text-paper">
              <span>{latestDecision.symbol}</span>
              <span className="text-fog">{latestDecision.timeframe}</span>
              <span className="text-fog">{latestDecision.signal_side}</span>
              {latestDecision.p_up !== null ? <span>p_up {latestDecision.p_up.toFixed(2)}</span> : null}
              {latestDecision.edge_atr !== null ? <span>edge {latestDecision.edge_atr.toFixed(2)} ATR</span> : null}
            </div>
            <p className="leading-relaxed text-paper/80">
              {latestDecision.reasoning || "No reasoning recorded."}
            </p>
            {latestDecision.execution_error ? (
              <p className="rounded border border-short/35 bg-short/10 px-2 py-1 text-short">
                Execution blocked: {latestDecision.execution_error}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-[12px] text-fog">No structured decision has been recorded yet.</p>
        )}
      </Panel>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="flex flex-col gap-4">
          <Panel
            title="Command the agent"
            subtitle="Read-only analysis and explanation requests"
            className="order-1"
          >
            <AgentChat onSubmit={submit} loading={chat.isPending} />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {["what is my current risk", "show my positions", "daily brief", "analyse XAUUSD M15"].map((command) => (
                <button
                  key={command}
                  type="button"
                  onClick={() => submit(command)}
                  disabled={chat.isPending}
                  className="rounded border border-line/60 bg-ink-800/50 px-2 py-1 text-[10.5px] text-fog transition-colors hover:border-gold-500/40 hover:text-paper disabled:opacity-50"
                >
                  {command}
                </button>
              ))}
            </div>
            {lastRequest ? (
              <div className="mt-3 rounded-lg border border-line/60 bg-ink-800/50 px-3 py-2 text-[12px]">
                <span className="text-fog">Latest request: </span>
                <span className="text-paper">{lastRequest}</span>
              </div>
            ) : null}
            {requestError ? (
              <div className="mt-3 rounded-lg border border-short/35 bg-short/10 px-3 py-2 text-[12px] text-short">
                {requestError}
              </div>
            ) : null}
            {chat.data ? (
              <div className="mt-3 rounded-lg border border-gold-500/25 bg-gold-500/[0.06] p-3">
                <div className="mb-1 flex items-center justify-between gap-3">
                  <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-gold-300">
                    {chat.data.route.skill.replaceAll("_", " ")}
                  </span>
                  <span className="font-mono text-[10px] text-fog">
                    {Math.round(chat.data.route.confidence * 100)}% route confidence
                  </span>
                </div>
                <p className="text-[12px] leading-relaxed text-paper/85">
                  {chat.data.output.narrative || chat.data.output.error || "No response returned."}
                </p>
              </div>
            ) : null}
          </Panel>

          <Panel title="Latest agent activity" subtitle="Immutable runs, newest first" className="order-2">
            {runs.isError ? (
              <div className="text-[12px] text-short">Agent runs are unavailable.</div>
            ) : runs.data?.runs.length ? (
              <div className="space-y-2">
                {runs.data.runs.map((run) => (
                  <RunCard key={run.id} run={run} />
                ))}
              </div>
            ) : (
              <div className="py-6 text-center text-[12px] text-fog">
                No agent runs yet. Use the command box to start one.
              </div>
            )}
          </Panel>

        </div>

        <div className="space-y-4 xl:sticky xl:top-20">
          <Panel title="Exposure" subtitle={info?.server}>
            <Row label="Equity" value={money(info?.equity)} />
            <Row label="Floating P/L" value={signedMoney(info?.profit)} tone={info && info.profit < 0 ? "short" : "long"} />
            <Row label="Open risk" value={money(risk?.open_risk_usd)} />
            <Row label="Risk used" value={`${percent(risk?.open_risk_pct)} / ${percent(risk?.cap_pct)}`} />
          </Panel>
          <Panel title="System guardrails">
            <Row label="Terminal" value={connected ? "connected" : "offline"} tone={connected ? "long" : "short"} />
            <Row label="Kronos" value={health.data?.kronos.ready ? "ready" : "offline"} tone={health.data?.kronos.ready ? "long" : "short"} />
            <Row label="Kill switch" value={health.data?.kill_switch ? "engaged" : "clear"} tone={health.data?.kill_switch ? "short" : "long"} />
            <Row label="Worker heartbeat" value={dateTime(status.data?.worker_heartbeat)} />
            <Row label="Latest run" value={latestRun?.status ?? "none"} />
          </Panel>
        </div>
      </div>
    </div>
  );
}

function StatusTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-line/60 bg-ink-800/50 p-3">
      <p className="text-[11px] uppercase tracking-[0.12em] text-fog">{label}</p>
      <p className="mt-1 font-mono text-[15px] text-paper">{value}</p>
    </div>
  );
}

function RunCard({ run }: { run: { id: string; created_at: string; skill: string; subject: string | null; status: string; fallback: boolean; narrative: string | null; error: string | null } }) {
  return (
    <article className="rounded-lg border border-line/60 bg-ink-800/40 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-[12px] font-semibold uppercase tracking-[0.08em] text-paper">
            {run.skill.replaceAll("_", " ")}
          </span>
          <Badge tone={run.status === "ok" ? "long" : run.fallback ? "warn" : "short"}>
            {run.fallback ? "fallback" : run.status}
          </Badge>
        </div>
        <span className="font-mono text-[10.5px] text-fog">{dateTime(run.created_at)}</span>
      </div>
      <p className="mt-2 text-[12px] leading-relaxed text-paper/80">
        {run.narrative || run.error || "No narrative returned."}
      </p>
      {run.subject ? <p className="mt-2 font-mono text-[10.5px] text-fog">subject: {run.subject}</p> : null}
    </article>
  );
}
