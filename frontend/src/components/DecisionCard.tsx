import { useState } from "react";
import type { ReactNode } from "react";

import { Badge, Button, Panel } from "../components/ui";
import { DecisionExplanation } from "../lib/types";
import {
  AlertTriangleIcon,
  BrainIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  ClockIcon,
  CopyIcon,
  ExternalLinkIcon,
  LinkIcon,
  MinusIcon,
  ShieldIcon,
  TargetIcon,
  TrendingDownIcon,
  TrendingUpIcon,
  XCircleIcon,
} from "../components/icons";

const actionConfig = {
  LONG: { tone: "long" as const, icon: TrendingUpIcon, label: "LONG", rule: "border-l-long" },
  SHORT: { tone: "short" as const, icon: TrendingDownIcon, label: "SHORT", rule: "border-l-short" },
  NO_TRADE: { tone: "neutral" as const, icon: MinusIcon, label: "NO TRADE", rule: "border-l-line" },
  WAIT: { tone: "info" as const, icon: ClockIcon, label: "WAIT", rule: "border-l-info" },
  MONITOR: { tone: "gold" as const, icon: TargetIcon, label: "MONITOR", rule: "border-l-gold-500" },
  CLOSE: { tone: "short" as const, icon: XCircleIcon, label: "CLOSE", rule: "border-l-short" },
  MODIFY: { tone: "info" as const, icon: AlertTriangleIcon, label: "MODIFY", rule: "border-l-info" },
} as const;

interface DecisionCardProps {
  decision: DecisionExplanation;
  compact?: boolean;
  onAction?: (action: string) => void;
}

function Stat({
  label,
  value,
  sub,
  rule = "border-l-line",
  icon,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  rule?: string;
  icon?: ReactNode;
}) {
  return (
    <div className={`border border-line/60 border-l-2 bg-ink-900/60 px-3 py-2.5 ${rule}`}>
      <div className="flex items-center gap-1.5 text-micro font-semibold uppercase tracking-[0.1em] text-text-muted">
        {icon}
        {label}
      </div>
      <div className="mt-1.5 truncate font-mono text-[17px] leading-none tabular-nums text-paper">
        {value}
      </div>
      {sub ? <div className="mt-1.5 truncate text-[10px] text-fog">{sub}</div> : null}
    </div>
  );
}

