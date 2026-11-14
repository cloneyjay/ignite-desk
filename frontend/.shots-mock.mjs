/**
 * Design-review harness: renders every screen against deterministic fixtures
 * so panels can be inspected with realistic density (no MT5 terminal needed).
 * Throwaway, like the other .shots-* scripts.
 */
import fs from "node:fs/promises";
import path from "node:path";
import puppeteer from "puppeteer-core";

const CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const BASE = "http://127.0.0.1:5173";
const OUT = path.resolve(".shots/mock");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const now = Date.now();
const iso = (ms) => new Date(ms).toISOString();
const round = (v, d = 2) => Number(v.toFixed(d));

/* ------------------------------------------------------------------ bars */
function makeBars(symbol, tf, count = 200) {
  const stepMs = { M5: 300_000, M15: 900_000, M30: 1_800_000, H1: 3_600_000 }[tf] ?? 900_000;
  const digits = symbol.includes("JPY") ? 3 : symbol === "XAUUSD" ? 2 : 5;
  const base = symbol === "XAUUSD" ? 2618 : symbol.includes("JPY") ? 154.2 : symbol === "EURUSD" ? 1.0872 : 1.2645;
  let price = base;
  const bars = [];
  const start = now - stepMs * count;
  for (let i = 0; i < count; i += 1) {
    const drift = Math.sin(i / 11) * base * 0.00035 + (i > count * 0.72 ? base * 0.00012 : 0);
    const noise = (Math.sin(i * 2.17) + Math.cos(i * 0.71)) * base * 0.00042;
    const open = price;
    const close = open + drift + noise;
    const high = Math.max(open, close) + Math.abs(Math.sin(i * 1.3)) * base * 0.00055;
    const low = Math.min(open, close) - Math.abs(Math.cos(i * 0.9)) * base * 0.0005;
    bars.push({
      time: iso(start + i * stepMs),
      open: round(open, digits),
      high: round(high, digits),
      low: round(low, digits),
      close: round(close, digits),
      volume: Math.round(800 + Math.abs(noise) * 90000),
      spread: 12 + (i % 5),
    });
    price = close;
  }
  return bars;
}

const goldBars = makeBars("XAUUSD", "M15");
const lastBar = goldBars[goldBars.length - 1];
const lastClose = lastBar.close;

const health = {
  ok: true,
  timezone: "Europe/London",
  local_utc_offset_minutes: 0,
  server_time_utc: iso(now),
  broker_time_server: iso(now),
  broker_offset_hours: 0,
  mcp: { reachable: true, url: "http://127.0.0.1:22346/mcp", tools: 24, error: null },
  terminal: {
    connected: true,
    state: "synchronized",
    build: 4620,
    trade_allowed: true,
    server: "MetaQuotes-Demo",
  },
  kronos: { ready: true, model: "Kronos-mini", model_id: "NeoQuasar/Kronos-mini", load_s: 1.8, threads: 8 },
  queue_depth: 0,
  kill_switch: false,
  llm: { nim: true, local: true, extra: false },
  knowledge: { ok: true, cards: 148, reviewed: 132, directory: "knowledge" },
};

const settings = {
  kill_switch: false,
  risk_pct: 0.02,
  max_risk_pct: 0.02,
  max_drift_atr: 0.3,
  max_spread_points: 30,
  sl_atr: 1.5,
  tp_atr: 3,
  draft_ttl_s: 90,
  timeframes: ["M5", "M15", "M30", "H1"],
  news: { pre_minutes: 30, post_minutes: 15, currencies: ["USD", "EUR", "CNH", "JPY"] },
};

