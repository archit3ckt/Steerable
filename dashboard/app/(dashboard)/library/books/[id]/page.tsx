import type { Metadata } from "next";
import { LibraryBookPage } from "../../../../../src/screens/library";
import { host } from "../../../../../local/host";

export const metadata: Metadata = { title: "Book" };

export default function Page({ params, searchParams }: PageProps<"/library/books/[id]">) {
  return <LibraryBookPage host={host} id={params.then((p) => p.id)} searchParams={searchParams} />;
}
