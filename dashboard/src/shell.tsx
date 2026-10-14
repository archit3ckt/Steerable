import { Suspense, type ReactNode } from "react";
import { AgentError } from "./backend/agent";
import type { Health } from "./backend/types";
import type { DashboardHost } from "./host";
import Link from "next/link";
import { Logo, LogoMark } from "./logo";
import { RailNav, SideNav, TabBar, WideMode } from "./nav";
import { StatusButton } from "./status-panel";
import { CooAvatar, Skeleton, cx } from "./ui";

/** Shell parts render on every page, so if the COO can't be reached they show less, not an error. */
export async function orNull<T>(load: Promise<T>): Promise<T | null> {
  try {
    return await load;
  } catch (error) {
    if (error instanceof AgentError) return null;
    throw error;
  }
}

export async function DecisionBadge({ host }: { host: DashboardHost }) {
  const decisions = (await orNull((await host.backend()).decisions())) ?? [];
  if (decisions.length === 0) return null;
  const urgent = decisions.some((d) => d.urgent);
  return (
    <span
      className={cx(
        "grid h-5 min-w-5 place-items-center rounded-full px-1.5 text-[0.7rem] leading-none font-semibold tabular-nums",
        urgent ? "bg-rose text-bg" : "bg-accent text-accent-ink",
      )}
    >
      {decisions.length}
      <span className="sr-only"> waiting</span>
    </span>
  );
}

const HEALTH_DOT = { good: "bg-accent", attention: "bg-amber", problem: "bg-rose" };

/** The company's name, its COO, and how things stand, as at the top of the sidebar. */
export function CompanyCardView({ name, cooName, health, statusUrl }: { name: string; cooName: string; health: Health; statusUrl?: string }) {
  const line = (
    <>
      <span className={cx("size-1.5 shrink-0 rounded-full", HEALTH_DOT[health.state])} />
      <span className="truncate">{health.summary}</span>
    </>
  );
  return (
    <div className="flex items-center gap-3">
      <CooAvatar name={cooName} />
      <div className="min-w-0">
        <p className="truncate font-medium">{name}</p>
        {statusUrl ? (
          <StatusButton statusUrl={statusUrl} cooName={cooName}>
            {line}
          </StatusButton>
        ) : (
          <p className="flex items-center gap-1.5 truncate text-xs text-ink-2">{line}</p>
        )}
      </div>
    </div>
  );
}

/** The company card from the engine's overview; `fallback` names it while the COO can't be reached. */
export async function CompanyCard({ host, fallback }: { host: DashboardHost; fallback: { name: string; cooName: string } }) {
  const overview = await orNull((await host.backend()).overview());
  const name = overview?.company.name ?? fallback.name;
  const cooName = overview?.company.cooName ?? fallback.cooName;
  const health = overview?.health ?? { state: "attention" as const, summary: `Can't reach ${cooName} right now` };
  return <CompanyCardView name={name} cooName={cooName} health={health} statusUrl={host.statusUrl} />;
}

export function CompanyCardSkeleton() {
  return (
    <div className="flex items-center gap-3">
      <Skeleton className="size-9 rounded-full" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-3.5 w-28 rounded-md" />
        <Skeleton className="h-3 w-36 rounded-md" />
      </div>
    </div>
  );
}

/**
 * The dashboard's frame: sidebar on large screens, a header and tab bar on phones. The host
 * fills the slots (each rendered inside Suspense where it's placed):
 *   company   top of the sidebar and the phone header (CompanyCard, or the host's own). A
 *             function, because it's rendered twice and each place needs its own element.
 *   footer    bottom of the sidebar (account menu, notes)
 *   header    right side of the phone header (a compact account menu)
 *   after     anything else on every page (an overlay, a background sync)
 */
export function DashboardShell({
  host,
  company,
  footer,
  header,
  after,
  children,
}: {
  host: DashboardHost;
  company: () => ReactNode;
  footer?: ReactNode;
  header?: ReactNode;
  after?: ReactNode;
  children: ReactNode;
}) {
  const badge = (
    <Suspense>
      <DecisionBadge host={host} />
    </Suspense>
  );
  return (
    // On a wide page (the library: WideMode puts data-wide in here) the shell takes the whole width
    // and trades its sidebar for a slim rail of the main pages, so the page can show its own sidebar,
    // like monday's boards.
    <div className="group/shell mx-auto flex min-h-dvh max-w-7xl has-[[data-wide]]:max-w-none">
      <WideMode />
      <aside className="sticky top-0 hidden h-dvh w-72 shrink-0 flex-col gap-8 px-6 py-8 lg:flex lg:group-has-[[data-wide]]/shell:hidden">
        <Logo />
        <Suspense fallback={<CompanyCardSkeleton />}>{company()}</Suspense>
        <SideNav badge={badge} connections={host.connections} />
        {footer && <div className="mt-auto space-y-3">{footer}</div>}
      </aside>
      <aside className="sticky top-0 hidden h-dvh w-16 shrink-0 flex-col items-center gap-6 border-r border-line py-6 lg:group-has-[[data-wide]]/shell:flex">
        <Link href="/today" aria-label="Today" className="text-accent">
          <LogoMark className="h-7 w-auto" />
        </Link>
        <RailNav badge={badge} connections={host.connections} />
      </aside>

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-2 border-b border-line bg-bg/85 px-4 py-3 backdrop-blur-xl sm:px-6 lg:hidden">
          <div className="min-w-0 flex-1">
            <Suspense fallback={<CompanyCardSkeleton />}>{company()}</Suspense>
          </div>
          {header && (
            <div className="shrink-0">
              <Suspense>{header}</Suspense>
            </div>
          )}
        </header>
        <main id="main" className="px-4 pt-8 pb-32 sm:px-8 lg:px-12 lg:pt-14 lg:pb-16">
          {children}
        </main>
      </div>

      <TabBar badge={badge} />
      {after}
    </div>
  );
}
