# Running Steerable yourself

Everything about installing and running the engine on your own machine or server. Back to the [README](../README.md).

## Install

### With Docker (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/archit3ckt/steerable/master/get.sh | sh
```

It asks for your business's name, a passphrase for your dashboard, and your [Anthropic API key](https://console.anthropic.com) (or skip it and sign in with your Claude account), then starts two containers: your COO (the engine, with Claude Code, Python and a browser inside) and your **dashboard** at http://localhost:3100. Everything your COO knows and does lives on a Docker volume, so restarts and updates keep it.

Open the dashboard, and your COO starts by getting to know your business, one question at a time. It ends with **one** first routine to take off your plate, with a plan and what it saves you. Nothing gets built until you approve it.

```bash
docker compose pull && docker compose up -d     # update (in ~/steerable-docker; your data stays)
docker compose logs -f engine                  # watch your COO work
docker compose exec -it engine claude          # talk to it in the terminal, or /login to sign in
```

Settings live in `~/steerable-docker/.env` (see [.env.example](../.env.example)): Telegram, email alerts, the monthly budget, and whether the dashboard is open to your network. From a clone, `sh get.sh --build` builds the images yourself.

**Website logins:** for sites without an app (a supplier portal, a booking system), Connections → "Log in to a website" opens the site in a browser on your server, shown live in the dashboard. You log in yourself; Steerable keeps only the logged-in session (in `.cache/sites/`, which no AI can read), and approved routines get a browser that's already logged in. When a routine needs one, its decision says "Log in to …" with a button.

**Telegram** (optional): on the dashboard's Connections page, paste a bot token from [@BotFather](https://t.me/BotFather) and open the link it shows. Your brief, anything urgent and your decisions then come to Telegram too, and you can chat with your COO there.

**Connect your services:** the dashboard's **Connections** page lists services with an official MCP server you can sign in to with one click (Notion, Airtable, Linear, Jira, monday.com, ClickUp, Close, Intercom, Calendly, PayPal, Dropbox, Klaviyo, Canva, Wix, and Zapier), Stripe with a restricted key, and a box for any other MCP server by its address. Signed in with your Claude account instead of an API key? The connectors you add at [claude.ai](https://claude.ai/settings/connectors) (Gmail, Google Calendar, Slack, HubSpot...) work too, with nothing to set up. Your COO looks things up in them on its own; anything that would send, create or change something waits in your Decisions (allow once, always allow, or don't). Some services only accept sign-ins that come back to `http://localhost`, so connect from the machine running Steerable.

**Moving a company:** "Download your company" in the dashboard gives you one file with everything your COO knows. Start a new install from it with `sh get.sh --import company.tar.gz`, or bring it to Steerable Cloud when you sign up.

**More than one business or project (spaces):** each space has its own COO, memory, chat, routines and connections, kept apart from your others, all in one dashboard. Open the menu next to the business name → **New space or manage**: give it a name and a COO (and, if you like, a company you downloaded from another Steerable to start from). It's ready in about a minute; its COO signs in to its AI on its own Connections page. Delete a space from the same page.

Each space is its own engine container (about 150 MB of memory), made from your first one with its own data volume, so spaces are as separate as two installs. They're made by the `spaces` service in docker-compose.yml, the only part of Steerable with access to Docker: it only makes and removes spaces, and only the dashboard can reach it (a private network, and `SPACES_TOKEN`, which get.sh writes to `.env`). Spaces start and stop with the rest (`docker compose up -d` / `down`), and after an update they run the new version too. They share your settings from `.env`, except Telegram: one bot can talk to one space, so each other space connects its own. To bring two installs together, download the company from one and start a new space from it in the other.

**Connect to Steerable Cloud** (optional): keep running it yourself, but get AI included in a plan instead of your own key, connected accounts like Gmail and Calendar through Steerable's verified apps, and **Steerable playbooks**: a library of proven know-how on running a business (cash flow, pricing, getting paid, customers, hiring, planning) that your COO works from. Choose "On my own server" when you sign up, then copy `STEERABLE_URL` and `STEERABLE_KEY` from its "Your server" page into `.env` and run `docker compose up -d`.

### On your machine

```bash
curl -fsSL https://raw.githubusercontent.com/archit3ckt/steerable/master/install.sh | bash
steerable setup
```

`setup` asks for a company name, builds the project (Python env, Playwright, git), asks for your API keys (each one can be skipped), and offers to start the background services. Then talk to your COO:

```bash
cd ~/companies/<your-company>
steerable
```

