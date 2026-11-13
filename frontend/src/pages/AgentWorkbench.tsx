import { useEffect, useRef, useState } from "react";

import {
  useAgentChat,
  useAgentMessages,
  useAgentOverview,
  useAgentSessions,
  useAgentStatus,
  useAgentToggle,
} from "../hooks/useAgent";
import { useHealth } from "../hooks/useApi";
import { useEvents } from "../hooks/useEvents";
import { api, ApiError } from "../lib/api";
import type { AgentMessage, AgentSession, AgentToolCall, AgentStatus } from "../lib/types";
import { dateTime, money, percent, signedMoney } from "../lib/format";
import { useToast } from "../components/Toast";
import { Badge, Button, Panel, Row } from "../components/ui";
import { BoltIcon, PlusIcon, WifiIcon, WifiOffIcon } from "../components/icons";
import { ToolRow } from "../components/ToolRow";
import { DecisionCard } from "../components/DecisionCard";

const QUICK_PROMPTS = [
  "What are you watching?",
  "What is my current risk?",
  "Give me a daily brief.",
  "Analyse XAUUSD M15.",
];

export default function AgentWorkbench() {
  const { push } = useToast();
  const sessions = useAgentSessions();
  const overview = useAgentOverview();
  const status = useAgentStatus();
  const health = useHealth();
  const chat = useAgentChat();
  const toggle = useAgentToggle();
  const createSession = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [chatError, setChatError] = useState<string | null>(null);
  const initialized = useRef(false);

  // SSE real-time events
  const { connectionState, subscribe: _subscribe } = useEvents({
    autoConnect: true,
    onEvent: (event) => {
      // Handle specific event types
      switch (event.type) {
        case "decision.final":
        case "tool.call":
        case "position.opened":
        case "position.protected":
        case "position.trailed":
        case "position.scaled":
        case "position.closed":
        case "position.orphaned":
          // Invalidate relevant queries to trigger refetch
          // The queries have refetchInterval so they'll pick up changes
          break;
        case "kill_switch":
          // Handle kill switch state change
          break;
        case "agent.toggled":
          // Invalidate agent status
          break;
        case "agent.cycle.completed":
          // Invalidate agent status
          break;
      }
    },
  });

  const sessionList = sessions.data?.sessions ?? [];
  const selectedSession = sessionList.find((session) => session.id === selectedId) ?? sessionList[0];
  const activeId = selectedSession?.id ?? null;
  const messages = useAgentMessages(activeId);
  const enabled = status.data?.enabled ?? false;
  const connected = health.data?.terminal.connected ?? false;
  const account = overview.data?.account;
  const risk = overview.data?.risk;

  useEffect(() => {
    if (!initialized.current && sessions.isSuccess) {
      initialized.current = true;
      if (sessionList.length > 0) {
        setSelectedId(sessionList[0].id);
      } else {
        void openNewSession();
      }
    }
  }, [sessionList, sessions.isSuccess]);

  const openNewSession = async () => {
    if (createSession[0]) return;
    createSession[1](true);
    try {
      const result = await api.createAgentSession();
      setSelectedId(result.session.id);
      await sessions.refetch();
    } catch (error) {
      push({ tone: "danger", title: "Could not create conversation", message: String(error) });
    } finally {
      createSession[1](false);
    }
  };

  const retry = () => {
    if (!draft.trim() || chat.isPending || !activeId) return;
    setChatError(null);
    chat.mutate(
      { text: draft, sessionId: activeId },
      {
        onError: (error) => {
          const message = error instanceof ApiError ? error.message : String(error);
          setChatError(message);
        },
      },
    );
  };

  const submit = (text: string) => {
    const value = text.trim();
    if (!value || chat.isPending || !activeId) return;
    setDraft("");
    setChatError(null);
    chat.mutate(
      { text: value, sessionId: activeId },
      {
        onError: (error) => {
          const message = error instanceof ApiError ? error.message : String(error);
          setChatError(message);
        },
      },
    );
  };

  return (
    <div className="grid min-h-[calc(100vh-100px)] gap-4 xl:grid-cols-[270px_minmax(0,1fr)_300px]">
      <div className="space-y-4">
        <AutonomousRail
          enabled={enabled}
          connected={connected}
          status={status.data}
          health={health.data}
          onToggle={() => toggle.mutate(!enabled)}
          toggling={toggle.isPending}
        />
        <SessionHistory
          sessions={sessionList}
          selectedId={activeId}
          loading={createSession[0]}
          onSelect={setSelectedId}
          onNew={openNewSession}
        />
      </div>
      <main className="flex min-w-0 flex-col overflow-hidden rounded-xl border border-line/80 bg-ink-900/50">
        <header className="flex items-center justify-between border-b border-line/70 px-5 py-4">
          <div>
            <h1 className="text-[14px] font-semibold uppercase tracking-[0.14em] text-paper">
              Aegus · trading desk
            </h1>
            <p className="mt-1 text-[12px] text-fog">Your personal market copilot — watching, reasoning, and acting when you are away.</p>
          </div>
          <div className="flex items-center gap-3">
            <Badge tone={enabled && connected ? "long" : enabled ? "short" : "neutral"} dot>
              {enabled ? (connected ? "AUTONOMOUS" : "BLOCKED") : "OBSERVE"}
            </Badge>
            <div className="flex items-center gap-1.5">
              {connectionState === "connected" && (
                <WifiIcon className="h-3.5 w-3.5 text-long" title="SSE connected" />
              )}
              {connectionState === "connecting" && (
                <WifiIcon className="h-3.5 w-3.5 text-short animate-pulse" title="SSE connecting..." />
              )}
              {(connectionState === "disconnected" || connectionState === "error") && (
                <WifiOffIcon className="h-3.5 w-3.5 text-short" title="SSE disconnected" />
              )}
            </div>
          </div>
        </header>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-5">
          {messages.isLoading ? <p className="text-[12px] text-fog">Loading conversation…</p> : null}
          {!messages.isLoading && messages.data.length === 0 ? (
            <Welcome onPrompt={submit} />
          ) : null}
          {messages.data.map((message: AgentMessage) => (
            <MessageBubble key={message.id} message={message} />
          ))}
          {chat.isPending ? (
            <div className="rounded-lg border border-gold-500/30 bg-gold-500/[0.06] px-3 py-2 text-[12px] text-gold-200">
              Agent is working through its tools…
            </div>
          ) : null}
        </div>

        <div className="border-t border-line/70 p-4">
          <div className="mb-2 flex flex-wrap gap-1.5">
            {QUICK_PROMPTS.map((prompt) => (
              <button
                key={prompt}
                type="button"
                onClick={() => submit(prompt)}
                disabled={chat.isPending || !activeId}
                className="rounded border border-line/60 bg-ink-800/60 px-2 py-1 text-[10.5px] text-fog hover:border-gold-500/50 hover:text-paper disabled:opacity-50"
              >
                {prompt}
              </button>
            ))}
          </div>
            {chatError && (
              <div className="w-full flex items-center gap-2 text-[11px] text-short bg-short/10 border border-short/20 rounded px-2 py-1.5">
                <span className="flex-1">{chatError}</span>
                <Button size="sm" variant="secondary" onClick={retry} disabled={chat.isPending || !activeId}>
                  Retry
                </Button>
              </div>
            )}
            <div className="mb-2 flex flex-wrap gap-1.5">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  onClick={() => submit(prompt)}
                  disabled={chat.isPending || !activeId}
                  className="rounded border border-line/60 bg-ink-800/60 px-2 py-1 text-[10.5px] text-fog hover:border-gold-500/50 hover:text-paper disabled:opacity-50"
                >
                  {prompt}
                </button>
              ))}
            </div>
            <form
              className="flex flex-col items-end gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                submit(draft);
              }}
            >
              <textarea
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    submit(draft);
                  }
                }}
                rows={2}
                disabled={chat.isPending || !activeId}
                placeholder="Talk to Aegus naturally — ask anything about your desk, trading, or the market…"
                className="field min-h-[52px] flex-1 resize-none"
              />
              <Button type="submit" variant="primary" loading={chat.isPending} disabled={!draft.trim() || !activeId}>
                <BoltIcon className="h-3.5 w-3.5" />
                Send
              </Button>
            </form>
          </div>
      </main>

      <ContextRail
        enabled={enabled}
        connected={connected}
        status={status.data}
        health={health.data}
        account={account}
        risk={risk}
        onToggle={() => toggle.mutate(!enabled)}
        toggling={toggle.isPending}
        latestDecision={overview.data?.decisions[0]?.reasoning ?? null}
      />
    </div>
  );
}

