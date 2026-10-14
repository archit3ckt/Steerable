import type { Metadata } from "next";
import { LibraryTablePage } from "../../../../src/screens/library";
import { host } from "../../../../local/host";

export const metadata: Metadata = { title: "Library" };

export default function Page({ params, searchParams }: PageProps<"/library/[id]">) {
  return <LibraryTablePage host={host} id={params.then((p) => p.id)} searchParams={searchParams} />;
}
