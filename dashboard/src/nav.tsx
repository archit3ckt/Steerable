"use client";

import { Suspense, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { History, Inbox, KeyRound, ListChecks, MessageCircle, Plug, Sun, Table2, Target } from "lucide-react";
import { cx } from "./ui";

const ITEMS = [
  { href: "/today", label: "Today", Icon: Sun, mobile: true },
  { href: "/decisions", label: "Decisions", Icon: Inbox, mobile: true, badge: true },
  { href: "/timeline", label: "Timeline", Icon: History, mobile: true },
  { href: "/work", label: "Work", Icon: ListChecks, mobile: true },
  { href: "/library", label: "Library", Icon: Table2, mobile: true },
  { href: "/goals", label: "Goals", Icon: Target, mobile: false },
  { href: "/chat", label: "Chat", Icon: MessageCircle, mobile: true },
  { href: "/connections", label: "Connections", Icon: Plug, mobile: false, needsConnections: true },
  { href: "/accounts", label: "Accounts", Icon: KeyRound, mobile: false, needsConnections: true },
];

type IsActive = (href: string) => boolean;
const none: IsActive = () => false;

/**
 * Which item is current comes from the address, which pages with an id in it (a routine's page)
 * only know at request time; so each nav shows unhighlighted first, inside Suspense.
 */
function WithActive({ render }: { render: (isActive: IsActive) => ReactNode }) {
  const pathname = usePathname();
  return render((href) => pathname.startsWith(href));
}

/** `connections`: show the Connections page (hosts that have one). */
export function SideNav(props: { badge: ReactNode; connections: boolean }) {
  return (
    <Suspense fallback={<SideNavList {...props} isActive={none} />}>
      <WithActive render={(isActive) => <SideNavList {...props} isActive={isActive} />} />
    </Suspense>
  );
}

/** Pages that bring their own sidebar and take the whole width. */
const WIDE = ["/library"];

/**
 * Marks the shell as wide (data-wide) while the address is one of WIDE. From the address, not from
 * the page: Next keeps recently visited pages mounted but hidden, and a hidden library page must not
 * keep the shell wide.
 */
export function WideMode() {
  return (
    <Suspense fallback={null}>
      <WideMarker />
    </Suspense>
  );
}

function WideMarker() {
  const pathname = usePathname();
  return WIDE.some((p) => pathname === p || pathname.startsWith(`${p}/`)) ? <span data-wide hidden /> : null;
}

/** The main pages as icons only, for pages that bring their own sidebar (the library). */
export function RailNav(props: { badge: ReactNode; connections: boolean }) {
  return (
    <Suspense fallback={<RailList {...props} isActive={none} />}>
      <WithActive render={(isActive) => <RailList {...props} isActive={isActive} />} />
    </Suspense>
  );
}

function RailList({ badge, connections, isActive }: { badge: ReactNode; connections: boolean; isActive: IsActive }) {
  return (
    <nav aria-label="Main" className="flex flex-col items-center gap-1">
      {ITEMS.filter((i) => connections || !i.needsConnections).map(({ href, label, Icon, badge: hasBadge }) => {
        const active = isActive(href);
        return (
          <Link
            key={href}
            href={href}
            aria-label={label}
            title={label}
            aria-current={active ? "page" : undefined}
            className={cx(
              "relative grid size-10 place-items-center rounded-xl transition-colors",
              active ? "bg-surface text-accent shadow-sm" : "text-ink-3 hover:bg-surface-2 hover:text-ink",
            )}
          >
            <Icon className="size-5" strokeWidth={active ? 2.2 : 1.8} />
            {hasBadge && <span className="absolute -top-1 -right-1 scale-90">{badge}</span>}
          </Link>
        );
      })}
    </nav>
  );
}

export function TabBar(props: { badge: ReactNode }) {
  return (
    <Suspense fallback={<TabBarList {...props} isActive={none} />}>
      <WithActive render={(isActive) => <TabBarList {...props} isActive={isActive} />} />
    </Suspense>
  );
}

function SideNavList({ badge, connections, isActive }: { badge: ReactNode; connections: boolean; isActive: IsActive }) {
  return (
    <nav aria-label="Main" className="space-y-1">
      {ITEMS.filter((i) => connections || !i.needsConnections).map(({ href, label, Icon, badge: hasBadge }) => {
        const active = isActive(href);
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={cx(
              "flex items-center gap-3 rounded-xl px-3 py-2.5 text-[0.95rem] transition-colors",
              active ? "bg-surface font-medium text-ink shadow-card" : "text-ink-2 hover:bg-surface/60 hover:text-ink",
            )}
          >
            <Icon className={cx("size-[18px]", active ? "text-accent" : "text-ink-3")} />
            {label}
            {hasBadge && <span className="ml-auto">{badge}</span>}
          </Link>
        );
      })}
    </nav>
  );
}

function TabBarList({ badge, isActive }: { badge: ReactNode; isActive: IsActive }) {
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-bg/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden"
    >
      <ul className="mx-auto grid max-w-md grid-cols-6">
        {ITEMS.filter((i) => i.mobile).map(({ href, label, Icon, badge: hasBadge }) => {
          const active = isActive(href);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "relative flex flex-col items-center gap-1 pt-2.5 pb-2 text-[0.7rem]",
                  active ? "font-medium text-accent" : "text-ink-3",
                )}
              >
                <Icon className="size-[22px]" strokeWidth={active ? 2.2 : 1.8} />
                {label}
                {hasBadge && <span className="absolute top-1 left-1/2 ml-2">{badge}</span>}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
