"use client";

/*
 * Candles are drawn with TradingView Lightweight Charts™ (Apache License 2.0).
 * Copyright (c) 2025 TradingView, Inc. https://www.tradingview.com/
 * Its attribution logo stays on the chart: that's the link to TradingView its license asks for.
 */

import { useEffect, useRef, useState } from "react";
import type { DashboardWidgetData } from "./backend/types";
import { bucketTitle, formatValue } from "./dashboard-format";
import { cx } from "./ui";

type Candle = NonNullable<DashboardWidgetData["candles"]>[number];
type Every = "day" | "week" | "month";

/** A theme token's color now (the chart is a canvas, so it can't use the CSS variables itself). */
function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

function alpha(hex: string, a: number): string {
  const m = hex.match(/^#([0-9a-f]{6})$/i);
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

/** Moving average of the close over `size` candles, from the first candle that has enough before it. */
function average(candles: Candle[], size: number) {
  const out: { time: string; value: number }[] = [];
  let sum = 0;
  candles.forEach((c, i) => {
    sum += c.close;
    if (i >= size) sum -= candles[i - size].close;
    if (i >= size - 1) out.push({ time: c.start, value: sum / size });
  });
  return out;
}

// The averages share one hue (checked against the candles for colorblindness) and differ by line style.
const AVERAGE_STYLES = [0, 2, 1] as const; // solid, dashed, dotted (LineStyle)
const AVERAGE_KEYS = ["", "border-dashed", "border-dotted"];
const NONE: never[] = []; // stable, so the chart isn't rebuilt on every render

/**
 * A trading chart of a number column: a candle per day, week or month (up in the accent, down in the
 * quiet gray, and said in words in the readout), volume under it, moving averages over it. Scroll to
 * zoom, drag to pan; the readout follows the crosshair.
 */
export function CandleChart({ data, every, averages = NONE }: { data: DashboardWidgetData; every: Every; averages?: number[] }) {
  const box = useRef<HTMLDivElement>(null);
  const candles = data.candles ?? NONE;
  const [at, setAt] = useState<number | null>(null);
  const hasVolume = candles.some((c) => c.volume !== undefined);

  useEffect(() => {
    const el = box.current;
    if (!el || !candles.length) return;
    let dispose = () => {};
    let live = true;
    import("lightweight-charts").then(({ createChart, CandlestickSeries, HistogramSeries, LineSeries, CrosshairMode }) => {
      if (!live) return;
      const chart = createChart(el, { autoSize: true, crosshair: { mode: CrosshairMode.Normal }, localization: { priceFormatter: (p: number) => formatValue(p, data.unit, true) } });
      const up = chart.addSeries(CandlestickSeries, { priceLineVisible: false });
      up.setData(candles.map((c) => ({ time: c.start, open: c.open, high: c.high, low: c.low, close: c.close })));
      const volume = hasVolume ? chart.addSeries(HistogramSeries, { priceScaleId: "", priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false }) : null;
      if (volume) chart.priceScale("").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
      const lines = averages.map((size, i) => {
        const line = chart.addSeries(LineSeries, { lineWidth: 2, lineStyle: AVERAGE_STYLES[i], lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false });
        line.setData(average(candles, size));
        return line;
      });

      const paint = () => {
        const [accent, previous, ink3, line, surface, sky] = ["--accent", "--chart-previous", "--ink-3", "--line", "--surface", "--sky"].map(token);
        chart.applyOptions({
          layout: { background: { color: surface }, textColor: ink3, fontFamily: getComputedStyle(document.body).fontFamily, attributionLogo: true },
          grid: { vertLines: { visible: false }, horzLines: { color: line } },
          rightPriceScale: { borderVisible: false },
          timeScale: { borderVisible: false, timeVisible: false },
          crosshair: { vertLine: { color: ink3, labelBackgroundColor: ink3 }, horzLine: { color: ink3, labelBackgroundColor: ink3 } },
        });
        up.applyOptions({ upColor: accent, downColor: previous, wickUpColor: accent, wickDownColor: previous, borderVisible: false });
        volume?.setData(candles.map((c) => ({ time: c.start, value: c.volume ?? 0, color: alpha(c.close >= c.open ? accent : previous, 0.35) })));
        for (const l of lines) l.applyOptions({ color: sky });
      };
      paint();
      // All of them if they fit at a readable width (about 9px a candle), else the latest, dragged back for more.
      const room = Math.floor(el.clientWidth / 9);
      if (candles.length > room) chart.timeScale().setVisibleLogicalRange({ from: candles.length - room, to: candles.length - 1 });
      else chart.timeScale().fitContent();
      chart.subscribeCrosshairMove((p) => {
        const i = p.time === undefined ? -1 : candles.findIndex((c) => c.start === p.time);
        setAt(i < 0 ? null : i);
      });

      // The page's theme: the device's, or the one the owner picked (data-theme on <html>).
      const media = window.matchMedia("(prefers-color-scheme: dark)");
      const watch = new MutationObserver(paint);
      watch.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });
      media.addEventListener("change", paint);
      dispose = () => {
        watch.disconnect();
        media.removeEventListener("change", paint);
        chart.remove();
      };
    });
    return () => {
      live = false;
      dispose();
    };
  }, [candles, averages, hasVolume, data.unit]);

  if (!candles.length) return <p className="py-4 text-sm text-ink-3">No prices to draw yet.</p>;
  const c = candles[at ?? candles.length - 1];
  const rising = c.close >= c.open;
  const n = (v: number | undefined) => formatValue(v ?? null, data.unit);
  return (
    <div>
      <p className="mb-1 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm text-ink-3 tabular-nums">
        <span className="text-2xl font-semibold text-ink">{formatValue(c.close, data.unit, true)}</span>
        <span>{bucketTitle(c.start, every)}</span>
        <span className="text-ink-2">{c.close === c.open ? "unchanged" : rising ? "↑ up" : "↓ down"} from {n(c.open)}</span>
        <span>
          high {n(c.high)} · low {n(c.low)}
          {c.volume !== undefined && ` · volume ${formatValue(c.volume, undefined, true)}`}
        </span>
      </p>
      {averages.length > 0 && (
        <p className="mb-2 flex flex-wrap gap-x-4 text-xs text-ink-3">
          {averages.map((size, i) => (
            <span key={size} className="inline-flex items-center gap-1.5">
              <span className={cx("w-4 border-t-2 border-sky", AVERAGE_KEYS[i])} aria-hidden />
              Average of {size} {every}s
            </span>
          ))}
        </p>
      )}
      <div ref={box} className="h-72 w-full" role="img" aria-label={`Candles of the last ${candles.length} ${every}s, last close ${n(c.close)}`} />
    </div>
  );
}
