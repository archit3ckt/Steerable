import type { Metadata } from "next";
import { LibraryPage } from "../../../src/screens/library";
import { host } from "../../../local/host";

export const metadata: Metadata = { title: "Library" };

export default function Page({ searchParams }: PageProps<"/library">) {
  return <LibraryPage host={host} searchParams={searchParams} />;
}
