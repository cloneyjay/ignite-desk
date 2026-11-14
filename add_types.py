# Read the current types.ts file
with open('frontend/src/lib/types.ts', 'r', encoding='utf-8') as f:
    content = f.read()

# New types to append
new_types = '''

export interface AgentPlan {
  plan_id: string;
  goal: string;
  steps: AgentPlanStep[];
  status: "created" | "running" | "completed" | "failed";
  current_step: number;
  created_at: string;
}

export interface AgentPlanStep {
  tool: string;
  args: Record<string, unknown>;
  expected_outcome: string;
  success_criteria: string;
  status: "pending" | "running" | "completed" | "failed";
  tool_result: Record<string, unknown> | null;
}

export interface AgentReflection {
  reflection_id: string;
  decision_id: string;
  outcome: string;
  insights: Record<string, unknown>;
  created_at: string;
}

export interface DecisionExplanation {
  action: string;
  conviction: number;
  thesis: string;
  evidence: string[];
  counterfactuals: string[];
  entry: { type: "market" | "limit"; price: number };
  risk: { lots: number; sl: number; tp: number };
  expected_rr: number;
  invalidate_if: string[];
  links: { analysis_id: string | null; draft_id: string | null; decision_id: string };
  confidence_score: number;
}

export interface Pattern {
  pattern_id: string;
  name: string;
  description: string;
  win_rate: number;
  avg_r: number;
  sample_size: number;
  conditions: Record<string, unknown>;
  regime: string | null;
}

export interface ABTestReport {
  variant_a: string;
  variant_b: string;
  winner: string;
  p_value: number;
  confidence: number;
  sample_size_a: number;
  sample_size_b: number;
  metric_a: number;
  metric_b: number;
  lift_pct: number;
}

export interface BacktestReport {
  total_decisions: number;
  winning_decisions: number;
  losing_decisions: number;
  win_rate: number;
  total_pnl: number;
  sharpe: number;
  max_drawdown: number;
  avg_r_multiple: number;
  profit_factor: number;
  expectancy: number;
  decisions: Array<Record<string, unknown>>;
}

export interface LearningReport {
  patterns: Pattern[];
  ab_tests: ABTestReport[];
  policy_updates: PolicyUpdate[];
  regime_policies: Record<string, RegimePolicy>;
}

export interface PlanPanelProps {
  plan: AgentPlan | null;
  onStepClick: (step: AgentPlanStep) => void;
}

export interface MemoryPanelProps {
  messages: AgentMessage[];
  onLoadMore: () => void;
  hasMore: boolean;
}

export interface ReasoningStreamProps {
  events: Array<{ type: string; content: string; tool_name?: string; timestamp: string }>;
}

export interface DecisionCardProps {
  decision: DecisionExplanation;
}

export interface ToolRowProps {
  tool: { name: string; status: string; latency_ms: number | null; result_preview: string | null; arguments: Record<string, unknown> | null };
}

export interface DecisionCardProps {
  decision: DecisionExplanation;
}

export interface ToolRowProps {
  tool: { name: string; status: string; latency_ms: number | null; result_preview: string | null; arguments: Record<string, unknown> | null };
}

export interface DecisionCardProps {
  decision: DecisionExplanation;
}
'''

# Read the file
with open('frontend/src/lib/types.ts', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the end of the file and append new types
# Find the last closing brace
last_brace = content.rfind('}')
if last_brace != -1:
    new_content = content[:last_brace + 1] + '\n' + new_types
    with open('frontend/src/lib/types.ts', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Types appended successfully")
else:
    print("Could not find end of file")