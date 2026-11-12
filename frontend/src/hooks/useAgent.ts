import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";
import type { AgentStatus } from "../lib/types";

export const keys = {
  agentStatus: ["agent", "status"] as const,
  agentRuns: ["agent", "runs"] as const,
};

export function useAgentStatus() {
  return useQuery<AgentStatus>({
    queryKey: keys.agentStatus,
    queryFn: api.agentStatus,
    refetchInterval: 5000,
  });
}

export function useAgentToggle() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) => api.agentToggle({ enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.agentStatus });
    },
  });
}

export function useAgentChat() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => api.agentChat(text),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: keys.agentRuns });
    },
  });
}

export function useAgentPositions() {
  return useQuery({
    queryKey: ["agent", "positions"],
    queryFn: api.agentPositions,
    refetchInterval: 10000,
  });
}

export function useAgentConfig() {
  return useQuery({
    queryKey: ["agent", "config"],
    queryFn: api.agentConfig,
  });
}