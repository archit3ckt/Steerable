# Cheaper Routine Builds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut what building a routine costs, with the same model, by giving the builder what it would look up, continuing its own session instead of starting cold, retrying only what a retry can fix, and starting common routines from tested code we wrote.

**Architecture:** All changes are in the engine's `template/scripts/`. `builder.py` gains a ready brief (`_brief`), session reuse (`session` on each build record, passed as `agent.run(resume=)`), and a failure triage (`_triage`, through `decide.decide`, so Jev first). A new `catalog.py` plus `template/scripts/catalog/<id>/` holds routines we wrote and tested; `catalog.match()` (Jev) routes an approved task to one of them, and the builder then adapts it instead of writing from nothing. Spend per routine, across all its attempts, is kept so before/after can be compared.

**Tech Stack:** Python 3 standard library, `unittest`, the engine's fake-`claude` test pattern (`tests/test_supervision.py`), `decide.py` (Jev / Haiku / rules backends).

**Spec:** This plan (owner's request, 2026-10-20, in conversation): "(1) a ready brief instead of exploration, (2) continue the build's own session for auto-fix rounds and owner revisions, (3) stop blind retries, Jev classifies whether a failure is retryable, (4) a routine catalog of tested routines we write ourselves, with Jev routing an approved task to a catalog entry or a full build, (5) measure before/after." Constraint from the owner: never a cheaper model for the work itself.

## Global Constraints

- The build itself always runs on `tier="smart"`. Jev (or Haiku when Jev is unsure) is used only to route and classify.
- Nothing the owner reads says "workflow", "session", "catalog", "token", "Jev". Summaries stay plain words.
- Catalog code lives under `template/scripts/` so it is engine code (`common.ENGINE_CODE`): updated with the engine, never editable by the AI.
- Every catalog routine passes `routine_check.check()` and runs with `STEERABLE_DRY_RUN=1`, exit 0.
- An adapted catalog build is capped at `ADAPT_CAP_USD = "0.75"`; a full build stays at `PER_BUILD_CAP_USD = "2.00"`.
- Engine tests: `python3 -m unittest discover -s tests` from the engine root; all pass at the end of every task.

## Review Focus

- A resumed session that no longer exists (engine restarted on another node, OpenCode agent, `.home` wiped): the build must fall back to a full cold prompt, not fail. → Task 3 test `test_resume_falls_back_when_session_is_gone`.
- The worktree path changes between attempts (`WORKTREES/<bid>`): a resumed session must be told the new path and get permission rules for it, or every edit is denied. → Task 3 test `test_resumed_attempt_gets_the_new_worktree`.
- A vague or unusual task that only looks like a catalog entry ("remind me about invoices I owe suppliers" vs. invoices customers owe): it must go to a full build, not a wrong template. → Task 5 test `test_low_confidence_or_none_goes_to_a_full_build`.
- Jev unreachable or every backend failing during triage: the build must keep today's behavior (retry on the schedule), never get stuck or silently stop. → Task 4 test `test_triage_falls_back_to_retry_when_deciding_fails`.
- A routine whose attempts span several build ids (auto-fix, revise, retry): its cost must add up across all of them, not just the last. → Task 1 test `test_cost_adds_up_across_attempts`.

---

### Task 1: Spend per routine, across attempts

**Files:**
- Modify: `template/scripts/builder.py` (`_open`, `_auto_fix`, `retry_failed`, `recover_stale`, `revise`, `retry`, `build`, `__main__`)
- Test: `tests/test_build_costs.py`

**Interfaces:**
- Produces: build records carry `prev` (the build id this attempt continues, or absent) and `cost_usd`, `turns` (from `out.raw.get("num_turns")`), `session` (from `out.session_id`). `builder.costs() -> list[dict]`: one dict per workflow `{"workflow", "builds", "cost_usd", "turns", "catalog"}`, chains followed through `prev`, newest first. CLI: `python scripts/builder.py costs` prints one line per workflow.

- [ ] **Step 1: Write the failing test** `test_cost_adds_up_across_attempts`: write `.cache/builds.json` with three records for `invoices` (`b1` cost 1.2 turns 30; `b2` prev `b1` cost 0.4 turns 8; `b3` prev `b2` cost 0.3 turns 6) and one for `weekly` (cost 0.5); assert `costs()` gives `invoices` → `builds == 3`, `cost_usd == 1.9`, `turns == 44`, and `weekly` → `builds == 1`. Use a copied template company like `tests/test_recovery.py`.
- [ ] **Step 2: Run it, expect FAIL** (`AttributeError: module 'builder' has no attribute 'costs'`): `python3 -m unittest tests.test_build_costs -v`
- [ ] **Step 3: Implement.** Every `_open(...)` call that starts a new attempt from an old one passes `prev=<old bid>` (in `_auto_fix`, `retry_failed`, `recover_stale`, `revise`, `retry`). In `build()`, store `turns` and `session` with `cost_usd` in `fields`, and also on the failure paths that return early after `agent.run` (no structured result). Add `costs()` and the `costs` CLI branch.
- [ ] **Step 4: Run it, expect PASS**, then the whole suite.
- [ ] **Step 5: Commit** `Builds: keep each routine's spend across all its attempts`

### Task 2: A ready brief instead of exploring

**Files:**
- Modify: `template/scripts/builder.py` (`_prompt`, `_change_prompt`, new `_brief`)
- Test: `tests/test_build_brief.py`

**Interfaces:**
- Produces: `builder._brief() -> str`, a block placed in both prompts after `_accounts()`, containing, each under its own heading: `memory/company.md`, `memory/processes.md`, `memory/decisions.md` (each cut to its last 4,000 characters, marked when cut); the mission board (`ops_db.py --show` output, cut to 3,000); library tables (`library.tables()`: name and columns, and row count); `workflows/_template.py` in full. Ends with: "This is everything you'd look up in those files: don't read them again. Read other files only when the task needs them."

- [ ] **Step 1: Write the failing test** `test_prompt_carries_the_brief`: in a copied company with a library table `Clients` (columns `Name:text, Email:text`) and `memory/company.md` containing `Bakery in Leeds`, assert `builder._prompt(b, "/wt")` contains `Bakery in Leeds`, `Clients`, `Email`, the first line of `workflows/_template.py`, and `don't read them again`. Same assertions for a change build (`b["change"] = "x"`). A second test, `test_brief_cuts_long_memory`: a 10,000-character `memory/decisions.md` appears cut to at most 4,000 characters plus the cut marker.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement `_brief()`** and put it into both prompts. Remove the line in `_prompt` that tells it to read memory/ and the board ("Read memory/ (company.md, ...)"); keep "meeting every point of the Workflow standard in CLAUDE.md" (CLAUDE.md is already loaded by Claude Code).
- [ ] **Step 4: Run, expect PASS**, then the suite (`test_supervision` and `test_recovery` build prompts too).
- [ ] **Step 5: Commit** `Builder: hand it what it would look up, so it doesn't explore`

### Task 3: Continue the build's own session

**Files:**
- Modify: `template/scripts/builder.py` (`build`, `_auto_fix`, `revise`, `retry_failed`, new `_resume_prompt`)
- Test: `tests/test_build_resume.py`

**Interfaces:**
- Consumes: `session` and `prev` on build records (Task 1).
- Produces: `_open(..., resume=<session id>)` stores `resume` on the new record; `build()` passes `resume=b.get("resume")` to `agent.run` with `_resume_prompt(b, wt)` instead of `_prompt`. `_resume_prompt(b, wt) -> str`: says the work continues, the worktree is now at `{wt}` (branch `build/<name>`, holding the last version), repeats the "How to work" paths and commands with the new `{wt}`, and adds `_feedback(b)` and the failure (Task 4's `failure` field, when present). If the resumed run returns no structured result, `build()` runs once more cold with the full prompt (`resume=None`) in the same worktree, and records both costs.
- `_auto_fix` and `revise` pass `resume=b.get("session")`; `retry_failed` passes it only for a failure triaged `retry` (Task 4).

- [ ] **Step 1: Write the failing tests** with a fake `claude` (pattern of `tests/test_supervision.py`) that logs its argv and, when given `--resume`, answers only if the id is `s-ok`:
  - `test_review_fixes_continue_the_same_session`: a build whose fake first run returns `session_id: "s-ok"` and a review with fixes; assert the auto-fix attempt's argv contains `--resume s-ok` and its prompt is the short one (contains `now at` and not `Build it as workflows/`).
  - `test_resumed_attempt_gets_the_new_worktree`: the resumed run's `--add-dir` and allow rules name the new `WORKTREES/<new bid>`, and the prompt contains that path.
  - `test_resume_falls_back_when_session_is_gone`: the first run returns `session_id: "s-gone"`; the resumed attempt fails, then a cold run (no `--resume`, full prompt) follows and the build ends `ready`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** as in Interfaces.
- [ ] **Step 4: Run, expect PASS**, then the suite.
- [ ] **Step 5: Commit** `Builder: fixes and changes continue the build's own conversation`

### Task 4: Retry only what a retry can fix

**Files:**
- Modify: `template/scripts/builder.py` (`build` failure paths, `retry_failed`, new `_triage`)
- Test: `tests/test_build_triage.py`

**Interfaces:**
- Consumes: `decide.decide(question, options: dict, context) -> Decision` (`.choice`, `.backend`).
- Produces: `_triage(b: dict, fields: dict, error: str = "") -> str`, one of `"retry"`, `"owner"`, `"stop"`. Order:
  1. no AI: `BudgetExceeded` → the build stays failed with `wait_month=True` (retried by `retry_failed` only after the 1st, UTC, not on the minutes schedule); interrupted (`recover_stale`) → `"retry"`; standards or engine-code refusal → `"retry"`.
  2. otherwise `decide.decide("A routine build failed. What would help?", {"retry": "a passing problem (timeout, network, a site or service down for a while, the AI ran out of turns); or a fixable mistake in its own code", "owner": "it needs something only the owner can give: a login, a connected account, a choice about how the business works, a clearer request", "stop": "it can't be built this way at all (the service doesn't allow it, the task is impossible)"}, context=<summary + needs + last 1,500 chars of test_output and error>)`, the last option listed being the safe default.
  3. any exception from `decide` → `"retry"` (today's behavior).
- `"retry"`: stored as `triage="retry"` and `failure=<summary + error tail>`; `retry_failed` starts it with `resume=b.get("session")` and the failure as context (Task 3), on the existing `RETRY_AFTER` schedule, at most `len(RETRY_AFTER)` times as now.
- `"owner"`: status `needs_owner`, `needs` = `owner_words.say(<the summary>, wait=True)` (so it shows in Decisions like any build that needs the owner); never retried on its own.
- `"stop"`: no retries; `burst.report_problem("build_failed", ...)` at once, and the owner's summary says it couldn't be built and why.

- [ ] **Step 1: Write the failing tests**, with `DECIDE_BACKEND=rules` in `.env` and keyword rules passed by `_triage` (`"timeout": "retry"`, `"log in": "owner"`, `"not allowed": "stop"`) so no model is called:
  - `test_passing_problem_is_retried_with_its_failure`: a failure whose output says `timeout` → `triage == "retry"`, and the retry's prompt contains the failure text.
  - `test_needs_owner_is_not_retried`: summary `it has to log in to the supplier portal` → status `needs_owner`, and `retry_failed()` starts nothing for it.
  - `test_impossible_is_reported_once`: `not allowed` → no retry, one `report_problem` call (patch `burst.report_problem`).
  - `test_budget_waits_for_next_month`: `BudgetExceeded` → `retry_failed()` with a `now` in the same month starts nothing; with a `now` in the next month starts one.
  - `test_triage_falls_back_to_retry_when_deciding_fails`: `decide.decide` patched to raise → `"retry"`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** `retry_failed` takes an optional `now: datetime | None = None` for the test.
- [ ] **Step 4: Run, expect PASS**, then the suite.
- [ ] **Step 5: Commit** `Builder: retry only what a retry can fix; the rest asks the owner or stops`

### Task 5: The routine catalog and routing to it

**Files:**
- Create: `template/scripts/catalog.py`, `template/scripts/catalog/README.md` (format and the bar an entry must meet)
- Modify: `template/scripts/builder.py` (`build`: pick adapt or full; new `_adapt_prompt`), `template/scripts/common.py` only if `ENGINE_CODE` does not already cover `scripts/`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Entry layout: `template/scripts/catalog/<id>/routine.py`, `routine.flow.json`, `about.json` = `{"title", "description" (one sentence a classifier can match a task line to), "services": [provider ids], "settings": {"<NAME>": "<what it is, plain words>"}}`. A routine's settings are a `SETTINGS = {...}` dict at the top of `routine.py`, the only part an adaptation is expected to change.
- `catalog.entries() -> list[dict]`: each `about.json` plus `"id"`.
- `catalog.match(task: str) -> dict | None`: `decide.decide("Which ready-made routine does this task ask for?", {<id>: <description>, ..., "none": "none of these: something different, or only similar"}, context=task)`; returns the entry only if `choice != "none"` and `confidence >= MATCH_MIN = 0.8`; `None` on any exception.
- `catalog.install(entry: dict, wt: Path, name: str) -> None`: copies `routine.py` → `workflows/<name>.py` and `routine.flow.json` → `workflows/<name>.flow.json` in the worktree and commits them (`Start <name> from <id>`).
- `builder.build()`: for a new routine (no `change`, no `resume`, no `base`), `entry = catalog.match(b["task"])`; with an entry, `install`, record `catalog=<id>` on the build, run `_adapt_prompt(b, wt, entry)` with `budget_usd=ADAPT_CAP_USD`. Later attempts of the same routine (fixes, revisions, retries) keep `catalog` and go on from the branch as today.
- `_adapt_prompt(b, wt, entry) -> str`: the routine is already in the worktree, tested by us; set `SETTINGS` for this company from the brief and the task, change code only where this company truly differs, keep the rest; same test, `routine_check`, commit and result rules as `_prompt` (reuse its "How to work" text rather than copying it); includes `_accounts()` and `_brief()`.

- [ ] **Step 1: Write the failing tests** (rules backend, a test-only entry `demo` written into a temp `scripts/catalog/demo/`):
  - `test_matching_task_starts_from_the_catalog`: task `Remind clients about overdue invoices every Monday`, rules map `overdue invoices` → `demo`; with a fake decide confidence of 0.9 the worktree's first commit is `Start ... from demo`, the agent's prompt is the adapt prompt and its `--max-budget-usd` (or the equivalent the fake logs) is `0.75`, and the build record has `catalog == "demo"`.
  - `test_low_confidence_or_none_goes_to_a_full_build`: confidence 0.6 → full prompt, cap `2.00`, no `catalog`; choice `none` → the same.
  - `test_every_catalog_routine_meets_the_standard`: for each real entry in `template/scripts/catalog/`, `about.json` has every key, `routine.flow.json` passes `flow.valid`, `routine_check.check()` returns `[]`, and `SETTINGS` is a top-level dict whose keys equal `about.json`'s `settings`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement** `catalog.py`, the README, and the builder branch.
- [ ] **Step 4: Run, expect PASS**, then the suite.
- [ ] **Step 5: Commit** `Routine catalog: common routines start from code we wrote and tested`

### Task 6: First three catalog routines

Each is its own commit, written to the Workflow standard (steps, `act()` for anything it can't undo, records in a library table with a key, `tell_owner` only with news, dry run honored), with a dry-run test against fake service answers.

**Files:**
- Create: `template/scripts/catalog/overdue_invoices/` (Stripe: open invoices past due by `DAYS_OVERDUE`, a polite reminder per invoice through Stripe's own reminder, each through `act()`, at most once per `REMIND_EVERY_DAYS`; library table `Invoice reminders`, key = invoice id)
- Create: `template/scripts/catalog/weekly_numbers/` (Stripe: last week's revenue, refunds, new customers vs. the week before; `save_report` and one `tell_owner` with the numbers; library table `Weekly numbers`, key = week)
- Create: `template/scripts/catalog/email_follow_ups/` (Gmail: threads the owner sent that got no reply in `WAIT_DAYS`, from senders not in `SKIP`; a follow-up drafted with `save_draft` (never sent) and listed in one `tell_owner`; library table `Follow-ups`, key = thread id)
- Test: `tests/test_catalog_routines.py`

**Interfaces:**
- Consumes: `integrations.call` / `integrations.mcp_call`, `common.act/step/tell_owner/save_draft/save_report`, `library.table`.
- Test hook: the routines get service answers through `integrations`; the test replaces them with a fixture by a `STEERABLE_FAKE_INTEGRATIONS=<json file>` read in `integrations.call`/`mcp_call` only when `STEERABLE_DRY_RUN=1` (add it to `integrations.py` if no such hook exists; check `tests/test_supervision.py` and `tests/test_tools.py` first).

- [ ] **Step 1: Write the failing test per routine**: copied company, fixture answers, `STEERABLE_DRY_RUN=1 python workflows/<id>.py "<task>"` exits 0, its last printed line is a plain sentence naming the count (`Would remind 2 clients about overdue invoices`), `act()` was noted for each reminder and nothing else, and a second run adds no new library rows.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Write the routine.**
- [ ] **Step 4: Run, expect PASS**, plus `test_every_catalog_routine_meets_the_standard`.
- [ ] **Step 5: Commit** one per routine: `Catalog: overdue invoice reminders` / `Catalog: weekly numbers` / `Catalog: email follow-ups`

### Task 7: Docs and measurement

**Files:**
- Modify: `template/CLAUDE.md` (where routine building is described: routines may start from the catalog), `README.md` or `docs/` page on routines (catalog format, adding an entry), and the cloud repo's `CLAUDE.md` "Current state" with one line.

- [ ] **Step 1:** Document the catalog bar (from `catalog/README.md`) and how to add an entry.
- [ ] **Step 2:** Measurement procedure, run by us with a real key: on a fresh company, approve the same three tasks (one per catalog routine) and one unusual task, on `master` before this branch and after; record `python scripts/builder.py costs` for each. Write the numbers into the PR description.
- [ ] **Step 3: Commit** `Docs: the routine catalog and cheaper builds`

## Later (not in this plan)

- Batch API (half price) for background AI. Looked at 2026-10-20: almost all spend is agent runs (chat, builds, incidents, books, learning), which the Batch API can't run; the direct calls (`agent.complete`) are ones someone waits on (watched-run checks, "Test it", reviews, owner wording). The one candidate is the nightly learning review (`learn.py`, capped $0.30/day): it would become one batched Messages call returning skill edits that the engine writes, saving at most ~$4.50 a company a month, and needs the gateway to pass `/v1/messages/batches` through and record usage at the batch price. Do it once beta numbers show learning is a real share of spend.
- The next seven catalog routines, picked from what owners ask for in the beta (candidates: review requests after a sale, new-lead follow-up, booking confirmations and reminders, reorder alerts, unpaid supplier bills, social post from the week's news, monthly summary for the accountant).
- Jev triage in the chat: send a short message that needs no tools ("thanks", "ok do it") to a cheap single call on the same model instead of a full Claude Code turn.

## Status (2026-10-20)

Tasks 1 to 7 done on branch `cheaper-builds`, 173 engine tests passing. Two choices made while building:
- A retry after a failure starts afresh with what went wrong (`failure`, shown in both prompts), not in the old
  conversation: a failed build's branch is deleted, so the old conversation would point at code that's gone.
  Fixes after a practice run and the owner's changes do continue the conversation.
- The email follow-ups routine keeps follow-ups as drafts in the company's drafts/ (Google's connection has
  no Gmail drafts scope) and sends only when the owner set `SEND`.

Not yet tried with a real model, Jev or real accounts. To measure (needs a real Anthropic key, ~$20):
1. On a fresh company on `master`, approve: "Remind clients about overdue invoices every Monday", "Send me
   last week's numbers every Monday", "Follow up on emails that got no reply", and one unusual task.
2. Note `python scripts/builder.py costs` once each build is ready.
3. Repeat on `cheaper-builds`; check `catalog.py match` picks the first three and not the fourth (tune
   `catalog.MATCH_MIN` if Jev's confidences sit differently).
