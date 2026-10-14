# Tasks

The heartbeat (`scripts/heartbeat.py`) reads this file. It never calls a model just to check for work.

Format, one task per line:

    - [ ] Short description  @workflow:<name>  due:YYYY-MM-DD  every:daily|weekly|3h  at:08:00,13:00  needs:approval  saves:2h

- `@workflow:<name>` runs `workflows/<name>.py`. Tasks without it are for you or for Claude in a session.
- `due:` the heartbeat skips the task until this date.
- `every:` recurring. The task stays open after a successful run.
- `needs:approval` the heartbeat won't run it until you approve it (Telegram button, the app, or change it to `approved`).
- `paused:owner` the owner paused it (from the app). `paused:<incident id>` means it's contained while an incident is open.
- `saves:<hours>h` roughly how many hours a week this routine saves the owner (shown as "time given back").
- `@you` on a task without `@workflow:` makes it the owner's to-do; otherwise it's the COO's.
- When a one-off task succeeds, the heartbeat ticks it `[x]` and adds `done:YYYY-MM-DD`.

## Goals
- (pending onboarding)

## Open

## Done