const symbols = [
  { symbol: "XAUUSD", digits: 2, point: 0.01, contract_size: 100, tick_value: 1, volume_min: 0.01, volume_max: 50, volume_step: 0.01, stops_level: 30, added_at: iso(now - 86400000 * 12), bid: lastClose - 0.18, ask: lastClose + 0.12, spread_points: 30 },
  { symbol: "EURUSD", digits: 5, point: 0.00001, contract_size: 100000, tick_value: 1, volume_min: 0.01, volume_max: 100, volume_step: 0.01, stops_level: 10, added_at: iso(now - 86400000 * 9), bid: 1.08721, ask: 1.08734, spread_points: 13 },
  { symbol: "GBPUSD", digits: 5, point: 0.00001, contract_size: 100000, tick_value: 1, volume_min: 0.01, volume_max: 100, volume_step: 0.01, stops_level: 10, added_at: iso(now - 86400000 * 8), bid: 1.26442, ask: 1.26458, spread_points: 16 },
  { symbol: "USDJPY", digits: 3, point: 0.001, contract_size: 100000, tick_value: 0.65, volume_min: 0.01, volume_max: 100, volume_step: 0.01, stops_level: 10, added_at: iso(now - 86400000 * 7), bid: 154.212, ask: 154.224, spread_points: 12 },
];

const checks = [
  { code: "kill_switch", ok: true, message: "Kill switch is clear" },
  { code: "terminal", ok: true, message: "Terminal synchronized · MetaQuotes-Demo" },
  { code: "spread", ok: true, message: "Spread 30 pts is inside the 30 pt cap" },
  { code: "drift", ok: true, message: "Price drift 0.08 ATR is inside 0.30 ATR" },
  { code: "blackout", ok: true, message: "No high-impact window overlaps this draft" },
  { code: "margin", ok: true, message: "Free margin covers the worst case" },
];

const analysis = {
  id: "ana-20261114-xauusd-m15",
  symbol: "XAUUSD",
  timeframe: "M15",
  created_at: iso(now - 42_000),
  last_bar_time: lastBar.time,
  lookback: 512,
  horizon: 12,
  samples: 25,
  model_id: "NeoQuasar/Kronos-mini",
  infer_s: 1.42,
  features: {
    atr: 3.84,
    last_close: lastClose,
    last_time: lastBar.time,
    ema_fast: round(lastClose - 0.62),
    ema_slow: round(lastClose - 1.18),
    realized_vol_pct: 0.42,
    spread_points: 30,
    trend: "up",
  },
  signal: {
    side: "long",
    p_up: 0.638,
    edge: 4.12,
    edge_atr: 1.07,
    dispersion: 0.34,
    version: "signal-v3.2",
    reasons: [
      "Fast EMA is above the slow EMA on the last closed bar",
      "Path distribution skewed positive: 64% of 25 samples close above spot",
      "Realised volatility is inside the 30-day median band",
      "No high-impact release inside the 30/15 minute blackout window",
    ],
  },
  risk_version: "risk-v2.1",
  draft: {
    id: "draft-9f31",
    analysis_id: "ana-20261114-xauusd-m15",
    created_at: iso(now - 40_000),
    expires_at: iso(now + 88_000),
    expires_in_s: 88,
    state: "draft",
    side: "long",
    lots: 0.06,
    reference_price: lastClose,
    sl: round(lastClose - 5.76),
    tp: round(lastClose + 11.52),
    risk_usd: 34.56,
    risk_pct: 0.0141,
    rr: 2,
    margin: 157.08,
    worst_case_usd: 36.1,
    blocked: false,
    block_reason: null,
    executable: true,
    checks,
    live: {
      bid: round(lastClose - 0.18),
      ask: round(lastClose + 0.12),
      reference: lastClose,
      spread_points: 30,
      drift_atr: 0.08,
    },
    blackout: null,
  },
  paths: [],
};

const narrative = {
  run_id: "run-7c2",
  skill: "analysis_narrative",
  subject: "XAUUSD M15",
  analysis_id: analysis.id,
  narrative:
    "Gold is holding a constructive intraday structure. The 25-sample path distribution leans long, with the median path extending roughly one ATR above the last close while dispersion stays contained. The deterministic draft sizes 0.06 lots against a 1.5 ATR stop, keeping risk at 1.41% of equity. Treat the setup as invalid if price closes back below the fast EMA before the 12-bar horizon completes.",
  provider: "nim",
  model: "nvidia/nemotron-3-ultra-550b-a55b",
  status: "ok",
  fallback: false,
  created_at: iso(now - 30_000),
  latency_ms: 1840,
  cards: [{ id: "trend-follow", title: "Trend continuation", version: 3, scope: "intraday" }],
  checks: { ok: true, numbers_checked: 9, violations: [], style_issues: [] },
  error: null,
};

