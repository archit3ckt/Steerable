"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import type { DashboardActions } from "./host";

/** Asks the COO to open the onboarding conversation, once, when the page first loads. */
export function OnboardingKickoff({ start }: { start: DashboardActions["startOnboarding"] }) {
  const router = useRouter();
  const sent = useRef(false);
  useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    start().then(() => router.refresh());
  }, [router, start]);
  return null;
}
