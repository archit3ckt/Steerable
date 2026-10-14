# Plan: the company library (tables and docs, run by the COO)

Status: planned 2026-10-10, not built. Owner's decision: build a monday-style workspace into
Steerable, but AI-run: the COO creates and keeps it, the owner reads, edits and decides. Companies
already on monday, Airtable or Notion keep using their tool (see "Their own tool").

## Why

- monday costs a 5-person team about $60-70 a month (3-seat minimum, AI extra). A library included
  in the plan is a selling point: "replaces monday".
- Today the COO's knowledge lives in memory/*.md and its records in ops.db, an outside tool like Teable or
  a workflow's own JSON. The owner can't see most of it. The library is one place for both.

## What the owner gets (v1)

1. **Library** in the sidebar (between Goals and Chat): a list of tables and docs, newest first,
   with search across both.
2. **Tables** (monday "boards"):
   - Rows in groups, each group with a coloured header and a collapse toggle.
   - Typed columns: text, long text, number (with unit $ % or none), date, status (coloured
     labels, full-colour cell like monday), person (you / COO / a team member), link, checkbox.
   - Click a cell to edit in place; Enter saves, Esc cancels. Add a row at the bottom of a group.
   - Sort and filter by any column; a search box. Column widths fixed per type (no resizing in v1).
   - Kanban view: the same rows as cards, by a status column (drag to change status).
   - Export CSV.
