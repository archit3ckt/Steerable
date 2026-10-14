import type { ReactNode } from "react";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

export const inputClass =
  "w-full rounded-xl border border-line bg-surface px-4 py-3 text-base shadow-card placeholder:text-ink-3 focus:border-accent focus:ring-2 focus:ring-accent/20 focus:outline-none focus-visible:outline-none";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cx("rounded-2xl border border-line bg-surface shadow-card", className)}>{children}</div>
  );
}

export function PageHeader({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="font-display text-4xl leading-tight tracking-tight sm:text-5xl">{title}</h1>
        {subtitle && <p className="mt-2 max-w-xl text-ink-2">{subtitle}</p>}
      </div>
      {children}
    </header>
  );
}

export function SectionHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-4">
      <h2 className="text-sm font-medium tracking-wide text-ink-3 uppercase">{title}</h2>
      {action}
    </div>
  );
}

const TONES = {
  neutral: "bg-surface-2 text-ink-2",
  accent: "bg-accent-soft text-accent",
  amber: "bg-amber-soft text-amber",
  rose: "bg-rose-soft text-rose",
  sky: "bg-sky-soft text-sky",
  violet: "bg-violet-soft text-violet",
} as const;

export type Tone = keyof typeof TONES;

export function Pill({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function CooAvatar({ name, size = "md" }: { name: string; size?: "sm" | "md" | "lg" }) {
  const dims = { sm: "size-6 text-sm", md: "size-9 text-lg", lg: "size-12 text-2xl" }[size];
  return (
    <span
      aria-hidden
      className={cx(
        "inline-grid shrink-0 place-items-center rounded-full bg-accent-soft font-display text-accent ring-1 ring-accent/15",
        dims,
      )}
    >
      {name.charAt(0)}
    </span>
  );
}

export function Progress({ value, tone = "accent" }: { value: number; tone?: "accent" | "amber" | "rose" }) {
  const pct = Math.max(0, Math.min(100, value * 100));
  const bar = { accent: "bg-accent", amber: "bg-amber", rose: "bg-rose" }[tone];
  return (
    <div className="h-2 overflow-hidden rounded-full bg-surface-2" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
      <div className={cx("h-full rounded-full transition-[width] duration-700", bar)} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <Card className="flex flex-col items-center px-6 py-14 text-center">
      <div className="mb-4 grid size-12 place-items-center rounded-full bg-accent-soft text-accent">{icon}</div>
      <p className="font-display text-2xl">{title}</p>
      {children && <p className="mt-1 max-w-sm text-ink-2">{children}</p>}
    </Card>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-2xl bg-surface-2", className)} />;
}
