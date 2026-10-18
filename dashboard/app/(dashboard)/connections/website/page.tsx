import type { Metadata } from "next";
import { Suspense } from "react";
import { ShieldCheck } from "lucide-react";
import { Card, PageHeader, Skeleton } from "../../../../src/ui";
import { LiveLogin } from "../../../../src/live-login";

export const metadata: Metadata = { title: "Log in to a website" };

export default function Page({ searchParams }: PageProps<"/connections/website">) {
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Log in to a website"
        subtitle="For sites without an app on the Connections page, like a supplier portal or a booking system. Your COO uses it only in routines you approve."
      />
      <Card className="mb-6 flex gap-4 p-5 text-sm text-ink-2">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-accent" />
        <p>
          You log in yourself, in a private browser running on your server and shown here. Steerable keeps the logged-in
          session, never your password, where no AI can read it. Some sites don&apos;t allow automated logins (social
          networks, big marketplaces, banks), so they&apos;re not offered. Add only logins you&apos;re allowed to share,
          for sites whose terms allow it: what your COO does on the site is done as you, and is your responsibility.
        </p>
      </Card>
      <Card className="p-6">
        <Suspense fallback={<Skeleton className="h-48" />}>
          <Start searchParams={searchParams} />
        </Suspense>
      </Card>
    </div>
  );
}

async function Start({ searchParams }: { searchParams: PageProps<"/connections/website">["searchParams"] }) {
  const params = await searchParams;
  const url = typeof params.url === "string" && /^https?:\/\//.test(params.url) ? params.url : "";
  const name = typeof params.name === "string" ? params.name.slice(0, 60) : "";
  return <LiveLogin initialUrl={url} initialName={name} />;
}