function makeEquity(range) {
  const count = range === "1d" ? 36 : range === "1w" ? 56 : range === "1m" ? 60 : 90;
  const points = [];
  let equity = 26_400;
  for (let i = 0; i < count; i += 1) {
    const wave = Math.sin(i / 3.2) * 110 + Math.cos(i / 1.7) * 42;
    const lift = i * (range === "1d" ? 16 : 38);
    points.push({
      ts: iso(now - (count - i) * (range === "1d" ? 1_500_000 : 7_200_000)),
      balance: round(24_000 + lift * 0.4),
      equity: round(equity + wave + lift),
      margin: 420,
      free_margin: round(equity + wave + lift - 420),
    });
    equity += 0;
  }
  return { range, points };
}

const positions = [
  {
    ticket: "91440218",
    symbol: "XAUUSD",
    side: "buy",
    lots: 0.08,
    price_open: 2607.4,
    price_current: lastClose,
    sl: 2599.1,
    tp: 2636.8,
    profit: 86.4,
    swap: -0.72,
    contract_size: 100,
    comment: "ignite-draft:9f31",
    open_time: iso(now - 4_200_000),
    update_time: iso(now - 12_000),
    risk_at_stop_usd: 66.4,
    atr: 3.84,
    distance_to_stop_atr: 2.16,
  },
  {
    ticket: "91440107",
    symbol: "EURUSD",
    side: "sell",
    lots: 0.35,
    price_open: 1.08942,
    price_current: 1.08727,
    sl: 1.0921,
    tp: 1.0839,
    profit: 75.25,
    swap: 0.18,
    contract_size: 100000,
    comment: "ignite-draft:8a20",
    open_time: iso(now - 9_600_000),
    update_time: iso(now - 9_000),
    risk_at_stop_usd: 93.8,
    atr: 0.00091,
    distance_to_stop_atr: 2.36,
  },
];

const accountPayload = {
  account: {
    server: "MetaQuotes-Demo",
    login: "61420877",
    name: "Ignite Research",
    type: "demo",
    read_only: false,
    margin_mode: "retail hedging",
    currency: "USD",
    balance: 26_842.18,
    credit: 0,
    equity: 26_978.42,
    margin: 612.4,
    margin_free: 26_366.02,
    margin_level: 4405.1,
    profit: 161.65,
    swaps: -0.54,
    commissions: -7.2,
    terminal: {
      connected: true,
      state: "synchronized",
      ping_usd: 38,
      build: 4620,
      trade_allowed: true,
      experts_trade_allowed: true,
      server_time_utc: iso(now),
    },
  },
  positions,
  risk: { open_risk_usd: 160.2, open_risk_pct: 0.0059, cap_pct: 0.02, unprotected_tickets: [] },
  today: { local_day_start_utc: iso(now - 8 * 3600_000), realised_usd: 184.3, trades: 4, wins: 3 },
  server_time_utc: iso(now),
};

