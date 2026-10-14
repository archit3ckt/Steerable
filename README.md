<div align="center">

<h1>
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/steerable-logo-white.png">
  <img src="brand/steerable-logo.png" alt="Steerable" width="360">
</picture>
</h1>

**An AI COO for your small business. You're the CEO; it runs everything else.**

[![License: AGPL v3](https://img.shields.io/badge/license-AGPL--3.0-blue.svg)](LICENSE)
[![Built on Claude Code](https://img.shields.io/badge/built%20on-Claude%20Code-D97757.svg)](https://claude.com/claude-code)

[Quick start](#quick-start) · [Docs](#docs) · [Steerable Cloud](https://steerable.app)

</div>

---

- **See it before it runs.** Every new routine does a practice run first. You see each page, click and message, then switch it on.
- **One COO instead of many AI tools.** Chat, automations, writing and research in one place that knows your business.
- **Cheap to run.** Routines are plain programs that cost nothing per run. AI is used only where judgment is needed, under a monthly cap.
- **Teach it a book.** Give it a business book you love; it suggests habits, routines and goals from it.
- **Yours.** Open source, plain files and git. Export your company any time and move it anywhere.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/archit3ckt/steerable/master/get.sh | sh
```

It asks for your business's name, a dashboard passphrase and an [Anthropic API key](https://console.anthropic.com) (or sign in with your Claude account later), then starts Steerable with Docker. Open http://localhost:3100 and your COO starts by getting to know your business.

Don't want to run it yourself? [Steerable Cloud](https://steerable.app) hosts it for you, with AI included.

## Docs

- [Running it yourself](docs/self-hosting.md): install, settings, connecting your services, commands
- [How it works](docs/how-it-works.md): routines, the heartbeat, writing your own, how it learns
- [Security and your responsibility](docs/security.md)
- [The dashboard](dashboard/README.md)

## License

[AGPL-3.0](LICENSE). Use it, change it and self-host it freely. If you run a modified version as a service for others, publish your changes under the same license.
