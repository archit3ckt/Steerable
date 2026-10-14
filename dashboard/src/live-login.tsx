"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent, type MouseEvent } from "react";
import { useRouter } from "next/navigation";
import { AtSign, Globe, KeyRound, Link2, Loader2, Lock, Mail, Phone, Store, X, type LucideIcon } from "lucide-react";
import { inputClass } from "./ui";

const WIDTH = 1280; // the browser's viewport (the engine's scripts/sites.py, Steerable Cloud's browser service)
const BATCH_MS = 150; // typed characters are sent together after this long without a key
const SPECIAL = new Set(["Enter", "Tab", "Backspace", "Escape", "ArrowDown", "ArrowUp"]);

/** Where on the page (in the browser's own pixels) a pointer event over its picture is. */
function pagePoint(e: MouseEvent<HTMLImageElement>): [number, number] {
  const box = e.currentTarget.getBoundingClientRect();
  const scale = WIDTH / box.width;
  return [Math.round((e.clientX - box.left) * scale), Math.round((e.clientY - box.top) * scale)];
}

/** One of the COO's own accounts, signing up (or logging back in) through this screen. */
export type SignupAccount = { site: string; name: string; url: string; email: string | null; hasPhone: boolean; again: boolean };

/** Where the code or link the site emailed the COO shows up (the engine reads its mailbox). */
type Mail = { from: string; subject: string; code: string | null; link: string | null };

const FILLS: { field: string; label: string; Icon: LucideIcon }[] = [
  { field: "email", label: "Its email", Icon: AtSign },
  { field: "password", label: "Its password", Icon: KeyRound },
  { field: "phone", label: "Your phone", Icon: Phone },
  { field: "company", label: "Business name", Icon: Store },
];

/**
 * Log in to a website through a live browser: the owner sees the page and clicks and types into
 * it. Self-hosted, the engine runs the browser; in Steerable Cloud, its browser service. The host
 * serves /api/sites/sessions (start, frame, info, input, save, cancel).
 * With `account`, it signs the COO up to a site: buttons type its details into the field the
 * owner clicked, so its password never reaches this page.
 */
