import type { Metadata } from "next";
import { ChatPage } from "../../../src/screens/chat";
import { host } from "../../../local/host";

export const metadata: Metadata = { title: "Chat" };

export default function Page({ searchParams }: PageProps<"/chat">) {
  return <ChatPage host={host} searchParams={searchParams} />;
}
