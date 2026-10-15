import type { Metadata } from "next";
import { LibraryPlanPage } from "../../../../../src/screens/library";
import { host } from "../../../../../local/host";

export const metadata: Metadata = { title: "Plan" };

export default function Page({ params, searchParams }: PageProps<"/library/plans/[id]">) {
  return <LibraryPlanPage host={host} id={params.then((p) => p.id)} searchParams={searchParams} />;
}