function AutonomousRail({
  enabled,
  connected,
  status,
  health,
  onToggle,
  toggling,
}: {
  enabled: boolean;
  connected: boolean;
  status: AgentStatus | undefined;
  health: ReturnType<typeof useHealth>["data"];
  onToggle: () => void;
  toggling: boolean;
}) {
  const { push } = useToast();

  const handlePromote = async (target: "demo" | "live") => {
    let accountNumber: string | undefined;
    if (target === "live") {
      const input = prompt("Enter account number for LIVE promotion:");
      if (!input) return;
      accountNumber = input;
    }
    try {
      await api.promoteMode(target, true, accountNumber);
      push({ tone: "ok", title: `Promoted to ${target.toUpperCase()}` });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      push({ tone: "danger", title: "Promotion failed", message });
    }
  };

  const handleDemote = async () => {
    try {
      await api.demoteMode(true);
      push({ tone: "ok", title: "Demoted to SHADOW" });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      push({ tone: "danger", title: "Demotion failed", message });
    }
  };

  const currentMode = status?.execution_mode ?? "shadow";
  const canPromote = enabled && connected && currentMode !== "live";
  const canDemote = currentMode !== "shadow";

  return (
    <aside className="space-y-4">
      <Panel title="Autonomous desk" subtitle="Aegus is the loop, not a button">
        <div className="flex items-center justify-between">
          <Badge tone={enabled && connected ? "long" : enabled ? "short" : "neutral"} dot>
            {enabled ? (connected ? "TRADING LOOP ON" : "WAITING FOR MT5") : "CHAT ONLY"}
          </Badge>
          <Button size="sm" variant={enabled ? "danger-outline" : "primary"} loading={toggling} onClick={onToggle}>
            {enabled ? "Pause" : "Start"}
          </Button>
        </div>
        <p className="mt-3 text-[12px] leading-relaxed text-paper/75">
          When enabled, Aegus watches the configured symbols, asks Kronos for the next-bar forecast, checks news and risk, then uses the guarded MT5 path only when every condition clears.
        </p>
      </Panel>
      <Panel title="Engine status">
        <Row label="Worker heartbeat" value={dateTime(status?.worker_heartbeat)} />
        <Row label="Last cycle" value={dateTime(status?.last_cycle)} />
        <Row label="Next cycle" value={dateTime(status?.next_cycle)} />
        <Row label="Kronos" value={health?.kronos.ready ? "forecasting ready" : "offline"} tone={health?.kronos.ready ? "long" : "short"} />
        <Row label="NVIDIA NIM" value={health?.llm.nim ? "connected" : "unavailable"} tone={health?.llm.nim ? "long" : "short"} />
        <Row label="MT5 MCP" value={connected ? "connected" : "offline"} tone={connected ? "long" : "short"} />
      </Panel>
      <Panel title="Execution mode" subtitle={`Current: ${currentMode.toUpperCase()}`}>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[12px] text-fog">Current mode</span>
            <Badge tone={currentMode === "live" ? "short" : currentMode === "demo" ? "long" : "neutral"} dot>
              {currentMode.toUpperCase()}
            </Badge>
          </div>
          <div className="space-y-2">
            {canPromote && currentMode === "shadow" && (
              <Button
                size="sm"
                variant="primary"
                className="w-full"
                onClick={() => handlePromote("demo")}
                disabled={status?.operating_mode !== "autonomous"}
              >
                Promote to DEMO
              </Button>
            )}
            {canPromote && currentMode === "demo" && (
              <Button
                size="sm"
                variant="primary"
                className="w-full"
                onClick={() => handlePromote("live")}
                disabled={status?.operating_mode !== "autonomous"}
              >
                Promote to LIVE
              </Button>
            )}
            {canDemote && (
              <Button
                size="sm"
                variant="danger"
                className="w-full"
                onClick={handleDemote}
              >
                Demote to SHADOW
              </Button>
            )}
            {!canPromote && !canDemote && (
              <p className="text-[11px] text-fog text-center">
                Enable autonomous mode and connect MT5 to change execution mode
              </p>
            )}
          </div>
        </div>
      </Panel>
      <Panel title="Why no trade?">
        <p className="text-[12px] leading-relaxed text-paper/75">
          {status?.last_guard ?? "No cycle has been blocked. Aegus will explain every skip, block, and execution in the desk log."}
        </p>
      </Panel>
    </aside>
  );
}

