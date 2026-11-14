import { Badge, Button, EmptyState, Panel } from "../components/ui";
import { AgentPlan, AgentPlanStep } from "../lib/types";
import { ChevronDownIcon, ChevronRightIcon, CheckCircleIcon, XCircleIcon, ClockIcon, ZapIcon } from "../components/icons";

interface PlanPanelProps {
  plan: AgentPlan | null;
  onStepClick: (step: AgentPlanStep, index: number) => void;
  isActive?: boolean;
}

const stepStatusConfig = {
  pending: { tone: "neutral" as const, icon: ClockIcon, label: "Pending" },
  running: { tone: "gold" as const, icon: ZapIcon, label: "Running" },
  completed: { tone: "long" as const, icon: CheckCircleIcon, label: "Completed" },
  failed: { tone: "short" as const, icon: XCircleIcon, label: "Failed" },
} as const;

function StepRow({ step, index, isCurrent, onClick }: { step: AgentPlanStep; index: number; isCurrent: boolean; onClick: () => void }) {
  const config = stepStatusConfig[step.status];
  const Icon = config.icon;

  return (
    <button
      onClick={onClick}
      className={`relative w-full border border-l-2 text-left transition-colors ${
        isCurrent
          ? "border-gold-500/40 border-l-gold-500 bg-gold-500/[0.05]"
          : "border-line/60 border-l-line bg-ink-900/60 hover:border-line-strong hover:bg-ink-850/60"
      }`}
      style={{ padding: isCurrent ? "12px 14px" : "10px 14px" }}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center border border-line/60 bg-ink-950/60">
          <span className="font-mono text-[10px] tabular-nums text-fog">{index + 1}</span>
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Badge tone={config.tone} dot size="sm">{config.label}</Badge>
            <span className="truncate font-mono text-[10px] text-gold-400/90">{step.tool}</span>
            {isCurrent && <span className="pulse-soft font-mono text-[9px] uppercase tracking-[0.1em] text-gold-400">live</span>}
          </div>
          <p className="mt-1.5 text-[12px] leading-snug text-paper/85">{step.expected_outcome}</p>
          <p className="mt-1 text-[10.5px] leading-snug text-fog">Success: {step.success_criteria}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Icon className={`h-3.5 w-3.5 ${config.tone === "neutral" ? "text-fog" : config.tone === "gold" ? "text-gold-400" : config.tone === "long" ? "text-long" : "text-short"}`} />
          <ChevronRightIcon className="h-3.5 w-3.5 text-fog/40" />
        </div>
      </div>
      {step.tool_result && (
        <details className="mt-3 animate-fade border-t border-line/50 pt-3">
          <summary className="flex cursor-pointer items-center gap-2 text-[10px] font-medium uppercase tracking-[0.08em] text-gold-400">
            <ChevronDownIcon className="h-3 w-3" />
            Tool result
          </summary>
          <pre className="mt-2 overflow-x-auto border border-line/50 bg-ink-950 p-2.5 font-mono text-[10px] leading-relaxed text-paper/80">
            {JSON.stringify(step.tool_result, null, 2)}
          </pre>
        </details>
      )}
    </button>
  );
}

export function PlanPanel({ plan, onStepClick, isActive = false }: PlanPanelProps) {
  if (!plan) {
    return (
      <Panel
        title="Execution Plan"
        subtitle="Multi-step tool orchestration"
        className={isActive ? "border-gold-500/30" : ""}
      >
        <EmptyState
          title="No active plan"
          message="Ask Aegus to create a plan for complex tasks like position analysis, risk assessment, or multi-step workflows."
          action={
            <Button variant="ghost" size="sm" onClick={() => onStepClick({ tool: "", args: {}, expected_outcome: "", success_criteria: "", status: "pending", tool_result: null }, -1)}>
              Create Plan
            </Button>
          }
        />
      </Panel>
    );
  }

  return (
    <Panel
      title="Execution Plan"
      subtitle={`${plan.steps.length} steps · Step ${plan.current_step + 1} of ${plan.steps.length}`}
      className={isActive ? "border-gold-500/30" : ""}
      bodyClassName="space-y-3 p-4"
    >
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-[12.5px] font-semibold text-paper">{plan.goal}</h3>
        <Badge tone={plan.status === "running" ? "gold" : plan.status === "completed" ? "long" : plan.status === "failed" ? "short" : "neutral"} dot>
          {plan.status}
        </Badge>
      </div>
      <ProgressBar pct={((plan.current_step + (plan.steps[plan.current_step]?.status === "completed" ? 1 : 0)) / plan.steps.length) * 100} className="mb-3" />
      <div className="space-y-2" role="list" aria-label="Plan steps">
        {plan.steps.map((step, index) => (
          <StepRow
            key={index}
            step={step}
            index={index}
            isCurrent={index === plan.current_step}
            onClick={() => onStepClick(step, index)}
          />
        ))}
      </div>
    </Panel>
  );
}

function ProgressBar({ pct, className = "" }: { pct: number; className?: string }) {
  return (
    <div className={`h-1 w-full overflow-hidden bg-ink-700 ${className}`}>
      <div
        className="h-full bg-gold-500 transition-[width] duration-300"
        style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
      />
    </div>
  );
}