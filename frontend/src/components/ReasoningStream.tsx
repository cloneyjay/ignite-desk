import { Badge, Panel, EmptyState } from "../components/ui";
import { BrainIcon, ZapIcon, SearchIcon, CheckCircleIcon, XCircleIcon, FilterIcon } from "../components/icons";
import { useState, useMemo } from "react";

interface ReasoningEvent {
  type: "thinking" | "tool" | "observation" | "conclusion" | "error";
  content: string;
  tool_name?: string;
  timestamp: string;
}

interface ReasoningStreamProps {
  events: ReasoningEvent[];
}

const typeConfig = {
  thinking: { icon: BrainIcon, label: "Thinking", tone: "neutral" as const, color: "text-fog", bg: "bg-ink-900/50", rule: "border-l-line" },
  tool: { icon: ZapIcon, label: "Tool", tone: "gold" as const, color: "text-gold-400", bg: "bg-gold-500/[0.05]", rule: "border-l-gold-500" },
  observation: { icon: SearchIcon, label: "Observation", tone: "long" as const, color: "text-long", bg: "bg-long/[0.05]", rule: "border-l-long" },
  conclusion: { icon: CheckCircleIcon, label: "Conclusion", tone: "info" as const, color: "text-info", bg: "bg-info/[0.05]", rule: "border-l-info" },
  error: { icon: XCircleIcon, label: "Error", tone: "short" as const, color: "text-short", bg: "bg-short/[0.05]", rule: "border-l-short" },
} as const;

function EventRow({ event, index }: { event: ReasoningEvent; index: number }) {
  const config = typeConfig[event.type];
  const Icon = config.icon;

  return (
    <div
      className={`relative flex gap-3 border border-line/50 border-l-2 p-2.5 animate-slide-in ${config.bg} ${config.rule}`}
      style={{ animationDelay: `${index * 20}ms` }}
    >
      <div className="flex h-7 w-7 shrink-0 items-center justify-center border border-line/60 bg-ink-950/60">
        <Icon className={`h-3.5 w-3.5 ${config.color}`} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <Badge tone={config.tone} dot size="sm">{config.label}</Badge>
          <span className="font-mono text-[9px] text-text-faint">{event.timestamp.slice(11, 19)}.{event.timestamp.slice(20, 23)}</span>
          {event.tool_name && (
            <Badge tone="neutral" size="sm" className="ml-auto">
              <FilterIcon className="h-2.5 w-2.5" />
              {event.tool_name}
            </Badge>
          )}
        </div>
        <p className="mt-1.5 text-[11.5px] leading-relaxed text-paper/85">{event.content}</p>
      </div>
    </div>
  );
}

export function ReasoningStream({ events }: ReasoningStreamProps) {
  const [filter, setFilter] = useState<"all" | ReasoningEvent["type"]>("all");

  const filteredEvents = useMemo(() => {
    if (filter === "all") return events;
    return events.filter(e => e.type === filter);
  }, [events, filter]);

  if (events.length === 0) {
    return (
      <Panel title="Reasoning Stream" subtitle="Live agent thought process">
        <EmptyState
          title="No reasoning events"
          message="Reasoning events appear here when Aegus processes a request. You'll see thinking steps, tool calls, observations, and conclusions in real-time."
        />
      </Panel>
    );
  }

  return (
    <Panel
      title="Reasoning Stream"
      subtitle={`${events.length} events${filteredEvents.length !== events.length ? ` · ${filteredEvents.length} shown` : ""}`}
      actions={
        <div className="flex items-center gap-1" role="group" aria-label="Filter reasoning events">
          {(["all", "thinking", "tool", "observation", "conclusion", "error"] as const).map(type => (
            <button
              key={type}
              onClick={() => setFilter(type)}
              className={`border px-2 py-1 font-mono text-[9px] uppercase tracking-[0.08em] transition-colors ${
                filter === type
                  ? "border-gold-500/40 bg-gold-500/10 text-gold-300"
                  : "border-transparent text-text-faint hover:border-line/60 hover:text-fog"
              }`}
            >
              {type === "all" ? "All" : type.charAt(0).toUpperCase() + type.slice(1)}
            </button>
          ))}
        </div>
      }
      bodyClassName="p-4"
    >
      <div className="max-h-[500px] space-y-2 overflow-y-auto" role="log" aria-live="polite" aria-label="Reasoning events">
        {filteredEvents.map((event, index) => (
          <EventRow key={index} event={event} index={index} />
        ))}
        {filteredEvents.length === 0 && (
          <div className="text-center py-8 text-fog/50">
            <FilterIcon className="h-8 w-8 mx-auto mb-2 opacity-30" />
            <p className="text-[12px]">No {filter} events</p>
          </div>
        )}
      </div>
    </Panel>
  );
}