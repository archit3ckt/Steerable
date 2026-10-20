"use client";

import { useState, useTransition } from "react";
import { Loader2, Trash2 } from "lucide-react";
import { deleteSpace, switchSpace } from "../../../local/space-actions";
import { inputClass } from "../../../src/ui";

/** One space in the list: open it, or delete it (not the first). */
export function SpaceRow({ id, name, cooName, current, first }: { id: string; name: string; cooName: string; current: boolean; first: boolean }) {
  const [confirming, setConfirming] = useState(false);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState("");
  const [pending, start] = useTransition();
  return (
    <div className="px-5 py-4">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">{name}</p>
          <p className="text-sm text-ink-3">
            {cooName}
            {current && " · you're here"}
          </p>
        </div>
        {!current && (
          <button type="button" disabled={pending} onClick={() => start(() => switchSpace(id))} className="rounded-full px-3 py-1.5 text-sm text-ink-2 hover:bg-surface-2 hover:text-ink">
            Open
          </button>
        )}
        {!first && (
          <button type="button" onClick={() => setConfirming((v) => !v)} title={`Delete ${name}`} className="grid size-8 place-items-center rounded-full text-ink-3 hover:bg-rose-soft hover:text-rose">
            <Trash2 className="size-4" />
            <span className="sr-only">Delete {name}</span>
          </button>
        )}
      </div>
      {confirming && (
        <form
          className="mt-4 space-y-3 rounded-xl bg-rose-soft p-4"
          onSubmit={(e) => {
            e.preventDefault();
            start(async () => setError((await deleteSpace(id, typed)).error ?? ""));
          }}
        >
          <p className="text-sm text-rose">
            This deletes {name}: {cooName}, its memory, routines, chat and connections, for good. Download it first (the download button, while
            you&apos;re in it) if you want to keep anything.
          </p>
          <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder={`Type ${name} to confirm`} className={inputClass} />
          {error && <p className="text-sm text-rose">{error}</p>}
          <button type="submit" disabled={pending} className="inline-flex items-center gap-2 rounded-full bg-rose px-4 py-2 text-sm font-medium text-bg disabled:opacity-60">
            {pending && <Loader2 className="size-4 animate-spin" />}
            Delete {name}
          </button>
        </form>
      )}
    </div>
  );
}

/** A new space: its name, its COO's, and optionally a company to start from. Then waits for its COO. */
export function NewSpaceForm() {
  const [error, setError] = useState("");
  const [waiting, setWaiting] = useState<{ id: string; name: string } | null>(null);
  const [pending, start] = useTransition();

  async function create(form: FormData) {
    setError("");
    const file = form.get("archive");
    const params = new URLSearchParams({ name: String(form.get("name") ?? ""), coo: String(form.get("coo") ?? "") });
    const res = await fetch(`/api/spaces?${params}`, { method: "POST", body: file instanceof File && file.size ? file : undefined }).catch(() => null);
    const data = res ? await res.json().catch(() => ({})) : {};
    if (!res?.ok) return setError(data.error ?? "That didn't work. Try again in a minute.");
    setWaiting({ id: data.space.id, name: data.space.name });
    for (let i = 0; i < 120; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      const ready = await fetch(`/api/spaces/ready?id=${data.space.id}`, { cache: "no-store" }).then((r) => r.json()).catch(() => ({}));
      if (ready.ready) return switchSpace(data.space.id);
    }
    setWaiting(null);
    setError(`${data.space.name} is taking longer than usual to start. It will show in the list when it's ready.`);
  }

  if (waiting) {
    return (
      <p className="flex items-center gap-3 py-2 text-ink-2">
        <Loader2 className="size-5 animate-spin text-accent" />
        Setting up {waiting.name}. This takes a minute.
      </p>
    );
  }
  return (
    <form action={(form) => start(() => create(form))} className="mt-4 space-y-5">
      <label className="block">
        <span className="text-sm font-medium">Name</span>
        <span className="mt-0.5 block text-sm text-ink-3">A business, a brand or a project.</span>
        <input name="name" required maxLength={80} placeholder="Bloom & Root Events" className={`${inputClass} mt-2`} />
      </label>
      <label className="block">
        <span className="text-sm font-medium">Its business manager</span>
        <span className="mt-0.5 block text-sm text-ink-3">Each space has its own, who only knows this space.</span>
        <input name="coo" maxLength={40} defaultValue="Juno" className={`${inputClass} mt-2`} />
      </label>
      <label className="block">
        <span className="text-sm font-medium">Start from a company you have (optional)</span>
        <span className="mt-0.5 block text-sm text-ink-3">A download from another Steerable, or from Steerable Cloud (company.tar.gz).</span>
        <input name="archive" type="file" accept=".gz,.tgz,application/gzip" className="mt-2 block text-sm text-ink-2" />
      </label>
      {error && (
        <p role="alert" className="text-sm text-rose">
          {error}
        </p>
      )}
      <button type="submit" disabled={pending} className="inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 font-medium text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-70">
        {pending && <Loader2 className="size-4 animate-spin" />}
        Create the space
      </button>
      <p className="text-sm text-ink-3">
        Its business manager signs in to its AI on its own Connections page (your Claude account works for every space). Give your server about 150 MB of memory per space.
      </p>
    </form>
  );
}