export function LiveLogin({ initialUrl = "", initialName = "", account }: { initialUrl?: string; initialName?: string; account?: SignupAccount }) {
  const router = useRouter();
  const [name, setName] = useState(initialName);
  const [startUrl, setStartUrl] = useState(initialUrl);
  const [session, setSession] = useState<string | null>(null);
  const [frame, setFrame] = useState(0);
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mail, setMail] = useState<Mail | null>(null);
  const typed = useRef("");
  const gaps = useRef<number[]>([]); // ms before each typed character: the owner's own rhythm
  const lastKey = useRef(0);
  const flushTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loading = useRef(false);
  const moves = useRef<[number, number, number][]>([]); // the pointer's path: x, y, ms since the one before
  const lastMove = useRef(0);
  const moveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const downAt = useRef(0);
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  // Inputs reach the page in the order they happened: one request at a time.
  const send = useCallback(
    (body: object, quiet = false) => {
      if (!session) return Promise.resolve();
      const next = queue.current.then(async () => {
        const res = await fetch(`/api/sites/sessions/${session}/input`, { method: "POST", body: JSON.stringify(body) }).catch(() => null);
        if (!res) return;
        if (res.status === 404) setError("That login session ended. Start again.");
        else if (quiet) return;
        else if (!res.ok) setError((await res.json().catch(() => ({}))).error ?? "That didn't work.");
        else setError(null);
        if (!quiet) setTimeout(() => setFrame((f) => f + 1), 250);
      });
      queue.current = next;
      return next;
    },
    [session],
  );

  // The owner's real pointer path goes to the page too, so the site sees a person's movement.
  function flushMoves() {
    if (moveTimer.current) clearTimeout(moveTimer.current);
    moveTimer.current = null;
    const points = moves.current;
    moves.current = [];
    if (points.length) void send({ kind: "move", points }, true);
  }

  function onMove(e: MouseEvent<HTMLImageElement>) {
    const now = performance.now();
    if (now - lastMove.current < 16) return;
    const [x, y] = pagePoint(e);
    moves.current.push([x, y, lastMove.current ? Math.min(Math.round(now - lastMove.current), 400) : 0]);
    lastMove.current = now;
    if (moves.current.length >= 40) flushMoves();
    else moveTimer.current ??= setTimeout(flushMoves, 120);
  }

  // Keep the picture and address fresh while the session is open.
  useEffect(() => {
    if (!session) return;
    const tick = setInterval(() => {
      if (!loading.current) setFrame((f) => f + 1);
    }, 800);
    const info = setInterval(async () => {
      const res = await fetch(`/api/sites/sessions/${session}`).catch(() => null);
      if (res?.ok) {
        const info = await res.json();
        setAddress(info.url ?? "");
        setMail(info.mail ?? null);
      }
    }, 2000);
    return () => {
      clearInterval(tick);
      clearInterval(info);
    };
  }, [session]);

  async function start(e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    const res = await fetch("/api/sites/sessions", { method: "POST", body: JSON.stringify({ url: startUrl, account: account?.site }) });
    const body = await res.json().catch(() => ({}));
    setBusy(false);
    if (!res.ok) return setError(body.error ?? "That didn't work. Try again.");
    setSession(body.id);
  }

  function flush() {
    const text = typed.current;
    const rhythm = gaps.current;
    typed.current = "";
    gaps.current = [];
    if (text) void send({ kind: "type", text, gaps: rhythm });
  }

  function onKey(e: KeyboardEvent) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (SPECIAL.has(e.key)) {
      e.preventDefault();
      flush();
      void send({ kind: "key", key: e.key });
    } else if (e.key.length === 1) {
      e.preventDefault();
      const now = performance.now();
      // Keys go in small batches, sent after a short lull: a batch's first gap is what's left of the pause before it.
      const since = now - lastKey.current;
      gaps.current.push(typed.current ? Math.min(Math.round(since), 400) : lastKey.current && since < 2000 ? Math.max(0, Math.min(Math.round(since - BATCH_MS), 400)) : 0);
      lastKey.current = now;
      typed.current += e.key;
      if (flushTimer.current) clearTimeout(flushTimer.current);
      flushTimer.current = setTimeout(flush, BATCH_MS);
    }
  }

  async function save() {
    setBusy(true);
    setError(null);
    const res = await fetch(`/api/sites/sessions/${session}/save`, { method: "POST", body: JSON.stringify({ name, startUrl }) });
    const body = await res.json().catch(() => ({}));
    setBusy(false);
    if (!res.ok) return setError(body.error ?? "That didn't save. Try again.");
    router.push(account ? `/accounts?saved=${encodeURIComponent(account.name)}` : `/connections?site=${encodeURIComponent(body.site ?? body.host)}`);
  }

  async function cancel() {
    if (session) await fetch(`/api/sites/sessions/${session}`, { method: "DELETE" }).catch(() => {});
    router.push(account ? "/accounts" : "/connections");
  }

  if (!session && account) {
    return (
      <div className="space-y-4">
        <p className="text-ink-2">
          {account.again
            ? `This opens ${account.name} so you can log it back in. Click a field on the page, then tap what goes in it.`
            : `This opens ${account.name}'s sign-up. Click a field on the page, then tap what goes in it: its email, the password made for it, your phone. You handle anything that checks you're human, and codes sent to your phone.`}
        </p>
        {error && (
          <p role="alert" className="rounded-xl bg-rose-soft px-4 py-3 text-sm text-rose">
            {error}
          </p>
        )}
        <button
          type="button"
          onClick={() => void start()}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 font-medium text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-70"
        >
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Globe className="size-4" />}
          Open {account.name}
        </button>
      </div>
    );
  }

  if (!session) {
    return (
      <form onSubmit={start} className="space-y-5">
        <label className="block">
          <span className="text-sm font-medium">What is it?</span>
          <span className="block text-sm text-ink-3">So you&apos;ll recognize it later, like &ldquo;Supplier portal&rdquo;.</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} placeholder="Optional" className={`mt-2 ${inputClass}`} />
        </label>
        <label className="block">
          <span className="text-sm font-medium">Its login page</span>
          <input
            value={startUrl}
            onChange={(e) => setStartUrl(e.target.value)}
            required
            type="url"
            placeholder="https://portal.yoursupplier.com/login"
            className={`mt-2 ${inputClass}`}
          />
        </label>
        {error && (
          <p role="alert" className="rounded-xl bg-rose-soft px-4 py-3 text-sm text-rose">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 font-medium text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-70"
        >
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Globe className="size-4" />}
          Open it
        </button>
      </form>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-ink-2">
        {account
          ? "Click a field on the page, then tap what goes in it. When you see the account is ready, save it."
          : "Log in as you normally would: click the page, then type. When you see you're logged in, save it."}
      </p>
      {account && (
        <div className="space-y-3 rounded-2xl border border-line bg-surface-2 p-4">
          <div className="flex flex-wrap gap-2">
            {FILLS.filter((f) => f.field !== "phone" || account.hasPhone).map(({ field, label, Icon }) => (
              <button
                key={field}
                type="button"
                onClick={() => void send({ kind: "fill", field })}
                className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3.5 py-1.5 text-sm transition-colors hover:border-accent"
              >
                <Icon className="size-4 text-ink-3" />
                {label}
              </button>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
            <Mail className="size-4 shrink-0 text-ink-3" />
            {mail ? (
              <>
                <span className="min-w-0">
                  {mail.code ? (
                    <>
                      Code from {account.name}: <strong className="font-mono text-ink">{mail.code}</strong>
                    </>
                  ) : (
                    <>{account.name} emailed a link</>
                  )}
                </span>
                {mail.code && (
                  <button type="button" onClick={() => void send({ kind: "fill", field: "code" })} className="font-medium text-accent hover:underline">
                    Fill it in
                  </button>
                )}
                {mail.link && (
                  <button
                    type="button"
                    onClick={() => void send({ kind: "open-link" })}
                    className="inline-flex items-center gap-1 font-medium text-accent hover:underline"
                  >
                    <Link2 className="size-3.5" /> Open the link
                  </button>
                )}
              </>
            ) : (
              <span>{account.email ? `Codes and links sent to ${account.email} show up here.` : "Set up its mailbox on the Accounts page to get emailed codes here."}</span>
            )}
          </div>
          <p className="text-xs text-ink-3">
            A code sent to your phone? Type it into the page yourself. Only ever for {account.name}: never type a code from your
            bank, Google or Apple here.
          </p>
        </div>
      )}
      <div className="overflow-hidden rounded-2xl border border-line bg-surface shadow-card">
        <div className="flex items-center gap-2 border-b border-line bg-surface-2 px-4 py-2 text-xs text-ink-2">
          <Lock className="size-3.5 shrink-0" />
          <span className="truncate">{address || startUrl}</span>
        </div>
        {/* eslint-disable-next-line @next/next/no-img-element -- a live frame, not a static image */}
        <img
          src={`/api/sites/sessions/${session}/frame?f=${frame}`}
          alt="The website, live. Click it and type to log in."
          tabIndex={0}
          onLoad={() => (loading.current = false)}
          onLoadStart={() => (loading.current = true)}
          onMouseMove={onMove}
          onMouseDown={() => (downAt.current = performance.now())}
          onClick={(e) => {
            const [x, y] = pagePoint(e);
            e.currentTarget.focus();
            flushMoves();
            flush();
            void send({ kind: "click", x, y, hold: downAt.current ? Math.min(Math.round(performance.now() - downAt.current), 600) : 0 });
          }}
          onKeyDown={onKey}
          onWheel={(e) => void send({ kind: "scroll", dy: Math.round(e.deltaY) })}
          className="block aspect-[1280/800] w-full cursor-pointer bg-white outline-none focus-visible:ring-2 focus-visible:ring-accent"
        />
      </div>
      {error && (
        <p role="alert" className="rounded-xl bg-rose-soft px-4 py-3 text-sm text-rose">
          {error}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-full bg-accent px-5 py-2.5 font-medium text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-70"
        >
          {busy && <Loader2 className="size-4 animate-spin" />}
          {account ? (account.again ? "It's logged in, save it" : "It's signed up, save it") : <>I&apos;m logged in, save it</>}
        </button>
        <button type="button" onClick={cancel} className="inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink">
          <X className="size-4" /> Cancel
        </button>
      </div>
    </div>
  );
}
