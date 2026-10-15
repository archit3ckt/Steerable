"use client";

import { Fragment, useCallback, useEffect, useLayoutEffect, useOptimistic, useRef, useState, useTransition, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { ArrowDown, ArrowUp, Check, ChevronRight, FileText, Loader2, MessageSquarePlus, Paperclip, X } from "lucide-react";
import type { ChatActivity, ChatFile, ChatMessage, ChatPage, ChatStep } from "./backend/types";
import { dayLabel } from "./format";
import type { DashboardActions } from "./host";
import { ChatArtifacts } from "./chat-artifacts";
import { CopyButton } from "./copy-button";
import { Markdown } from "./markdown";
import { CooAvatar, cx } from "./ui";

const SUGGESTIONS = ["How are we doing this month?", "What should I focus on this week?", "Pause all customer emails"];
const MAX_BYTES = 20 * 1024 * 1024;
const MAX_FILES = 10;
const MAX_CHARS = 20_000; // the engine's limit for one message
const ACCEPT = "image/png,image/jpeg,image/gif,image/webp,.pdf,.txt,.md,.csv,.json,.docx,.xlsx,.pptx";

const PAGE = 50;

/** Messages by id, oldest first: pages and new messages join without repeats. */
function merge(list: ChatMessage[], more: ChatMessage[]): ChatMessage[] {
  const byId = new Map(list.map((m) => [m.id, m]));
  for (const m of more) byId.set(m.id, m);
  return [...byId.values()].sort((a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : 0));
}

/** A file in the message box: uploading, ready to send, or refused. */
type Attachment = { key: string; name: string; size: number; preview?: string; file?: ChatFile; error?: string };

export function Chat({
  messages,
  hasEarlier = false,
  hasLater = false,
  pageUrl,
  focusId,
  now,
  cooName,
  suggestions = SUGGESTIONS,
  expectingReply = false,
  sendMessage,
  newConversation,
  activityUrl,
  filesUrl,
  plansUrl,
  changesUrl,
}: {
  /** The first page: the latest messages, or those around focusId. */
  messages: ChatMessage[];
  hasEarlier?: boolean;
  hasLater?: boolean;
  /** The host's chatPageUrl: load earlier messages on scrolling up, and new ones without a reload. */
  pageUrl?: string;
  /** A message to show and highlight (a search result), with the conversation around it. */
  focusId?: string;
  /** The request's time, for the day separators ("Today", "Yesterday", …). */
  now?: number;
  sendMessage: DashboardActions["sendMessage"];
  cooName: string;
  suggestions?: string[];
  /** The COO is about to write first (e.g. opening onboarding), so show it typing. */
  expectingReply?: boolean;
  /** Offers "New conversation": a fresh start for the COO, with the history kept above a divider. */
  newConversation?: DashboardActions["newConversation"];
  /** The host's chatActivityUrl: while the COO works, show what it's doing. */
  activityUrl?: string;
  /** The host's chatFilesUrl: attach pictures and files (and show the ones sent). */
  filesUrl?: string;
  /** The host's plansUrl and runChangesUrl: what a reply made in the library opens from under it. */
  plansUrl?: string;
  changesUrl?: string;
}) {
  const [list, setList] = useState(messages);
  const [earlier, setEarlier] = useState(hasEarlier);
  const [later, setLater] = useState(hasLater); // showing an older stretch (a search result), not the latest
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const [animateAfter] = useState(() => messages.at(-1)?.at ?? ""); // only messages that arrive now slide in
  const anchor = useRef<{ id: string; top: number } | null>(null); // the message on screen while earlier ones load
  const top = useRef<HTMLLIElement>(null);
  const thread = useRef<HTMLOListElement>(null);
  // What to keep in view as things render and pictures load: the newest messages, a found
  // message, or nothing once the reader scrolls themselves.
  const follow = useRef(!focusId);
  const pinned = useRef(focusId ?? null);

  // The server's copy changes after sending (refresh): take what's new, unless we're looking at an older stretch.
  const [fromServer, setFromServer] = useState(messages);
  if (messages !== fromServer) {
    setFromServer(messages);
    if (!later) setList((l) => merge(l, messages));
  }

  const [optimistic, addOptimistic] = useOptimistic(list, (list, sent: { text: string; files: ChatFile[] }) => [
    ...list,
    { id: `pending-${list.length}`, from: "you" as const, text: sent.text, at: "", ...(sent.files.length ? { files: sent.files } : {}) },
  ]);
  const [attached, setAttached] = useState<Attachment[]>([]);
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);

  const uploading = attached.some((a) => !a.file && !a.error);
  const ready = attached.filter((a) => a.file);
  const [pending, startTransition] = useTransition();
  const [starting, startFresh] = useTransition(); // its own, so a fresh start doesn't look like the COO typing
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  // The message box grows with what's written, up to half the screen, then scrolls.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, Math.round(window.innerHeight * 0.5))}px`;
  }, [draft]);
  const end = useRef<HTMLDivElement>(null);
  const router = useRouter();
  // A real COO can take a while to answer. Until the last message is theirs, check back.
  const waiting = !pending && !later && (expectingReply || list.at(-1)?.from === "you");
  const typing = pending || waiting;

  // To the very bottom of the page, so the newest message sits above the message box, not under it.
  const toEnd = useCallback((smooth = true) => {
    follow.current = true;
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: smooth ? "smooth" : "instant" });
  }, []);

  const fetchPage = useCallback(
    async (query: Record<string, string>): Promise<ChatPage | null> => {
      if (!pageUrl) return null;
      const res = await fetch(`${pageUrl}?${new URLSearchParams({ limit: String(PAGE), ...query })}`, { cache: "no-store" }).catch(() => null);
      return res?.ok ? ((await res.json()) as ChatPage) : null;
    },
    [pageUrl],
  );

  // Open at the bottom, or at the message asked for (highlighted).
  useLayoutEffect(() => {
    const target = focusId && document.getElementById(`m-${focusId}`);
    if (target) target.scrollIntoView({ block: "center" });
    else toEnd(false);
  }, [focusId, toEnd]);

  // Where the reader is: near the newest messages, new ones scroll in; otherwise a button offers them.
  useEffect(() => {
    const onScroll = () => {
      const left = document.documentElement.scrollHeight - (window.scrollY + window.innerHeight);
      follow.current = left < 150;
      setAtBottom(left < 300);
    };
    const byHand = () => (pinned.current = null); // the reader moves: stop holding a found message in view
    window.addEventListener("scroll", onScroll, { passive: true });
    for (const e of ["wheel", "touchstart", "keydown"]) window.addEventListener(e, byHand, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      for (const e of ["wheel", "touchstart", "keydown"]) window.removeEventListener(e, byHand);
    };
  }, []);

  // As messages render and pictures load, keep the newest (or the found message) where it was.
  useEffect(() => {
    const el = thread.current;
    if (!el) return;
    const keep = new ResizeObserver(() => {
      const found = pinned.current && document.getElementById(`m-${pinned.current}`);
      if (found) found.scrollIntoView({ block: "center", behavior: "instant" });
      else if (follow.current && !anchor.current) window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "instant" });
    });
    keep.observe(el);
    return () => keep.disconnect();
  }, []);

  const lastId = optimistic.at(-1)?.id;
  useEffect(() => {
    if (follow.current) toEnd();
    // Only when something arrives, not when the reader scrolls away.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastId, typing]);

  // Scrolled up to the top: the page before, keeping the reader's place.
  const loadEarlier = useCallback(async () => {
    const first = list[0]?.id;
    if (!first || loadingEarlier || !earlier) return;
    setLoadingEarlier(true);
    const page = await fetchPage({ before: first });
    if (page && !page.reset) {
      // Remember the first message on screen and where it is, to put it back there after.
      const onScreen = [...document.querySelectorAll<HTMLElement>("li[id^='m-']")].find((li) => li.getBoundingClientRect().bottom > 0);
      if (onScreen) anchor.current = { id: onScreen.id, top: onScreen.getBoundingClientRect().top };
      setList((l) => merge(page.messages, l));
      setEarlier(page.hasEarlier);
    } else if (!page) {
      setEarlier(false); // no page route, or the engine is away: stop asking
    }
    setLoadingEarlier(false);
  }, [list, loadingEarlier, earlier, fetchPage]);

  useLayoutEffect(() => {
    if (!anchor.current) return;
    const { id, top: was } = anchor.current;
    anchor.current = null;
    const el = document.getElementById(id);
    if (el) window.scrollBy({ top: el.getBoundingClientRect().top - was, behavior: "instant" });
  }, [list]);

  useEffect(() => {
    const el = top.current;
    if (!el || !earlier) return;
    const seen = new IntersectionObserver(([entry]) => entry.isIntersecting && void loadEarlier(), { rootMargin: "600px 0px 0px 0px" });
    seen.observe(el);
    return () => seen.disconnect();
  }, [earlier, loadEarlier]);

  // Back to the latest messages, from an older stretch.
  const toLatest = useCallback(async () => {
    const page = await fetchPage({});
    if (page) {
      setList(page.messages);
      setEarlier(page.hasEarlier);
    }
    setLater(false);
    pinned.current = null;
    if (location.search.includes("at=")) history.replaceState(null, "", location.pathname); // a reload shows the latest too
    requestAnimationFrame(() => toEnd(false));
  }, [fetchPage, toEnd]);

  // Waiting for a reply: ask only for what's new (or reload the page, without a page route).
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(async () => {
      if (!pageUrl) return router.refresh();
      const last = list.at(-1)?.id;
      const page = await fetchPage(last ? { after: last } : {});
      if (!page) return;
      setList((l) => (page.reset ? page.messages : merge(l, page.messages)));
    }, 4000);
    return () => clearInterval(timer);
  }, [waiting, router, pageUrl, list, fetchPage]);

  function attach(list: FileList | File[]) {
    if (!filesUrl) return;
    const room = MAX_FILES - attached.length;
    for (const f of Array.from(list).slice(0, Math.max(0, room))) {
      const key = `${f.name}-${f.size}-${Math.random()}`;
      const preview = f.type.startsWith("image/") ? URL.createObjectURL(f) : undefined;
      const tooBig = f.size > MAX_BYTES ? "Too big: files up to 20 MB." : undefined;
      setAttached((a) => [...a, { key, name: f.name || "pasted.png", size: f.size, preview, error: tooBig }]);
      if (tooBig) continue;
      const done = (patch: Partial<Attachment>) => setAttached((a) => a.map((x) => (x.key === key ? { ...x, ...patch } : x)));
      fetch(`${filesUrl}?name=${encodeURIComponent(f.name || "pasted.png")}`, { method: "POST", body: f })
        .then(async (r) => {
          const body = await r.json().catch(() => null);
          if (r.ok && body?.id) done({ file: body as ChatFile });
          else done({ error: typeof body?.error === "string" ? body.error : "It didn't upload. Try again." });
        })
        .catch(() => done({ error: "It didn't upload. Try again." }));
    }
  }

  function unattach(key: string) {
    setAttached((a) => {
      const gone = a.find((x) => x.key === key);
      if (gone?.preview) URL.revokeObjectURL(gone.preview);
      return a.filter((x) => x.key !== key);
    });
  }

  function send(text: string, withFiles = true) {
    const t = text.trim();
    const files = withFiles ? ready.map((a) => a.file!) : [];
    if ((!t && files.length === 0) || typing || (withFiles && uploading) || t.length > MAX_CHARS) return;
    const kept = attached;
    setDraft("");
    setError(null);
    if (withFiles) setAttached([]);
    startTransition(async () => {
      if (later) await toLatest(); // writing from an older stretch: the reply belongs at the end
      addOptimistic({ text: t, files });
      const result = await sendMessage(t, files.map((f) => f.id));
      if (result.error) {
        setError(result.error);
        setDraft(t);
        if (withFiles) setAttached(kept);
      } else if (withFiles) {
        kept.forEach((a) => a.preview && URL.revokeObjectURL(a.preview));
      }
    });
  }

  return (
    <div className="flex min-h-[60vh] flex-col">
      <ol ref={thread} className="flex-1 space-y-5">
        {pageUrl && optimistic.length > 0 && (
          <li ref={top} className="flex justify-center py-2 text-xs text-ink-3">
            {earlier ? (
              <span className="inline-flex items-center gap-2">
                <Loader2 className={cx("size-3.5", loadingEarlier && "animate-spin")} aria-hidden /> Earlier messages
              </span>
            ) : (
              "The start of your conversation"
            )}
          </li>
        )}
        {optimistic.map((m, i) => {
          const day = now && m.at ? dayLabel(m.at, now) : null;
          const newDay = day && day !== (optimistic[i - 1]?.at ? dayLabel(optimistic[i - 1].at, now!) : null);
          return (
          <Fragment key={m.id}>
          {newDay && m.from !== "divider" && (
            <li className="flex justify-center" aria-hidden>
              <span suppressHydrationWarning className="rounded-full bg-surface-2 px-3 py-1 text-xs text-ink-3">{day}</span>
            </li>
          )}
          <li
            id={`m-${m.id}`}
            className={cx(
              "group/msg flex gap-3",
              (!m.at || m.at > animateAfter) && "animate-rise",
              m.from === "you" && "justify-end",
              m.id === focusId && "-mx-3 rounded-2xl bg-amber-soft/60 px-3 py-2",
            )}
          >
            {m.from === "divider" ? (
              <p className="flex w-full items-center gap-3 py-1 text-xs text-ink-3">
                <span className="h-px flex-1 bg-line" />
                <span suppressHydrationWarning>
                  New conversation{m.at ? ` · ${new Date(m.at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}` : ""}
                </span>
                <span className="h-px flex-1 bg-line" />
              </p>
            ) : m.from === "you" ? (
              <div className="flex max-w-[80%] flex-col items-end gap-1.5">
                {m.files && m.files.length > 0 && <SentFiles files={m.files} filesUrl={filesUrl} />}
                {m.text && (
                  <p className="rounded-2xl rounded-br-md bg-accent px-4 py-2.5 leading-relaxed break-words whitespace-pre-line text-accent-ink">
                    {linked(m.text)}
                  </p>
                )}
                {m.text && <CopyButton text={m.text} label="Copy your message" className={REVEAL} />}
              </div>
            ) : (
              <>
                <CooAvatar name={cooName} size="sm" />
                <div className="max-w-[80%] min-w-0">
                  {m.steps && m.steps.length > 0 && <StepsDone steps={m.steps} />}
                  <div className="rounded-2xl rounded-tl-md border border-line bg-surface px-4 py-2.5 leading-relaxed break-words shadow-card">
                    <Markdown text={m.text} />
                  </div>
                  {m.artifacts && <ChatArtifacts artifacts={m.artifacts} plansUrl={plansUrl} changesUrl={changesUrl} />}
                  {m.text && <CopyButton text={m.text} label={`Copy ${cooName}'s message`} className={cx("mt-0.5", REVEAL)} />}
                </div>
              </>
            )}
          </li>
          </Fragment>
          );
        })}
        {typing && (
          <li className="flex gap-3" aria-live="polite">
            <CooAvatar name={cooName} size="sm" />
            {activityUrl ? <Working url={activityUrl} cooName={cooName} onGrow={toEnd} /> : <Dots cooName={cooName} />}
          </li>
        )}
        {error && (
          <li role="alert" className="rounded-2xl bg-rose-soft px-4 py-3 text-sm text-rose">
            {error}
          </li>
        )}
      </ol>

      <div className="sticky bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-20 -mx-2 mt-8 bg-linear-to-b from-transparent to-bg to-[1.5rem] px-2 pt-6 pb-2 lg:bottom-0 lg:pb-6">
        {(!atBottom || later) && optimistic.length > 0 && (
          <button
            type="button"
            onClick={() => (later ? void toLatest() : toEnd())}
            className="absolute -top-6 left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-line bg-surface px-3.5 py-1.5 text-sm text-ink-2 shadow-lift transition-colors hover:text-ink"
          >
            <ArrowDown className="size-4" /> Newest
          </button>
        )}
        {newConversation && !typing && !starting && list.length > 0 && list.at(-1)?.from !== "divider" && (
          <div className="mb-2 flex justify-end">
            <button
              type="button"
              onClick={() =>
                startFresh(async () => {
                  setError((await newConversation()).error ?? null);
                })
              }
              title={`${cooName} starts fresh. It still knows your business, and everything above stays here.`}
              className="inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-sm text-ink-3 transition-colors hover:bg-surface hover:text-ink"
            >
              <MessageSquarePlus className="size-4" /> New conversation
            </button>
          </div>
        )}
        <div className={cx("mb-3 flex flex-wrap gap-2", suggestions.length === 0 && "hidden")}>
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => send(s, false)}
              className="rounded-full border border-line bg-surface px-3.5 py-1.5 text-sm text-ink-2 transition-colors hover:border-accent hover:text-ink"
            >
              {s}
            </button>
          ))}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send(draft);
          }}
          onDragOver={(e) => {
            if (!filesUrl || !e.dataTransfer.types.includes("Files")) return;
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            if (!filesUrl) return;
            e.preventDefault();
            setDragging(false);
            attach(e.dataTransfer.files);
          }}
          className={cx(
            "rounded-3xl border bg-surface p-2 shadow-lift focus-within:border-accent",
            dragging ? "border-accent bg-accent-soft/40" : "border-line",
          )}
        >
          {attached.length > 0 && (
            <ul className="flex flex-wrap gap-2 px-1 pt-1 pb-2" aria-label="Attached">
              {attached.map((a) => (
                <li
                  key={a.key}
                  className={cx(
                    "flex max-w-56 items-center gap-2 rounded-xl border py-1 pr-1 pl-1 text-xs",
                    a.error ? "border-rose/40 bg-rose-soft text-rose" : "border-line bg-surface-2 text-ink-2",
                  )}
                  title={a.error ?? a.name}
                >
                  {a.preview ? (
                    // eslint-disable-next-line @next/next/no-img-element -- a local preview of the owner's own file
                    <img src={a.preview} alt="" className="size-8 shrink-0 rounded-lg object-cover" />
                  ) : (
                    <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-surface">
                      <FileText className="size-4" />
                    </span>
                  )}
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-ink">{a.name}</span>
                    <span className="block truncate">{a.error ?? (a.file ? size(a.size) : "Uploading…")}</span>
                  </span>
                  {!a.file && !a.error ? (
                    <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
                  ) : (
                    <button type="button" onClick={() => unattach(a.key)} aria-label={`Remove ${a.name}`} className="rounded-full p-1 hover:bg-surface">
                      <X className="size-3.5" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          <div className="flex items-end gap-2">
          {filesUrl && (
            <>
              <input
                ref={picker}
                type="file"
                multiple
                accept={ACCEPT}
                className="hidden"
                onChange={(e) => {
                  if (e.target.files) attach(e.target.files);
                  e.target.value = "";
                }}
              />
              <button
                type="button"
                onClick={() => picker.current?.click()}
                disabled={attached.length >= MAX_FILES}
                aria-label="Attach pictures or files"
                title="Attach pictures or files"
                className="grid size-11 shrink-0 place-items-center rounded-full text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-30"
              >
                <Paperclip className="size-5" />
              </button>
            </>
          )}
          <label htmlFor="chat-input" className="sr-only">
            Message {cooName}
          </label>
          <textarea
            id="chat-input"
            ref={box}
            rows={1}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              // On a phone, Enter starts a new line (there's no Shift); the arrow sends.
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && !matchMedia("(pointer: coarse)").matches) {
                e.preventDefault();
                send(draft);
              }
            }}
            onPaste={(e) => {
              if (filesUrl && e.clipboardData.files.length > 0) {
                e.preventDefault();
                attach(e.clipboardData.files);
              }
            }}
            placeholder={`Message ${cooName}…`}
            className="min-h-11 flex-1 resize-none overflow-y-auto bg-transparent px-3 py-2.5 leading-relaxed outline-none! placeholder:text-ink-3"
          />
          <button
            type="submit"
            disabled={(!draft.trim() && ready.length === 0) || typing || uploading || draft.trim().length > MAX_CHARS}
            aria-label="Send"
            className="grid size-11 shrink-0 place-items-center rounded-full bg-accent text-accent-ink transition-opacity disabled:opacity-30"
          >
            <ArrowUp className="size-5" />
          </button>
          </div>
          {draft.length > MAX_CHARS * 0.9 && (
            <p className={cx("px-3 pt-1 text-right text-xs tabular-nums", draft.trim().length > MAX_CHARS ? "text-rose" : "text-ink-3")}>
              {draft.trim().length.toLocaleString()} / {MAX_CHARS.toLocaleString()}
              {draft.trim().length > MAX_CHARS && " · too long for one message: attach it as a file"}
            </p>
          )}
        </form>
      </div>
      {/* Below the message box: scrolling here shows the newest message above it, not under it. */}
      <div ref={end} />
    </div>
  );
}

/** Shown on hover (and keyboard focus); always on touch screens, which have no hover. */
const REVEAL = "opacity-0 group-hover/msg:opacity-100 focus-visible:opacity-100 [@media(hover:none)]:opacity-100";

/** Web addresses in the owner's own words, as links (opened in a new tab). Trailing punctuation stays text. */
const URL_RE = /\b(?:https?:\/\/|www\.)[^\s<>"]+[^\s<>".,:;!?'")\]]/gi;

function linked(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const href = m[0].startsWith("www.") ? `https://${m[0]}` : m[0];
    out.push(
      <a key={at} href={href} target="_blank" rel="noopener noreferrer" className="underline underline-offset-2 break-all hover:opacity-85">
        {m[0]}
      </a>,
    );
    last = at + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function Dots({ cooName }: { cooName: string }) {
  return (
    <p className="flex items-center gap-1 rounded-2xl rounded-tl-md border border-line bg-surface px-4 py-3.5">
      <span className="sr-only">{cooName} is typing</span>
      {[0, 150, 300].map((d) => (
        <span key={d} className="size-1.5 animate-bounce rounded-full bg-ink-3" style={{ animationDelay: `${d}ms` }} />
      ))}
    </p>
  );
}

const SHOWN_STEPS = 6;

/** While the COO works on a reply: each thing it does, as it does it, and for how long. */
function Working({ url, cooName, onGrow }: { url: string; cooName: string; onGrow?: () => void }) {
  const [activity, setActivity] = useState<ChatActivity>({ working: true, steps: [] });
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    let stopped = false;
    async function check() {
      const next = await fetch(url, { cache: "no-store" })
        .then((r) => (r.ok ? (r.json() as Promise<ChatActivity>) : null))
        .catch(() => null);
      if (next && !stopped) setActivity(next);
    }
    void check();
    const poll = setInterval(check, 1500);
    const clock = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => {
      stopped = true;
      clearInterval(poll);
      clearInterval(clock);
    };
  }, [url]);

  const steps = activity.steps;
  // Keep the newest line in view as the list grows, not under the message box.
  useEffect(() => {
    onGrow?.();
  }, [steps.length, onGrow]);
  const hidden = Math.max(0, steps.length - SHOWN_STEPS);
  const current = steps.findLastIndex((s) => typeof s === "string"); // what it's doing now

  return (
    <div className="min-w-0 max-w-[80%] rounded-2xl rounded-tl-md border border-line bg-surface px-4 py-3 text-sm">
      {steps.length > 0 && (
        <ol className="mb-2 space-y-1.5">
          {hidden > 0 && <li className="pl-6 text-ink-3">Earlier steps</li>}
          {steps.slice(hidden).map((step, at) => {
            const i = hidden + at;
            if (typeof step !== "string") return <Remark key={i} say={step.say} recent={i > current - 2} />;
            return i === current ? (
              <li key={i} className="flex animate-rise items-start gap-2 text-ink">
                <span className="mt-1.5 ml-1 size-2 shrink-0 animate-pulse rounded-full bg-accent" aria-hidden />
                <span className="min-w-0 break-words">{step}…</span>
              </li>
            ) : (
              <li key={i} className="flex items-start gap-2 text-ink-3">
                <Check className="mt-0.5 size-4 shrink-0" aria-hidden />
                <span className="min-w-0 break-words">{step}</span>
              </li>
            );
          })}
        </ol>
      )}
      <p className="flex items-center gap-2 text-ink-3">
        <span className="flex gap-1" aria-hidden>
          {[0, 150, 300].map((d) => (
            <span key={d} className="size-1.5 animate-bounce rounded-full bg-ink-3" style={{ animationDelay: `${d}ms` }} />
          ))}
        </span>
        <span>
          {steps.length > 0 ? "Working" : `${cooName} is thinking`}
          {seconds >= 3 && <span className="tabular-nums"> · {seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`}</span>}
        </span>
      </p>
    </div>
  );
}

/** Something the COO said in passing, between the things it did. */
function Remark({ say, recent = false }: { say: string; recent?: boolean }) {
  return <li className={cx("animate-rise break-words pt-1 first:pt-0", recent ? "text-ink" : "text-ink-2")}>{say}</li>;
}

/** What the COO did on the way to a reply, and what it said as it went, folded away under it. */
function StepsDone({ steps }: { steps: ChatStep[] }) {
  const done = steps.filter((s) => typeof s === "string");
  return (
    <details className="group mb-1.5 text-sm text-ink-3">
      <summary className="flex w-fit cursor-pointer list-none items-center gap-1 rounded-full py-0.5 pr-2 hover:text-ink-2 [&::-webkit-details-marker]:hidden">
        <ChevronRight className="size-4 transition-transform group-open:rotate-90" aria-hidden />
        {done.length === 1 ? done[0] : `${done.length} steps`}
      </summary>
      <ol className="mt-1 mb-1 space-y-1 border-l border-line pl-3 ml-2">
        {steps.map((step, i) =>
          typeof step === "string" ? (
            <li key={i} className="flex items-start gap-2">
              <Check className="mt-0.5 size-3.5 shrink-0" aria-hidden />
              <span className="min-w-0 break-words">{step}</span>
            </li>
          ) : (
            <Remark key={i} say={step.say} />
          ),
        )}
      </ol>
    </details>
  );
}

function size(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** Files the owner sent: pictures as thumbnails (tap for the full picture), the rest as downloads. */
function SentFiles({ files, filesUrl }: { files: ChatFile[]; filesUrl?: string }) {
  const images = files.filter((f) => f.kind === "image");
  const others = files.filter((f) => f.kind !== "image");
  return (
    <>
      {images.length > 0 && (
        <div className="flex flex-wrap justify-end gap-1.5">
          {images.map((f) =>
            filesUrl ? (
              <a key={f.id} href={`${filesUrl}/${f.id}`} target="_blank" rel="noreferrer" className="block">
                {/* eslint-disable-next-line @next/next/no-img-element -- the owner's own picture, served by the engine */}
                <img src={`${filesUrl}/${f.id}`} alt={f.name} className="h-auto max-h-48 w-auto max-w-60 rounded-2xl border border-line object-cover sm:max-w-80" />
              </a>
            ) : (
              <span key={f.id} className="rounded-xl bg-surface-2 px-3 py-2 text-sm text-ink-2">{f.name}</span>
            ),
          )}
        </div>
      )}
      {others.map((f) => {
        const chip = (
          <>
            <FileText className="size-4 shrink-0 text-ink-3" />
            <span className="min-w-0 truncate">{f.name}</span>
            <span className="shrink-0 text-xs text-ink-3">{size(f.size)}</span>
          </>
        );
        return filesUrl ? (
          <a key={f.id} href={`${filesUrl}/${f.id}`} className="flex max-w-full items-center gap-2 rounded-2xl border border-line bg-surface px-3 py-2 text-sm text-ink hover:border-accent">
            {chip}
          </a>
        ) : (
          <span key={f.id} className="flex max-w-full items-center gap-2 rounded-2xl border border-line bg-surface px-3 py-2 text-sm text-ink">
            {chip}
          </span>
        );
      })}
    </>
  );
}