function EvidenceList({
  title,
  items,
  tone = "neutral",
}: {
  title: string;
  items: string[];
  tone?: "neutral" | "long" | "short";
}) {
  if (items.length === 0) return null;
  const rule = tone === "long" ? "border-l-long" : tone === "short" ? "border-l-short" : "border-l-gold-500";
  const dot = tone === "long" ? "bg-long" : tone === "short" ? "bg-short" : "bg-gold-500";
  return (
    <div className={`border-l-2 pl-3 ${rule}`}>
      <div className="text-micro font-semibold uppercase tracking-[0.11em] text-text-muted">
        {title}
      </div>
      <ul className="mt-2 space-y-1.5" role="list">
        {items.map((item, index) => (
          <li key={index} className="flex items-start gap-2 text-[11.5px] leading-relaxed text-paper/80">
            <span className={`mt-[5px] h-1 w-1 shrink-0 ${dot}`} />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DecisionCard({ decision, compact = false, onAction }: DecisionCardProps) {
  const [expanded, setExpanded] = useState(!compact);
  const config = actionConfig[decision.action as keyof typeof actionConfig] || actionConfig.NO_TRADE;
  const ActionIcon = config.icon;

  const expectedRR =
    decision.expected_rr > 0
      ? `+${decision.expected_rr.toFixed(1)}R`
      : `${decision.expected_rr.toFixed(1)}R`;
  const entryLabel = decision.entry.type === "market" ? "Market" : `${decision.entry.price}`;

  const copyToClipboard = (text: string) => {
    void navigator.clipboard?.writeText(text);
  };

  if (compact) {
    return (
      <article className={`animate-in border border-line/60 border-l-2 bg-ink-900 ${config.rule}`}>
        <div className="flex items-center justify-between gap-2 px-3 py-2">
          <div className="flex min-w-0 items-center gap-2">
            <Badge tone={config.tone} dot size="sm">
              <ActionIcon className="h-3 w-3" />
              {config.label}
            </Badge>
            <span className="truncate font-mono text-[10px] tabular-nums text-text-faint">
              {(decision.confidence_score * 100).toFixed(0)}% · {expectedRR}
            </span>
          </div>
          {onAction ? (
            <Button
              variant={config.tone === "long" ? "long" : config.tone === "short" ? "short" : "primary"}
              size="sm"
              onClick={() => onAction(decision.action)}
            >
              Execute
            </Button>
          ) : null}
        </div>

        {decision.thesis ? (
          <p className="line-clamp-2 border-t border-line/40 px-3 py-2 text-[11px] leading-relaxed text-paper/75">
            {decision.thesis}
          </p>
        ) : null}

        <div className="grid grid-cols-3 divide-x divide-line/40 border-t border-line/40 font-mono text-[10px]">
          <div className="px-2.5 py-1.5">
            <span className="block text-[8.5px] uppercase tracking-[0.1em] text-text-faint">Entry</span>
            <span className="mt-0.5 block truncate tabular-nums text-paper/85">{entryLabel}</span>
          </div>
          <div className="px-2.5 py-1.5">
            <span className="block text-[8.5px] uppercase tracking-[0.1em] text-text-faint">Risk</span>
            <span className="mt-0.5 block truncate tabular-nums text-paper/85">
              {decision.risk.lots} lots
            </span>
          </div>
          <div className="px-2.5 py-1.5">
            <span className="block text-[8.5px] uppercase tracking-[0.1em] text-text-faint">RR</span>
            <span className="mt-0.5 block truncate tabular-nums text-gold-300">{expectedRR}</span>
          </div>
        </div>
      </article>
    );
  }

  return (
    <Panel
      title="Trade decision"
      subtitle={`Confidence ${(decision.confidence_score * 100).toFixed(0)}%`}
      className="animate-in"
      bodyClassName="space-y-4 p-4"
      actions={
        <>
          <Button variant="ghost" size="sm" onClick={() => setExpanded(!expanded)}>
            {expanded ? (
              <ChevronUpIcon className="h-3.5 w-3.5" />
            ) : (
              <ChevronDownIcon className="h-3.5 w-3.5" />
            )}
          </Button>
          {onAction ? (
            <Button
              variant={config.tone === "long" ? "long" : config.tone === "short" ? "short" : "primary"}
              size="sm"
              onClick={() => onAction(decision.action)}
            >
              Execute {config.label}
            </Button>
          ) : null}
        </>
      }
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Badge tone={config.tone} dot size="lg">
            <ActionIcon className="h-3.5 w-3.5" />
            {config.label}
          </Badge>
          <span className="font-mono text-[11px] tabular-nums text-fog">
            expected {expectedRR} · {decision.risk.lots} lots
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 lg:grid-cols-4">
        <Stat label="Conviction" value={`${(decision.conviction * 100).toFixed(0)}%`} rule="border-l-gold-500" />
        <Stat label="Expected RR" value={expectedRR} rule={config.rule} />
        <Stat
          label="Entry"
          value={decision.entry.type === "market" ? "Market" : decision.entry.price}
          sub={decision.entry.type === "market" ? "immediate" : "limit"}
          rule="border-l-gold-500"
        />
        <Stat
          label="Risk"
          value={`${decision.risk.lots} lots`}
          sub={`SL ${decision.risk.sl} · TP ${decision.risk.tp}`}
          rule="border-l-line"
          icon={<ShieldIcon className="h-3 w-3" />}
        />
      </div>

      {expanded ? (
        <>
          <div className="border-t border-line/50 pt-4">
            <div className="mb-2 flex items-center gap-1.5 text-micro font-semibold uppercase tracking-[0.11em] text-text-muted">
              <BrainIcon className="h-3.5 w-3.5 text-gold-500" />
              Thesis
            </div>
            <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-paper/85">
              {decision.thesis}
            </p>
          </div>

          <div className="grid grid-cols-1 gap-4 border-t border-line/50 pt-4 lg:grid-cols-2">
            <EvidenceList title="Supporting evidence" items={decision.evidence} tone="long" />
            <EvidenceList
              title="Invalidation conditions"
              items={decision.invalidate_if}
              tone="short"
            />
          </div>

          {decision.counterfactuals.length > 0 ? (
            <div className="border-t border-line/50 pt-4">
              <EvidenceList
                title="Counterfactuals"
                items={decision.counterfactuals}
                tone="neutral"
              />
            </div>
          ) : null}
        </>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line/50 pt-3">
        <div className="flex items-center gap-1.5 font-mono text-[10px] text-text-faint">
          <LinkIcon className="h-3 w-3" />
          {decision.links.decision_id.slice(0, 12) || "unlinked"}
          {decision.links.decision_id ? (
            <button
              onClick={() => copyToClipboard(decision.links.decision_id)}
              className="p-0.5 transition-colors hover:text-gold-300"
              aria-label="Copy decision id"
            >
              <CopyIcon className="h-3 w-3" />
            </button>
          ) : null}
        </div>
        {decision.links.analysis_id ? (
          <a
            href={`#/analysis/${decision.links.analysis_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.08em] text-gold-400 transition-colors hover:text-gold-300"
          >
            <ExternalLinkIcon className="h-3 w-3" />
            Analysis
          </a>
        ) : null}
        {decision.links.draft_id ? (
          <a
            href={`#/drafts/${decision.links.draft_id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.08em] text-gold-400 transition-colors hover:text-gold-300"
          >
            <ExternalLinkIcon className="h-3 w-3" />
            Draft
          </a>
        ) : null}
      </div>
    </Panel>
  );
}
