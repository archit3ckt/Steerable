"use client";

import { useState, useTransition } from "react";
import { Check, Download, Puzzle } from "lucide-react";
import { Poll } from "./poll";
import { Card } from "./ui";

const button =
  "rounded-full bg-accent px-4 py-2 text-sm font-medium text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-70";
const quietButton = "rounded-full px-3 py-1.5 text-sm text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink disabled:opacity-70";

/** Whether a browser is paired through the extension (extension/). */
export type ExtensionStatus = { paired: boolean; pairedAt: string | null; browser: string | null };

/**
 * A login from the owner's own browser, through the Steerable extension: for sites that won't let
 * an automated browser log in (a "Sign in with Google" button, a check for a human every time).
 */
export function ExtensionCard({
  status,
  cooName,
  newCode,
  unpair,
  downloadUrl = "/extension.zip",
}: {
  status: ExtensionStatus;
  cooName: string;
  /** The host's Server Actions: a one-time pairing code, and unpairing. */
  newCode: () => Promise<{ error?: string; code?: string; minutes?: number }>;
  unpair: () => Promise<{ error?: string }>;
  /** Where the host serves extensionZipResponse() (./extension-zip). */
  downloadUrl?: string;
}) {
  const [pending, start] = useTransition();
  const [code, setCode] = useState<{ code: string; minutes: number }>();
  const [error, setError] = useState<string>();

  return (
    <Card className="flex gap-4 p-5">
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-violet-soft text-violet">
        {status.paired ? <Check className="size-5" /> : <Puzzle className="size-5" />}
      </span>
      <div className="min-w-0 flex-1 text-sm text-ink-2">
        <p className="font-medium text-ink">Use a login from your own browser</p>
        {status.paired ? (
          <p className="mt-1">
            Paired with {status.browser || "your browser"}. Open a site there, log in as usual, click the Steerable button and
            choose &ldquo;Let {cooName} use my login here&rdquo;. It stays in step from then on. Switch it on only for sites
            whose terms allow it: what {cooName} does there is done as you, and is your responsibility.
          </p>
        ) : (
          <>
            <p className="mt-1">
              For sites that won&apos;t let {cooName} log in here, like ones with &ldquo;Sign in with Google&rdquo;: you log in
              in your own browser (Chrome or Firefox), as always, and a small extension hands {cooName} that one site&apos;s
              login and keeps it fresh.
            </p>
            <ol className="mt-3 list-decimal space-y-1 pl-5">
              <li>
                <a href={downloadUrl} className="inline-flex items-center gap-1 font-medium text-accent hover:underline">
                  <Download className="size-3.5" /> Download the extension
                </a>{" "}
                and unzip it.
              </li>
              <li>
                In Chrome, open <code className="rounded bg-surface-2 px-1">chrome://extensions</code>, turn on Developer mode,
                choose &ldquo;Load unpacked&rdquo; and pick the folder.
              </li>
              <li>Make a pairing code here, click the Steerable button in your browser, and type it in with this page&apos;s address.</li>
            </ol>
            <details className="mt-2">
              <summary className="cursor-pointer text-ink-3 hover:text-ink">Using Firefox?</summary>
              <p className="mt-1">
                Open <code className="rounded bg-surface-2 px-1">about:debugging</code>, choose &ldquo;This Firefox&rdquo;, then
                &ldquo;Load Temporary Add-on&rdquo; and pick <code className="rounded bg-surface-2 px-1">manifest.json</code> in the
                unzipped folder. Firefox forgets add-ons loaded this way when it restarts, so you&apos;d load and pair it again;
                to keep it, the extension has to be signed by Mozilla, or you can use Firefox Developer Edition.
              </p>
            </details>
          </>
        )}
        {code && !status.paired && (
          <>
            <Poll seconds={4} />
            <p className="mt-3 rounded-xl bg-surface-2 px-4 py-3">
              Your code: <strong className="font-mono text-base tracking-wider text-ink">{code.code}</strong>
              <span className="block text-xs text-ink-3">Works once, for {code.minutes} minutes. This page notices when it&apos;s paired.</span>
            </p>
          </>
        )}
        {error && (
          <p role="alert" className="mt-2 text-rose">
            {error}
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={pending}
            className={status.paired ? quietButton : button}
            onClick={() =>
              start(async () => {
                const result = await newCode();
                setError(result.error);
                if (result.code) setCode({ code: result.code, minutes: result.minutes ?? 10 });
              })
            }
          >
            {status.paired ? "Pair another browser instead" : code ? "Make a new code" : "Make a pairing code"}
          </button>
          {status.paired && (
            <button
              type="button"
              disabled={pending}
              className={quietButton}
              onClick={() =>
                confirm("Unpair your browser? Logins it already handed over stay until you remove them, but stop being kept fresh.") &&
                start(async () => setError((await unpair()).error))
              }
            >
              Unpair
            </button>
          )}
        </div>
      </div>
    </Card>
  );
}
