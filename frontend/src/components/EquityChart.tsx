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
        textColor: "#8B9BB0",
        fontFamily: "ui-monospace, Consolas, monospace",
        fontSize: 10,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "rgba(34,48,63,0.35)" },
        horzLines: { color: "rgba(34,48,63,0.35)" },
      },
      rightPriceScale: {
        borderColor: "#22303F",
        scaleMargins: { top: 0.12, bottom: 0.08 },
      },
      timeScale: {
        borderColor: "#22303F",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 2,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "rgba(231,188,96,0.35)", labelBackgroundColor: "#B9852A" },
        horzLine: { color: "rgba(231,188,96,0.35)", labelBackgroundColor: "#B9852A" },
      },
      handleScale: { axisPressedMouseMove: false },
    });
    const series = chart.addAreaSeries({
      lineColor: "#E7BC60",
      topColor: "rgba(217,166,60,0.26)",
      bottomColor: "rgba(217,166,60,0.01)",
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
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-lg border border-dashed border-line/70 text-[12px] text-fog">
          Equity snapshots appear after the first account refresh.
        </div>
      ) : null}
    </div>
  );
}
