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
import type { StreamStatus } from "../hooks/useEventStream";
import { api, ApiError } from "../lib/api";
import type { AgentMessage, AgentSession } from "../lib/types";
import { dateTime, money, percent, signedMoney } from "../lib/format";
import { Badge, Button, Panel, Row } from "../components/ui";
import { BoltIcon, PlusIcon } from "../components/icons";
import { ToolRow } from "../components/ToolRow";

const QUICK_PROMPTS = [
  "What are you watching?",
  "What is my current risk?",
  "Give me a daily brief.",
  "Analyse XAUUSD M15.",
];

export default function AgentWorkbench({ streamStatus }: { streamStatus: StreamStatus }) {
  const sessions = useAgentSessions();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const initialized = useRef(false);

  const sessionList = sessions.data?.sessions ?? [];
  const activeId = selectedId ?? sessionList[0]?.id ?? null;

  useEffect(() => {
    if (!initialized.current && sessions.isSuccess) {
      initialized.current = true;
      if (sessionList.length > 0 && !selectedId) {
        setSelectedId(sessionList[0].id);
      }
    }
  }, [sessionList, sessions.isSuccess, selectedId]);

  const openNewSession = async () => {
    try {
      const result = await api.createAgentSession();
      setSelectedId(result.session.id);
      await sessions.refetch();
    } catch {
      // no-op
    }
  };

  return (
    <div className="grid min-h-[calc(100vh-100px)] gap-4 lg:grid-cols-[minmax(0,1fr)_320px] xl:grid-cols-[264px_minmax(0,1fr)_340px]">
      <aside className="hidden xl:flex xl:flex-col gap-4 min-w-0">
        <AutonomousRail />
        <SessionHistory
          sessions={sessionList}
          selectedId={activeId}
          loading={sessions.isLoading}
          onSelect={setSelectedId}
          onNew={openNewSession}
        />
      </aside>

      <main className="min-w-0">
        <ChatWorkspace streamStatus={streamStatus} activeId={activeId} />
      </main>

      <aside className="hidden lg:block min-w-0">
        <RightRail />
      </aside>
    </div>
  );
}

function AutonomousRail() {
  const status = useAgentStatus();
  const health = useHealth();
  const toggle = useAgentToggle();
  const enabled = status.data?.enabled ?? false;
  const connected = health.data?.terminal.connected ?? false;

  return (
    <Panel title="Autonomous desk" subtitle="Aegus is the loop, not a button">
      <div className="flex items-center justify-between">
        <Badge tone={enabled && connected ? "long" : enabled ? "short" : "neutral"} dot>
          {enabled ? (connected ? "TRADING LOOP ON" : "WAITING FOR MT5") : "CHAT ONLY"}
        </Badge>
        <Button size="sm" variant={enabled ? "danger-outline" : "primary"} loading={toggle.isPending} onClick={() => toggle.mutate(!enabled)}>
          {enabled ? "Pause" : "Start"}
        </Button>
      </div>
    </Panel>
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
    <Panel title="Chat history" actions={<button className="rounded p-1" onClick={onNew} disabled={loading}><PlusIcon className="h-4 w-4" /></button>}>
      <div className="max-h-[300px] overflow-y-auto p-2 space-y-1">
        {sessions.map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={`w-full text-left px-3 py-2 rounded-lg text-[11px] ${s.id === selectedId ? "bg-gold-500/15 text-gold-200" : "text-fog hover:bg-ink-800"}`}
          >
            <div className="truncate">{s.title}</div>
            <div className="font-mono text-[9px] opacity-60">{dateTime(s.updated_at)}</div>
          </button>
        ))}
        {sessions.length === 0 && <div className="p-2 text-[11px] text-fog">No saved chats yet.</div>}
      </div>
    </Panel>
  );
}

