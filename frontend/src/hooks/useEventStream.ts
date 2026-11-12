import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { keys } from "./useApi";
import { useToast } from "../components/Toast";
import type { IgniteEvent } from "../lib/types";

export type StreamStatus = "connecting" | "live" | "down";

const EVENT_TYPES = [
  "analysis.started",
  "analysis.progress",
  "analysis.done",
  "analysis.failed",
  "draft.created",
  "execution.done",
  "execution.failed",
  "kill_switch",
];

/**
 * Subscribe once at the app shell. Events invalidate queries; they never mutate
 * local business state. A dropped stream only degrades freshness, not safety.
 */
export function useEventStream(): StreamStatus {
  const queryClient = useQueryClient();
  const { push } = useToast();
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const retry = useRef(0);

  useEffect(() => {
    let source: EventSource | null = null;
    let disposed = false;
    let reconnectTimer: number | undefined;

    const connect = () => {
      if (disposed) return;
      source = new EventSource("/api/events");

      source.onopen = () => {
        retry.current = 0;
        setStatus("live");
      };

      source.onerror = () => {
        setStatus("down");
        source?.close();
        const delay = Math.min(30_000, 1_000 * 2 ** retry.current++);
        reconnectTimer = window.setTimeout(connect, delay);
      };

      for (const type of EVENT_TYPES) {
        source.addEventListener(type, (raw) => {
          let event: IgniteEvent;
          try {
            event = JSON.parse((raw as MessageEvent<string>).data) as IgniteEvent;
          } catch {
            return;
          }
          handle(event);
        });
      }
    };

    const handle = (event: IgniteEvent) => {
      switch (event.type) {
        case "analysis.done": {
          const symbol = String(event.symbol ?? "");
          const timeframe = String(event.timeframe ?? "");
          queryClient.invalidateQueries({ queryKey: ["latest", symbol, timeframe] });
          if (event.analysis_id) {
            queryClient.invalidateQueries({ queryKey: ["analysis", event.analysis_id] });
          }
          const side = String(event.side ?? "").toUpperCase();
          push({
            tone: side === "LONG" ? "ok" : side === "SHORT" ? "warn" : "info",
            title: `Analysis complete · ${side || "NO TRADE"}`,
            message: `${symbol} ${timeframe}${event.cached ? " · cached" : ""}`,
          });
          break;
        }
        case "analysis.failed":
          push({
            tone: "danger",
            title: "Analysis failed",
            message: String(event.error ?? "unknown error"),
          });
          break;
        case "execution.done":
          queryClient.invalidateQueries({ queryKey: keys.account });
          queryClient.invalidateQueries({ queryKey: ["trades"] });
          queryClient.invalidateQueries({ queryKey: ["stats"] });
          push({
            tone: event.state === "filled" ? "ok" : "warn",
            title:
              event.state === "filled"
                ? `Order filled · ${String(event.side ?? "").toUpperCase()}`
                : "Order unconfirmed",
            message: `${event.symbol} ${event.lots} lots @ ${event.filled_price ?? "?"}`,
          });
          break;
        case "execution.failed":
          push({
            tone: "danger",
            title: "Execution rejected",
            message: String(event.error ?? "broker rejected the order"),
          });
          break;
        case "kill_switch":
          queryClient.invalidateQueries({ queryKey: keys.settings });
          queryClient.invalidateQueries({ queryKey: keys.health });
          push({
            tone: event.enabled ? "danger" : "ok",
            title: event.enabled ? "Kill switch enabled" : "Kill switch released",
            message: event.enabled
              ? "All execution is blocked."
              : "Execution is allowed again.",
          });
          break;
        default:
          break;
      }
    };

    connect();

    return () => {
      disposed = true;
      window.clearTimeout(reconnectTimer);
      source?.close();
    };
  }, [queryClient, push]);

  return status;
}
