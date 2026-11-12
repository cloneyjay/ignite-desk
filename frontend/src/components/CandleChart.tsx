import { useCallback, useEffect, useRef, useState } from "react";
import {
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type UTCTimestamp,
} from "lightweight-charts";

import type { Analysis, Bar, Blackout } from "../lib/types";
import { shortTime } from "../lib/format";

const TF_MINUTES: Record<string, number> = { M5: 5, M15: 15, M30: 30, H1: 60 };
const UP = "#3FB950";
const DOWN = "#F0616D";

interface Forecast {
  times: number[];
  p10: number[];
  p50: number[];
  p90: number[];
}

function percentiles(paths: number[][]): Forecast | null {
  if (!paths.length || !paths[0]?.length) return null;
  const horizon = paths[0].length;
  const p10: number[] = [];
  const p50: number[] = [];
  const p90: number[] = [];
  for (let step = 0; step < horizon; step += 1) {
    const column = paths
      .map((path) => path[step])
      .filter((value) => Number.isFinite(value))
      .sort((a, b) => a - b);
    if (!column.length) return null;
    const at = (q: number) => column[Math.min(column.length - 1, Math.floor(q * (column.length - 1)))];
    p10.push(at(0.1));
    p50.push(at(0.5));
    p90.push(at(0.9));
  }
  return { times: [], p10, p50, p90 };
}

function timeSecs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime();
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}