function SessionHistory({
  sessions,
  selectedId,
  loading,
  onSelect,
  onNew,
}: {
  sessions: AgentSession[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <Panel
      title="Chat history"
      subtitle="Saved locally and restored after refresh"
      actions={
        <button type="button" onClick={onNew} disabled={loading} className="rounded p-1 text-fog hover:bg-ink-800 hover:text-paper">
          <PlusIcon className="h-4 w-4" />
        </button>
      }
      bodyClassName="max-h-[270px] space-y-1 overflow-y-auto p-2"
    >
      {sessions.map((session) => (
        <button
          key={session.id}
          type="button"
          onClick={() => onSelect(session.id)}
          className={`w-full rounded-lg px-3 py-2 text-left text-[11px] ${
            session.id === selectedId ? "bg-gold-500/15 text-gold-200" : "text-fog hover:bg-ink-800 hover:text-paper"
          }`}
        >
          <span className="block truncate">{session.title}</span>
          <span className="mt-1 block font-mono text-[9px] opacity-60">{dateTime(session.updated_at)}</span>
        </button>
      ))}
      {!sessions.length ? <p className="p-2 text-[11px] text-fog">No saved chats yet.</p> : null}
    </Panel>
  );
}

function Welcome({ onPrompt }: { onPrompt: (prompt: string) => void }) {
  return (
    <div className="flex min-h-[280px] flex-col items-center justify-center text-center">
      <div className="mb-3 rounded-full border border-gold-500/30 bg-gold-500/10 p-3 text-gold-300">
        <BoltIcon className="h-5 w-5" />
      </div>
      <h2 className="text-[15px] font-semibold text-paper">Good to see you. What should Aegus handle?</h2>
      <p className="mt-2 max-w-md text-[12px] leading-relaxed text-fog">
        I can watch the desk, explain a setup, check your exposure, or run the autonomous loop while you are away.
      </p>
      <button type="button" onClick={() => onPrompt(QUICK_PROMPTS[0])} className="mt-4 text-[11px] text-gold-300 hover:text-gold-200">
        Check current risk →
      </button>
    </div>
  );
}

function MessageBubble({ message }: { message: AgentMessage }) {
  if (message.role === "tool") {
    const toolCall: AgentToolCall = {
      name: message.tool_name ?? "agent tool",
      status: message.status ?? "completed",
      latency_ms: message.latency_ms ?? null,
      result_preview: message.tool_result ? JSON.stringify(message.tool_result) : null,
      arguments: message.tool_args ?? null,
    };
    return <ToolRow tool={toolCall} />;
  }
  const user = message.role === "user";
  return (
    <article className={`max-w-[88%] rounded-xl border px-4 py-3 ${user ? "ml-auto border-gold-500/25 bg-gold-500/[0.08]" : "border-line/70 bg-ink-850/70"}`}>
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-fog">{user ? "You" : "Agent"}</div>
      <p className="whitespace-pre-wrap text-[12px] leading-relaxed text-paper/90">{message.content}</p>
      {/* Render decision card if agent message has decision data */}
      {!user && message.tool_result && (
        <DecisionCard
          decision={{
            action: "LONG",
            conviction: 0.8,
            thesis: message.content,
            evidence: [],
            failed_conditions: [],
            entry: { type: "market", price: 0 },
            risk: { lots: 0, sl: 0, tp: 0 },
            expected_rr: 0,
            invalidate_if: [],
            links: { analysis_id: null, draft_id: null, decision_id: "" },
          }}
        />
      )}
    </article>
  );
}

function ContextRail({
  enabled,
  connected,
  status,
  health,
  account,
  risk,
  onToggle,
  toggling,
  latestDecision,
}: {
  enabled: boolean;
  connected: boolean;
  status: ReturnType<typeof useAgentStatus>["data"];
  health: ReturnType<typeof useHealth>["data"];
  account: { equity: number; profit: number; server: string; currency: string; margin_free: number; mode: "demo" | "live" } | undefined | null;
  risk: { open_risk_usd: number; open_risk_pct: number; cap_pct: number; daily_pnl: number; daily_loss_limit_pct: number } | undefined | null;
  onToggle: () => void;
  toggling: boolean;
  latestDecision: string | null;
}) {
  return (
    <aside className="space-y-4">
      <Panel title="Operating mode" subtitle={account?.server}>
        <div className="flex items-center justify-between">
          <Badge tone={enabled && connected ? "long" : enabled ? "short" : "neutral"} dot>
            {enabled ? (connected ? "AUTONOMOUS" : "BLOCKED") : "OBSERVE"}
          </Badge>
          <Button size="sm" variant={enabled ? "danger-outline" : "primary"} loading={toggling} onClick={onToggle}>
            {enabled ? "Disable" : "Enable"}
          </Button>
        </div>
        <div className="mt-3 space-y-1">
          <Row label="Worker" value={dateTime(status?.worker_heartbeat)} />
          <Row label="Next cycle" value={dateTime(status?.next_cycle)} />
          <Row label="Kill switch" value={health?.kill_switch ? "engaged" : "clear"} tone={health?.kill_switch ? "short" : "long"} />
        </div>
      </Panel>
      <Panel title="Live context">
        <Row label="Equity" value={money(account?.equity)} />
        <Row label="Floating P/L" value={signedMoney(account?.profit)} />
        <Row label="Open risk" value={money(risk?.open_risk_usd)} />
        <Row label="Risk used" value={`${percent(risk?.open_risk_pct)} / ${percent(risk?.cap_pct)}`} />
        <Row label="Terminal" value={connected ? "connected" : "offline"} tone={connected ? "long" : "short"} />
        <Row label="Kronos" value={health?.kronos.ready ? "ready" : "offline"} tone={health?.kronos.ready ? "long" : "short"} />
      </Panel>
      <Panel title="Latest decision">
        <p className="text-[12px] leading-relaxed text-paper/80">{latestDecision ?? "No decision recorded yet."}</p>
      </Panel>
    </aside>
  );
}