3. **Item page** (click a row): every field, a notes area, and its history ("Juno set Status to
   Contacted, 2h ago", "You changed Price"). The owner can comment; the COO reads comments.
4. **Docs**: rich-text pages (headings, lists, links, bold/italic, simple tables). The COO keeps
   them current: how we work, prices, suppliers, policies. Edit in place.
5. **Ask**: a box on the Library page ("What did we charge Café Luna last time?") that goes to the
   chat with the library as context.

Not in v1 (the COO is the automation): automation builder, dashboard widgets, forms, per-table
permissions, formulas, column resizing, attachments (v2: files stored next to the doc).

Look: Steerable's own tokens and fonts (theme.css), not a copy of monday's brand. Status colours
from the existing tones (accent, sky, amber, rose, violet, neutral). Checked for WCAG AA in both
themes, phone layout: table scrolls sideways with the first column sticky; kanban scrolls.

## Data model

Stored in the company folder so it's exported, imported and moved with the company, and no
extra service is needed (self-hosted and cloud alike). SQLite file `library.db` next to ops.db
(add it to EXPORT_PATHS and IMPORTABLE in agent_api.py / container/entrypoint.py).

```sql
CREATE TABLE tables   (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, icon TEXT,
                       created TEXT, updated TEXT, archived INTEGER DEFAULT 0);
CREATE TABLE columns  (id TEXT PRIMARY KEY, table_id TEXT REFERENCES tables(id), name TEXT NOT NULL,
                       type TEXT CHECK (type IN ('text','longtext','number','date','status','person','link','checkbox')),
                       options TEXT,            -- JSON: status labels [{id,label,tone}], number unit
                       position INTEGER);
CREATE TABLE groups   (id TEXT PRIMARY KEY, table_id TEXT, name TEXT, tone TEXT, position INTEGER);
CREATE TABLE rows     (id TEXT PRIMARY KEY, table_id TEXT, group_id TEXT, position INTEGER,
                       cells TEXT NOT NULL,     -- JSON {column_id: value}
                       created TEXT, updated TEXT, archived INTEGER DEFAULT 0);
CREATE TABLE history  (id INTEGER PRIMARY KEY, row_id TEXT, doc_id TEXT, who TEXT CHECK (who IN ('you','coo','autopilot')),
                       what TEXT, at TEXT);     -- "set Status to Contacted", comments too (what='comment: ...')
CREATE TABLE docs     (id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,  -- Markdown
                       created TEXT, updated TEXT, archived INTEGER DEFAULT 0);
CREATE VIRTUAL TABLE search USING fts5(kind, ref, title, text);   -- tables' rows and docs
```

Ids are short random strings (like `t_3kq9`), never names, so renames are safe. Deletes are
archives (the owner can restore; the export includes them).

memory/*.md: keep them as the COO's working memory, and show each as a read-only doc in the
library ("From Juno's memory"); later, migrate the owner-facing ones into docs.

## Engine (template/scripts/library.py)

One module, used by the agent API, by routines (import), and by the COO in chat (CLI, allowed as
`.venv/bin/python scripts/library.py ...`):

```
library.py tables                                   # list
library.py create-table "Leads" --columns "Name:text, Status:status(New|Contacted|Won|Lost), Value:number($), Next step:date"
library.py add-row Leads --group "This week" --set Name="Café Luna" Status=New Value=400
library.py update-row Leads <row id or Name value> --set Status=Contacted
library.py find Leads --where Status=New            # JSON out
library.py doc "Pricing" --from-file drafts/pricing.md   # create or replace
library.py search "Café Luna"
```

Python API for routines: `library.table("Leads").add(...)`, `.update(...)`, `.rows(where=...)`,
`library.doc("Pricing").write(markdown)`. Every write records history with who = coo (chat),
autopilot (routines, STEERABLE_CONTEXT=routine) or you (agent API).

Rules for the COO (add to template/CLAUDE.md and bridge.APP_NOTES):
- Keep what the owner would want to look up in the library: leads, customers, suppliers, orders,
  conversations, prices, how-tos. Don't make a table for one-off data.
- One table per kind of thing; reuse before creating; name tables in the owner's words.
- Never delete; archive. Tell the owner in a sentence when you create a table or doc.
- If a work tool is connected (monday, Airtable, Notion), keep that kind of record there instead
  and only link to it (see below).

## Agent API (template/scripts/agent_api.py)

```
GET  /v1/library                         {tables: [...], docs: [...]}  (names, counts, updated)
GET  /v1/library/tables/<id>             table, columns, groups, rows (paged: ?offset&limit, default 500)
POST /v1/library/tables/<id>/rows        {group_id, cells}                 add
POST /v1/library/rows/<id>               {cells}  partial update            (history: who=you)
POST /v1/library/rows/<id>/move          {group_id, position}
POST /v1/library/rows/<id>/archive
GET  /v1/library/rows/<id>               row + history
POST /v1/library/rows/<id>/comment       {text}
POST /v1/library/tables/<id>/columns     add/rename/retype (owner can too)
GET  /v1/library/docs/<id>               POST /v1/library/docs/<id> {title, body}
GET  /v1/library/search?q=
GET  /v1/library/tables/<id>/export.csv  (raw response, like /v1/export)
```

Validation in library.py: values must fit the column type (status must be one of its labels;
date ISO; number numeric). Errors are plain sentences.

## Dashboard (open-source package, ../steerable/dashboard)

- `backend/types.ts`: LibraryOverview, LibraryTable, LibraryColumn (+ StatusOption), LibraryRow,
  LibraryDoc, RowHistory. `CompanyBackend` gains library methods (mirror the API); `agent.ts`
  implements them; `mock.ts` gets a sample "Leads" table, "Wholesale cafes" table, and a
  "Pricing" doc for demos; the cloud's `self-hosted.ts` returns empty/elsewhere.
- `DashboardActions` gains: updateCells, addRow, moveRow, archiveRow, comment, saveDoc,
  addColumn. Hosts implement them in local/actions.ts and src/lib/actions.ts.
- Screens: `screens/library.tsx` (list + search + ask box), `screens/library-table.tsx`
  (table/kanban toggle), `screens/library-row.tsx` (item page), `screens/library-doc.tsx`.
- Components (client): `table-grid.tsx` (groups, sticky first column, typed cell editors with
  optimistic updates via useOptimistic, keyboard: arrows, Enter, Esc), `status-cell.tsx`
  (full-colour cell, popover with the labels), `kanban.tsx` (native drag and drop, no library),
  `doc-editor.tsx` (Markdown with a small toolbar; render with the chat's Markdown renderer).
- Nav: add "Library" (icon: Library or Table) to ITEMS in nav.tsx, desktop; on phones put it in
  the account header like Connections.
- Routes, one-liners in both hosts: /library, /library/t/[id], /library/r/[id], /library/d/[id].
  Cloud: add `/library/:path*` to src/proxy.ts matcher; wrap in ForHosting like other screens.
- Plain language in the UI: "table", "row" are fine; never "schema", "record", "workflow".

## Reusing Teable's code

Teable (github.com/teableio/teable) splits its license: the apps (nestjs-backend, nextjs-app) are
AGPL-3.0, everything under `packages/` is MIT. `@teable/sdk` (MIT) has a canvas spreadsheet grid
(`packages/sdk/src/components/grid`), cell editors, filter, sort, group, record view and a
Markdown editor.

- OK: copy MIT parts into the dashboard, keeping Teable's copyright and MIT notice in the copied
  files (and a NOTICE entry). Best candidate: the canvas grid, for tables with thousands of rows.
- Not OK: copying from the AGPL apps into steerable-cloud (private).
- Effort: the SDK is wired to Teable's backend (its hooks, models, API client), targets React 18
  (we're on 19) and pulls in heavy deps (Plate editor and more). Lift the grid component alone
  and adapt it to our data; don't take the whole SDK.
- Suggested: v1 with our own DOM table (simpler, accessible, fine to a few thousand rows); swap
  in the Teable canvas grid later if tables get big.

### What to study in Teable before building (read for how, write our own)

Clone: `git clone --depth 1 https://github.com/teableio/teable`. All paths below are MIT
(`packages/`), but treat them as reference: we write our own code.

- **Field types and validation**: `packages/core/src/models/field/derivate/*.field.ts` (one class
  per type: how each validates, converts and displays a value), `select-option.schema.ts`
  (status/select labels and colours), `cell-value-validation.ts`. Model our column types on this.
- **Cell editors**: `packages/sdk/src/components/cell-value-editor/` (one editor per type,
  `CellEditorMain.tsx` picks it) and `grid/components/editor/`.
- **The grid** (canvas, for big tables): `packages/sdk/src/components/grid/`: `Grid.tsx`,
  `RenderLayer.tsx` + `renderers/` (drawing), `InteractionLayer.tsx` + `hooks/useSelection.ts`,
  `useKeyboardSelection.ts`, `useColumnFreeze.ts`, `useDrag.ts` (selection, keys, frozen first
  column, drag), `managers/coordinate-manager` (row/column positions, virtual scrolling).
- **Record page**: `packages/sdk/src/components/expand-record/` (`RecordEditor.tsx`,
  `RecordHistory.tsx`: our item page and its history).
- **Filter, sort, group**: `packages/sdk/src/components/filter/`, `sort/`, `group/` (condition
  builder UI and how conditions are represented).

## Their own tool (monday, Airtable, Notion)

- Already one-click in Connections (cloud catalog and the self-hosted tools catalog).
- library.py checks integrations.connected(): if monday/Airtable/Notion is connected, the COO is
  told (CLAUDE.md + chat notes) to keep tables there through their MCP tools, and the library
  shows a card per connected tool: "Your boards live in monday" with a link, plus any tables the
  COO still keeps locally.
- v2: read-through view of their boards inside the library (via mcp_call), read-only.

## Tests

- Engine (`tests/test_library.py`): create table with typed columns, add/update/find rows,
  validation errors, history who=coo/autopilot/you, archive, docs, search (fts5), CSV export,
  agent API endpoints, export/import includes library.db, plain-words check on API output.
- Dashboard: typecheck, lint; a browser run: create a table via CLI, open it, edit a status cell,
  switch to kanban and drag, open a row, comment, edit a doc, phone layout, both themes.
- Cloud: dashboard:update, typecheck, lint, the routes behind ForHosting.

## Build order

1. library.py + library.db + CLI + tests.
2. Agent API endpoints + tests.
3. Types, agent client, mock, actions (both hosts).
4. Library list + table grid (typed cells, groups, inline edit) + item page.
5. Kanban, docs, search, ask box, CSV export.
6. COO instructions (CLAUDE.md, APP_NOTES, builder: routines write to the library), and the
   "their own tool" cards.
7. Import tables from an outside tool (Teable, Airtable)? Only if the owner wants; until then it stays connected.
