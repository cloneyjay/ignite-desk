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

  const isConnected = health.data?.terminal?.connected ?? false;
  const serverName = health.data?.terminal?.server ?? "";
  const isDemo = serverName.toLowerCase().includes("demo");
  const modeLabel = isDemo ? "Demo" : "Live";

  let statusText = "Off";
  let statusTone: "long" | "short" | "warn" | "neutral" = "neutral";

  if (status.isLoading) {
    statusText = "Loading";
    statusTone = "neutral";
  } else if (enabled) {
    if (isConnected) {
      statusText = `Running · ${modeLabel}`;
      statusTone = "long";
    } else {
      statusText = "Error";
      statusTone = "short";
    }
  }

  return (
    <Panel
      title="Agent"
      subtitle={`${modeLabel} account · loop control`}
      actions={<Badge tone={statusTone} dot>{statusText}</Badge>}
      bodyClassName="p-3 space-y-3"
    >
      <div className="grid grid-cols-2 gap-2">
        <MetricTile label="Next cycle" value={nextCycle} />
        <MetricTile label="Decisions today" value={decisions.toString()} />
        <MetricTile label="Positions" value={positions.toString()} />
        <MetricTile label="P&L" value={pnlDisplay} tone={pnlTone} />
      </div>

      <Button
        variant={enabled ? "danger-outline" : "primary"}
        onClick={() => {
          if (enabled && !isDemo) {
            if (!window.confirm("Disable agent on LIVE account? Open positions stay open.")) return;
          } else if (enabled) {
            if (!window.confirm("Disable agent? Open positions stay open.")) return;
          }
          toggle.mutate(!enabled);
        }}
        disabled={toggle.isPending}
        className="w-full"
      >
        {toggle.isPending ? "Working…" : enabled ? "Disable agent" : "Enable agent"}
      </Button>

      <div className="space-y-1.5 border-t border-line/40 pt-2.5">
        <div className="flex items-center justify-between">
          <span className="text-[9.5px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            Daily loss limit
          </span>
          <span className="font-mono text-[10px] tabular-nums text-fog">
            {(dailyLossLimit * 100).toFixed(0)}% equity
          </span>
        </div>
        <ProgressBar
          pct={Math.min(100, Math.max(0, (pnlValue / (10000 * (dailyLossLimit || 1))) * 100))}
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
    <div className="border border-line/60 px-2.5 py-2">
      <p className="text-[9px] font-semibold uppercase tracking-[0.08em] text-text-muted">{label}</p>
      <p className={`mt-1.5 font-mono text-[17px] font-medium leading-none tabular-nums ${toneClass}`}>
        {value}
      </p>
    </div>
  );
}
