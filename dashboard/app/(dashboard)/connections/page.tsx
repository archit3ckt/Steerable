import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";
import { Check, ExternalLink, Globe, Plug, ShieldCheck } from "lucide-react";
import { Card, PageHeader, SectionHeader, Skeleton } from "../../../src/ui";
import { ago } from "../../../src/format";
import { company, now } from "../../../local/host";
import {
  aiStatus,
  extensionStatus,
  savedSites,
  telegramStatus,
  toolsOverview,
  ToolsError,
  type AiStatus,
  type ExtensionStatus,
  type SavedSite,
  type TelegramStatus,
  type ToolsOverview,
} from "../../../local/tools";
import { ExtensionCard } from "../../../src/extension-card";
import { newExtensionCode, unpairExtension } from "../../../local/tool-actions";
import { AddOwn, Catalog, ClaudeCard, DisconnectButton, JevCard, RemoveSiteButton, StopAlwaysButton, TelegramCard } from "./parts";

export const metadata: Metadata = { title: "Connections" };

export default function Page({ searchParams }: PageProps<"/connections">) {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Connections"
        subtitle={`The services your business runs on. ${company.cooName} looks things up in them on its own, and asks you before changing anything.`}
      />
      <Suspense fallback={<Skeleton className="h-[32rem] rounded-3xl" />}>
        <Connections searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

async function Connections({ searchParams }: { searchParams: PageProps<"/connections">["searchParams"] }) {
  const q = await searchParams;
  const note =
    typeof q.connected === "string"
      ? { ok: true, text: `${q.connected} is connected.` }
      : typeof q.site === "string"
        ? { ok: true, text: `Your login to ${q.site} is saved.` }
        : typeof q.error === "string"
          ? { ok: false, text: q.error }
          : null;
  let data: ToolsOverview;
  let telegram: TelegramStatus;
  let sites: SavedSite[];
  let extension: ExtensionStatus;
  let ai: AiStatus;
  try {
    [data, telegram, sites, extension, ai] = await Promise.all([
      toolsOverview(),
      telegramStatus(),
      savedSites(),
      extensionStatus(),
      aiStatus(),
    ]);
  } catch (error) {
    if (!(error instanceof ToolsError)) throw error;
    return <Card className="p-6 text-ink-2">{error.message}</Card>;
  }
  const connectedIds = new Set(data.connected.map((c) => c.id));
  const at = await now();
  // Tabs, so nothing is at the bottom of a long page; a saved website login opens its own tab.
  const tab = TABS.some(([id]) => id === q.tab) ? (q.tab as Tab) : typeof q.site === "string" ? "websites" : "services";
  const counts: Record<Tab, string> = {
    services: data.connected.length ? `${data.connected.length} connected` : "",
    websites: sites.length ? `${sites.length} saved` : "",
    other: "",
    ai: "",
  };

  return (
    <div className="space-y-10">
      {note && (
        <p
          role="status"
          className={note.ok ? "rounded-xl bg-accent-soft px-4 py-3 text-accent" : "rounded-xl bg-rose-soft px-4 py-3 text-rose"}
        >
          {note.text}
        </p>
      )}

      <nav aria-label="Kinds of connections" className="flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map(([id, label]) => (
          <Link
            key={id}
            href={`/connections?tab=${id}`}
            aria-current={tab === id ? "page" : undefined}
            className={`-mb-px shrink-0 border-b-2 px-4 py-3 text-sm whitespace-nowrap transition-colors ${
              tab === id ? "border-accent font-medium text-ink" : "border-transparent text-ink-2 hover:text-ink"
            }`}
          >
            {label}
            {counts[id] && <span className="ml-1.5 text-xs font-normal text-ink-3">{counts[id]}</span>}
          </Link>
        ))}
      </nav>

      {tab === "ai" && (
        <>
          <section aria-label="AI" className="space-y-3">
            <ClaudeCard status={ai.claude} cooName={company.cooName} />
            <JevCard status={ai.jev} cooName={company.cooName} throughSteerable={data.throughSteerable} />
          </section>
          <TelegramCard status={telegram} cooName={company.cooName} />
        </>
      )}

      {tab === "services" && (
        <>
          {data.claudeAccount && <ClaudeConnectors />}

          {data.connected.length > 0 && (
            <section>
              <SectionHeader title="Connected" />
              <Card className="divide-y divide-line">
                {data.connected.map((c) => (
                  <div key={c.id} className="flex items-center gap-3 px-5 py-4">
                    <span className="grid size-8 place-items-center rounded-full bg-accent-soft text-accent">
                      <Check className="size-4" />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="font-medium">{c.name}</p>
                      <p className="text-sm text-ink-3">
                        {c.tools === 1 ? "1 thing" : `${c.tools} things`} {company.cooName} can do there
                        {c.custom ? ` · ${new URL(c.url).hostname}` : ""}
                      </p>
                    </div>
                    <DisconnectButton id={c.id} name={c.name} />
                  </div>
                ))}
              </Card>
            </section>
          )}

          {data.alwaysAllowed.length > 0 && (
            <section>
              <SectionHeader title="Allowed without asking" />
              <Card className="divide-y divide-line">
                {data.alwaysAllowed.map((a) => (
                  <div key={a.tool} className="flex items-center gap-3 px-5 py-3">
                    <ShieldCheck className="size-4 shrink-0 text-ink-3" />
                    <p className="min-w-0 flex-1 text-sm">
                      {a.what} in {a.service}
                    </p>
                    <StopAlwaysButton tool={a.tool} />
                  </div>
                ))}
              </Card>
            </section>
          )}

          <section>
            <SectionHeader title="Connect a service" />
            <Catalog items={data.catalog.filter((c) => !connectedIds.has(c.id))} />
          </section>
        </>
      )}

      {tab === "websites" && (
        <section>
          <SectionHeader
            title="Your logins"
            action={
              <Link href="/connections/website" className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline">
                <Globe className="size-4" /> Log in to a website
              </Link>
            }
          />
          {sites.length > 0 ? (
            <Card className="divide-y divide-line">
              {sites.map((s) => (
                <div key={s.site} className="flex items-center gap-3 px-5 py-4">
                  <span className="grid size-8 place-items-center rounded-full bg-surface-2 text-ink-2">
                    <Globe className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{s.name}</p>
                    <p className="text-sm text-ink-3">
                      {s.site}
                      {s.source === "browser" && s.status !== "EXPIRED" && <> · from your browser, in step {ago(s.savedAt, at)}</>}
                      {s.status === "EXPIRED" &&
                        (s.source === "browser" ? (
                          <span className="text-rose"> · logged out: log in there again in your browser, and it follows</span>
                        ) : (
                          <>
                            {" · "}
                            <Link
                              href={`/connections/website?url=${encodeURIComponent(s.startUrl)}&name=${encodeURIComponent(s.name)}`}
                              className="text-rose hover:underline"
                            >
                              logged out: log in again
                            </Link>
                          </>
                        ))}
                    </p>
                  </div>
                  <RemoveSiteButton site={s.site} />
                </div>
              ))}
            </Card>
          ) : (
            <p className="text-sm text-ink-3">
              For sites without an app here, like a supplier portal: you log in once, and {company.cooName}&apos;s routines can use your
              account there.
            </p>
          )}
          <div className="mt-4">
            <ExtensionCard status={extension} cooName={company.cooName} newCode={newExtensionCode} unpair={unpairExtension} />
          </div>
        </section>
      )}

      {tab === "other" && (
        <section aria-label="Any other service">
          <AddOwn />
        </section>
      )}
    </div>
  );
}

type Tab = "services" | "websites" | "other" | "ai";
const TABS: [Tab, string][] = [
  ["services", "Services"],
  ["websites", "Website logins"],
  ["other", "Any other service"],
  ["ai", "AI and Telegram"],
];

function ClaudeConnectors() {
  return (
    <Card className="flex gap-4 p-5">
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-violet-soft text-violet">
        <Plug className="size-5" />
      </span>
      <div className="text-sm text-ink-2">
        <p className="font-medium text-ink">Gmail, Google Calendar, Slack and more</p>
        <p className="mt-1">
          {company.cooName} is signed in with your Claude account, so the connectors you add at claude.ai work here too. It reads with them
          freely and asks you before sending or changing anything.
        </p>
        <a
          href="https://claude.ai/settings/connectors"
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-flex items-center gap-1 font-medium text-accent hover:underline"
        >
          Your connectors at claude.ai <ExternalLink className="size-3.5" />
        </a>
      </div>
    </Card>
  );
}