function ChatWorkspace({ streamStatus, activeId }: { streamStatus: StreamStatus; activeId: string | null }) {
  const messages = useAgentMessages(activeId);
  const chat = useAgentChat();
  const [draft, setDraft] = useState("");
  const [chatError, setChatError] = useState<string | null>(null);

  const submit = (text: string) => {
    const value = text.trim();
    if (!value || chat.isPending || !activeId) return;
    setDraft("");
    setChatError(null);
    chat.mutate({ text: value, sessionId: activeId }, {
      onError: (e) => setChatError(e instanceof ApiError ? e.message : String(e)),
    });
  };

  return (
    <div className="flex min-h-[calc(100vh-100px)] max-h-[calc(100vh-100px)] flex-col rounded-xl border border-line/80 bg-ink-900/50">
      <div className="flex items-center justify-between px-5 py-3 border-b border-line/70">
        <div className="text-[11px] uppercase tracking-[0.1em] text-text-faint">Conversation</div>
        <div className="text-[10px] font-mono uppercase">
          <span className={streamStatus === "live" ? "text-long" : streamStatus === "connecting" ? "text-warn" : "text-short"}>
            {streamStatus}
          </span>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-5 space-y-3">
        {messages.isLoading && <div className="text-[12px] text-fog">Loading conversation…</div>}
        {!messages.isLoading && messages.data.length === 0 && (
          <div className="text-center py-16 text-fog text-[12px]">No messages yet. Start a conversation.</div>
        )}
        {messages.data.map((m) => (
          <MessageBubble
            key={m.id}
            message={m}
            onExecuteDraft={() => submit("execute that trade")}
          />
        ))}
        {chat.isPending && <div className="text-[12px] text-gold-200">Agent is working…</div>}
      </div>
      <div className="border-t border-line/70 p-4 space-y-2">
        <div className="flex flex-wrap gap-1.5">
          {QUICK_PROMPTS.map((p) => (
            <button key={p} disabled={chat.isPending || !activeId} onClick={() => submit(p)} className="rounded border border-line/60 bg-ink-800/60 px-2 py-1 text-[10.5px] text-fog hover:border-gold-500/50">
              {p}
            </button>
          ))}
        </div>
        {chatError && <div className="text-[11px] text-short">{chatError}</div>}
        <form onSubmit={(e) => { e.preventDefault(); submit(draft); }} className="flex gap-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(draft); } }}
            rows={2}
            disabled={chat.isPending || !activeId}
            placeholder="Talk to Aegus…"
            className="field min-h-[52px] flex-1 resize-none"
          />
          <Button type="submit" variant="primary" loading={chat.isPending} disabled={!draft.trim() || !activeId}>
            <BoltIcon className="h-3.5 w-3.5" /> Send
          </Button>
        </form>
      </div>
    </div>
  );
}

function MessageBubble({
  message,
  onExecuteDraft,
}: {
  message: AgentMessage;
  onExecuteDraft?: (draftId: string) => void;
}) {
  const user = message.role === "user";

  // Tool result bubbles with structured analysis/execution data
  if (message.role === "tool" && message.tool_result) {
    const result = message.tool_result as Record<string, unknown>;
    if ((result as { kind?: string }).kind === "analysis") {
      return (
        <AnalysisBubble
          result={result as unknown as AnalysisResult}
          onExecuteDraft={onExecuteDraft}
        />
      );
    }
    if ((result as { kind?: string }).kind === "execution") {
      return <ExecutionBubble result={result as unknown as ExecutionResultUI} />;
    }
  }

  if (message.role === "tool") {
    const tool = {
      name: message.tool_name ?? "tool",
      status: message.status ?? "completed",
      latency_ms: message.latency_ms ?? null,
      result_preview: message.tool_result ? JSON.stringify(message.tool_result) : null,
      arguments: message.tool_args ?? null,
    };
    return <ToolRow tool={tool} />;
  }

  return (
    <article className={`w-fit max-w-[88%] rounded-xl border px-4 py-3 ${user ? "ml-auto border-gold-500/25 bg-gold-500/[0.08]" : "border-line/70 bg-ink-850/70"}`}>
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-fog">{user ? "You" : "Agent"}</div>
      <p className="whitespace-pre-wrap text-[12px] leading-relaxed text-paper/90">{message.content}</p>
    </article>
  );
}

interface AnalysisResult {
  kind: string;
  symbol: string;
  timeframe: string;
  signal: string;
  p_up: number;
  edge_atr: number;
  draft_id: string | null;
  rationale: string;
}

interface ExecutionResultUI {
  kind: string;
  draft_id: string;
  ok: boolean;
  ticket: string | null;
  fill_price: number | null;
  detail: string;
  blocked: boolean | null;
  block_reason: string | null;
}

