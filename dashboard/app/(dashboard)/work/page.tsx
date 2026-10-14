import type { Metadata } from "next";
import { WorkPage } from "../../../src/screens/work";
import { host } from "../../../local/host";

export const metadata: Metadata = { title: "Work" };

export default function Page() {
  return <WorkPage host={host} />;
}
