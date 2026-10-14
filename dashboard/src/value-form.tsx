"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import type { DashboardActions } from "./host";
import { cx, inputClass } from "./ui";

/** The owner pastes in what the COO asked for. It goes straight to the engine's private store. */
export function ValueForm({ name, label, save }: { name: string; label: string; save: DashboardActions["saveValue"] }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const router = useRouter();
  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        start(async () => {
          const result = await save(name, value);
          if (result.error) return setError(result.error);
          router.push("/decisions");
        });
      }}
    >
      <label className="block">
        <span className="sr-only">{label}</span>
        <input
          type="password"
          autoComplete="off"
          required
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={`Paste ${label} here`}
          className={inputClass}
        />
      </label>
      {error && (
        <p role="alert" className="text-sm text-rose">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={pending || !value.trim()}
        className={cx("rounded-full bg-accent px-5 py-2.5 font-medium text-accent-ink transition-colors hover:bg-accent-hover disabled:opacity-60")}
      >
        {pending ? "Saving…" : "Save"}
      </button>
    </form>
  );
}
