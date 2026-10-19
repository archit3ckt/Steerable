"use client";

import { useRef, useState } from "react";
import type { FlowStep } from "./backend/types";
import { FlowChart, KIND } from "./routine-flow";
import { cx } from "./ui";

/**
 * "How it works" on a routine's page: its steps as a flow chart, or, with the toggle, its code, the
 * lines of each step marked in that step's color and number (worked out by the engine's flow.map_code).
 * Clicking a step opens its code.
 */
export function HowItWorks({
  steps,
  current,
  code,
  codeMap,
  codeMapPending,
}: {
  steps: FlowStep[];
  current: number | null;
  code?: string;
  codeMap?: [number, number][][] | null;
  codeMapPending?: boolean;
}) {
  const [view, setView] = useState<"steps" | "code">("steps");
  const box = useRef<HTMLDivElement>(null);

  function openStep(step: number) {
    setView("code");
    const first = codeMap?.[step]?.[0]?.[0];
    if (!first) return;
    requestAnimationFrame(() => {
      const row = box.current?.querySelector<HTMLElement>(`[data-line="${first}"]`);
      if (row && box.current) box.current.scrollTo({ top: row.offsetTop - 24, behavior: "smooth" });
    });
  }

  return (
    <div>
      {code !== undefined && (
        <div role="tablist" aria-label="How it works" className="mb-3 inline-flex rounded-full border border-line bg-surface p-0.5 text-sm">
          {(["steps", "code"] as const).map((v) => (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={view === v}
              onClick={() => setView(v)}
              className={cx("rounded-full px-3.5 py-1 transition-colors", view === v ? "bg-accent text-accent-ink" : "text-ink-2 hover:text-ink")}
            >
              {v === "steps" ? "Steps" : "Code"}
            </button>
          ))}
        </div>
      )}
      {view === "steps" || code === undefined ? (
        <FlowChart steps={steps} current={current} numbered={code !== undefined} onSelect={code !== undefined ? openStep : undefined} />
      ) : (
        <CodeView box={box} code={code} steps={steps} codeMap={codeMap ?? null} pending={Boolean(codeMapPending)} onStep={openStep} />
      )}
    </div>
  );
}

function CodeView({
  box,
  code,
  steps,
  codeMap,
  pending,
  onStep,
}: {
  box: React.RefObject<HTMLDivElement | null>;
  code: string;
  steps: FlowStep[];
  codeMap: [number, number][][] | null;
  pending: boolean;
  onStep: (step: number) => void;
}) {
  // Which step each line belongs to, and where each of a step's parts begins.
  const owner = new Map<number, number>();
  const starts = new Map<number, number>();
  codeMap?.forEach((ranges, step) =>
    ranges.forEach(([a, b]) => {
      starts.set(a, step);
      for (let l = a; l <= b; l++) owner.set(l, step);
    }),
  );
  const lines = code.split("\n");
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface">
      <div className="flex flex-wrap gap-1.5 border-b border-line px-4 py-3">
        {steps.map((s, n) => (
          <button
            key={n}
            type="button"
            onClick={() => onStep(n)}
            disabled={!codeMap?.[n]?.length}
            className={cx("rounded-full px-2.5 py-1 text-xs font-medium disabled:opacity-40", KIND[s.kind].tone)}
          >
            {n + 1} · {s.label}
          </button>
        ))}
        {!codeMap && (
          <span className="self-center text-xs text-ink-3">
            {pending ? "Marking which lines do each step. Open this again in a moment." : "The steps aren't marked in the code yet."}
          </span>
        )}
      </div>
      <div ref={box} className="relative max-h-[36rem] overflow-auto py-2 font-mono text-[12.5px] leading-[1.6]">
        {lines.map((text, i) => {
          const n = i + 1;
          const step = owner.get(n);
          const begins = starts.get(n);
          const comment = /^\s*#/.test(text);
          return (
            <div key={n}>
              {begins !== undefined && (
                <div className={cx("sticky left-0 mt-2 ml-14 inline-block rounded-md px-2 py-0.5 font-sans text-[11px] font-medium", KIND[steps[begins].kind].tone)}>
                  {begins + 1} · {steps[begins].label}
                </div>
              )}
              <div
                data-line={n}
                className={cx("flex border-l-4", step !== undefined ? KIND[steps[step].kind].line : "border-transparent")}
              >
                <span className="w-12 shrink-0 pr-3 text-right text-ink-3 select-none tabular-nums">{n}</span>
                <code className={cx("pr-4 whitespace-pre", comment ? "text-ink-3" : "text-ink")}>{text || " "}</code>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
