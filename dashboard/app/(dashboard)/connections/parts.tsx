"use client";

import { useActionState, useMemo, useState, useTransition } from "react";
import { Check, ExternalLink, Globe, KeyRound, Scale, Search, Send, Sparkles } from "lucide-react";
import { Poll } from "../../../src/poll";
import { Card, cx, inputClass } from "../../../src/ui";
import {
  cancelClaudeSignIn,
  connectTelegram,
  connectTool,
  disconnectTelegram,
  disconnectTool,
  finishClaudeSignIn,
  newTelegramLink,
  removeJevKey,
  removeSite,
  saveJevKey,
  signOutOfClaude,
  startClaudeSignIn,
  stopAlwaysAllowing,
  type ConnectState,
} from "../../../local/tool-actions";
import type { AiStatus, CatalogItem, TelegramStatus } from "../../../local/tools";

const button =
  "rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-70";
const quietButton = "rounded-full px-3 py-1.5 text-sm text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-70";

export function Catalog({ items }: { items: CatalogItem[] }) {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return items.filter((i) => {
      const text = [i.name, i.description, i.category, ...i.uses].join(" ").toLowerCase();
      return words.every((w) => text.includes(w));
    });
  }, [items, query]);
  const categories = [...new Set(shown.map((i) => i.category))];

  return (
    <div className="space-y-6">
      <label className="relative block">
        <span className="sr-only">Search</span>
        <Search className="pointer-events-none absolute top-1/2 left-4 size-4 -translate-y-1/2 text-ink-3" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="What do you use? Shopify, Gmail, your supplier's site…"
          className={cx(inputClass, "pl-11")}
        />
      </label>
      {categories.map((category) => (
        <div key={category}>
          <h3 className="mb-2 text-sm font-medium text-ink-2">{category}</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {shown
              .filter((i) => i.category === category)
              .map((i) => (
                <ServiceCard key={i.id} item={i} />
              ))}
          </div>
        </div>
      ))}
      {shown.length === 0 && query.trim() && <NotListed asked={query.trim()} />}
    </div>
  );
}

/** Nothing in the catalog matches: a website login works for most services, or its MCP server by address. */
function NotListed({ asked }: { asked: string }) {
  const site = /^[\w-]+(\.[\w-]+)+(\/.*)?$/.test(asked) ? `https://${asked.replace(/^https?:\/\//, "")}` : null;
  return (
    <div role="status" className="rounded-3xl border border-dashed border-line p-5 text-sm text-ink-2">
      <p>
        <span className="font-medium text-ink">{asked}</span> isn&apos;t in the list. If it has a website you log in to,
        that works too: you log in once, and your COO uses it from there. Or, if it has an MCP server, add it by its address below.
      </p>
      <a
        href={`/connections/website?${site ? `url=${encodeURIComponent(site)}` : `name=${encodeURIComponent(asked)}`}`}
        className={cx(button, "mt-3 inline-flex items-center gap-2")}
      >
        <Globe className="size-4" /> Use a website login for {asked}
      </a>
    </div>
  );
}

function ServiceCard({ item }: { item: CatalogItem }) {
  const [state, action, pending] = useActionState<ConnectState, FormData>(connectTool, {});
  const [withKey, setWithKey] = useState(item.auth.type === "apikey" && !item.auth.optional);
  return (
    <Card className="flex flex-col p-4">
      <p className="flex items-center gap-2 font-medium">
        {item.name}
        {!item.tested && <span className="rounded-full bg-surface-2 px-2 py-0.5 text-xs font-medium text-ink-3">Beta</span>}
      </p>
      <p className="mt-1 flex-1 text-sm text-ink-2">{item.description}</p>
      {item.uses.length > 0 && <p className="mt-2 text-xs text-ink-3">For: {item.uses.join(" · ").toLowerCase()}</p>}
      <form action={action} className="mt-4 space-y-2">
        <input type="hidden" name="id" value={item.id} />
        {withKey && (
          <>
            <input
              name="key"
              type="password"
              autoComplete="off"
              required={!item.auth.optional}
              placeholder={item.auth.keyLabel ?? "Key"}
              aria-label={item.auth.keyLabel ?? "Key"}
              className={cx(inputClass, "py-2 text-sm")}
            />
            {item.auth.keyHint && <p className="text-xs text-ink-3">{item.auth.keyHint}</p>}
          </>
        )}
        {state.error && (
          <p role="alert" className="text-sm text-rose">
            {state.error}
          </p>
        )}
        {state.connected && <p className="text-sm text-accent">{state.connected} is connected.</p>}
        <div className="flex items-center gap-2">
          <button type="submit" disabled={pending} className={button}>
            {pending ? "Connecting…" : item.auth.type === "apikey" ? "Connect" : "Sign in"}
          </button>
          {item.auth.type === "apikey" && item.auth.optional && !withKey && (
            <button type="button" onClick={() => setWithKey(true)} className={cx(quietButton, "inline-flex items-center gap-1")}>
              <KeyRound className="size-3.5" /> I have a key
            </button>
          )}
        </div>
      </form>
    </Card>
  );
}

