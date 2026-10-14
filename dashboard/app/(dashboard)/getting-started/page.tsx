import type { Metadata } from "next";
import { GettingStartedPage } from "../../../src/screens/getting-started";
import { host } from "../../../local/host";

export const metadata: Metadata = { title: "Getting started" };

export default function Page() {
  return <GettingStartedPage host={host} />;
}
