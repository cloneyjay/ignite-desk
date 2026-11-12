import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";

import { api, ApiError } from "../lib/api";
import type { Analysis, Job } from "../lib/types";

export const keys = {
  health: ["health"] as const,
  settings: ["settings"] as const,
  account: ["account"] as const,
  equity: (range: string) => ["equity", range] as const,
  symbols: ["symbols"] as const,
  bars: (symbol: string, tf: string, count: number) =>
    ["bars", symbol, tf, count] as const,
  analysis: (id: string) => ["analysis", id] as const,
  latest: (symbol: string, tf: string) => ["latest", symbol, tf] as const,
  job: (id: string) => ["job", id] as const,
  draft: (id: string) => ["draft", id] as const,
  calendar: (impact: string, currency: string) =>
    ["calendar", impact, currency] as const,
  blackouts: ["blackouts"] as const,
  news: ["news"] as const,
  trades: (filters: string) => ["trades", filters] as const,
  stats: (filters: string) => ["stats", filters] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: api.health,
    refetchInterval: 15_000,
    retry: 1,
  });
}

export function useSettings() {
  return useQuery({ queryKey: keys.settings, queryFn: api.settings });
}

export function useAccount() {
  return useQuery({
    queryKey: keys.account,
    queryFn: api.account,
    refetchInterval: 5_000,
    refetchIntervalInBackground: false,
    retry: 1,
  });
}

export function useEquity(range: string) {
  return useQuery({
    queryKey: keys.equity(range),
    queryFn: () => api.equity(range),
    refetchInterval: 30_000,
  });
}

export function useSymbols() {
  return useQuery({
    queryKey: keys.symbols,
    queryFn: api.symbols,
    refetchInterval: 15_000,
  });
}

export function useBars(symbol: string | null, tf: string, count = 320) {
  return useQuery({
    queryKey: keys.bars(symbol ?? "-", tf, count),
    queryFn: () => api.bars(symbol as string, tf, count),
    enabled: Boolean(symbol),
    refetchInterval: 30_000,
  });
}

export function useLatestAnalysis(symbol: string | null, tf: string) {
  return useQuery({
    queryKey: keys.latest(symbol ?? "-", tf),
    queryFn: () => api.latestAnalysis(symbol as string, tf),
    enabled: Boolean(symbol),
    retry: false,
    staleTime: 30_000,
  });
}

export function useAnalysis(analysisId: string | null) {
  return useQuery({
    queryKey: keys.analysis(analysisId ?? "-"),
    queryFn: () => api.analysis(analysisId as string),
    enabled: Boolean(analysisId),
    staleTime: 60_000,
  });
}

export function useJob(jobId: string | null) {
  return useQuery({
    queryKey: keys.job(jobId ?? "-"),
    queryFn: () => api.job(jobId as string),
    enabled: Boolean(jobId),
    refetchInterval: (query) => {
      const status = (query.state.data as Job | undefined)?.status;
      return status === "running" || status === "queued" ? 800 : false;
    },
  });
}

export function useDraft(draftId: string | null, active: boolean) {
  return useQuery({
    queryKey: keys.draft(draftId ?? "-"),
    queryFn: () => api.draft(draftId as string),
    enabled: Boolean(draftId) && active,
    refetchInterval: 4_000,
    retry: 1,
  });
}

export function useStartAnalysis() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.startAnalysis,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.health });
    },
  });
}

export function useRefreshDraft() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (analysisId: string) => api.refreshDraft(analysisId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: keys.analysis(result.analysis.id) });
      queryClient.invalidateQueries({
        queryKey: keys.latest(result.analysis.symbol, result.analysis.timeframe),
      });
    },
  });
}

export function useConfirmDraft() {
  return useMutation({ mutationFn: (draftId: string) => api.confirmDraft(draftId) });
}

export function useExecuteDraft() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ draftId, token }: { draftId: string; token: string }) =>
      api.executeDraft(draftId, token),
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: keys.account });
      queryClient.invalidateQueries({ queryKey: ["trades"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
      queryClient.invalidateQueries({ queryKey: keys.health });
    },
  });
}

export function useAddSymbol() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (symbol: string) => api.addSymbol(symbol),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.symbols }),
  });
}

export function useRemoveSymbol() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (symbol: string) => api.removeSymbol(symbol),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.symbols }),
  });
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.updateSettings,
    onSuccess: (settings) => {
      queryClient.setQueryData(keys.settings, settings);
      queryClient.invalidateQueries({ queryKey: keys.health });
      queryClient.invalidateQueries({ queryKey: keys.account });
    },
  });
}

export function useTrades(
  params: { from?: string; to?: string; symbol?: string; side?: string; result?: string },
  options?: Partial<UseQueryOptions>,
) {
  const filterKey = JSON.stringify(params);
  return useQuery({
    queryKey: keys.trades(filterKey),
    queryFn: () => api.trades(params),
    ...(options as object),
  });
}

export function useStats(params: { from?: string; to?: string }) {
  const filterKey = JSON.stringify(params);
  return useQuery({
    queryKey: keys.stats(filterKey),
    queryFn: () => api.stats(params),
    retry: 1,
  });
}

export function useCalendar(impact: string, currency: string) {
  return useQuery({
    queryKey: keys.calendar(impact, currency),
    queryFn: () => api.calendar({ impact, currency }),
    refetchInterval: 120_000,
  });
}

export function useBlackouts() {
  return useQuery({
    queryKey: keys.blackouts,
    queryFn: api.blackouts,
    refetchInterval: 120_000,
  });
}

export function useNews() {
  return useQuery({ queryKey: keys.news, queryFn: () => api.news(60) });
}

export function isNoAnalysis(error: unknown): boolean {
  return error instanceof ApiError && error.code === "no_analysis";
}

export function analysisOrNull(
  data: Analysis | undefined,
  error: unknown,
): Analysis | null {
  if (data) return data;
  if (isNoAnalysis(error)) return null;
  return null;
}