const trades = [
  { ticket: "91439772", symbol: "XAUUSD", side: "buy", lots: 0.05, entry: 2598.4, exit: 2611.7, gross: 66.5, commission: -2.4, swap: -0.2, open_time: iso(now - 26_400_000), close_time: iso(now - 22_000_000), comment: "ignite-draft:7b12", net: 63.9, duration_s: 4400, risk_usd: 28.8, r_multiple: 2.22 },
  { ticket: "91439410", symbol: "EURUSD", side: "sell", lots: 0.4, entry: 1.0908, exit: 1.0872, gross: 144, commission: -3.2, swap: 0.1, open_time: iso(now - 34_000_000), close_time: iso(now - 29_000_000), comment: "ignite-draft:6c44", net: 140.9, duration_s: 5000, risk_usd: 71.2, r_multiple: 1.98 },
  { ticket: "91439002", symbol: "XAUUSD", side: "sell", lots: 0.04, entry: 2614.2, exit: 2617.9, gross: -14.8, commission: -1.9, swap: -0.1, open_time: iso(now - 44_000_000), close_time: iso(now - 41_000_000), comment: "ignite-draft:5a91", net: -16.8, duration_s: 3000, risk_usd: 22.4, r_multiple: -0.75 },
  { ticket: "91438655", symbol: "GBPUSD", side: "buy", lots: 0.3, entry: 1.2618, exit: 1.2649, gross: 93, commission: -2.8, swap: 0.05, open_time: iso(now - 52_000_000), close_time: iso(now - 48_400_000), comment: "ignite-draft:4d10", net: 90.25, duration_s: 3600, risk_usd: 58.4, r_multiple: 1.55 },
  { ticket: "91438211", symbol: "USDJPY", side: "sell", lots: 0.25, entry: 154.62, exit: 154.18, gross: 71.2, commission: -2.1, swap: 0.22, open_time: iso(now - 70_000_000), close_time: iso(now - 64_000_000), comment: "ignite-draft:3f27", net: 69.32, duration_s: 6000, risk_usd: 44.6, r_multiple: 1.55 },
  { ticket: "91437940", symbol: "XAUUSD", side: "buy", lots: 0.06, entry: 2621.3, exit: 2614.0, gross: -43.8, commission: -2.6, swap: -0.15, open_time: iso(now - 88_000_000), close_time: iso(now - 83_000_000), comment: "ignite-draft:2b88", net: -46.55, duration_s: 5000, risk_usd: 33.2, r_multiple: -1.4 },
  { ticket: "91437412", symbol: "EURUSD", side: "buy", lots: 0.5, entry: 1.0841, exit: 1.0869, gross: 140, commission: -3.4, swap: -0.02, open_time: iso(now - 105_000_000), close_time: iso(now - 99_000_000), comment: "ignite-draft:1e52", net: 136.58, duration_s: 6000, risk_usd: 84.1, r_multiple: 1.62 },
  { ticket: "91437008", symbol: "GBPUSD", side: "sell", lots: 0.2, entry: 1.2691, exit: 1.2702, gross: -22, commission: -1.6, swap: 0.03, open_time: iso(now - 121_000_000), close_time: iso(now - 117_000_000), comment: "ignite-draft:0c19", net: -23.57, duration_s: 4000, risk_usd: 39.8, r_multiple: -0.59 },
];

const stats = {
  from: iso(now - 30 * 86400000),
  to: iso(now),
  trades: 8,
  wins: 5,
  losses: 3,
  win_rate: 0.625,
  net_usd: 414.03,
  gross_win_usd: 511.7,
  gross_loss_usd: -97.7,
  profit_factor: 2.61,
  average_win_usd: 100.19,
  average_loss_usd: -30.76,
  average_r: 1.03,
  expectancy_usd: 51.75,
  max_drawdown_usd: 72.4,
  average_hold_s: 5000,
};

