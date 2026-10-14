import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";
import { AtSign, KeyRound } from "lucide-react";
import { Card, PageHeader, Pill, SectionHeader, Skeleton } from "../../../src/ui";
import { ago } from "../../../src/format";
import { company, now } from "../../../local/host";
import { accountsOverview, ToolsError, type AccountsOverview } from "../../../local/tools";
import { AccountActions, MailboxCard, PhoneForm } from "./parts";

export const metadata: Metadata = { title: "Accounts" };

export default function Page({ searchParams }: PageProps<"/accounts">) {
  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title={`${company.cooName}'s accounts`}
        subtitle={`${company.cooName} has an email of its own, and signs up to sites your business needs with it, always with your OK. Everything it has is listed here, and you can take any of it over.`}
      />
      <Suspense fallback={<Skeleton className="h-[28rem] rounded-3xl" />}>
        <Accounts searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

async function Accounts({ searchParams }: { searchParams: PageProps<"/accounts">["searchParams"] }) {
  const { saved } = await searchParams;
  let data: AccountsOverview;
  try {
    data = await accountsOverview();
  } catch (error) {
    if (!(error instanceof ToolsError)) throw error;
    return <Card className="p-6 text-ink-2">{error.message}</Card>;
  }
  const at = await now();
  const coo = company.cooName;

  return (
    <div className="space-y-10">
      {typeof saved === "string" && (
        <p role="status" className="rounded-xl bg-accent-soft px-4 py-3 text-accent">
          {coo}&apos;s account on {saved} is saved.
        </p>
      )}

      <section>
        <SectionHeader title="Its email" />
        <MailboxCard mailbox={data.mailbox} cooName={coo} />
      </section>

      <section>
        <SectionHeader title="Your phone, for codes" />
        <Card className="p-5">
          <p className="text-sm text-ink-2">
            Some sites text a code when {coo} signs up. They go to your phone, and you type them into the sign-up screen
            yourself. {coo} never asks for a code in chat.
          </p>
          <PhoneForm phone={data.phone} />
        </Card>
      </section>

      <section>
        <SectionHeader title="Its accounts" />
        {data.accounts.length === 0 ? (
          <p className="text-sm text-ink-3">
            None yet. When a routine needs one, like a design tool or a supplier&apos;s shop, {coo} asks you in Decisions first.
          </p>
        ) : (
          <Card className="divide-y divide-line">
            {data.accounts.map((a) => (
              <div key={a.site} className="flex flex-wrap items-start gap-3 px-5 py-4">
                <span className="grid size-8 shrink-0 place-items-center rounded-full bg-surface-2 text-ink-2">
                  <KeyRound className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-center gap-2 font-medium">
                    {a.name}
                    {a.status === "ACTIVE" ? (
                      <Pill tone="accent">Active</Pill>
                    ) : a.status === "APPROVED" ? (
                      <Pill tone="amber">Waiting for sign-up</Pill>
                    ) : (
                      <Pill tone="neutral">Asked you</Pill>
                    )}
                  </p>
                  <p className="text-sm text-ink-2">{a.why}</p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-1 text-xs text-ink-3">
                    <span>{a.site}</span>
                    {a.email && (
                      <>
                        · <AtSign className="size-3" /> {a.email}
                      </>
                    )}
                    {a.lastUsed ? <span>· used {ago(a.lastUsed, at)}</span> : a.createdAt ? <span>· made {ago(a.createdAt, at)}</span> : null}
                  </p>
                  {a.status === "APPROVED" && (
                    <Link
                      href={`/accounts/signup?site=${encodeURIComponent(a.site)}`}
                      className="mt-2 inline-flex rounded-full bg-accent px-4 py-1.5 text-sm font-medium text-accent-ink hover:bg-accent-hover"
                    >
                      Sign it up now
                    </Link>
                  )}
                </div>
                <AccountActions site={a.site} name={a.name} status={a.status} />
              </div>
            ))}
          </Card>
        )}
      </section>
    </div>
  );
}
