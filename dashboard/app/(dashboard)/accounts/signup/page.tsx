import type { Metadata } from "next";
import { Suspense } from "react";
import { ShieldCheck } from "lucide-react";
import { Card, PageHeader, Skeleton } from "../../../../src/ui";
import { company } from "../../../../local/host";
import { accountsOverview, cooAccount, ToolsError, type AccountsOverview, type CooAccount } from "../../../../local/tools";
import { LiveLogin } from "../../../../src/live-login";

export const metadata: Metadata = { title: "Sign up" };

export default function Page({ searchParams }: PageProps<"/accounts/signup">) {
  return (
    <div className="mx-auto max-w-5xl">
      <Suspense fallback={<Skeleton className="h-96 rounded-3xl" />}>
        <Signup searchParams={searchParams} />
      </Suspense>
    </div>
  );
}

async function Signup({ searchParams }: { searchParams: PageProps<"/accounts/signup">["searchParams"] }) {
  const { site, again } = await searchParams;
  let account: CooAccount;
  let overview: AccountsOverview;
  try {
    if (typeof site !== "string") throw new ToolsError("Which account? Start from the Accounts page.");
    [account, overview] = await Promise.all([cooAccount(site), accountsOverview()]);
  } catch (error) {
    if (!(error instanceof ToolsError)) throw error;
    return <Card className="p-6 text-ink-2">{error.message}</Card>;
  }
  const loggingIn = again === "1" || account.status === "ACTIVE";
  return (
    <>
      <PageHeader
        title={loggingIn ? `Log ${company.cooName} back in to ${account.name}` : `Sign ${company.cooName} up to ${account.name}`}
        subtitle={account.why}
      />
      <Card className="mb-6 flex gap-4 p-5 text-sm text-ink-2">
        <ShieldCheck className="mt-0.5 size-5 shrink-0 text-accent" />
        <p>
          It&apos;s your business&apos;s account, run by {company.cooName}. Its password was made on your server and is typed in
          from there: no AI ever sees it, and you can see it on the Accounts page anytime. Your business is the account holder:
          signing up agrees to the site&apos;s terms, and what {company.cooName} does with the account is your responsibility.
        </p>
      </Card>
      <Card className="p-6">
        <LiveLogin
          initialUrl={loggingIn ? account.loginUrl || account.signupUrl : account.signupUrl}
          initialName={account.name}
          account={{
            site: account.site,
            name: account.name,
            url: account.signupUrl,
            email: overview.mailbox.address,
            hasPhone: Boolean(overview.phone),
            again: loggingIn,
          }}
        />
      </Card>
    </>
  );
}
