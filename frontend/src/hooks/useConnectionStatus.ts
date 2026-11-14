import { useQuery } from "@tanstack/react-query";

import { api, ApiError } from "../lib/api";

export interface ConnectionStatus {
  connected: boolean;
  lastChecked: number | null;
  error: string | null;
  health: Awaited<ReturnType<typeof api.health>> | null;
}

export function useConnectionStatus() {
  return useQuery<ConnectionStatus, Error>({
    queryKey: ["connection"],
    queryFn: async () => {
      const start = Date.now();
      try {
        const health = await api.health();
        return {
          connected: true,
          lastChecked: start,
          error: null,
          health,
        };
      } catch (exc) {
        const error = exc as Error;
        return {
          connected: false,
          lastChecked: start,
          error: error instanceof ApiError ? error.message : error.message,
          health: null,
        };
      }
    },
    refetchInterval: 10_000,
    retry: 1,
    staleTime: 5_000,
  });
}
