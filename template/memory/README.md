# Memory index

Plain-text memory that persists across Claude Code sessions. You can read and edit any of it; Claude reads it at the start of relevant work and updates it after meaningful work.

| File | What goes in it |
|---|---|
| [company.md](company.md) | What the company is: offer, customers, revenue model, tools and accounts (names only, never secrets), goals. Changes rarely. |
| [processes.md](processes.md) | How work gets done: daily and weekly routines, repetitive tasks, time spent, and each process's automation status. |
| [plan.md](plan.md) | The current revenue plan: the bet, steps, metrics, expectations and what's needed from the CEO. |
| [validation.md](validation.md) | How we prove demand before building (YC, The Mom Test, smoke tests), plus the current validation test and its pass/fail bar. |
| [ideas.md](ideas.md) | Parking lot: ideas that wait until the current focus test ends. |
| [decisions.md](decisions.md) | Dated log of decisions and their reasons, newest first. Approvals for spending, workflows, and agents are recorded here. |

Rules
- Facts only. Mark guesses as `(unconfirmed)`.
- Don't duplicate. Update the existing line instead of adding a new one.
- Secrets never go here. They live in `.env`.
- Run history and costs live in `logs/`, not here.
- Curated, not a journal. Only save what a future session needs to act correctly. Never save session summaries, progress notes, chat recaps, or "today I did X". Those belong in logs/, tasks.md or the mission board.
- Keep each file under ~1 page. When a file is near that, merge or delete stale lines before adding. When a fact changes, replace the old line rather than adding a new one.
- Only the main COO writes memory. Clones and headless runs report back and don't edit memory/.
