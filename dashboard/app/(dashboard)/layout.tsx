import { Suspense } from "react";
import { Download, LogOut, Plug, Sparkles } from "lucide-react";
import { CompanyCard, DashboardShell } from "../../src/shell";
import { ThemeToggle } from "../../src/theme-toggle";
import { currentCompany, currentSpace, host, spaces } from "../../local/host";
import { SpaceSwitcher } from "./space-switcher";
import { signOut } from "../../local/login";
import { aiStatus } from "../../local/tools";

const iconLink = "grid size-8 place-items-center rounded-full text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink";

/** Phones have no sidebar, so Connections sits up here with the account buttons. */
function Account({ phone = false }: { phone?: boolean }) {
  return (
    <div className="flex items-center gap-1">
      {phone && (
        <a href="/connections" title="Connections" className={iconLink}>
          <Plug className="size-4" />
          <span className="sr-only">Connections</span>
        </a>
      )}
      <ThemeToggle />
      <a
        href="/export"
        title="Download your company"
        className="grid size-8 place-items-center rounded-full text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
      >
        <Download className="size-4" />
        <span className="sr-only">Download your company</span>
      </a>
      <SignOut />
    </div>
  );
}

function SignOut() {
  return (
    <form action={signOut}>
      <button
        type="submit"
        title="Sign out"
        className="grid size-8 place-items-center rounded-full text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink"
      >
        <LogOut className="size-4" />
        <span className="sr-only">Sign out</span>
      </button>
    </form>
  );
}

/** Until the COO has AI (a Claude account or a key), nothing works: say so on every page. */
async function AiNotice() {
  const ai = await aiStatus().catch(() => null);
  if (ai?.claude.method !== "none") return null;
  const company = await currentCompany();
  return (
    <a
      href="/connections"
      className="fixed inset-x-4 bottom-24 z-40 flex items-start gap-3 rounded-2xl border border-amber/30 bg-amber-soft px-4 py-3 text-sm text-amber shadow-card lg:inset-x-auto lg:right-6 lg:bottom-6 lg:max-w-sm"
    >
      <Sparkles className="mt-0.5 size-4 shrink-0" />
      <span>
        {company.cooName} isn&apos;t signed in to its AI yet, so it can&apos;t work.{" "}
        <span className="font-medium underline underline-offset-4">Sign it in with Claude</span>
      </span>
    </a>
  );
}

/** The current space's card, with the menu of spaces. */
async function SpaceCard() {
  const [space, company] = await Promise.all([currentSpace(), currentCompany()]);
  return (
    <SpaceSwitcher current={space.id} spaces={spaces().map((s) => ({ id: s.id, name: s.name }))}>
      <CompanyCard host={host} fallback={company} />
    </SpaceSwitcher>
  );
}

export default function DashboardLayout({ children }: LayoutProps<"/">) {
  return (
    <DashboardShell
      host={host}
      company={() => <SpaceCard />}
      footer={<Account />}
      header={<Account phone />}
      after={
        <Suspense>
          <AiNotice />
        </Suspense>
      }
    >
      {children}
    </DashboardShell>
  );
}
