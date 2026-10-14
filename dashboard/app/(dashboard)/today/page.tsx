import type { Metadata } from "next";
import { TodayPage } from "../../../src/screens/today";
import { host } from "../../../local/host";

export const metadata: Metadata = { title: "Today" };

export default function Page() {
  return <TodayPage host={host} />;
}