export default function CandleChart({
  bars,
  blackouts,
  analysis,
  timeframe,
  digits = 2,
  height = 430,
}: {
  bars: Bar[];
  blackouts: Blackout[];
  analysis: Analysis | null;
  timeframe: string;
  digits?: number;
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const upperRef = useRef<ISeriesApi<"Line"> | null>(null);
  const lowerRef = useRef<ISeriesApi<"Line"> | null>(null);
  const medianRef = useRef<ISeriesApi<"Line"> | null>(null);

  const barsRef = useRef<Bar[]>([]);
  const blackoutsRef = useRef<Blackout[]>([]);
  const forecastRef = useRef<Forecast | null>(null);

  const [hover, setHover] = useState<{ o: number; h: number; l: number; c: number; t: string } | null>(
    null,
  );

  const draw = useCallback(() => {
    const canvas = overlay.current;
    const host = container.current;
    const chart = chartRef.current;
    const candle = candleRef.current;
    if (!canvas || !host || !chart || !candle) return;

    const dpr = window.devicePixelRatio || 1;
    const width = host.clientWidth;
    const heightPx = host.clientHeight;
    if (width === 0 || heightPx === 0) return;
    if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(heightPx * dpr)) {
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(heightPx * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${heightPx}px`;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, heightPx);

    const scale = chart.timeScale();
    const frame = barsRef.current;
    if (!frame.length) return;

    const secs = frame.map((bar) => timeSecs(bar.time) ?? 0);
    const firstSec = secs[0];
    const lastSec = secs[secs.length - 1];
    const barSeconds =
      secs.length > 1 ? Math.max(1, Math.round((lastSec - firstSec) / (secs.length - 1))) : 60;
    const firstX = scale.timeToCoordinate(firstSec as UTCTimestamp);
    const lastX = scale.timeToCoordinate(lastSec as UTCTimestamp);
    const spacing =
      secs.length > 1 && firstX !== null && lastX !== null
        ? (lastX - firstX) / (secs.length - 1)
        : Math.max(4, scale.options().barSpacing);

    /**
     * Blackout windows often sit after the last closed bar, where no series has
     * a point. Inside the bar window we interpolate between neighbours; outside
     * it we extrapolate on the bar grid so future windows still get drawn.
     */
    const coordinateFor = (target: number): number | null => {
      if (firstX === null || lastX === null) return null;
      if (target <= firstSec) return firstX - ((firstSec - target) / barSeconds) * spacing;
      if (target >= lastSec) return lastX + ((target - lastSec) / barSeconds) * spacing;
      let low = 0;
      let high = secs.length - 1;
      while (low + 1 < high) {
        const mid = (low + high) >> 1;
        if (secs[mid] <= target) low = mid;
        else high = mid;
      }
      const span = secs[high] - secs[low];
      const ratio = span > 0 ? (target - secs[low]) / span : 0;
      const x1 = scale.timeToCoordinate(secs[low] as UTCTimestamp);
      const x2 = scale.timeToCoordinate(secs[high] as UTCTimestamp);
      if (x1 === null || x2 === null) return null;
      return x1 + (x2 - x1) * ratio;
    };

    const paneWidth = Math.max(0, width - chart.priceScale("right").width());
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, paneWidth, heightPx - 24);
    ctx.clip();

    // Deterministic blackout windows, snapped to the bar grid.
    for (const window of blackoutsRef.current) {
      const start = timeSecs(window.start);
      const end = timeSecs(window.end);
      if (start === null || end === null) continue;
      const x1 = coordinateFor(start);
      const x2 = coordinateFor(end);
      if (x1 === null || x2 === null) continue;
      const left = Math.max(0, Math.min(x1, x2));
      const right = Math.min(paneWidth, Math.max(x1, x2));
      if (right <= left) continue;
      ctx.fillStyle = "rgba(240,97,109,0.09)";
      ctx.fillRect(left, 0, Math.max(1, right - left), heightPx - 24);
      ctx.fillStyle = "rgba(240,97,109,0.35)";
      ctx.fillRect(left, 0, 1, heightPx - 24);
      ctx.fillStyle = "rgba(240,97,109,0.18)";
      ctx.fillRect(right - 1, 0, 1, heightPx - 24);
    }

    // Forecast fan: p10..p90 band + median, drawn only where coordinates exist.
    const forecast = forecastRef.current;
    if (forecast) {
      const xs = forecast.times.map((t) => scale.timeToCoordinate(t as UTCTimestamp));
      const highs = forecast.p90.map((v) => candle.priceToCoordinate(v));
      const lows = forecast.p10.map((v) => candle.priceToCoordinate(v));
      const mids = forecast.p50.map((v) => candle.priceToCoordinate(v));

      const points: { x: number; hi: number; lo: number }[] = [];
      for (let index = 0; index < xs.length; index += 1) {
        const x = xs[index];
        const hi = highs[index];
        const lo = lows[index];
        if (x === null || hi === null || lo === null) continue;
        points.push({ x, hi, lo });
      }

      if (points.length > 1) {
        ctx.beginPath();
        points.forEach((point, index) => {
          if (index === 0) ctx.moveTo(point.x, point.hi);
          else ctx.lineTo(point.x, point.hi);
        });
        [...points].reverse().forEach((point) => ctx.lineTo(point.x, point.lo));
        ctx.closePath();
        ctx.fillStyle = "rgba(231,188,96,0.13)";
        ctx.fill();
      }

      ctx.beginPath();
      let started = false;
      for (let index = 0; index < xs.length; index += 1) {
        const x = xs[index];
        const y = mids[index];
        if (x === null || y === null) continue;
        if (!started) {
          ctx.moveTo(x, y);
          started = true;
        } else {
          ctx.lineTo(x, y);
        }
      }
      if (started) {
        ctx.strokeStyle = "rgba(231,188,96,0.95)";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      const tail = points[points.length - 1];
      if (tail) {
        const mid = mids[mids.length - 1];
        ctx.fillStyle = "rgba(231,188,96,0.9)";
        ctx.font = "600 10px ui-monospace, Consolas, monospace";
        const label = "KRONOS p10–p90";
        const textWidth = ctx.measureText(label).width;
        const x = Math.min(tail.x + 6, Math.max(0, paneWidth - textWidth - 8));
        ctx.fillText(label, x, (mid ?? tail.hi) - 6);
      }
    }
    ctx.restore();
  }, []);

  useEffect(() => {
    if (!container.current) return;
    const host = container.current;
    const chart = createChart(host, {
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8B9BB0",
        fontFamily: "ui-monospace, Consolas, monospace",
        fontSize: 10,
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: "rgba(34,48,63,0.32)" },
        horzLines: { color: "rgba(34,48,63,0.32)" },
      },
      rightPriceScale: {
        borderColor: "#22303F",
        scaleMargins: { top: 0.08, bottom: 0.1 },
      },
      timeScale: {
        borderColor: "#22303F",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 18,
        barSpacing: 6,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "rgba(231,188,96,0.3)", labelBackgroundColor: "#B9852A" },
        horzLine: { color: "rgba(231,188,96,0.3)", labelBackgroundColor: "#B9852A" },
      },
      localization: {
        priceFormatter: (value: number) =>
          value.toLocaleString(undefined, {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
          }),
      },
    });

    const candle = chart.addCandlestickSeries({
      upColor: UP,
      downColor: DOWN,
      borderVisible: false,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceFormat: {
        type: "price",
        precision: digits,
        minMove: 1 / Math.pow(10, digits),
      },
    });

    const hidden = {
      lineVisible: false,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    };
    const upper = chart.addLineSeries({ ...hidden, color: "rgba(0,0,0,0)" });
    const lower = chart.addLineSeries({ ...hidden, color: "rgba(0,0,0,0)" });
    const median = chart.addLineSeries({
      ...hidden,
      lineVisible: false,
      lineStyle: LineStyle.Dashed,
    });

    chartRef.current = chart;
    candleRef.current = candle;
    upperRef.current = upper;
    lowerRef.current = lower;
    medianRef.current = median;

    const onCrosshair = (param: MouseEventParams) => {
      if (!param.time || !param.seriesData.size) {
        setHover(null);
        return;
      }
      const data = param.seriesData.get(candle) as
        | { open: number; high: number; low: number; close: number }
        | undefined;
      if (!data) {
        setHover(null);
        return;
      }
      setHover({
        o: data.open,
        h: data.high,
        l: data.low,
        c: data.close,
        t: new Date(Number(param.time) * 1000).toISOString(),
      });
    };
    chart.subscribeCrosshairMove(onCrosshair);

    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: host.clientWidth });
      draw();
    });
    observer.observe(host);

    const onRange = () => draw();
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);
    requestAnimationFrame(draw);

    return () => {
      observer.disconnect();
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      chart.unsubscribeCrosshairMove(onCrosshair);
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      upperRef.current = null;
      lowerRef.current = null;
      medianRef.current = null;
    };
  }, [digits, height, draw]);

  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    if (!chart || !candle) return;
    const data = bars
      .map((bar) => ({
        time: timeSecs(bar.time) as UTCTimestamp,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }))
      .filter((bar) => Number.isFinite(bar.time))
      .sort((a, b) => a.time - b.time);

    candle.setData(data);
    barsRef.current = bars;
    candle.setMarkers(
      data.length
        ? [
            {
              time: data[data.length - 1].time,
              position: "aboveBar",
              color: "#E7BC60",
              shape: "circle",
              text: "",
            },
          ]
        : [],
    );
    if (data.length) chart.timeScale().fitContent();
    requestAnimationFrame(draw);
  }, [bars, draw]);

  useEffect(() => {
    blackoutsRef.current = blackouts;
    requestAnimationFrame(draw);
  }, [blackouts, draw]);

  useEffect(() => {
    const upper = upperRef.current;
    const lower = lowerRef.current;
    const median = medianRef.current;
    if (!upper || !lower || !median) return;

    const frame = barsRef.current;
    if (!analysis?.paths?.length || !frame.length) {
      upper.setData([]);
      lower.setData([]);
      median.setData([]);
      forecastRef.current = null;
      requestAnimationFrame(draw);
      return;
    }

    const bands = percentiles(analysis.paths);
    if (!bands) return;
    const minutes = TF_MINUTES[timeframe] ?? 15;
    const last = timeSecs(frame[frame.length - 1].time);
    if (last === null) return;
    bands.times = bands.p10.map((_, index) => last + (index + 1) * minutes * 60);

    const asLine = (values: number[]) =>
      values.map((value, index) => ({
        time: bands.times[index] as UTCTimestamp,
        value,
      }));

    upper.setData(asLine(bands.p90));
    lower.setData(asLine(bands.p10));
    median.setData(asLine(bands.p50));
    forecastRef.current = bands;
    requestAnimationFrame(draw);
  }, [analysis, timeframe, draw]);

  const last = bars[bars.length - 1];
  const legend = hover ?? (last ? {
    o: last.open,
    h: last.high,
    l: last.low,
    c: last.close,
    t: last.time,
  } : null);
  const rising = legend ? legend.c >= legend.o : true;

  return (
    <div className="relative">
      <div className="pointer-events-none absolute left-3 top-2 z-10 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10.5px] text-fog/90">
        {legend ? (
          <>
            <span className="text-paper/60">{shortTime(legend.t)}</span>
            <span>O <b className="text-paper/90">{legend.o.toFixed(digits)}</b></span>
            <span>H <b className={rising ? "text-long" : "text-short"}>{legend.h.toFixed(digits)}</b></span>
            <span>L <b className={rising ? "text-long" : "text-short"}>{legend.l.toFixed(digits)}</b></span>
            <span>C <b className={rising ? "text-long" : "text-short"}>{legend.c.toFixed(digits)}</b></span>
          </>
        ) : null}
        {analysis ? (
          <span className="rounded border border-gold-500/30 bg-gold-500/10 px-1.5 py-0.5 text-[9.5px] font-semibold uppercase tracking-[0.12em] text-gold-300">
            forecast overlay
          </span>
        ) : null}
      </div>
      <div ref={container} className="w-full" style={{ height }} />
      <canvas
        ref={overlay}
        className="pointer-events-none absolute inset-0 z-[5]"
        aria-hidden
      />
    </div>
  );
}
