import type { Metadata } from "next";
import { RoutinePage } from "../../../../src/screens/routine";
import { host } from "../../../../local/host";

export const metadata: Metadata = { title: "Routine" };

export default function Page({ params }: PageProps<"/work/[id]">) {
  return <RoutinePage host={host} id={params.then((p) => p.id)} />;
}
