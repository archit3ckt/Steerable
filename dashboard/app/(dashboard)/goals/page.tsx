import type { Metadata } from "next";
import { GoalsPage } from "../../../src/screens/goals";
import { host } from "../../../local/host";

export const metadata: Metadata = { title: "Goals" };

export default function Page() {
  return <GoalsPage host={host} />;
}