export function AddOwn() {
  const [state, action, pending] = useActionState<ConnectState, FormData>(connectTool, {});
  return (
    <Card className="p-5">
      <p className="text-sm text-ink-2">
        Any service with an MCP server can be connected by its address. You&apos;ll find it in the service&apos;s help pages,
        usually under &ldquo;MCP&rdquo; or &ldquo;AI assistants&rdquo;.
      </p>
      <form action={action} className="mt-4 grid gap-3 sm:grid-cols-2">
        <input name="name" required placeholder="Name, like “My CRM”" aria-label="Name" className={inputClass} />
        <input name="url" type="url" required placeholder="https://mcp.example.com/mcp" aria-label="Address" className={inputClass} />
        <input
          name="key"
          type="password"
          autoComplete="off"
          placeholder="Key, if it gave you one (optional)"
          aria-label="Key (optional)"
          className={cx(inputClass, "sm:col-span-2")}
        />
        {state.error && (
          <p role="alert" className="text-sm text-rose sm:col-span-2">
            {state.error}
          </p>
        )}
        {state.connected && <p className="text-sm text-accent sm:col-span-2">{state.connected} is connected.</p>}
        <div className="sm:col-span-2">
          <button type="submit" disabled={pending} className={button}>
            {pending ? "Connecting…" : "Connect"}
          </button>
        </div>
      </form>
    </Card>
  );
}

function useResultAction(run: () => Promise<{ error?: string }>) {
  const [pending, start] = useTransition();
  const [error, setError] = useState<string>();
  return { pending, error, go: () => start(async () => setError((await run()).error)) };
}

export function DisconnectButton({ id, name }: { id: string; name: string }) {
  const { pending, error, go } = useResultAction(() => disconnectTool(id));
  return (
    <div className="text-right">
      <button
        type="button"
        disabled={pending}
        className={quietButton}
        onClick={() => confirm(`Disconnect ${name}? Routines that use it will stop working.`) && go()}
      >
        Disconnect
      </button>
      {error && <p className="text-xs text-rose">{error}</p>}
    </div>
  );
}

export function StopAlwaysButton({ tool }: { tool: string }) {
  const { pending, error, go } = useResultAction(() => stopAlwaysAllowing(tool));
  return (
    <div className="text-right">
      <button type="button" disabled={pending} className={quietButton} onClick={go}>
        Ask me again
      </button>
      {error && <p className="text-xs text-rose">{error}</p>}
    </div>
  );
}