const calendar = {
  from: iso(now - 86400000),
  to: iso(now + 86400000),
  events: [
    { id: "ev1", event_id: "us-cpi", time: iso(now + 2 * 3600_000), currency: "USD", country: "United States", country_code: "US", name: "Core CPI m/m", impact: "high", actual: null, forecast: "0.3%", previous: "0.2%", unit: "%", digits: 1, sector: "Inflation", time_unknown: false },
    { id: "ev2", event_id: "eu-gdp", time: iso(now + 3.5 * 3600_000), currency: "EUR", country: "Euro Area", country_code: "EU", name: "GDP q/q (prelim)", impact: "high", actual: null, forecast: "0.2%", previous: "0.1%", unit: "%", digits: 1, sector: "Growth", time_unknown: false },
    { id: "ev3", event_id: "uk-retail", time: iso(now + 5 * 3600_000), currency: "GBP", country: "United Kingdom", country_code: "GB", name: "Retail sales m/m", impact: "medium", actual: null, forecast: "0.4%", previous: "-0.3%", unit: "%", digits: 1, sector: "Consumer", time_unknown: false },
    { id: "ev4", event_id: "jp-tankan", time: iso(now + 24 * 3600_000), currency: "JPY", country: "Japan", country_code: "JP", name: "Tankan large manufacturers index", impact: "medium", actual: null, forecast: "12", previous: "11", unit: null, digits: 0, sector: "Business", time_unknown: false },
    { id: "ev5", event_id: "cn-trade", time: iso(now + 26 * 3600_000), currency: "CNH", country: "China", country_code: "CN", name: "Trade balance", impact: "high", actual: null, forecast: "72.4B", previous: "68.1B", unit: "USD", digits: 1, sector: "Trade", time_unknown: false },
    { id: "ev6", event_id: "us-claims", time: iso(now + 27 * 3600_000), currency: "USD", country: "United States", country_code: "US", name: "Unemployment claims", impact: "medium", actual: null, forecast: "221K", previous: "218K", unit: "K", digits: 0, sector: "Labour", time_unknown: false },
  ],
};

const blackouts = {
  from: iso(now),
  to: iso(now + 48 * 3600_000),
  pre_minutes: 30,
  post_minutes: 15,
  blackouts: [
    { event_id: "us-cpi", name: "Core CPI m/m", currency: "USD", impact: "high", event_time: iso(now + 2 * 3600_000), start: iso(now + 1.5 * 3600_000), end: iso(now + 2.25 * 3600_000) },
    { event_id: "eu-gdp", name: "GDP q/q (prelim)", currency: "EUR", impact: "high", event_time: iso(now + 3.5 * 3600_000), start: iso(now + 3 * 3600_000), end: iso(now + 3.75 * 3600_000) },
    { event_id: "cn-trade", name: "Trade balance", currency: "CNH", impact: "high", event_time: iso(now + 26 * 3600_000), start: iso(now + 25.5 * 3600_000), end: iso(now + 26.25 * 3600_000) },
  ],
};

const news = {
  count: 5,
  news: [
    { id: "n1", time: iso(now - 1.2 * 3600_000), subject: "Dollar steadies before US CPI as traders trim rate-cut bets", category: "FX", priority: 1 },
    { id: "n2", time: iso(now - 3.4 * 3600_000), subject: "Gold holds above $2,600 as ETF inflows resume", category: "Metals", priority: 1 },
    { id: "n3", time: iso(now - 6.1 * 3600_000), subject: "ECB officials signal patience after softer GDP prints", category: "Rates", priority: 2 },
    { id: "n4", time: iso(now - 8.8 * 3600_000), subject: "Yen firms as Tokyo signals readiness to intervene", category: "FX", priority: 2 },
    { id: "n5", time: iso(now - 11.5 * 3600_000), subject: "Copper slips on weaker China property data", category: "Commodities", priority: 3 },
  ],
};

const newsDetail = {
  id: "n1",
  time: iso(now - 1.2 * 3600_000),
  subject: "Dollar steadies before US CPI as traders trim rate-cut bets",
  category: "FX",
  body:
    "The dollar held a narrow range on Friday as traders waited for the US consumer price report, the last major data point before the December policy decision.\n\nOptions markets now imply a lower probability of an early cut, and short-dated yields have edged higher. The desk treats the release as a high-impact blackout: new orders are blocked from 30 minutes before the print until 15 minutes after it.\n\nGold remains bid above $2,600 while the euro consolidates near 1.0870.",
};

const agentStatus = {
  enabled: true,
  operating_mode: "autonomous",
  execution_mode: "shadow",
  last_cycle: iso(now - 4 * 60_000),
  last_guard: "Skipped EURUSD: spread 34 pts above the 30 pt cap.",
  worker_started: iso(now - 7 * 3600_000),
  worker_heartbeat: iso(now - 18_000),
  next_cycle: iso(now + 11 * 60_000),
  decisions_today: 6,
  executed_today: 2,
  positions_open: 2,
  daily_pnl: 184.3,
  daily_loss_limit: 536.0,
};

