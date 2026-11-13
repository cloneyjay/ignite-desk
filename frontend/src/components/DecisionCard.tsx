import { ChevronRightIcon, ExternalLinkIcon } from "./icons";

interface DecisionCardProps {
  decision: {
    action: string;
    conviction: number;
    thesis: string;
    evidence: string[];
    failed_conditions: string[];
    entry: { type: "market" | "limit"; price: number };
    risk: { lots: number; sl: number; tp: number };
    expected_rr: number;
    invalidate_if: string[];
    links: {
      analysis_id: string | null;
      draft_id: string | null;
      decision_id: string;
    };
  };
}

const getActionColor = (action: string) => {
  switch (action) {
    case "LONG":
      return "text-long bg-long/10 border-long/20";
    case "SHORT":
      return "text-short bg-short/10 border-short/20";
    case "NO_TRADE":
    case "WAIT":
    case "MONITOR":
      return "text-short bg-short/10 border-short/20";
    case "CLOSE":
    case "MODIFY":
      return "text-fog bg-ink-800/50 border-line/50";
    default:
      return "text-fog bg-ink-800/50 border-line/50";
  }
};

const formatNumber = (num: number) => {
  return num.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
};

export function DecisionCard({ decision }: DecisionCardProps) {
  return (
    <div className="rounded-lg border border-line/60 bg-ink-800/50 p-3 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className={`badge ${getActionColor(decision.action)}`}>
          {decision.action}
        </span>
        <span className="font-mono text-[11px] text-gold-300">
          Conviction: {(decision.conviction * 100).toFixed(0)}%
        </span>
      </div>

      {/* Thesis */}
      <div className="space-y-1">
        <div className="font-semibold text-fog">Thesis</div>
        <p className="text-[12px] leading-relaxed text-paper/90">
          {decision.thesis}
        </p>
      </div>

      {/* Evidence */}
      {decision.evidence.length > 0 && (
        <div className="space-y-1">
          <div className="font-semibold text-fog">Evidence</div>
          <ul className="ml-4 space-y-0.5 list-disc">
            {decision.evidence.map((evidence, i) => (
              <li key={i} className="text-[11px] text-paper/80">
                {evidence}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Failed Conditions */}
      {decision.failed_conditions.length > 0 && (
        <div className="space-y-1">
          <div className="font-semibold text-short">Failed Conditions</div>
          <ul className="ml-4 space-y-0.5 list-disc">
            {decision.failed_conditions.map((cond, i) => (
              <li key={i} className="text-[11px] text-short/80">
                {cond}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Entry & Risk */}
      <div className="grid grid-cols-2 gap-3 pt-2 border-t border-line/60">
        <div className="space-y-1">
          <div className="font-semibold text-fog">Entry</div>
          <div className="text-[11px] text-paper/90">
            {decision.entry.type === "market" ? (
              "Market order"
            ) : (
              <>
                Limit @ {formatNumber(decision.entry.price)}
              </>
            )}
          </div>
        </div>
        <div className="space-y-1">
          <div className="font-semibold text-fog">Risk</div>
          <div className="text-[11px] text-paper/90 font-mono">
            {formatNumber(decision.risk.lots)} lots • SL: {formatNumber(decision.risk.sl)} • TP: {formatNumber(decision.risk.tp)}
          </div>
        </div>
        <div className="space-y-1">
          <div className="font-semibold text-fog">Expected RR</div>
          <div className="text-[11px] text-paper/90 font-mono">
            {decision.expected_rr.toFixed(2)}R
          </div>
        </div>
        <div className="space-y-1">
          <div className="font-semibold text-fog">Conviction</div>
          <div className="text-[11px] text-paper/90 font-mono">
            {(decision.conviction * 100).toFixed(0)}%
          </div>
        </div>
      </div>

      {/* Invalidate If */}
      {decision.invalidate_if.length > 0 && (
        <div className="space-y-1">
          <div className="font-semibold text-short">Invalidate If</div>
          <ul className="ml-4 space-y-0.5 list-disc">
            {decision.invalidate_if.map((cond, i) => (
              <li key={i} className="text-[11px] text-short/80">
                {cond}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Links */}
      <div className="flex flex-wrap gap-2 pt-2 border-t border-line/60">
        {decision.links.analysis_id && (
          <a
            href={`#/analysis/${decision.links.analysis_id}`}
            className="flex items-center gap-1 text-[11px] text-gold-300 hover:text-gold-200"
            target="_blank"
            rel="noopener noreferrer"
          >
            <ExternalLinkIcon className="h-3 w-3" />
            Analysis: {decision.links.analysis_id.slice(0, 8)}...
          </a>
        )}
        {decision.links.draft_id && (
          <a
            href={`#/drafts/${decision.links.draft_id}`}
            className="flex items-center gap-1 text-[11px] text-gold-300 hover:text-gold-200"
            target="_blank"
            rel="noopener noreferrer"
          >
            <ExternalLinkIcon className="h-3 w-3" />
            Draft: {decision.links.draft_id.slice(0, 8)}...
          </a>
        )}
        <span className="flex items-center gap-1 text-[11px] text-fog font-mono">
          <ChevronRightIcon className="h-2.5 w-2.5" />
          Decision: {decision.links.decision_id.slice(0, 8)}...
        </span>
      </div>
    </div>
  );
}