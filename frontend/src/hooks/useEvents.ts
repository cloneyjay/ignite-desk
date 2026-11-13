import { useEffect, useRef, useState, useCallback } from "react";

export type ConnectionState = "connecting" | "connected" | "disconnected" | "error";

export interface SSEEvent {
  type: string;
  data: unknown;
  timestamp: number;
}

type EventCallback = (event: SSEEvent) => void;

interface UseEventsOptions {
  url?: string;
  onEvent?: (event: SSEEvent) => void;
  autoConnect?: boolean;
  reconnectInterval?: number;
  maxReconnectInterval?: number;
  reconnectDecay?: number;
}

interface UseEventsReturn {
  connectionState: ConnectionState;
  lastEvent: SSEEvent | null;
  subscribe: (callback: EventCallback) => () => void;
  connect: () => void;
  disconnect: () => void;
}

export function useEvents(options: UseEventsOptions = {}): UseEventsReturn {
  const {
    url = "/api/events",
    onEvent,
    autoConnect = true,
    reconnectInterval = 1000,
    maxReconnectInterval = 30000,
    reconnectDecay = 1.5,
  } = options;

  const [connectionState, setConnectionState] = useState<ConnectionState>("disconnected");
  const [lastEvent, setLastEvent] = useState<SSEEvent | null>(null);
  
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);
  const callbacksRef = useRef<Set<EventCallback>>(new Set());
  const urlRef = useRef(url);
  const isVisibleRef = useRef(true);
  const isConnectingRef = useRef(false);

  // Update url ref when it changes
  useEffect(() => {
    urlRef.current = url;
  }, [url]);

  // Track document visibility
  useEffect(() => {
    const handleVisibilityChange = () => {
      isVisibleRef.current = !document.hidden;
      if (document.hidden) {
        disconnect();
      } else if (isConnectingRef.current === false && autoConnect) {
        connect();
      }
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, [autoConnect]);

  const notifyCallbacks = useCallback((event: SSEEvent) => {
    callbacksRef.current.forEach((callback) => {
      try {
        callback(event);
      } catch (error) {
        console.error("Error in SSE callback:", error);
      }
    });
    if (onEvent) {
      try {
        onEvent(event);
      } catch (error) {
        console.error("Error in onEvent callback:", error);
      }
    }
    setLastEvent(event);
  }, [onEvent]);

  const connect = useCallback(() => {
    if (eventSourceRef.current || isConnectingRef.current) {
      return;
    }
    if (!isVisibleRef.current) {
      return;
    }

    isConnectingRef.current = true;
    setConnectionState("connecting");

    try {
      const es = new EventSource(urlRef.current);
      eventSourceRef.current = es;

      es.onopen = () => {
        isConnectingRef.current = false;
        reconnectAttemptRef.current = 0;
        setConnectionState("connected");
      };

      es.onmessage = (message) => {
        try {
          const data = JSON.parse(message.data);
          const event: SSEEvent = {
            type: message.type || "message",
            data,
            timestamp: Date.now(),
          };
          notifyCallbacks(event);
        } catch (error) {
          console.error("Failed to parse SSE message:", error);
        }
      };

      es.addEventListener("analysis.progress", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "analysis.progress", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse analysis.progress:", error);
        }
      });

      es.addEventListener("agent.toggled", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "agent.toggled", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse agent.toggled:", error);
        }
      });

      es.addEventListener("agent.cycle.blocked", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "agent.cycle.blocked", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse agent.cycle.blocked:", error);
        }
      });

      es.addEventListener("agent.cycle.completed", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "agent.cycle.completed", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse agent.cycle.completed:", error);
        }
      });

      es.addEventListener("decision.final", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "decision.final", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse decision.final:", error);
        }
      });

      es.addEventListener("tool.call", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "tool.call", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse tool.call:", error);
        }
      });

      es.addEventListener("position.opened", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "position.opened", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse position.opened:", error);
        }
      });

      es.addEventListener("position.protected", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "position.protected", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse position.protected:", error);
        }
      });

      es.addEventListener("position.trailed", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "position.trailed", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse position.trailed:", error);
        }
      });

      es.addEventListener("position.scaled", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "position.scaled", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse position.scaled:", error);
        }
      });

      es.addEventListener("position.closed", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "position.closed", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse position.closed:", error);
        }
      });

      es.addEventListener("position.orphaned", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "position.orphaned", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse position.orphaned:", error);
        }
      });

      es.addEventListener("kill_switch", (message) => {
        try {
          const data = JSON.parse(message.data);
          notifyCallbacks({ type: "kill_switch", data, timestamp: Date.now() });
        } catch (error) {
          console.error("Failed to parse kill_switch:", error);
        }
      });

      es.onerror = (error) => {
        isConnectingRef.current = false;
        console.error("SSE connection error:", error);
        setConnectionState("error");
        es.close();
        eventSourceRef.current = null;
        scheduleReconnect();
      };
    } catch (error) {
      isConnectingRef.current = false;
      console.error("Failed to create EventSource:", error);
      setConnectionState("error");
      scheduleReconnect();
    }
  }, [autoConnect, notifyCallbacks]);

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    const attempt = reconnectAttemptRef.current;
    const delay = Math.min(
      reconnectInterval * Math.pow(reconnectDecay, attempt),
      maxReconnectInterval
    );
    reconnectTimeoutRef.current = setTimeout(() => {
      reconnectAttemptRef.current += 1;
      if (isVisibleRef.current) {
        connect();
      }
    }, delay);
  }, [connect, reconnectInterval, maxReconnectInterval, reconnectDecay]);

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    isConnectingRef.current = false;
    reconnectAttemptRef.current = 0;
    setConnectionState("disconnected");
  }, []);

  const subscribe = useCallback((callback: EventCallback) => {
    callbacksRef.current.add(callback);
    return () => {
      callbacksRef.current.delete(callback);
    };
  }, []);

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect();
    }
    return () => {
      disconnect();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    connectionState,
    lastEvent,
    subscribe,
    connect,
    disconnect,
  };
}