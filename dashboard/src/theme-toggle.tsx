"use client";

import { useSyncExternalStore } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { THEME_KEY, type Theme } from "./theme";

const NEXT: Record<Theme, Theme> = { auto: "light", light: "dark", dark: "auto" };
const LABEL: Record<Theme, string> = { auto: "Theme: like this device", light: "Theme: light", dark: "Theme: dark" };
const listeners = new Set<() => void>();

function current(): Theme {
  const t = document.documentElement.dataset.theme;
  return t === "light" || t === "dark" ? t : "auto";
}

function choose(theme: Theme) {
  if (theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  try {
    if (theme === "auto") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, theme);
  } catch {}
  listeners.forEach((l) => l());
}

/** One button: like this device → light → dark. */
export function ThemeToggle({ className = "" }: { className?: string }) {
  const theme = useSyncExternalStore(
    (l) => (listeners.add(l), () => listeners.delete(l)),
    current,
    () => "auto" as Theme,
  );
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  return (
    <button
      type="button"
      onClick={() => choose(NEXT[theme])}
      title={`${LABEL[theme]} (click to change)`}
      className={`grid size-8 place-items-center rounded-full text-ink-3 transition-colors hover:bg-surface-2 hover:text-ink ${className}`}
    >
      <Icon className="size-4" />
      <span className="sr-only">{LABEL[theme]}. Change it.</span>
    </button>
  );
}
