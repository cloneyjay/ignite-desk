/** Types mirroring the FastAPI payloads exactly. No derived business logic. */

export type Side = "long" | "short" | "none";
export type DraftState =
  | "draft"
  | "blocked"
  | "executing"
  | "filled"
  | "failed"
  | "unconfirmed"
  | "expired";

export interface Health {
  ok: boolean;
  timezone: string;
  local_utc_offset_minutes: number;
  server_time_utc: string | null;
  broker_time_server: string | null;
  broker_offset_hours: number | null;
  mcp: { reachable: boolean; url: string; tools: number; error: string | null };
  terminal: {
    connected: boolean;
    state: string | null;
    build: number | null;
    trade_allowed: boolean;
    server: string | null;
  };
  kronos: {
    ready: boolean;
    model?: string;
    model_id?: string;
    load_s?: number;
    threads?: number;
    error?: string;
  };
  queue_depth: number;
  kill_switch: boolean;
  llm: { nim: boolean; local: boolean; extra?: boolean };
  knowledge: {
    ok: boolean;
    cards: number;
    reviewed: number;
    directory?: string;
    issues?: { source: string; code: string; message: string }[];
    error?: string;
  };
}

export interface AccountInfo {
  server: string;
  login: string;
  name: string;
  type: string;
  read_only: boolean;
  margin_mode: string;
  currency: string;
  balance: number;
  credit: number;
  equity: number;
  margin: number;
  margin_free: number;
  margin_level: number | null;
  profit: number;
  swaps: number;
  commissions: number;
  terminal: {
    connected: boolean;
    state: string | null;
    ping_us: number | null;
    build: number | null;
    trade_allowed: boolean;
    experts_trade_allowed: boolean;
    server_time_utc: string | null;
  };
}

export interface Position {
  ticket: string;
  symbol: string;
  side: string;
  lots: number;
  price_open: number;
  price_current: number;
  sl: number | null;
  tp: number | null;
  profit: number;
  swap: number;
  contract_size: number;
  comment: string | null;
  open_time: string | null;
  update_time: string | null;
  risk_at_stop_usd: number | null;
  atr: number | null;
  distance_to_stop_atr: number | null;
}

export interface AccountPayload {
  account: AccountInfo;
  positions: Position[];
  risk: {
    open_risk_usd: number;
    open_risk_pct: number | null;
    cap_pct: number;
    unprotected_tickets: string[];
  };
  today: {
    local_day_start_utc: string;
    realised_usd: number | null;
    trades: number | null;
    wins: number | null;
  };
  server_time_utc: string;
}

export interface EquityPoint {
  ts: string;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
}

export interface SymbolRow {
  symbol: string;
  digits: number;
  point: number;
  contract_size: number;
  tick_value: number;
  volume_min: number;
  volume_max: number;
  volume_step: number;
  stops_level: number;
  added_at: string;
  bid: number | null;
  ask: number | null;
  spread_points: number | null;
}

export interface Bar {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  spread: number;
}

export interface BarsPayload {
  symbol: string;
  timeframe: string;
  count: number;
  last_bar_time: string;
  bars: Bar[];
}

export interface Job {
  job_id: string;
  status: "queued" | "running" | "done" | "failed";
  symbol: string;
  timeframe: string;
  step: string;
  message: string;
  pct: number;
  analysis_id: string | null;
  error: string | null;
  cached: boolean;
  created_at: string;
  progress: { step: string; message: string; pct: number; ts: string }[];
}

export interface Check {
  code: string;
  ok: boolean;
  message: string;
}

export interface Draft {
  id: string;
  analysis_id: string;
  created_at: string;
  expires_at: string;
  expires_in_s: number;
  state: DraftState;
  side: Side;
  lots: number;
  reference_price: number;
  sl: number;
  tp: number;
  risk_usd: number;
  risk_pct: number;
  rr: number;
  margin: number | null;
  worst_case_usd: number | null;
  blocked: boolean;
  block_reason: string | null;
  executable: boolean;
  checks?: Check[];
  live?: {
    bid: number;
    ask: number;
    reference: number;
    spread_points: number;
    drift_atr: number;
  };
  blackout?: {
    event_id: string;
    name: string;
    currency: string;
    impact: string;
    event_time: string;
    start: string;
    end: string;
  } | null;
}

export interface Features {
  atr: number;
  last_close: number;
  last_time: string | null;
  ema_fast: number;
  ema_slow: number;
  realized_vol_pct: number;
  spread_points: number;
  trend: string;
  [key: string]: number | string | null;
}

export interface Signal {
  side: Side;
  p_up: number;
  edge: number;
  edge_atr: number;
  dispersion: number;
  reasons: string[];
  version: string;
}

export interface Analysis {
  id: string;
  symbol: string;
  timeframe: string;
  created_at: string;
  last_bar_time: string;
  lookback: number;
  horizon: number;
  samples: number;
  model_id: string;
  infer_s: number;
  features: Features;
  signal: Signal;
  risk_version: string;
  draft: Draft | null;
  paths?: number[][];
}

