# Security and your responsibility

How Steerable keeps the AI on a short leash, and what you're responsible for. Back to the [README](../README.md).

## Security model

Steerable lets an AI act for your company, so it is built to keep that AI on a short leash.

- **New work waits for you.** A routine runs only after you approve it and see its practice run (every page, click and message it would send). It then runs under watch: anything that can't be undone is checked first and held when in doubt, until you let it run on its own. From the chat, anything that spends money, contacts customers, publishes or deletes waits in your Decisions.
- **Headless agents are sandboxed by permission rules.** None of them can read `.env` or `.cache`.
  - The **Telegram chat agent** works only inside the project. It can't edit `scripts/`, `workflows/` or `tasks.md`, so it can't create workflows or approve its own tasks. It can run only the project's scripts and read-only git commands.
  - The **incident fixer** writes only to its own git worktree and `drafts/`, so the live project is never touched until a fix is applied.
  - The **learning loop** writes only to `.claude/skills/` and has no shell.
- **Connected services ask before changing anything.** In the chat, tools that only read run; every other tool call goes to `scripts/approvals.py` (Claude Code's `--permission-prompt-tool`), which puts it in your Decisions and lets through only the exact call you allowed, or tools you chose to always allow (never ones that delete). Their sign-ins and keys stay in `.cache/tools/`, which no agent can read and the export leaves out.
- **Every AI call has a spending cap:** $0.50 per Telegram message, $1 per incident, $0.30 per learning run, plus the monthly budget across everything.
- **Secrets stay in `.env`** (mode `600`, gitignored), never in memory files or git. `steerable config` masks them.
- **Outside text is untrusted.** The COO's rules forbid passing web pages, form answers or emails to an agent with broad write access.
- **Everything is auditable:** `logs/runs.jsonl` (every run), `logs/spend.jsonl` (every paid call), git history (every change), and `ops.db` (every mission step).

## Your responsibility

Steerable is a tool you run. Your COO acts in your name: the emails it sends, the sites and accounts it uses, the information it collects and the changes it makes are your actions, and you're responsible for them.

- Use it only with accounts, sites and data you have the right to use, and within those sites' and services' terms. Some sites forbid automated use and may limit or close your account for it.
- Follow the laws that apply to your business and to what your COO does for it: privacy and data protection (you're the one in charge of the information it handles), anti-spam and marketing rules, consumer, employment and tax law, and telling people they're dealing with AI where that's required.
- AI makes mistakes. Approve routines you're happy to see run unsupervised, check the timeline, and don't treat anything it says as legal, tax, financial or other professional advice.

Steerable comes with no warranty, and its authors aren't liable for how it's used (sections 15 and 16 of the [license](../LICENSE)). Connected to Steerable Cloud, the [Steerable Terms](https://steerable.app/terms) apply too.
