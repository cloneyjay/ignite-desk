import { useAgentStatus, useAgentToggle } from "../hooks/useAgent";
import { Badge, Button, Panel } from "./ui";

export default function AgentPanel() {
  const status = useAgentStatus();
  const toggle = useAgentToggle();

  const enabled = status.data?.enabled ?? false;
  const nextCycle = status.data?.next_cycle
    ? new Date(status.data.next_cycle).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "—";

  return (
    <Panel title="Agent" subtitle={enabled ? "LIVE" : "STANDBY"} bodyClassName="p-3 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <span className={enabled ? "text-long" : "text-fog"}>
          {enabled ? "LIVE" : "STANDBY"}
        </span>
        <Badge tone={enabled ? "long" : "neutral"}>
          {enabled ? "ACTIVE" : "PAUSED"}
        </Badge>
      </div>

      <div className="grid grid-cols-2 gap-2 text-[11px]">
        <div>
          <span className="text-fog">Next cycle</span>
          <div className="font-mono">{nextCycle}</div>
        </div>
        <div>
          <span className="text-fog">Decisions today</span>
          <div className="font-mono">{status.data?.decisions_today ?? 0}</div>
        </div>
        <div>
          <span className="text-fog">Positions</span>
          <div className="font-mono">{status.data?.positions_open ?? 0}</div>
        </div>
        <div>
          <span className="text-fog">P&L</span>
          <div className={`font-mono ${(status.data?.daily_pnl ?? 0) >= 0 ? "text-long" : "text-short"}`}>
            {status.data?.daily_pnl?.toFixed(2) ?? "0.00"}
          </div>
        </div>
      </div>

      <div className="flex gap-2">
        <Button
          variant={enabled ? "danger" : "primary"}
          onClick={() => toggle.mutate(!enabled)}
          disabled={toggle.isPending}
          className="flex-1"
        >
          {toggle.isPending ? "Working…" : enabled ? "Disable Agent" : "Enable Agent"}
        </Button>
      </div>

      <div className="pt-2 text-[10px] text-fog/70">
        Daily loss limit: {(status.data?.daily_loss_limit ?? 0) * 100}% equity
      </div>
    </Panel>
  );
}