const agentOverview = {
  status: agentStatus,
  account: { equity: 26_978.42, profit: 161.65, server: "MetaQuotes-Demo", currency: "USD", margin_free: 26_366.02, mode: "demo" },
  account_error: null,
  risk: { open_risk_usd: 160.2, open_risk_pct: 0.0059, cap_pct: 0.02, daily_pnl: 184.3, daily_loss_limit_pct: 0.02 },
  positions: positions.map((p) => ({
    ticket: p.ticket,
    symbol: p.symbol,
    side: p.side,
    entry_price: p.price_open,
    volume: p.lots,
    sl: p.sl,
    tp: p.tp,
    trail_sl: null,
    opened_at: p.open_time,
    unrealised_pnl: p.profit,
    max_favourable_atr: 1.8,
    max_adverse_atr: -0.4,
    status: "protected",
  })),
  decisions: [
    { id: "dec-3", created_at: iso(now - 4 * 60_000), symbol: "XAUUSD", timeframe: "M15", signal_side: "long", p_up: 0.638, edge_atr: 1.07, decision: "LONG", confidence: 0.74, reasoning: "Trend continuation with contained dispersion; risk sized at 1.41% of equity and the draft passed every live check.", executed: false, execution_error: null, draft_id: "draft-9f31" },
    { id: "dec-2", created_at: iso(now - 34 * 60_000), symbol: "EURUSD", timeframe: "M15", signal_side: "none", p_up: 0.512, edge_atr: 0.18, decision: "NO_TRADE", confidence: 0.41, reasoning: "Edge below the 0.35 ATR threshold; the spread also widened past the cap.", executed: false, execution_error: null, draft_id: null },
    { id: "dec-1", created_at: iso(now - 64 * 60_000), symbol: "GBPUSD", timeframe: "M30", signal_side: "short", p_up: 0.34, edge_atr: 0.92, decision: "SHORT", confidence: 0.68, reasoning: "Failed breakout above the session high; draft blocked by the economic calendar window.", executed: false, execution_error: "blackout", draft_id: null },
  ],
  drafts: [],
  last_run: null,
  guardrails: { kill_switch: false, risk: { risk_pct: 0.02, max_risk_pct: 0.02 }, autonomous_enabled: true },
  generated_at: iso(now),
};

const sessions = {
  count: 2,
  sessions: [
    { id: "ses-live", title: "Morning risk review", created_at: iso(now - 2 * 86400000), updated_at: iso(now - 9 * 60_000), archived: false },
    { id: "ses-brief", title: "Daily brief · 13 Nov", created_at: iso(now - 86400000), updated_at: iso(now - 86400000), archived: false },
  ],
};

const messages = {
  count: 5,
  hasMore: false,
  cursor: null,
  messages: [
    { id: "m1", session_id: "ses-live", created_at: iso(now - 12 * 60_000), role: "user", content: "What is my current risk?", status: "ok", tool_name: null, tool_args: null, tool_result: null, latency_ms: null, links: null },
    { id: "m2", session_id: "ses-live", created_at: iso(now - 11.8 * 60_000), role: "tool", content: "portfolio risk snapshot", status: "success", tool_name: "portfolio.risk", tool_args: { include_positions: true }, tool_result: { open_risk_usd: 160.2, cap_pct: 0.02, positions: 2 }, latency_ms: 184, links: null },
    { id: "m3", session_id: "ses-live", created_at: iso(now - 11.6 * 60_000), role: "agent", content: "Open risk is $160.20, or 0.59% of equity against a 2.00% cap. Two positions are open and both carry a stop.\n\nXAUUSD long is 2.16 ATR from its stop; EURUSD short is 2.36 ATR away. Daily realised P/L is +$184.30, so the loss limit is nowhere near binding.\n\nThe next scheduled cycle is in 11 minutes. I will leave sizing unchanged unless the CPI blackout shifts the spread.", status: "ok", tool_name: null, tool_args: null, tool_result: null, latency_ms: 1430, links: null },
    { id: "m4", session_id: "ses-live", created_at: iso(now - 10 * 60_000), role: "user", content: "Anything I should avoid before the CPI print?", status: "ok", tool_name: null, tool_args: null, tool_result: null, latency_ms: null, links: null },
    { id: "m5", session_id: "ses-live", created_at: iso(now - 9.7 * 60_000), role: "agent", content: "Yes — the USD core CPI window opens in 90 minutes and runs for 45 minutes. New drafts during that window will be blocked deterministically, regardless of the forecast.\n\nIf you want exposure before the print, the {analysis} link shows the current XAUUSD draft; it expires in 88 seconds and would need a refresh.", status: "ok", tool_name: null, tool_args: null, tool_result: null, latency_ms: 1210, links: { analysis: analysis.id } },
  ],
};

