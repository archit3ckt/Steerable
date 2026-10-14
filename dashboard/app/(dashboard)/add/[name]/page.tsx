import type { Metadata } from "next";
import { AddValuePage } from "../../../../src/screens/add-value";
import { host } from "../../../../local/host";

export const metadata: Metadata = { title: "Add it" };

export default function Page({ params }: PageProps<"/add/[name]">) {
  return <AddValuePage host={host} name={params.then((p) => p.name)} />;
}
