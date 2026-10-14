# Steerable dashboard

The owner's screens for a Steerable company: **Today** (the morning brief and what needs you), **Decisions**, **Timeline**, **Work** (routines and to-dos), **Goals** and **Chat** with your COO. It reads and acts through the engine's agent API (`scripts/agent_api.py`), so everything it shows comes from your company folder.

It's two things in one folder:

- **An app you can run yourself**, for one company, behind a passphrase.
- **A library** (`src/`, published as `@steerable/dashboard`) that other apps host. Steerable Cloud, the hosted version, is one: it adds accounts, teams, many companies, billing and connected accounts around these same screens.

## Run it yourself

You need Node.js 20+ and a Steerable company folder (see the main README).

1. In your company folder, give the agent API a token and start it:

   ```bash
   echo "AGENT_API_TOKEN=$(openssl rand -hex 24)" >> .env
   .venv/bin/python scripts/agent_api.py          # http://127.0.0.1:8787
   ```

2. Here, configure and start the dashboard:

   ```bash
   cp .env.example .env.local     # set DASHBOARD_PASSWORD, AGENT_API_TOKEN (the same token), names
   npm install
   npm run build && npm start     # http://localhost:3100
   ```

   `npm run dev` runs it with live reload while you change things.

Open it, enter your passphrase, and you're in. **Connections** is where you connect services (scripts/tools.py in the engine; the sign-ins come back to `/connections/callback` here). It's meant for you alone: keep it on your machine or a private network, or put it behind HTTPS. Telegram keeps working alongside it.

The easiest way to run both the engine and the dashboard is Docker; see "Run it with Docker" in the main README.

## Host it in your own app

The screens don't know about sessions or companies. A host provides them through a `DashboardHost` (`src/host.ts`):

```ts
import type { DashboardHost } from "@steerable/dashboard/host";
import * as actions from "./actions";            // your "use server" actions (see host.ts)

export const host: DashboardHost = {
  backend: getMyBackend,                          // checks who's signed in, returns their CompanyBackend
  now: requestTime,                               // Date.now() after connection()
  actions,                                        // decide, setRoutinePaused, toggleTodo, startOnboarding, sendMessage
  connections: false,                             // true if you have a Connections page
};
```

Then each route is one line, for example `app/today/page.tsx`:

```tsx
import { TodayPage } from "@steerable/dashboard/screens/today";
export default function Page() {
  return <TodayPage host={host} />;
}
```

and the layout wraps them in `DashboardShell` (`src/shell.tsx`) with your own slots: the company card, a footer (account menu), a phone header, and anything else every page needs. `app/` and `local/` in this folder are a complete, small example.

For the look, import the theme after Tailwind and point Tailwind at the sources:

```css
@import "tailwindcss";
@import "@steerable/dashboard/theme.css";
@source "../node_modules/@steerable/dashboard/src";
```

and add `transpilePackages: ["@steerable/dashboard"]` to `next.config.ts`. It's built for Next.js 16 with `cacheComponents`.

The contract between the screens and the engine is `CompanyBackend` in `src/backend/types.ts`; `src/backend/agent.ts` implements it over the agent API and `src/backend/mock.ts` with a sample company, for demos.

## Developing

```bash
npm run dev          # the self-hosted app, against your agent API
npm run typecheck
npm run lint
```

The UI speaks plain language to business owners: never "workflow", "incident", "heartbeat", "cron" or "token". Colors are checked for WCAG AA contrast in light and dark; recheck if you change `theme.css`.

License: AGPL-3.0, like the rest of Steerable.