function AnalysisBubble({
  result,
  onExecuteDraft,
}: {
  result: AnalysisResult;
  onExecuteDraft?: (draftId: string) => void;
}) {
  const side = result.signal;
  const tone = side === "LONG" ? "long" : side === "SHORT" ? "short" : "neutral";
  const hasDraft = !!result.draft_id;

  return (
    <article className="w-fit max-w-[88%] rounded-xl border px-4 py-3 border-line/70 bg-ink-850/70">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-fog">Agent</div>
      <div className="mb-3">
        <Badge tone={tone}>{side}</Badge>{" "}
        <Badge tone="neutral">{result.timeframe}</Badge>{" "}
        <Badge tone="neutral">p_up {result.p_up.toFixed(2)}</Badge>{" "}
        <Badge tone={result.edge_atr >= 0 ? "long" : "short"}>edge {result.edge_atr >= 0 ? "+" : ""}{result.edge_atr.toFixed(2)} ATR</Badge>
      </div>
      <p className="whitespace-pre-wrap text-[12px] leading-relaxed text-paper/90 mb-3">{result.rationale}</p>
      {hasDraft && (
        <div className="rounded-lg border border-line/60 bg-ink-900/60 p-3 mb-3">
          <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-fog mb-2">Draft order</div>
          <div className="flex gap-2">
            <span className="text-[10px] text-fog">Side:</span>
            <span className="font-mono text-[11px] text-paper">{side}</span>
          </div>
          <div className="flex gap-2">
            <span className="text-[10px] text-fog">Draft:</span>
            <span className="font-mono text-[11px] text-fog">{result.draft_id?.slice(0, 8)}…</span>
          </div>
        </div>
      )}
      {hasDraft && onExecuteDraft && (
        <button
          onClick={() => onExecuteDraft(result.draft_id!)}
          className="text-[10px] underline underline-offset-4 hover:text-gold-400 text-gold-400"
        >
          Execute this trade
        </button>
      )}
    </article>
  );
}

function ExecutionBubble({
  result,
}: {
  result: ExecutionResultUI;
}) {
  const tone = result.ok ? "long" : result.blocked ? "short" : "neutral";

  return (
    <article className="w-fit max-w-[88%] rounded-xl border px-4 py-3 border-line/70 bg-ink-850/70">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-fog">Agent</div>
      <Badge tone={tone}>
        {result.ok ? "FILLED" : result.blocked ? "BLOCKED" : "EXECUTION"}
      </Badge>{" "}
      <span className="text-[10px] text-fog ml-2">{result.detail}</span>
      {result.ticket && (
        <div className="mt-1 flex gap-2">
          <span className="text-[10px] text-fog">Ticket:</span>
          <span className="font-mono text-[11px] text-paper">{result.ticket}</span>
        </div>
      )}
      {result.fill_price != null && (
        <div className="mt-1 flex gap-2">
          <span className="text-[10px] text-fog">Fill:</span>
          <span className="font-mono text-[11px] text-paper">{result.fill_price}</span>
        </div>
      )}
      {result.blocked && result.block_reason && (
        <div className="mt-2 rounded border border-short/30 bg-short/[0.06] p-2">
          <div className="text-[10px] text-short">{result.block_reason}</div>
        </div>
      )}
    </article>
  );
}

function RightRail() {
  const [tab, setTab] = useState<"context" | "tools" | "memory">("context");
  const status = useAgentStatus();
  const overview = useAgentOverview();
  const health = useHealth();

  const account = overview.data?.account;
  const risk = overview.data?.risk;

  return (
    <div className="space-y-4">
      <div className="flex border-b border-line/70">
        {(["context", "tools", "memory"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`px-3 py-2 text-[11px] capitalize ${tab === t ? "text-gold-300 border-b border-gold-500" : "text-fog"}`}>{t}</button>
        ))}
      </div>
      {tab === "context" && (
        <Panel title="Live context">
          <Row label="Equity" value={money(account?.equity)} />
          <Row label="Floating P/L" value={signedMoney(account?.profit)} />
          <Row label="Open risk" value={money(risk?.open_risk_usd)} />
          <Row label="Risk used" value={`${percent(risk?.open_risk_pct)} / ${percent(risk?.cap_pct)}`} />
          <Row label="Worker" value={dateTime(status.data?.worker_heartbeat)} />
          <Row label="Kronos" value={health.data?.kronos.ready ? "ready" : "offline"} />
        </Panel>
      )}
      {tab === "tools" && <Panel title="Tools"><div className="text-[12px] text-fog">No tool calls yet.</div></Panel>}
      {tab === "memory" && <Panel title="Memory"><div className="text-[12px] text-fog">Memory view.</div></Panel>}
    </div>
  );
}
