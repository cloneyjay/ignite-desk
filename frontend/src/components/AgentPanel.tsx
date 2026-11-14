import { useAgentStatus, useAgentToggle } from "../hooks/useAgent";
import { useHealth } from "../hooks/useApi";
import { Badge, Button, Panel, ProgressBar } from "./ui";

export default function AgentPanel() {
  const status = useAgentStatus();
  const health = useHealth();
  const toggle = useAgentToggle();

  const enabled = status.data?.enabled ?? false;
  const nextCycle = status.data?.next_cycle
    ? new Date(status.data.next_cycle).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "—";

  const decisions = status.data?.decisions_today ?? 0;
  const positions = status.data?.positions_open ?? 0;
  const dailyPnl = status.data?.daily_pnl;
  const dailyLossLimit = status.data?.daily_loss_limit ?? 0;
  const pnlValue = dailyPnl ?? 0;
  const pnlDisplay = dailyPnl !== null && dailyPnl !== undefined ? dailyPnl.toFixed(2) : "—";
  const pnlTone = dailyPnl !== null && dailyPnl !== undefined ? (dailyPnl >= 0 ? "long" : "short") : "neutral";

  // Determine agent status text and tone
  const isConnected = health.data?.terminal?.connected ?? false;
  const serverName = health.data?.terminal?.server ?? "";
  const isDemo = serverName.toLowerCase().includes("demo");
  const modeLabel = isDemo ? "DEMO" : "LIVE";

  let statusText = "OFF";
  let statusTone: "long" | "short" | "warn" | "neutral" = "neutral";

  if (status.isLoading) {
    statusText = "LOADING";
    statusTone = "neutral";
  } else if (enabled) {
    if (isConnected) {
      statusText = `RUNNING · ${modeLabel}`;
      statusTone = "long";
    } else {
      statusText = "ERROR";
      statusTone = "short";
    }
  } else {
    statusText = "OFF";
    statusTone = "neutral";
  }

  // Daily loss limit progress: pnl / (equity * limit)
  // We don't have equity here, so show limit percentage as reference
  const lossLimitPct = dailyLossLimit * 100;

  return (
    <Panel
      title="Agent"
      className="border-line/80 bg-ink-850/70"
      bodyClassName="p-4 space-y-4"
    >
      {/* Header: title + status pill */}
      <div className="flex items-center justify-between">
        <h3 className="text-[13px] font-semibold uppercase tracking-[0.08em] text-paper">AGENT</h3>
        <Badge tone={statusTone} className="px-2.5 py-1 text-[11px]">
          {statusText}
        </Badge>
      </div>

      {/* Metrics grid 2x2 */}
      <div className="grid grid-cols-2 gap-3">
        <MetricTile label="Next cycle" value={nextCycle} />
        <MetricTile label="Decisions today" value={decisions.toString()} />
        <MetricTile label="Positions" value={positions.toString()} />
        <MetricTile label="P&L" value={pnlDisplay} tone={pnlTone} />
      </div>

      {/* Primary control: Disable/Enable */}
      <Button
        variant={enabled ? "danger-outline" : "primary"}
        onClick={() => {
          if (enabled && !isDemo) {
            // Extra confirmation for LIVE account
            if (!window.confirm("Disable agent on LIVE account? Open positions stay open.")) return;
          } else if (enabled) {
            if (!window.confirm("Disable agent? Open positions stay open.")) return;
          }
          toggle.mutate(!enabled);
        }}
        disabled={toggle.isPending}
        className="w-full h-10"
      >
        {toggle.isPending ? "Working…" : enabled ? "Disable Agent" : "Enable Agent"}
      </Button>

      {/* Footer: Daily loss limit with progress bar */}
      <div className="space-y-1.5 pt-2 border-t border-line/60">
        <p className="text-[12px] text-fog">
          Daily loss limit: {lossLimitPct.toFixed(0)}% equity
        </p>
        <ProgressBar
          pct={Math.min(100, Math.max(0, (pnlValue / (10000 * dailyLossLimit)) * 100))}
          className="h-1.5"
        />
      </div>
    </Panel>
  );
}

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
    <div className="rounded-lg border border-line/60 bg-ink-800/50 p-3">
      <p className="text-[11px] uppercase tracking-[0.12em] text-fog">{label}</p>
      <p className={`mt-1 font-mono tabular-nums text-[20px] font-semibold ${toneClass}`}>{value}</p>
    </div>
  );
}