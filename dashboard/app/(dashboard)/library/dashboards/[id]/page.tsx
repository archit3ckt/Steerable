import type { Metadata } from "next";
import { LibraryDashboardPage } from "../../../../../src/screens/library";
import { host } from "../../../../../local/host";

export const metadata: Metadata = { title: "Dashboard" };

export default function Page({ params }: PageProps<"/library/dashboards/[id]">) {
  return <LibraryDashboardPage host={host} id={params.then((p) => p.id)} />;
}
