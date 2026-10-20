# Routine catalog

Routines we wrote and tested for work most small businesses need. When an owner approves a routine
that clearly asks for one of these, the builder starts from it and only fits it to the company
(sets its `SETTINGS`, changes what truly differs), which costs a fraction of building from nothing.
The match is made by `catalog.match()` (Jev through `decide.py`; below 0.8 confidence it's a full
build). See `scripts/catalog.py`.

## An entry

A folder named for the entry's id (lowercase, underscores):

- `routine.py`: the routine, meeting every point of the Workflow standard in CLAUDE.md. A `SETTINGS`
  dict at the top holds everything a company sets (days, amounts, wording, which list); the code
  reads only from it. Sensible defaults, so it runs as it is.
- `routine.flow.json`: its flow chart, `{"steps": [...]}`, step 0 the trigger; the routine calls
  `step(n)` for each.
- `about.json`: `{"title", "description", "services", "settings"}`. The description is one sentence a
  task line is matched against: say what it does, for whom, specifically enough that something only
  similar doesn't match. `services` are provider ids from `integrations/providers.json`. `settings`
  explains each `SETTINGS` key in plain words.

## The bar

- `tests/test_catalog.py` checks every entry: `about.json` complete, the flow chart valid,
  `routine_check` clean, `SETTINGS` keys equal to `about.json`'s.
- A dry-run test with fixture answers from its services (`tests/test_catalog_routines.py`): it exits 0,
  its last line is a plain sentence, everything it can't undo goes through `act()`, and a second run
  adds nothing new.
- Anything it can't undo (send, post, pay) goes through `common.act()`; it keeps its records in a
  library table with a key; it tells the owner only when there's news (`tell_owner`).
- Our own words and code. Nothing copied from a vendor's samples without checking their license.
