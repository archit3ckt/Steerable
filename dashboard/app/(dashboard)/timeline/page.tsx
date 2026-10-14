import type { Metadata } from "next";
import { TimelinePage } from "../../../src/screens/timeline";
import { host } from "../../../local/host";

export const metadata: Metadata = { title: "Timeline" };

export default function Page() {
  return <TimelinePage host={host} />;
}