const agentConfig = {
  enabled: true,
  symbols: ["XAUUSD", "EURUSD", "GBPUSD", "USDJPY"],
  timeframe: "M15",
  cycle_interval_min: 15,
  session_open_hour: 7,
  max_concurrent_analyses: 2,
  position_check_interval_sec: 30,
  max_concurrent_positions: 3,
  daily_loss_limit_pct: 0.02,
  trail_sl_atr: 1.2,
  scale_in_atr: 0.8,
  scale_out_levels: [1, 2, 3],
  max_correlation: 0.7,
  session_end_hour: 21,
};

const payloadFor = (url) => {
  const u = new URL(url);
  const p = u.pathname.replace(/^\/api/, "");
  const q = u.searchParams;

  if (p === "/health") return health;
  if (p === "/settings") return settings;
  if (p === "/symbols") return { symbols };
  if (p === "/account") return accountPayload;
  if (p === "/portfolio/equity") return makeEquity(q.get("range") ?? "1d");
  if (p === "/bars") {
    const symbol = q.get("symbol") ?? "XAUUSD";
    const tf = q.get("tf") ?? "M15";
    const bars = symbol === "XAUUSD" ? goldBars : makeBars(symbol, tf);
    return { symbol, timeframe: tf, count: bars.length, last_bar_time: bars[bars.length - 1].time, bars };
  }
  if (p === "/analyses/latest") return analysis;
  if (p === "/analyses/ana-20261114-xauusd-m15") return analysis;
  if (p === `/analyses/${analysis.id}/narrative`) return narrative;
  if (p === `/drafts/${analysis.draft.id}`) return { draft: analysis.draft, analysis };
  if (p === `/drafts/${analysis.draft.id}/confirm`)
    return { token: "tok-fixture", draft_id: analysis.draft.id, expires_at: iso(now + 30_000), expires_in_s: 30, summary: analysis.draft };
  if (p === `/drafts/${analysis.draft.id}/execute`)
    return {
      ok: true,
      state: "filled",
      confirmed: true,
      draft: { ...analysis.draft, state: "filled" },
      order: { id: "ord-1", draft_id: analysis.draft.id, created_at: iso(now), symbol: "XAUUSD", side: "buy", lots: 0.06, requested_price: lastClose, filled_price: round(lastClose + 0.12), sl: analysis.draft.sl, tp: analysis.draft.tp, ticket: "91440219", position_id: "91440219", state: "filled", comment: "fixture", error: null },
      position: positions[0],
      checks,
      live: analysis.draft.live,
      margin: analysis.draft.margin,
      worst_case_usd: analysis.draft.worst_case_usd,
      broker_check: {},
      broker_response: {},
    };
  if (p === "/trades") return { from: stats.from, to: stats.to, trades, orders: [] };
  if (p === "/stats") return stats;
  if (p === "/calendar") return calendar;
  if (p === "/blackouts") return blackouts;
  if (p === "/news") return news;
  if (p === "/news/n1") return newsDetail;
  if (p === "/agent/status") return agentStatus;
  if (p === "/agent/overview") return agentOverview;
  if (p === "/agent/sessions") return sessions;
  if (p.startsWith("/agent/sessions/") && p.endsWith("/messages")) return messages;
  if (p === "/agent/config") return agentConfig;
  if (p === "/agent/runs") return { runs: [], count: 0 };
  if (p === "/agent/positions") return { positions: agentOverview.positions };
  return null;
};

