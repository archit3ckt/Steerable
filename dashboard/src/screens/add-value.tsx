import { Suspense } from "react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ExternalLink, ShieldCheck } from "lucide-react";
import type { DashboardHost } from "../host";
import { Card, PageHeader, Skeleton } from "../ui";
import { ValueForm } from "../value-form";

/** Add something the COO asked for: what it is, why, where to find it, and one box. */
export function AddValuePage({ host, name }: { host: DashboardHost; name: string | Promise<string> }) {
  return (
    <div className="mx-auto max-w-xl">
      <Link href="/decisions" className="mb-6 inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink">
        <ArrowLeft className="size-4" /> Decisions
      </Link>
      <Suspense fallback={<Skeleton className="h-80" />}>
        <AddValue host={host} name={name} />
      </Suspense>
    </div>
  );
}

async function AddValue({ host, name }: { host: DashboardHost; name: string | Promise<string> }) {
  const backend = await host.backend();
  const [request, { company }] = await Promise.all([backend.valueRequest(decodeURIComponent(await name)), backend.overview()]);
  if (!request) notFound();
  return (
    <>
      <PageHeader title={`Add ${request.label}`} subtitle={request.why ?? undefined} />
      <Card className="space-y-5 p-6">
        {request.url && (
          <a href={request.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 font-medium text-accent hover:underline">
            Where to find it <ExternalLink className="size-4" />
          </a>
        )}
        {request.hint && <p className="text-sm text-ink-2">{request.hint}</p>}
        {request.saved && <p className="text-sm text-ink-3">You&apos;ve added it before. Saving replaces it.</p>}
        <ValueForm name={request.name} label={request.label} save={host.actions.saveValue} />
        <p className="flex gap-2 text-xs text-ink-3">
          <ShieldCheck className="size-4 shrink-0" />
          Kept private on {company.cooName}&apos;s side: only your routines use it, and no AI reads it.
        </p>
      </Card>
    </>
  );
}
