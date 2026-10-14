import { Suspense, type ReactNode } from "react";
import Form from "next/form";
import Link from "next/link";
import { ArrowLeft, Paperclip, Search } from "lucide-react";
import type { DashboardHost } from "../host";
import type { ChatMessage } from "../backend/types";
import { Chat } from "../chat";
import { clock, dayLabel } from "../format";
import { Card, PageHeader, Skeleton, cx, inputClass } from "../ui";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/**
 * The conversation: its latest messages, earlier ones as the owner scrolls up, or, with ?at=<id>,
 * the stretch around one message (a search result). With ?q=, the matches in its whole history.
 */
export function ChatPage({ host, searchParams }: { host: DashboardHost; searchParams?: SearchParams }) {
  return (
    <div className="mx-auto max-w-3xl">
      <Suspense fallback={<Skeleton className="h-[60vh]" />}>
        <Conversation host={host} searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

async function Conversation({ host, searchParams }: { host: DashboardHost; searchParams?: SearchParams }) {
  const params = await searchParams;
  const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);
  const q = one(params?.q)?.trim().slice(0, 200) ?? "";
  const at = one(params?.at)?.match(/^[\w-]{1,40}$/)?.[0];
  const backend = await host.backend();
  const [{ company }, found, page, now] = await Promise.all([
    backend.overview(),
    q ? backend.searchChat(q) : null,
    q ? null : backend.chatPage(at ? { around: at, limit: 40 } : { limit: 50 }),
    host.now(),
  ]);
  return (
    <>
      <PageHeader
        title={`Talk to ${company.cooName}`}
        subtitle={q ? undefined : "Ask anything about the business, or tell your COO what to do. Plain words are fine."}
      >
        <SearchBox q={q} />
      </PageHeader>
      {found ? (
        <Results q={q} found={found} cooName={company.cooName} now={now} filesUrl={host.chatFilesUrl} />
      ) : (
        <Chat
          key={at ?? "latest"}
          messages={page?.messages ?? []}
          hasEarlier={page?.hasEarlier}
          hasLater={page?.hasLater}
          focusId={page?.reset ? undefined : at}
          pageUrl={host.chatPageUrl}
          now={now}
          sendMessage={host.actions.sendMessage}
          newConversation={host.actions.newConversation}
          activityUrl={host.chatActivityUrl}
          filesUrl={host.chatFilesUrl}
          cooName={company.cooName}
        />
      )}
    </>
  );
}

function SearchBox({ q }: { q: string }) {
  return (
    <Form action="/chat" role="search" className="relative w-full sm:w-64">
      <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-ink-3" aria-hidden />
      <input
        name="q"
        type="search"
        defaultValue={q}
        placeholder="Search the conversation"
        aria-label="Search the conversation"
        maxLength={200}
        className={cx(inputClass, "py-2 pl-10 text-sm")}
      />
    </Form>
  );
}

function Results({ q, found, cooName, now, filesUrl }: { q: string; found: ChatMessage[]; cooName: string; now: number; filesUrl?: string }) {
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  return (
    <section aria-label="Search results">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="text-ink-2" role="status">
          {found.length === 0
            ? `Nothing in your conversation with ${cooName} matches “${q}”.`
            : `${found.length === 50 ? "The 50 newest" : found.length} message${found.length === 1 ? "" : "s"} with “${q}”, newest first. Tap one to see it in the conversation.`}
        </p>
        <Link href="/chat" className="inline-flex items-center gap-1.5 font-medium text-accent hover:underline">
          <ArrowLeft className="size-4" /> Back to the conversation
        </Link>
      </div>
      <ol className="space-y-3">
        {found.map((m) => (
          <li key={m.id}>
            <Card className="relative p-4 transition-colors hover:border-accent sm:p-5">
              {/* The whole card opens the conversation at this message; file links sit above it. */}
              <Link
                href={`/chat?at=${m.id}`}
                className="absolute inset-0 rounded-2xl"
                aria-label={`Show in the conversation: ${m.from === "you" ? "you" : cooName}, ${dayLabel(m.at, now)}`}
              />
              <p className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <span className={cx("font-medium", m.from === "you" ? "text-accent" : "text-ink")}>{m.from === "you" ? "You" : cooName}</span>
                <span className="text-xs text-ink-3">
                  {dayLabel(m.at, now)} · {clock(m.at)}
                </span>
              </p>
              {m.text && <p className="mt-2 leading-relaxed break-words whitespace-pre-line text-ink-2">{highlight(snippet(m.text, words), words)}</p>}
              {m.files && m.files.length > 0 && (
                <ul className="relative mt-2 flex flex-wrap gap-2 text-sm">
                  {m.files.map((f) => (
                    <li key={f.id}>
                      {filesUrl ? (
                        <a
                          href={`${filesUrl}/${f.id}`}
                          target={f.kind === "image" ? "_blank" : undefined}
                          rel="noreferrer"
                          className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1 hover:border-accent"
                        >
                          <Paperclip className="size-3.5 text-ink-3" /> {highlight(f.name, words)}
                        </a>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1">
                          <Paperclip className="size-3.5 text-ink-3" /> {f.name}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </li>
        ))}
      </ol>
    </section>
  );
}

const SNIPPET = 320;

/** Plain text around the first match, so a long message shows the part that matched. */
function snippet(text: string, words: string[]): string {
  const plain = text.replace(/[*_`#>]+/g, "").replace(/\n{3,}/g, "\n\n").trim();
  if (plain.length <= SNIPPET) return plain;
  const at = Math.min(...words.map((w) => plain.toLowerCase().indexOf(w)).filter((i) => i >= 0), plain.length);
  const start = Math.max(0, Math.min(at - 80, plain.length - SNIPPET));
  return `${start > 0 ? "…" : ""}${plain.slice(start, start + SNIPPET).trim()}${start + SNIPPET < plain.length ? "…" : ""}`;
}

function highlight(text: string, words: string[]): ReactNode[] {
  const pattern = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return text.split(pattern).map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} className="rounded bg-amber-soft px-0.5 text-ink">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}