async function main() {
  await fs.mkdir(OUT, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: true,
    protocolTimeout: 120_000,
    defaultViewport: { width: 1440, height: 920, deviceScaleFactor: 1 },
    args: ["--no-sandbox", "--disable-gpu", "--hide-scrollbars"],
  });
  const page = await browser.newPage();
  page.setDefaultTimeout(20_000);
  await page.setRequestInterception(true);
  page.on("request", (request) => {
    const url = request.url();
    if (!url.includes("/api/")) return request.continue();
    if (url.includes("/api/events")) return request.abort();
    const payload = payloadFor(url);
    if (!payload) return request.respond({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "not_mocked", message: url } }) });
    return request.respond({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });

  const errors = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error" && !msg.text().includes("favicon")) errors.push(`console: ${msg.text()}`);
  });

  const goto = async (route) => {
    await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded", timeout: 30_000 });
    await sleep(1800);
  };
  const shot = async (name) => {
    await page.screenshot({ path: path.join(OUT, `${name}.png`) });
    console.log(`shot ${name}`);
  };
  const clickText = async (selector, text) =>
    page.evaluate(
      (sel, needle) => {
        const el = [...document.querySelectorAll(sel)].find((node) => node.textContent?.trim().includes(needle));
        if (!el) return false;
        el.click();
        return true;
      },
      selector,
      text,
    );

  await page.evaluateOnNewDocument(() => {
    localStorage.setItem("drawerRetracted", "false");
    localStorage.removeItem("ignite-tweaks");
  });

  /* agent — context, tools, memory */
  await goto("/");
  await shot("agent-1440");
  await clickText("button", "Tools");
  await sleep(700);
  await shot("agent-tools");
  await clickText("button", "Memory");
  await sleep(700);
  await shot("agent-memory");

  /* portfolio */
  await goto("/portfolio");
  await shot("portfolio");

  /* watchlist + drawer + execution dialog */
  await goto("/watchlist");
  await sleep(1800);
  await shot("watchlist");
  await clickText("button", "View analysis");
  await sleep(1200);
  await shot("watchlist-analysis");
  await clickText("button", "Execute");
  await sleep(1400);
  await shot("execution-review");
  await clickText("button", "Review & arm");
  await sleep(900);
  await shot("execution-arming");
  await page.keyboard.press("Escape");
  await sleep(500);

  /* history */
  await goto("/history");
  await sleep(1200);
  await shot("history");

  /* news + article */
  await goto("/news");
  await sleep(1200);
  await shot("news");
  await clickText("button", "Dollar steadies");
  await sleep(900);
  await shot("news-article");

  /* responsive */
  await page.setViewport({ width: 1280, height: 900 });
  await goto("/");
  await shot("agent-1280");
  await goto("/watchlist");
  await sleep(1400);
  await shot("watchlist-1280");
  await page.setViewport({ width: 1024, height: 800 });
  await goto("/");
  await shot("agent-1024");
  await goto("/watchlist");
  await sleep(1200);
  await shot("watchlist-1024");
  await page.setViewport({ width: 390, height: 844 });
  await goto("/watchlist");
  await shot("watchlist-390");

  /* light theme */
  await page.setViewport({ width: 1440, height: 920 });
  await goto("/portfolio");
  await page.evaluate(() => {
    localStorage.setItem("ignite-tweaks", JSON.stringify({ theme: "light", density: 1, fontScale: 1, radiusScale: 1, showGrid: false, reducedMotion: false, compactMode: false }));
    document.documentElement.dataset.theme = "light";
  });
  await sleep(900);
  await shot("portfolio-light");

  await browser.close();
  if (errors.length) {
    console.log("errors:");
    for (const error of errors) console.log("-", error);
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
