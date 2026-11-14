import { useState } from "react";

import { Badge, Button, EmptyState } from "../components/ui";
import { AgentMessage } from "../lib/types";
import {
  ChevronDownIcon,
  ChevronUpIcon,
  ClockIcon,
  HashIcon,
  MessageSquareIcon,
  ToolIcon,
  CheckCircleIcon,
} from "../components/icons";
import { dateTime } from "../lib/format";

interface MemoryPanelProps {
  messages: AgentMessage[];
  onLoadMore: () => void;
  hasMore: boolean;
  /** Render the list without its own panel chrome (used inside the right rail). */
  embedded?: boolean;
}

function MessageBubble({ message }: { message: AgentMessage }) {
  const isUser = message.role === "user";
  const [expanded, setExpanded] = useState(false);

  return (
    <article className={`border-l-2 pl-3 ${isUser ? "border-l-gold-500" : "border-l-line"}`}>
      {!isUser && (
        <div className="mb-1 flex items-center gap-1.5 text-micro font-semibold uppercase tracking-[0.12em] text-text-faint">
          <MessageSquareIcon className="h-3 w-3 text-gold-500/70" />
          Agent
        </div>
      )}
      <p className="whitespace-pre-wrap text-[12px] leading-relaxed text-paper/85">
        {message.content}
      </p>

      {message.tool_name && (
        <div className="mt-2 border border-line/60 bg-ink-950/60">
          <div className="flex items-center gap-2 border-b border-line/40 px-2.5 py-1.5 text-[10px]">
            <ToolIcon className="h-3 w-3 text-gold-500/80" />
            <span className="truncate font-mono text-[10.5px] text-gold-300">
              {message.tool_name}
            </span>
            <Badge tone="neutral" size="sm">
              {message.status}
            </Badge>
            {message.latency_ms ? (
              <span className="ml-auto font-mono text-[9.5px] text-text-faint">
                {message.latency_ms}ms
              </span>
            ) : null}
          </div>
          {(message.tool_args || message.tool_result) && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-ink-850/60"
            >
              <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.08em] text-text-muted">
                {expanded ? (
                  <ChevronUpIcon className="h-3 w-3" />
                ) : (
                  <ChevronDownIcon className="h-3 w-3" />
                )}
                Details
              </span>
            </button>
          )}
          {expanded && (
            <div className="animate-fade-in space-y-2 border-t border-line/40 p-2.5">
              {message.tool_args && Object.keys(message.tool_args).length > 0 && (
                <div>
                  <div className="mb-1 flex items-center gap-1.5 text-[9.5px] uppercase tracking-[0.1em] text-text-faint">
                    <HashIcon className="h-3 w-3" />
                    Arguments
                  </div>
                  <pre className="overflow-x-auto border border-line/40 bg-ink-900 p-2 font-mono text-[10px] leading-relaxed text-paper/75">
                    {JSON.stringify(message.tool_args, null, 2)}
                  </pre>
                </div>
              )}
              {message.tool_result && (
                <div>
                  <div className="mb-1 flex items-center gap-1.5 text-[9.5px] uppercase tracking-[0.1em] text-long">
                    <CheckCircleIcon className="h-3 w-3" />
                    Result
                  </div>
                  <pre className="overflow-x-auto border border-line/40 bg-ink-900 p-2 font-mono text-[10px] leading-relaxed text-paper/75">
                    {JSON.stringify(message.tool_result, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="mt-1.5 flex items-center justify-end gap-2 font-mono text-[9px] text-text-faint">
        <span>{dateTime(message.created_at)}</span>
        {message.links?.decision_id ? (
          <span className="flex items-center gap-1 border border-line/60 px-1 py-0.5">
            <HashIcon className="h-2.5 w-2.5" />
            {message.links.decision_id.slice(0, 8)}
          </span>
        ) : null}
      </div>
    </article>
  );
}

export function MemoryPanel({ messages, onLoadMore, hasMore, embedded = false }: MemoryPanelProps) {
  const body = (
    <>
      {messages.length === 0 ? (
        <EmptyState
          title="No conversation yet"
          message="Start talking to Aegus. Every message, tool call, and decision is stored here for reference."
          action={
            <Button
              variant="ghost"
              size="sm"
              onClick={() => window.dispatchEvent(new CustomEvent("agent:focus-input"))}
            >
              New conversation
            </Button>
          }
        />
      ) : (
        <>
          <div
            className={embedded ? "space-y-3 p-2.5" : "panel-body space-y-3"}
            role="log"
            aria-label="Conversation history"
          >
            {messages
              .slice()
              .reverse()
              .map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))}
          </div>
          {hasMore && (
            <div className="border-t border-line/60 p-3">
              <Button variant="ghost" size="sm" className="w-full" onClick={onLoadMore}>
                <ClockIcon className="h-3.5 w-3.5" />
                Load older messages
              </Button>
            </div>
          )}
        </>
      )}
    </>
  );

  if (embedded) return <div>{body}</div>;

  return (
    <section className="panel">
      <header className="panel-header">
        <div className="min-w-0">
          <h2 className="panel-title">Conversation memory</h2>
          <p className="panel-subtitle">{messages.length} messages</p>
        </div>
      </header>
      {body}
    </section>
  );
}