/** The owner's own Telegram bot: paste the token from @BotFather, then open a one-time link. */
export function TelegramCard({ status, cooName }: { status: TelegramStatus; cooName: string }) {
  const [state, action, pending] = useActionState(connectTelegram, {});
  const link = useResultAction(newTelegramLink);
  const off = useResultAction(disconnectTelegram);
  const error = state.error ?? link.error ?? off.error;

  return (
    <Card className="flex gap-4 p-5">
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-sky-soft text-sky">
        {status.linked ? <Check className="size-5" /> : <Send className="size-5" />}
      </span>
      <div className="min-w-0 flex-1 text-sm text-ink-2">
        <p className="font-medium text-ink">Telegram</p>
        {status.linked ? (
          <p className="mt-1">
            Connected to @{status.bot}. Your morning brief, anything urgent and your decisions come there, and you can
            chat with {cooName} anytime.
          </p>
        ) : status.connected ? (
          <>
            <Poll seconds={4} />
            <p className="mt-1">Last step: open Telegram and tap Start. This page notices on its own.</p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              {status.linkUrl ? (
                <a href={status.linkUrl} target="_blank" rel="noreferrer" className={button}>
                  Open @{status.bot} in Telegram
                </a>
              ) : (
                <button type="button" onClick={link.go} disabled={link.pending} className={button}>
                  Make a new link
                </button>
              )}
              <span className="text-xs text-ink-3">The link works once, for 30 minutes.</span>
            </div>
          </>
        ) : (
          <>
            <p className="mt-1">Get your morning brief, anything urgent and your decisions in Telegram, and chat with {cooName} there.</p>
            <ol className="mt-3 list-decimal space-y-1 pl-5">
              <li>
                In Telegram, open{" "}
                <a href="https://t.me/BotFather" target="_blank" rel="noreferrer" className="font-medium text-accent hover:underline">
                  @BotFather
                </a>{" "}
                and send <code className="rounded bg-surface-2 px-1">/newbot</code>.
              </li>
              <li>Give it a name and a username (like “{cooName} for my shop”).</li>
              <li>Paste the token it gives you here.</li>
            </ol>
            <form action={action} className="mt-3 flex flex-wrap gap-2">
              <input
                name="token"
                type="password"
                required
                autoComplete="off"
                placeholder="123456789:AA…"
                aria-label="Bot token"
                className={cx(inputClass, "min-w-0 flex-1 py-2 text-sm")}
              />
              <button type="submit" disabled={pending} className={button}>
                {pending ? "Checking…" : "Connect"}
              </button>
            </form>
          </>
        )}
        {error && (
          <p role="alert" className="mt-2 text-rose">
            {error}
          </p>
        )}
        {status.connected && !status.fromSettings && (
          <button
            type="button"
            disabled={off.pending}
            className={cx(quietButton, "-ml-3 mt-2")}
            onClick={() => confirm("Disconnect Telegram? You'll stop getting messages there.") && off.go()}
          >
            Disconnect
          </button>
        )}
        {status.fromSettings && <p className="mt-2 text-xs text-ink-3">This bot is set in the server&apos;s settings (TELEGRAM_BOT_TOKEN).</p>}
      </div>
    </Card>
  );
}

export function RemoveSiteButton({ site }: { site: string }) {
  const { pending, error, go } = useResultAction(() => removeSite(site));
  return (
    <div className="text-right">
      <button
        type="button"
        disabled={pending}
        className={quietButton}
        onClick={() => confirm(`Remove your login to ${site}? Routines that use it will stop working.`) && go()}
      >
        Remove
      </button>
      {error && <p className="text-xs text-rose">{error}</p>}
    </div>
  );
}

