import { useState } from "react";
import type { AgentToolCall } from "../lib/types";
import { ChevronDownIcon, ChevronUpIcon } from "./icons";

interface ToolRowProps {
  tool: AgentToolCall;
}

export function ToolRow({ tool }: ToolRowProps) {
  const [expanded, setExpanded] = useState(false);
  
  const getStatusColor = (status: string) => {
    switch (status) {
      case "ok":
      case "completed":
        return "text-long bg-long/10 border-long/20";
      case "failed":
      case "error":
        return "text-short bg-short/10 border-short/20";
      case "pending":
      case "running":
        return "text-short bg-short/10 border-short/20 animate-pulse";
      default:
        return "text-fog bg-ink-800/50 border-line/50";
    }
  };

  return (
    <div className="rounded-lg border bg-ink-800/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-3 py-2 text-left"
      >
        <div className="flex items-center gap-2">
          <span className="font-mono text-paper">{tool.name}</span>
          <span className={`badge ${getStatusColor(tool.status)}`}>
            {tool.status}
          </span>
          {tool.latency_ms !== null && tool.latency_ms !== undefined && (
            <span className="text-[10px] text-fog font-mono">
              {tool.latency_ms}ms
            </span>
          )}
        </div>
        {expanded ? (
          <ChevronUpIcon className="h-3.5 w-3.5 text-fog" />
        ) : (
          <ChevronDownIcon className="h-3.5 w-3.5 text-fog" />
        )}
      </button>
      {expanded && (
        <div className="border-t border-line/60 px-3 py-2 space-y-2 text-[11px]">
          {tool.arguments && Object.keys(tool.arguments).length > 0 && (
            <div>
              <div className="font-semibold text-fog mb-1">Arguments</div>
              <pre className="rounded bg-ink-900/50 p-2 overflow-x-auto font-mono text-[10px] text-paper/90">
                {JSON.stringify(tool.arguments, null, 2)}
              </pre>
            </div>
          )}
          {tool.result_preview && (
            <div>
              <div className="font-semibold text-fog mb-1">Result Preview</div>
              <pre className="rounded bg-ink-900/50 p-2 overflow-x-auto font-mono text-[10px] text-paper/90">
                {tool.result_preview}
              </pre>
            </div>
          )}
          {tool.latency_ms !== null && tool.latency_ms !== undefined && (
            <div className="font-mono text-fog">
              Latency: {tool.latency_ms}ms
            </div>
          )}
        </div>
      )}
    </div>
  );
}