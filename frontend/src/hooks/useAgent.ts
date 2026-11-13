import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "../lib/api";
import type { AgentStatus, AgentMessage } from "../lib/types";

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

export function useAgentOverview() {
  return useQuery({
    queryKey: ["agent", "overview"],
    queryFn: api.agentOverview,
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
    mutationFn: (input: string | { text: string; sessionId?: string | null }) => {
      const request = typeof input === "string" ? { text: input } : input;
      return api.agentChat(request.text, request.sessionId);
    },
    onSuccess: (response) => {
      queryClient.invalidateQueries({ queryKey: keys.agentRuns });
      queryClient.invalidateQueries({ queryKey: ["agent", "sessions"] });
      queryClient.invalidateQueries({ queryKey: ["agent", "messages", response.session_id] });
    },
  });
}

export function useAgentSessions() {
  return useQuery({
    queryKey: ["agent", "sessions"],
    queryFn: api.agentSessions,
    refetchInterval: 10000,
  });
}

export interface PaginatedMessages {
  messages: AgentMessage[];
  count: number;
  hasMore: boolean;
  cursor: string | null;
}

export function useAgentMessages(sessionId: string | null) {
  const queryClient = useQueryClient();
  
  const query = useQuery<PaginatedMessages>({
    queryKey: ["agent", "messages", sessionId],
    queryFn: () => api.agentMessages(sessionId as string),
    enabled: Boolean(sessionId),
  });

  const loadMore = async () => {
    if (!sessionId || query.isFetching || !query.data?.hasMore || !query.data?.cursor) {
      return;
    }
    
    const cursor = query.data.cursor;
    const response = await api.agentMessages(sessionId, cursor);
    
    queryClient.setQueryData<PaginatedMessages>(
      ["agent", "messages", sessionId],
      (old) => {
        if (!old) return response;
        return {
          messages: [...old.messages, ...response.messages],
          count: response.count,
          hasMore: response.hasMore,
          cursor: response.cursor,
        };
      }
    );
  };

  return {
    ...query,
    data: query.data?.messages ?? [],
    loadMore,
    hasMore: query.data?.hasMore ?? false,
    isLoadingMore: query.isFetching && !!query.data?.cursor,
  };
}

export function useAgentPositions() {
  return useQuery({
    queryKey: ["agent", "positions"],
    queryFn: api.agentPositions,
    refetchInterval: 10000,
  });
}

export function useAgentRuns(limit = 20) {
  return useQuery({
    queryKey: [...keys.agentRuns, limit],
    queryFn: () => api.agentRuns(limit),
    refetchInterval: 10000,
  });
}

export function useAgentConfig() {
  return useQuery({
    queryKey: ["agent", "config"],
    queryFn: api.agentConfig,
  });
}