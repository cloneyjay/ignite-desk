import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Panel, Badge } from "./ui";

function MetricTile({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "long" | "short";
}) {
  const toneClass = tone === "long" ? "text-long" : tone === "short" ? "text-short" : "text-paper";
  return (
    <div className="border border-line/60 px-2.5 py-2">
      <p className="text-[9px] font-semibold uppercase tracking-[0.08em] text-text-muted">{label}</p>
      <p className={`mt-1.5 font-mono text-[17px] font-medium leading-none tabular-nums ${toneClass}`}>
        {value}
      </p>
    </div>
  );
}

export default function EvaluationPanel() {
  const { data: baseline } = useQuery({
    queryKey: ["agentBaselineReport", "XAUUSD", 30],
    queryFn: () => api.agentBaselineReport("XAUUSD", 30),
    staleTime: 5 * 60 * 1000,
  });

  const { data: promotion, isLoading: promotionLoading } = useQuery({
    queryKey: ["agentPromotionEligibility"],
    queryFn: () => api.agentPromotionEligibility(),
    staleTime: 5 * 60 * 1000,
  });

  const agentSumR = baseline?.agent?.sum_r ?? 0;
  const kronosSumR = baseline?.kronos?.sum_r ?? 0;
  const randomSumR = baseline?.random?.sum_r ?? 0;
  const noTradeSumR = baseline?.no_trade?.sum_r ?? 0;

  const agentTone = (agentSumR > kronosSumR && agentSumR > randomSumR) ? "long" : agentSumR < 0 ? "short" : "neutral";

  return (
    <Panel title="Evaluation" subtitle="Goal 5 baseline & promotion">
      <div className="grid grid-cols-4 gap-2">
        <MetricTile label="Agent sum R" value={agentSumR.toFixed(2)} tone={agentTone} />
        <MetricTile label="Kronos sum R" value={kronosSumR.toFixed(2)} tone="neutral" />
        <MetricTile label="Random sum R" value={randomSumR.toFixed(2)} tone="neutral" />
        <MetricTile label="No-trade sum R" value={noTradeSumR.toFixed(2)} tone="neutral" />
      </div>

      {baseline?.assumptions && (
        <div className="mt-3 text-[10px] text-fog">
          SL ATR {baseline.assumptions.sl_atr} · TP ATR {baseline.assumptions.tp_atr} · Slippage {baseline.assumptions.slippage_points}pts
        </div>
      )}

      {baseline?.disclaimer && (
        <div className="mt-2 rounded border border-warn/30 bg-warn/[0.06] p-2 text-[10px] text-warn">
          {baseline.disclaimer}
        </div>
      )}

      <div className="mt-4 border-t border-line/40 pt-3">
        <div className="flex items-center justify-between mb-2">
          <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-muted">Promotion eligibility</div>
          <Badge tone={promotion?.eligible ? "long" : "warn"} dot>
            {promotion?.eligible ? "Eligible" : "Not eligible"}
          </Badge>
        </div>

        {promotionLoading ? (
          <div className="text-[11px] text-fog">Loading…</div>
        ) : (
          <>
            <div className="text-[10px] text-fog mb-2">
              Current: {promotion?.current_mode} → Target: {promotion?.target_mode ?? "—"}
            </div>
            <div className="space-y-1.5">
              {(promotion?.checks ?? []).map((c) => (
                <div key={c.criterion} className="flex items-center justify-between text-[11px] border-b border-line/20 py-1">
                  <span className="text-fog">{c.criterion}</span>
                  <div className="flex items-center gap-2">
                    <span className="font-mono tabular-nums">{String(c.measured)}</span>
                    <Badge tone={c.met ? "long" : "short"} size="sm">{c.met ? "pass" : "fail"}</Badge>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-2 text-[10px] text-fog">
              Measured: sum R {promotion?.measured?.sum_r?.toFixed(2)}, avg R {promotion?.measured?.avg_r?.toFixed(2)}, win rate {promotion?.measured?.win_rate != null ? Math.round(promotion.measured.win_rate * 100) : 0}%, trades {promotion?.measured?.closed_trades}, DD R {promotion?.measured?.max_drawdown_r?.toFixed(2)}
            </div>
          </>
        )}
      </div>
    </Panel>
  );
}
