"use client";

import { useActionState, useState, useTransition } from "react";
import { AtSign, Check, Copy, Eye, Mail } from "lucide-react";
import { Card, cx, inputClass } from "../../../src/ui";
import { accountPassword, connectMailbox, disconnectMailbox, removeAccount, setPhone } from "../../../local/tool-actions";
import type { CooAccount, Mailbox } from "../../../local/tools";

const button =
  "rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-70";
const quietButton = "rounded-full px-3 py-1.5 text-sm text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-70";

/** The COO's own mailbox: set up here (self-hosted), or given by Steerable. */
export function MailboxCard({ mailbox, cooName }: { mailbox: Mailbox; cooName: string }) {
  const [state, action, pending] = useActionState(connectMailbox, {});
  const [offPending, startOff] = useTransition();
  const [offError, setOffError] = useState<string>();

  if (mailbox.address) {
    return (
      <Card className="flex items-center gap-4 p-5">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent-soft text-accent">
          <AtSign className="size-5" />
        </span>
        <div className="min-w-0 flex-1 text-sm text-ink-2">
          <p className="font-medium break-all text-ink">{mailbox.address}</p>
          <p>
            {cooName} signs up with this address, and the sign-up screen picks up the codes and links sites send to it.
            {mailbox.provider === "steerable" && " Steerable runs it for you."}
          </p>
          {offError && <p className="text-rose">{offError}</p>}
        </div>
        {mailbox.provider === "own" && (
          <button
            type="button"
            disabled={offPending}
            className={quietButton}
            onClick={() =>
              confirm(`Disconnect ${mailbox.address}? ${cooName} won't get codes there until you connect it again.`) &&
              startOff(async () => setOffError((await disconnectMailbox()).error))
            }
          >
            Disconnect
          </button>
        )}
      </Card>
    );
  }

  return (
    <Card className="flex gap-4 p-5">
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-sky-soft text-sky">
        <Mail className="size-5" />
      </span>
      <div className="min-w-0 flex-1 text-sm text-ink-2">
        <p className="font-medium text-ink">Give {cooName} an email of its own</p>
        <p className="mt-1">
          Make a mailbox for it at your email provider, like {cooName.toLowerCase()}@yourbusiness.com, then enter its details.
          Your provider&apos;s help pages list them under &ldquo;IMAP&rdquo;. If it uses two-step sign-in, make an app password
          for this.
        </p>
        <form action={action} className="mt-4 grid gap-3 sm:grid-cols-2">
          <input name="address" type="email" required placeholder="Its address" aria-label="Its address" className={cx(inputClass, "sm:col-span-2")} />
          <input name="imapHost" required placeholder="Mail server (IMAP), like imap.fastmail.com" aria-label="Mail server (IMAP)" className={inputClass} />
          <input name="imapPort" inputMode="numeric" placeholder="Port (993)" aria-label="Port" className={inputClass} />
          <input name="user" placeholder="Username, if not the address" aria-label="Username" className={inputClass} />
          <input name="password" type="password" required autoComplete="off" placeholder="Password or app password" aria-label="Password" className={inputClass} />
          {state.error && (
            <p role="alert" className="text-rose sm:col-span-2">
              {state.error}
            </p>
          )}
          <div className="sm:col-span-2">
            <button type="submit" disabled={pending} className={button}>
              {pending ? "Checking…" : "Connect"}
            </button>
          </div>
        </form>
        <p className="mt-3 text-xs text-ink-3">Its password stays on your server, where no AI can read it.</p>
      </div>
    </Card>
  );
}

export function PhoneForm({ phone }: { phone: string }) {
  const [state, action, pending] = useActionState(setPhone, {});
  return (
    <form action={action} className="mt-4 flex flex-wrap items-center gap-2">
      <input
        name="phone"
        type="tel"
        defaultValue={phone}
        placeholder="+44 7700 900123"
        aria-label="Your phone number"
        className={cx(inputClass, "max-w-xs min-w-0 flex-1 py-2 text-sm")}
      />
      <button type="submit" disabled={pending} className={button}>
        {pending ? "Saving…" : "Save"}
      </button>
      {state.saved && (
        <span className="inline-flex items-center gap-1 text-sm text-accent">
          <Check className="size-4" /> Saved
        </span>
      )}
      {state.error && (
        <p role="alert" className="w-full text-sm text-rose">
          {state.error}
        </p>
      )}
    </form>
  );
}

export function AccountActions({ site, name, status }: { site: string; name: string; status: CooAccount["status"] }) {
  const [pending, start] = useTransition();
  const [password, setPassword] = useState<string>();
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string>();

  return (
    <div className="flex flex-col items-end gap-1 text-right">
      <div className="flex flex-wrap justify-end gap-1">
        {status === "ACTIVE" && (
          <a href={`/accounts/signup?site=${encodeURIComponent(site)}&again=1`} className={quietButton}>
            Log in again
          </a>
        )}
        {status !== "PROPOSED" && !password && (
          <button
            type="button"
            disabled={pending}
            className={cx(quietButton, "inline-flex items-center gap-1")}
            onClick={() =>
              start(async () => {
                const result = await accountPassword(site);
                setError(result.error);
                setPassword(result.password);
              })
            }
          >
            <Eye className="size-3.5" /> Password
          </button>
        )}
        <button
          type="button"
          disabled={pending}
          className={quietButton}
          onClick={() =>
            confirm(`Forget ${name} here? The account still exists on ${site}: close it there if you don't need it.`) &&
            start(async () => setError((await removeAccount(site)).error))
          }
        >
          Remove
        </button>
      </div>
      {password && (
        <span className="inline-flex items-center gap-2 rounded-lg bg-surface-2 px-2 py-1">
          <code className="font-mono text-sm break-all">{password}</code>
          <button
            type="button"
            aria-label="Copy the password"
            className="text-ink-3 hover:text-ink"
            onClick={() => {
              void navigator.clipboard.writeText(password).then(() => setCopied(true));
            }}
          >
            {copied ? <Check className="size-4" /> : <Copy className="size-4" />}
          </button>
        </span>
      )}
      {error && <p className="text-xs text-rose">{error}</p>}
    </div>
  );
}
