import { useEffect, useRef } from "react";
import {
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";

import type { EquityPoint } from "../lib/types";

export default function EquityChart({
  points,
  height = 260,
  fill = false,
}: {
  points: EquityPoint[];
  height?: number;
  /** Stretch to the parent's height instead of using a fixed pixel height. */
  fill?: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);

  useEffect(() => {
    if (!container.current) return;
    const host = container.current;
    const chart = createChart(host, {
      width: host.clientWidth,
      height: fill ? host.clientHeight || height : height,
      autoSize: fill,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#9a8f83",
        fontFamily: "ui-monospace, Consolas, monospace",
        fontSize: 10,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "rgba(120,100,80,0.16)" },
        horzLines: { color: "rgba(120,100,80,0.16)" },
      },
      rightPriceScale: {
        borderColor: "#3a332c",
        scaleMargins: { top: 0.12, bottom: 0.08 },
      },
      timeScale: {
        borderColor: "#3a332c",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 2,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "rgba(224,178,90,0.35)", labelBackgroundColor: "#8a6420" },
        horzLine: { color: "rgba(224,178,90,0.35)", labelBackgroundColor: "#8a6420" },
      },
      handleScale: { axisPressedMouseMove: false },
    });
    const series = chart.addAreaSeries({
      lineColor: "#e0b25a",
      topColor: "rgba(200,149,47,0.24)",
      bottomColor: "rgba(200,149,47,0.01)",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      priceFormat: { type: "price", precision: 2, minMove: 0.01 },
    });
    chartRef.current = chart;
    seriesRef.current = series;

    const observer = new ResizeObserver(() => {
      if (!container.current) return;
      chart.applyOptions({
        width: container.current.clientWidth,
        ...(fill ? { height: container.current.clientHeight } : {}),
      });
    });
    observer.observe(host);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [height, fill]);

  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !chart) return;
    const data = points
      .map((point) => ({
        time: Math.floor(new Date(point.ts).getTime() / 1000) as UTCTimestamp,
        value: Number(point.equity),
      }))
      .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value))
      .sort((a, b) => a.time - b.time);
    series.setData(data);
    if (data.length > 0) chart.timeScale().fitContent();
  }, [points]);

  return (
    <div
      className={`relative w-full ${fill ? "h-full" : ""}`}
      style={fill ? undefined : { height }}
    >
      <div ref={container} className="h-full w-full" />
      {points.length === 0 ? (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center border border-dashed border-line/70 text-[11px] uppercase tracking-[0.08em] text-text-faint">
          Equity snapshots appear after the first account refresh.
        </div>
      ) : null}
    </div>
  );
}
