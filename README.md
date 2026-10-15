<div align="center">

<h1>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/steerable-logo-white.png">
  <img src="brand/steerable-logo.png" alt="Steerable" width="360">
</picture>
</h1>

**Hand off the repetitive work that eats your week.**

[![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Built on Claude Code](https://img.shields.io/badge/built%20on-Claude%20Code-D97757.svg)](https://claude.com/claude-code)

[Try it](#try-it) · [Docs](#docs) · [steerable.app](https://steerable.app)

</div>

---

Steerable is an AI assistant that runs the day-to-day of your small business, like a COO. It saves you hours every week by doing the repetitive work for you: following up with clients, chasing unpaid invoices, sending reminders and reports, keeping your records up to date.

## How it does it

1. **You tell it what takes up your time**, in plain words, like you'd brief a new hire.
2. **It sets up the work for you.** It writes a small program that does that job, tests it, and runs it on a schedule. It uses AI only where judgment is needed, like reading an email or drafting a reply.
3. **It keeps it running.** If something breaks, it finds the cause and fixes it. Each morning you get a short note on what got done and anything that needs you.

## You stay in control

- **You see it before it runs.** Before anything new starts, it does a practice run and shows you every page it would open and every message it would send. Nothing goes live until you say so.
- **You decide what it does alone.** New work that touches money, customers or anything public comes to you first. Once you approve a job, it does it on its own until you pause it.
- **Everything is on the record.** Every action is in a timeline you can read, and you can pause anything with one switch.
- **It's yours.** Open source, with your business kept in plain files. Download it any time and move it anywhere.

## Under the hood

For the technically minded:

- **Predictable by design.** The work is done by small coded routines that run on a schedule; a model is called only where judgment is needed (reading an email, drafting a reply). An agent that wakes up on a schedule decides everything afresh each time; a routine does the same thing every run.
- **Cheap to run.** Most runs call no model at all. There's a hard monthly cap, and a ledger of every paid call.
- **Testable and auditable.** Dry runs, practice runs with screenshots of every page, a log of every run, and quality checks that stop bad results from going out.
- **Self-healing, with guardrails.** A failing routine is paused, and its fix is made and tested on a git branch before it's merged.
- **Plain files.** Memory, plans and history are files and SQLite in one folder under git: readable, editable, exportable.

More in [How it works](docs/how-it-works.md).

## Try it

**On your own computer, free** (one line; it runs with Docker):

```bash
curl -fsSL https://raw.githubusercontent.com/archit3ckt/steerable/master/get.sh | sh
```

It asks for your business's name, a password for your dashboard and an [Anthropic API key](https://console.anthropic.com), then opens at http://localhost:3100 and starts by getting to know your business.

**Or let us run it for you:** [start a 7-day free trial](https://steerable.app) at steerable.app. Nothing to install, and the AI is included.

### Self-host or hosted?

| | Self-hosted | Hosted (steerable.app) |
|---|---|---|
| Price | Free | After a 7-day free trial: $49, $149 or $399 a month by plan (2 months free yearly) |
| AI | Your own Anthropic API key or Claude account | Included, up to a monthly limit per plan |
| Setup and updates | You run it (Docker) | Done for you, with backups |
| Your data | On your machine | In its own isolated space; download it any time |

You can move between them: export your company from one and import it into the other.

## Docs

- [Running it yourself](docs/self-hosting.md)
- [How it works under the hood](docs/how-it-works.md)
- [Security and your responsibility](docs/security.md)

## License

[AGPL-3.0](LICENSE): use it, change it and run it yourself for free.