/** The COO's AI: signed in with the owner's Claude account (done here), an API key, or Steerable. */
export function ClaudeCard({ status, cooName }: { status: AiStatus["claude"]; cooName: string }) {
  const start = useResultAction(startClaudeSignIn);
  const cancel = useResultAction(cancelClaudeSignIn);
  const out = useResultAction(signOutOfClaude);
  const [state, finish, finishing] = useActionState(finishClaudeSignIn, {});
  const error = start.error ?? cancel.error ?? out.error ?? state.error;
  const on = status.method !== "none";

  return (
    <Card className={cx("flex gap-4 p-5", !on && !status.signingIn && "border-amber/40")}>
      <span className={cx("grid size-10 shrink-0 place-items-center rounded-full", on ? "bg-accent-soft text-accent" : "bg-amber-soft text-amber")}>
        {on ? <Check className="size-5" /> : <Sparkles className="size-5" />}
      </span>
      <div className="min-w-0 flex-1 text-sm text-ink-2">
        <p className="font-medium text-ink">Claude, {cooName}&apos;s AI</p>
        {status.method === "steerable" ? (
          <p className="mt-1">It comes through Steerable, included in your plan.</p>
        ) : status.method === "key" ? (
          <p className="mt-1">
            {cooName} uses the Anthropic API key in this server&apos;s settings file. To use your Claude account instead,
            remove the key there and restart.
          </p>
        ) : status.method === "account" ? (
          <>
            <p className="mt-1">
              Signed in{status.email ? ` as ${status.email}` : ""}. {cooName} uses your Claude plan, and the connectors you
              add at claude.ai work here too.
            </p>
            <button
              type="button"
              disabled={out.pending}
              onClick={() => confirm(`Sign ${cooName} out? It can't work until it's signed in again.`) && out.go()}
              className={cx(quietButton, "mt-2 -ml-3")}
            >
              Sign out
            </button>
          </>
        ) : status.signingIn && status.url ? (
          <>
            <ol className="mt-2 list-decimal space-y-2 pl-5">
              <li>
                <a href={status.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                  Open Claude&apos;s sign-in <ExternalLink className="size-3.5" />
                </a>{" "}
                and sign in with your Claude account.
              </li>
              <li>Claude then shows you a code. Copy it and paste it here.</li>
            </ol>
            <form action={finish} className="mt-3 flex flex-wrap gap-2">
              <input
                name="code"
                required
                autoComplete="off"
                spellCheck={false}
                placeholder="Paste the code"
                aria-label="Code from Claude"
                className={cx(inputClass, "min-w-0 flex-1 py-2 font-mono text-sm")}
              />
              <button type="submit" disabled={finishing} className={button}>
                {finishing ? "Signing in…" : "Finish"}
              </button>
              <button type="button" onClick={cancel.go} disabled={cancel.pending || finishing} className={quietButton}>
                Cancel
              </button>
            </form>
            <p className="mt-2 text-xs text-ink-3">The sign-in waits 10 minutes for the code.</p>
          </>
        ) : (
          <>
            <p className="mt-1">
              {cooName} needs AI to work. Sign it in with your Claude account (a Pro or Max plan), and it uses that, with
              nothing else to pay for.
            </p>
            <button type="button" onClick={start.go} disabled={start.pending} className={cx(button, "mt-3")}>
              {start.pending ? "Starting…" : "Sign in with Claude"}
            </button>
          </>
        )}
        {error && <p className="mt-2 text-sm text-rose">{error}</p>}
      </div>
    </Card>
  );
}

/** Jev: cheaper everyday decisions, with the owner's own key (or through Steerable). */
export function JevCard({ status, cooName, throughSteerable }: { status: AiStatus["jev"]; cooName: string; throughSteerable: boolean }) {
  const [state, save, saving] = useActionState(saveJevKey, {});
  const off = useResultAction(removeJevKey);
  const error = state.error ?? off.error;

  return (
    <Card className="flex gap-4 p-5">
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-violet-soft text-violet">
        {status.on ? <Check className="size-5" /> : <Scale className="size-5" />}
      </span>
      <div className="min-w-0 flex-1 text-sm text-ink-2">
        <p className="font-medium text-ink">Jev, for everyday decisions</p>
        {status.ownKey ? (
          <>
            <p className="mt-1">
              On. {cooName} makes its small yes-or-no calls (is this email a lead, does this need you) with Jev, for a
              fraction of what Claude costs.
            </p>
            {status.fromSettings ? (
              <p className="mt-1 text-xs text-ink-3">Its key is in this server&apos;s settings file.</p>
            ) : (
              <button type="button" onClick={off.go} disabled={off.pending} className={cx(quietButton, "mt-2 -ml-3")}>
                Turn off
              </button>
            )}
          </>
        ) : throughSteerable ? (
          <p className="mt-1">On, through Steerable, included in your plan.</p>
        ) : (
          <>
            <p className="mt-1">
              {cooName} makes many small decisions a day (is this email a lead, does this need you). Jev answers them for a
              fraction of what Claude costs. Get a key from{" "}
              <a href="https://typesafe.ai" target="_blank" rel="noreferrer" className="font-medium text-accent hover:underline">
                TypeSafe
              </a>{" "}
              and paste it here.
            </p>
            <form action={save} className="mt-3 flex flex-wrap gap-2">
              <input
                name="key"
                type="password"
                required
                autoComplete="off"
                placeholder="Your Jev key"
                aria-label="Jev key"
                className={cx(inputClass, "min-w-0 flex-1 py-2 text-sm")}
              />
              <button type="submit" disabled={saving} className={button}>
                {saving ? "Checking…" : "Turn on"}
              </button>
            </form>
          </>
        )}
        {error && <p className="mt-2 text-sm text-rose">{error}</p>}
      </div>
    </Card>
  );
}
