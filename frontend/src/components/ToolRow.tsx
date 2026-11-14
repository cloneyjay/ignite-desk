import { Badge } from "../components/ui";
import { AgentToolCall } from "../lib/types";
import {
  ChevronDownIcon,
  ChevronUpIcon,
  ZapIcon,
  CheckCircleIcon,
  XCircleIcon,
  ClockIcon,
  CopyIcon,
  TerminalIcon,
  SearchIcon,
} from "../components/icons";
import { useState } from "react";

const statusConfig = {
  ok: { tone: "long" as const, icon: CheckCircleIcon, label: "Success", rule: "border-l-long" },
  completed: { tone: "long" as const, icon: CheckCircleIcon, label: "Completed", rule: "border-l-long" },
  failed: { tone: "short" as const, icon: XCircleIcon, label: "Failed", rule: "border-l-short" },
  error: { tone: "short" as const, icon: XCircleIcon, label: "Error", rule: "border-l-short" },
  pending: { tone: "gold" as const, icon: ClockIcon, label: "Pending", rule: "border-l-gold-500" },
  running: { tone: "gold" as const, icon: ZapIcon, label: "Running", rule: "border-l-gold-500" },
} as const;

interface ToolRowProps {
  tool: AgentToolCall;
}

export function ToolRow({ tool }: ToolRowProps) {
  const [expanded, setExpanded] = useState(false);
  const config =
    statusConfig[tool.status as keyof typeof statusConfig] ||
    ({ tone: "neutral" as const, icon: ZapIcon, label: tool.status, rule: "border-l-line" } as const);

  const formatJson = (obj: unknown) => {
    try {
      return JSON.stringify(obj, null, 2);
    } catch {
      return String(obj);
    }
  };

  return (
    <div className={`overflow-hidden border border-line/60 border-l-2 bg-ink-900 ${config.rule}`}>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors hover:bg-ink-850/60"
        aria-expanded={expanded}
      >
        <span className="flex h-6 w-6 shrink-0 items-center justify-center border border-line/60 text-gold-500/80">
          <ZapIcon className="h-3 w-3" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate font-mono text-[11.5px] text-paper">{tool.name}</span>
            <Badge tone={config.tone} dot size="sm">
              {config.label}
            </Badge>
            {tool.latency_ms !== null && tool.latency_ms !== undefined && (
              <span className="ml-auto flex shrink-0 items-center gap-1 font-mono text-[9.5px] tabular-nums text-text-faint">
                <ClockIcon className="h-2.5 w-2.5" />
                {tool.latency_ms}ms
              </span>
            )}
          </div>
          {tool.arguments && Object.keys(tool.arguments).length > 0 && (
            <p className="mt-0.5 truncate font-mono text-[9.5px] text-text-faint">
              {JSON.stringify(tool.arguments).slice(0, 76)}
              {JSON.stringify(tool.arguments).length > 76 ? "…" : ""}
            </p>
          )}
        </div>
        {expanded ? (
          <ChevronUpIcon className="h-3.5 w-3.5 shrink-0 text-text-faint" />
        ) : (
          <ChevronDownIcon className="h-3.5 w-3.5 shrink-0 text-text-faint" />
        )}
      </button>
      {expanded && (
        <div className="animate-fade-in space-y-2 border-t border-line/60 bg-ink-950/50 p-3">
          <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
            <div className="border border-line/50 bg-ink-950 p-2.5">
              <div className="mb-1.5 flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-text-muted">
                <TerminalIcon className="h-3 w-3" />
                Arguments
              </div>
              <pre className="max-h-48 overflow-x-auto font-mono text-[10px] leading-relaxed text-paper/80">
                {formatJson(tool.arguments)}
              </pre>
            </div>
            <div className="border border-line/50 bg-ink-950 p-2.5 md:col-span-2">
              <div className="mb-1.5 flex items-center gap-1.5 text-[9px] font-semibold uppercase tracking-[0.1em] text-text-muted">
                <SearchIcon className="h-3 w-3" />
                Result preview
              </div>
              <pre className="max-h-48 overflow-x-auto font-mono text-[10px] leading-relaxed text-paper/80">
                {tool.result_preview || "(no preview)"}
              </pre>
            </div>
          </div>
          <div className="flex items-center gap-3 border-t border-line/40 pt-2 font-mono text-[9.5px] text-text-faint">
            {tool.latency_ms !== null && tool.latency_ms !== undefined && (
              <span className="flex items-center gap-1">
                <ClockIcon className="h-2.5 w-2.5" />
                latency {tool.latency_ms}ms
              </span>
            )}
            <button
              onClick={() => navigator.clipboard.writeText(formatJson(tool.arguments || {}))}
              className="ml-auto flex items-center gap-1 transition-colors hover:text-gold-400"
              title="Copy arguments"
            >
              <CopyIcon className="h-2.5 w-2.5" />
              copy args
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