export interface DraftDetail {
  draft: Draft;
  analysis: Analysis | null;
}

export interface NarrativeCard {
  id: string;
  title: string;
  version: number;
  scope: string;
}

export interface Narrative {
  run_id: string | null;
  skill: string;
  subject: string | null;
  analysis_id: string | null;
  narrative: string | null;
  provider: "nim" | "local" | "extra" | "template" | string | null;
  model: string | null;
  status: "ok" | "fallback" | "error" | "not_generated" | string;
  fallback: boolean;
  created_at: string | null;
  latency_ms: number | null;
  cards: NarrativeCard[];
  checks: {
    ok?: boolean;
    numbers_checked?: number;
    violations?: { token: string; context: string }[];
    style_issues?: string[];
    template?: boolean;
    provider_errors?: string[];
    rejected_text?: string | null;
  };
  error: string | null;
}

export interface ConfirmResult {
  token: string;
  draft_id: string;
  expires_at: string;
  expires_in_s: number;
  summary: Draft;
}

export interface ExecutionResult {
  ok: boolean;
  state: string;
  confirmed: boolean;
  draft: Draft;
  order: OrderRow | null;
  position: Position | null;
  checks: Check[];
  live: Draft["live"];
  margin: number | null;
  worst_case_usd: number | null;
  broker_check: unknown;
  broker_response: unknown;
}

export interface OrderRow {
  id: string;
  draft_id: string | null;
  created_at: string;
  symbol: string;
  side: string;
  lots: number;
  requested_price: number | null;
  filled_price: number | null;
  sl: number | null;
  tp: number | null;
  ticket: string | null;
  position_id: string | null;
  state: string;
  comment: string | null;
  error: string | null;
}

export interface Trade {
  ticket: string;
  symbol: string;
  side: string | null;
  lots: number;
  entry: number | null;
  exit: number | null;
  gross: number;
  commission: number;
  swap: number;
  open_time: string | null;
  close_time: string | null;
  comment: string | null;
  net: number;
  duration_s: number | null;
  risk_usd: number | null;
  r_multiple: number | null;
}

export interface TradeStats {
  from: string;
  to: string;
  trades: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  net_usd: number;
  gross_win_usd: number;
  gross_loss_usd: number;
  profit_factor: number | null;
  average_win_usd: number | null;
  average_loss_usd: number | null;
  average_r: number | null;
  expectancy_usd: number | null;
  max_drawdown_usd: number;
  average_hold_s: number | null;
}

export interface CalendarEvent {
  id: string;
  event_id: string;
  time: string | null;
  currency: string;
  country: string | null;
  country_code: string | null;
  name: string;
  impact: "high" | "medium" | "low" | "none";
  actual: string | null;
  forecast: string | null;
  previous: string | null;
  unit: string | null;
  digits: number | null;
  sector: string | null;
  time_unknown: boolean;
}

export interface Blackout {
  event_id: string;
  name: string;
  currency: string;
  impact: string;
  event_time: string;
  start: string;
  end: string;
}

export interface NewsItem {
  id: string;
  time: string | null;
  subject: string;
  category: string | null;
  priority: string | number | null;
}

export interface NewsDetail {
  id: string;
  time: string | null;
  subject: string | null;
  category: string | null;
  body: string;
}

export interface Settings {
  kill_switch: boolean;
  risk_pct: number;
  max_risk_pct: number;
  max_drift_atr: number;
  max_spread_points: number;
  sl_atr: number;
  tp_atr: number;
  draft_ttl_s: number;
  timeframes: string[];
  news: { pre_minutes: number; post_minutes: number; currencies: string[] };
}

export interface IgniteEvent {
  type: string;
  ts: string;
  [key: string]: unknown;
}

export interface AgentStatus {
  enabled: boolean;
  operating_mode: string;
  execution_mode: string;
  last_cycle: string | null;
  last_guard: string | null;
  worker_started: string | null;
  worker_heartbeat: string | null;
  next_cycle: string | null;
  decisions_today: number;
  executed_today: number;
  positions_open: number;
  daily_pnl: number;
  daily_loss_limit: number;
}

export interface AgentRisk {
  open_risk_usd: number;
  open_risk_pct: number;
  cap_pct: number;
  daily_pnl: number;
  daily_loss_limit_pct: number;
}

export interface AgentAccount {
  equity: number;
  profit: number;
  server: string;
  currency: string;
  margin_free: number;
  mode: "demo" | "live";
}

export interface AgentOverview {
  status: AgentStatus;
  account: AgentAccount | null;
  account_error: string | null;
  risk: AgentRisk;
  positions: AgentPosition[];
  decisions: Array<{
    id: string;
    created_at: string;
    symbol: string;
    timeframe: string;
    signal_side: string;
    p_up: number | null;
    edge_atr: number | null;
    decision: string;
    confidence: number | null;
    reasoning: string | null;
    executed: boolean;
    execution_error: string | null;
    draft_id: string | null;
  }>;
  drafts: Array<Record<string, unknown>>;
  last_run: AgentRunSummary | null;
  guardrails: {
    kill_switch: boolean;
    risk: Record<string, number>;
    autonomous_enabled: boolean;
  };
  generated_at: string;
}

