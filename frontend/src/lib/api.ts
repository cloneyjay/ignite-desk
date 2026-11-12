/** fetch wrapper + one function per endpoint. No business logic lives here. */

import type {
  AccountPayload,
  Analysis,
  BarsPayload,
  Blackout,
  CalendarEvent,
  ConfirmResult,
  DraftDetail,
  EquityPoint,
  ExecutionResult,
  Health,
  Job,
  NewsDetail,
  NewsItem,
  OrderRow,
  Settings,
  SymbolRow,
  Trade,
  TradeStats,
} from "./types";

export class ApiError extends Error {
  status: number;
  code: string;
  detail: unknown;

  constructor(status: number, code: string, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { error: { code: "bad_response", message: text.slice(0, 300) } };
    }
  }
  if (!response.ok) {
    const envelope = (body as { error?: { code?: string; message?: string; detail?: unknown } })
      ?.error;
    throw new ApiError(
      response.status,
      envelope?.code ?? `http_${response.status}`,
      envelope?.message ?? response.statusText,
      envelope?.detail,
    );
  }
  return body as T;
}

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  health: () => request<Health>("/health"),
  settings: () => request<Settings>("/settings"),
  updateSettings: (body: { kill_switch?: boolean; risk_pct?: number }) =>
    request<Settings>("/settings", { method: "PUT", body: JSON.stringify(body) }),

  account: () => request<AccountPayload>("/account"),
  equity: (range: string) =>
    request<{ range: string; points: EquityPoint[] }>(`/portfolio/equity${query({ range })}`),

  symbols: () => request<{ symbols: SymbolRow[] }>("/symbols"),
  addSymbol: (symbol: string) =>
    request<{ symbol: SymbolRow }>("/symbols", {
      method: "POST",
      body: JSON.stringify({ symbol }),
    }),
  removeSymbol: (symbol: string) =>
    request<{ removed: string }>(`/symbols/${encodeURIComponent(symbol)}`, {
      method: "DELETE",
    }),

  bars: (symbol: string, tf: string, count = 320) =>
    request<BarsPayload>(`/bars${query({ symbol, tf, count })}`),

  startAnalysis: (body: {
    symbol: string;
    timeframe: string;
    samples?: number;
    horizon?: number;
  }) =>
    request<{ job: Job; horizon: number; lookback: number }>("/analyses", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  job: (jobId: string) => request<Job>(`/jobs/${jobId}`),
  analysis: (analysisId: string, includePaths = true) =>
    request<Analysis>(`/analyses/${analysisId}${query({ include_paths: includePaths })}`),
  latestAnalysis: (symbol: string, tf: string) =>
    request<Analysis>(`/analyses/latest${query({ symbol, tf })}`),
  refreshDraft: (analysisId: string) =>
    request<{ draft: DraftDetail["draft"]; analysis: Analysis }>(
      `/analyses/${analysisId}/draft`,
      { method: "POST" },
    ),

  draft: (draftId: string) => request<DraftDetail>(`/drafts/${draftId}`),
  confirmDraft: (draftId: string) =>
    request<ConfirmResult>(`/drafts/${draftId}/confirm`, {
      method: "POST",
      body: JSON.stringify({ confirm: true }),
    }),
  executeDraft: (draftId: string, token: string) =>
    request<ExecutionResult>(`/drafts/${draftId}/execute`, {
      method: "POST",
      body: JSON.stringify({ confirm: true, token }),
    }),

  trades: (params: {
    from?: string;
    to?: string;
    symbol?: string;
    side?: string;
    result?: string;
  }) => request<{ from: string; to: string; trades: Trade[]; orders: OrderRow[] }>(
    `/trades${query(params)}`,
  ),
  stats: (params: { from?: string; to?: string }) =>
    request<TradeStats>(`/stats${query(params)}`),

  calendar: (params: { from?: string; to?: string; impact?: string; currency?: string }) =>
    request<{ from: string; to: string; events: CalendarEvent[] }>(
      `/calendar${query(params)}`,
    ),
  blackouts: () =>
    request<{
      from: string;
      to: string;
      pre_minutes: number;
      post_minutes: number;
      blackouts: Blackout[];
    }>("/blackouts"),
  news: (limit = 60) => request<{ news: NewsItem[]; count: number }>(
    `/news${query({ limit })}`,
  ),
  newsItem: (id: string) => request<NewsDetail>(`/news/${encodeURIComponent(id)}`),
};
