import type { Metadata } from "next";
import { DecisionsPage } from "../../../src/screens/decisions";
import { host } from "../../../local/host";

export const metadata: Metadata = { title: "Decisions" };

export default function Page() {
  return <DecisionsPage host={host} />;
}
