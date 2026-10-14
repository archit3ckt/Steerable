import type { Metadata } from "next";
import { Wordmark } from "../../src/logo";
import { LoginForm } from "./form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <main id="main" className="grid min-h-dvh place-items-center px-4">
      <div className="w-full max-w-sm">
        <h1>
          <Wordmark className="text-3xl" />
        </h1>
        <p className="mt-2 text-ink-2">Enter your dashboard passphrase.</p>
        <LoginForm />
      </div>
    </main>
  );
}