export interface AgentToggleRequest { enabled: boolean; }
export interface AgentToggleResponse { enabled: boolean; }

export interface AgentPosition {
  ticket: string;
  symbol: string;
  side: "buy" | "sell";
  entry_price: number;
  volume: number;
  sl: number | null;
  tp: number | null;
  trail_sl: number | null;
  opened_at: string;
  unrealised_pnl: number;
  max_favourable_atr: number | null;
  max_adverse_atr: number | null;
  status: "pending" | "open" | "protected" | "trailing" | "partial" | "closing" | "closed" | "orphaned" | "unprotected";
}

export interface ChatMessage {
  role: "user" | "agent";
  content: string;
  timestamp: string;
}

export interface AgentConfig {
  enabled: boolean;
  symbols: string[];
  timeframe: string;
  cycle_interval_min: number;
  session_open_hour: number;
  max_concurrent_analyses: number;
  position_check_interval_sec: number;
  max_concurrent_positions: number;
  daily_loss_limit_pct: number;
  trail_sl_atr: number;
  scale_in_atr: number;
  scale_out_levels: number[];
  max_correlation: number;
  session_end_hour: number;
}

export interface AgentChatRequest {
  text: string;
  session_id?: string | null;
}

export interface AgentSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  archived: boolean;
}

export interface AgentMessage {
  id: string;
  session_id: string;
  created_at: string;
  role: "user" | "agent" | "tool" | "system";
  content: string;
  status: string;
  tool_name: string | null;
  tool_args: Record<string, unknown> | null;
  tool_result: Record<string, unknown> | null;
  latency_ms: number | null;
  links: Record<string, string> | null;
}

export interface AgentToolCall {
  name: string;
  status: string;
  latency_ms: number | null;
  result_preview: string | null;
  arguments: Record<string, unknown> | null;
}

export interface AgentChatResponse {
  route: {
    skill: string;
    args: Record<string, unknown>;
    confidence: number;
  };
  output: {
    run_id: string;
    skill: string;
    subject: string | null;
    analysis_id: string | null;
    narrative: string | null;
    provider: string | null;
    model: string | null;
    status: string;
    fallback: boolean;
    created_at: string | null;
    latency_ms: number | null;
    cards: { id: string; title: string; version: number; scope: string }[];
    checks: {
      ok?: boolean;
      numbers_checked?: number;
      violations?: { token: string; context: string }[];
      style_issues?: string[];
      template?: boolean;
      provider_errors?: string[];
      rejected_text?: string | null;
    };
    error: string | null;
    structured?: Record<string, unknown>;
  };
  session_id: string;
  tool_calls: AgentToolCall[];
}

export interface AgentRunSummary {
  id: string;
  created_at: string;
  skill: string;
  subject: string | null;
  provider: string | null;
  model: string | null;
  status: string;
  fallback: boolean;
  latency_ms: number | null;
  cards: string[];
  checks: {
    ok?: boolean;
    numbers_checked?: number;
    violations?: unknown[];
  };
  narrative: string | null;
  error: string | null;
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


export interface Strategy {
  id: string;
  name: string;
  description: string | null;
  symbol: string;
  timeframe: string;
  mql5_code: string;
  status: "draft" | "compiled" | "backtested" | "shadow" | "demo" | "live" | "archived";
  version: number;
  p_up: number | null;
  edge_atr: number | null;
  total_trades: number | null;
  winning_trades: number | null;
  losing_trades: number | null;
  win_rate: number | null;
  profit_factor: number | null;
  max_drawdown: number | null;
  sharpe_ratio: number | null;
  initial_balance: number | null;
  final_balance: number | null;
  parameters: Record<string, any>;
  created_at: string;
  updated_at: string;
  backtest_id: string | null;
}

export interface StrategyBacktest {
  id: string;
  strategy_id: string;
  version: number;
  start_date: string;
  end_date: string;
  symbol: string;
  timeframe: string;
  initial_balance: number;
  final_balance: number | null;
  gross_profit: number | null;
  gross_loss: number | null;
  net_profit: number | null;
  profit_factor: number | null;
  total_trades: number | null;
  winning_trades: number | null;
  losing_trades: number | null;
  win_rate: number | null;
  max_drawdown: number | null;
  max_drawdown_pct: number | null;
  sharpe_ratio: number | null;
  recovery_factor: number | null;
  expectancy: number | null;
  equity_curve: Array<{ ts: string; balance: number; equity: number }>;
  trades: any[];
  parameters: Record<string, any>;
  tester_report: any;
  created_at: string;
}

export interface StrategyStrategyResponse {
  strategy: Strategy;
  backtests: StrategyBacktest[];
}

export interface StrategiesListResponse {
  strategies: Strategy[];
  count: number;
}

export interface StrategyPromoteResponse {
  ok: boolean;
  strategy_id: string;
  from: string;
  to: string;
}

export interface StrategyDemoteResponse {
  ok: boolean;
  strategy_id: string;
  from: string;
  to: string;
}
