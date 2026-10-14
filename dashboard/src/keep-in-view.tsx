"use client";

import { useEffect, useRef } from "react";

/** Put inside something that should be visible when it appears (like a running routine's current step). */
export function KeepInView() {
  const here = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    here.current?.parentElement?.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
  }, []);
  return <span ref={here} hidden />;
}
