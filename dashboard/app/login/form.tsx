"use client";

import { useActionState } from "react";
import { signIn } from "../../local/login";

export function LoginForm() {
  const [state, action, pending] = useActionState(signIn, {});
  return (
    <form action={action} className="mt-6 space-y-3">
      <label className="block">
        <span className="sr-only">Passphrase</span>
        <input
          name="password"
          type="password"
          required
          autoFocus
          autoComplete="current-password"
          placeholder="Passphrase"
          className="w-full rounded-xl border border-line bg-surface px-4 py-3 shadow-card focus:border-accent focus:outline-none"
        />
      </label>
      {state.error && (
        <p role="alert" className="text-sm text-rose">
          {state.error}
        </p>
      )}
      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-full bg-accent px-5 py-3 font-medium text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-70"
      >
        Sign in
      </button>
    </form>
  );
}