Say **"start onboarding"**. The [dashboard](../dashboard/README.md) works here too: start `scripts/agent_api.py` and run it with Node.

> [!TIP]
> Something not working? Run `steerable doctor`. It checks your system, project, keys and services, and prints the fix for every problem it finds.

## Commands

| Command | |
|---|---|
| `steerable` | Chat with your COO (opens Claude Code in the project) |
| `steerable setup [NAME] [--dir PATH]` | Create a new company, guided |
| `steerable doctor` | Find anything that's broken, with the fix |
| `steerable status [--days N]` | Heartbeat, runs, spend, tasks |
| `steerable tasks` | Open tasks and approvals |
| `steerable approve N` · `reject N` | Decide on a waiting task |
| `steerable incidents [ID] [apply\|discard\|close] [--all]` | What broke, what the COO found, and its fix |
| `steerable logs [-n N] [-f] [-q]` | Run log with costs (`-f` follows, `-q` hides idle ticks) |
| `steerable run [--dry-run]` | Run the heartbeat once now |
| `steerable brief` | Preview today's brief |
| `steerable board` | Goals, missions and their status |
| `steerable config [list\|get\|set] [KEY] [VALUE]` | Show or change settings in `.env` (secrets are masked) |
| `steerable workflow NAME` | Start a new workflow from the template |
| `steerable start` · `stop` | Background services (cron, Telegram bridge) |
| `steerable update` · `version` | Update the kit, print its version |

Commands work inside a company folder or any folder below it. Anywhere else, they use the company you created last. `-C PATH` picks another one.

## Configuration

Settings live in each company's `.env`. Change them with `steerable config set KEY VALUE`.

| Key | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | Used by `decide()`, the incident fixer and the learning loop |
| `MONTHLY_BUDGET_USD` | `20` | Hard cap on paid API spend per month |
| `STEERABLE_MODEL_SMART`, `STEERABLE_MODEL_FAST` | `sonnet`, `haiku` | The models for the chat and builds, and for small decisions. Any model name your provider knows ([how it works](how-it-works.md#any-model-any-coding-agent)) |
| `STEERABLE_AGENT` | `claude` | The coding agent: `claude` (Claude Code) or `opencode` (needs an API key and an image built with `WITH_OPENCODE=1`) |
| `DECIDE_BACKEND` | `haiku` (`jev` when connected to Steerable) | `haiku`, `jev`, or `rules` (no model, keyword rules only) |
| `JEV_API_KEY` | none | Required when `DECIDE_BACKEND=jev` |
| `JEV_MIN_CONFIDENCE` | `0.6` | Below this, Jev hands the decision to Haiku |
| `JEV_ENDPOINT`, `JEV_MODEL` | `jev-latest` | Optional gateway and model pin |
| `TELEGRAM_BOT_TOKEN` | none | From [@BotFather](https://t.me/BotFather). Enables the brief, buttons and chat. Easier: paste it on the dashboard's Connections page. Either way, your chat is linked by a one-time link (`scripts/telegram.py link` in a terminal), so nobody else can claim the bot. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `ALERT_TO` | none | Email alerts to yourself |
| `RESTIC_PASSWORD` | generated | Backup encryption password. Keep a copy in a password manager. |

## Requirements

**With Docker:** Docker Desktop (Mac, Windows) or Docker Engine with the Compose plugin (Linux). That's all: Python, Claude Code, Node and the browser are inside the images. About 2 GB of disk.

**On your machine:**

- **Linux or macOS** (on Windows, use WSL2)
- **Python 3.10+** with `venv`. On Debian/Ubuntu: `sudo apt install python3-venv`
- **git**
- **[Claude Code](https://claude.com/claude-code)**, the runtime for your COO
- **cron**, so the heartbeat and brief run on their own
- **systemd** (Linux) to run the Telegram bridge as a service. On macOS, run `scripts/bridge.py` yourself.

The installer puts the kit in `~/.steerable` and the `steerable` command in `~/.local/bin`. You can change these with `STEERABLE_HOME` and `STEERABLE_REPO`.

## Known limitations

- The Telegram bridge service needs systemd. On macOS, run it yourself or under `launchd`.
- Backups are yours when you run it yourself (Steerable Cloud does them for you). Everything lives in one Docker volume; copy it with your usual backup tool, or: `docker run --rm -v steerable_company:/company -v "$PWD":/out alpine tar czf /out/company-$(date +%F).tar.gz -C /company .` "Download your company" in the dashboard gives you the company's files too (not its secrets or sessions).
- Running the unattended parts as a separate low-privilege user is planned but not set up by default.
