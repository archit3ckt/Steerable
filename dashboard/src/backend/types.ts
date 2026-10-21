/**
 * The contract between the web app and a customer's company.
 *
 * Every type here is a plain-language view of something the Steerable engine already
 * keeps inside the customer's container:
 *
 *   Decision      tasks.md `needs:approval` lines, incidents in `awaiting_ceo`,
 *                 and ops.db missions in "Waiting on CEO"
 *   TimelineEvent ops.db activity, logs/runs.jsonl and resolved incidents
 *   Routine       tasks.md lines tagged `@workflow:` (the heartbeat's schedule)
 *   Todo          tasks.md lines without `@workflow:`
 *   Goal/Project  ops.db goals and missions
 *   Spend         logs/spend.jsonl against MONTHLY_BUDGET_USD
 *
 * The UI never shows engine words (workflow, incident, heartbeat, exit code).
 * Backends translate them into these types.
 */

export type ISODate = string;

export type Company = {
  id: string;
  name: string;
  ownerFirstName: string;
  /** What the owner calls their COO. */
  cooName: string;
};

export type Health = {
  state: "good" | "attention" | "problem";
  /** One sentence for the owner, e.g. "Everything's running smoothly". */
  summary: string;
};

export type Brief = {
  /** The COO's short morning note, in plain words. */
  headline: string;
  points: string[];
};

export type Spend = {
  monthToDateUsd: number;
  /** 0: no cap (a self-hosted engine on a Claude subscription). */
  monthlyCapUsd: number;
};

export type DecisionKind =
  /** Something new the COO wants to start (an approval). */
  | "approval"
  /** Something went wrong and the COO prepared a fix or a reply. */
  | "problem"
  /** A direction-level choice between options. */
  | "choice";

export type DecisionOption = {
  id: string;
  label: string;
  /** What happens if the owner picks this, in one short line. */
  outcome?: string;
  tone?: "primary" | "neutral" | "quiet";
  /** Picking it asks the owner for a few words ("What should it do differently?"), sent with decide(). */
  input?: { placeholder: string; optional?: boolean };
  /** For a choice of direction (display "choice"): its case, a few short points each, and short facts. */
  pros?: string[];
  cons?: string[];
  tags?: string[];
};

/**
 * Something the owner authorizes by signing (display "authorize"): switching a routine on, letting it
 * run on its own. Read like what it is, then signed with optionId; the decision's other options stay.
 */
export type Authorization = {
  title: string;
  /** What it will do, a sentence or two each. */
  does: string[];
  limits: string[];
  wont: string[];
  /** How to take it back. */
  undo: string;
  /** How it's done so far (its practice or watched runs). */
  record?: string;
  optionId: string;
};

/** Something the owner signed; undo takes it back (the routine is switched off, or watched again). */
export type SignedDecision = { id: string; title: string; kind: "switch_on" | "trust"; at: ISODate; undone?: ISODate };

export type Decision = {
  id: string;
  kind: DecisionKind;
  urgent: boolean;
  title: string;
  /** Why this is on the owner's desk, in two or three sentences. */
  context: string;
  /** The COO's pick and why. An empty optionId means it has no pick: the owner chooses. */
  recommendation: { optionId: string; why: string };
  options: DecisionOption[];
  /** Small facts that help decide: cost, time saved, who it affects. */
  facts?: { label: string; value: string }[];
  /** Something the COO already prepared, like an email draft. */
  draft?: { label: string; body: string };
  /** A service the owner needs to connect first (a key in integrations/providers.json). */
  connect?: { provider: string; label: string };
  /** Things the COO noticed that the owner should weigh first, one sentence each. */
  concerns?: string[];
  /** A practice or watched run to look at before deciding: its id for trace(). */
  trace?: string;
  goal?: string;
  createdAt: ISODate;
  /** How to show it: options as cards to compare ("choice"), or a document to sign ("authorize", with `authorize`). Absent: a quick one. */
  display?: "choice" | "authorize";
  authorize?: Authorization;
};

export type Actor = "coo" | "you" | "autopilot";

export type TimelineKind =
  | "done" // work completed
  | "fixed" // a problem your business manager fixed on its own
  | "decided" // a decision the owner made
  | "learned" // your business manager got better at something
  | "milestone" // a goal or project moved forward
  | "heads-up"; // something worth knowing, no action needed

export type TimelineEvent = {
  id: string;
  at: ISODate;
  kind: TimelineKind;
  actor: Actor;
  title: string;
  detail?: string;
  goal?: string;
  costUsd?: number;
  /** From decide(): a page the owner goes to next, like the sign-up for an account they approved. */
  next?: string;
  /** A routine run or chat turn that changed the library: its id for runChanges(), and how much. */
  run?: string;
  changes?: TableChanges[];
};

/** "setting-up": approved, and the COO is building and testing it (or waiting on the owner in Decisions). */
export type RoutineStatus = "running" | "paused" | "needs-approval" | "setting-up";

export type Routine = {
  id: string;
  name: string;
  /** What it does, in plain words. */
  description: string;
  /** e.g. "Every morning", "Every Monday". */
  schedule: string;
  /** When it runs next, in the company's time zone and the owner's words ("Today at 13:00", "Once you approve it"). */
  nextRun?: string;
  status: RoutineStatus;
  /** Who paused it. The owner can restart only routines they paused themselves; the COO's
   * pauses end when the problem behind them is resolved in Decisions. */
  pausedBy?: "you" | "coo";
  lastRun?: { at: ISODate; ok: boolean; summary: string };
  goal?: string;
  monthlyCostUsd: number;
  /** Rough time it saves the owner, for the "hours saved" number. */
  hoursSavedPerWeek: number;
  /** Its first runs are watched: anything it can't undo is checked before it happens. */
  watching?: boolean;
  /**
   * How far along it is: proposed (waiting for the owner's OK), building (being set up), ready (built and
   * tried in a practice run, waiting for the owner to look), watched (live, checked first), trusted (on its own).
   * Paused is separate (status): a routine at any stage can be paused.
   */
  stage?: RoutineStage;
};

export type RoutineStage = "proposed" | "building" | "ready" | "watched" | "trusted";

/** One step in a routine's flow chart (workflows/<name>.flow.json in the engine). */
export type FlowStep = {
  kind: "trigger" | "read" | "think" | "write" | "ask" | "send" | "save";
  /** What happens, in a few plain words. */
  label: string;
  /** The app or site it uses, like Gmail. */
  service?: string;
  detail?: string;
};

/**
 * How many rows one run changed in one library table (library.run_counts in the engine). Each row
 * counts once: added (new, even if changed again in the same run), changed, archived or restored.
 */
export type TableChanges = { table: string; tableId: string; added?: number; changed?: number; archived?: number; restored?: number };

/** `id` names the run for runChanges(); `changes` is set when it changed the library; `trace`, when it was watched. */
export type RoutineRun = { id?: string; at: ISODate; ok: boolean; summary: string; changes?: TableChanges[]; trace?: string };

/**
 * One thing a practice or watched run did (runtrace.py in the engine), in order:
 * step       a step of its flow chart started
 * browse     it clicked, typed or opened a page (with a picture)
 * would      something it can't undo, in a practice run: not done
 * did        ... in a watched run: checked, then done
 * held       ... in a watched run: held back, with why
 * record     a row it would add or change in the library
 * message    news it would send the owner
 * draft      a draft or report it would save
 * unasked    a website was sent something it didn't say first
 */
export type TraceEvent = {
  n: number;
  at: ISODate;
  kind: "step" | "browse" | "would" | "did" | "held" | "record" | "message" | "draft" | "unasked";
  title: string;
  detail?: string | null;
  why?: string | null;
  url?: string | null;
  /** A picture of the page, for traceShot(). */
  shot?: string;
  /** In that picture, the element it clicked, typed into or is about to press: [x, y, width, height] as fractions of it. */
  box?: [number, number, number, number];
  /** The engine caught it, not the routine (it didn't ask first). */
  unasked?: boolean;
};

/** A routine's practice run (before it's switched on) or a watched run (its first live runs), step by step. */
export type Trace = {
  id: string;
  routineId: string;
  routine: string;
  kind: "practice" | "watched";
  startedAt: ISODate;
  finishedAt: ISODate | null;
  ok: boolean | null;
  /** The last thing it said, in plain words. */
  summary: string | null;
  /** The COO's read of a practice run: what it will do, and what it doesn't seem to handle. */
  review: { summary: string; concerns: string[] } | null;
  events: TraceEvent[];
};

/** A tags or files cell holds a list (labels; file ids). */
export type CellValue = string | number | boolean | null | string[];

/**
 * The library: tables of records the owner looks up and changes, kept by the COO and its routines
 * (library.py in the engine, library.db in the company folder). Nothing is deleted: rows are archived.
 */
export type LibraryColumnType = "text" | "longtext" | "number" | "date" | "status" | "person" | "link" | "checkbox" | "relation" | "tags" | "files";
export type LibraryColumn = {
  id: string;
  name: string;
  type: LibraryColumnType;
  /** status (and tags, when limited): its labels, in order; number: a unit like "$"; relation: the table it links to. */
  options: { labels?: string[]; unit?: string; table?: string };
};
export type LibraryTableSummary = { id: string; name: string; description: string; rows: number; updated: ISODate; columns: string[] };
/** Cells by column name. A relation's value is the related row's id (its label is in LibraryPage.related). */
export type LibraryRow = { id: string; key: string | null; created: ISODate; updated: ISODate; archived: boolean; cells: Record<string, CellValue> };
/** How a view shows its table; the owner's changes to filters, sort, grouping and fields are kept in it. */
export type LibraryViewConfig = {
  sort?: string;
  dir?: "asc" | "desc";
  where?: Record<string, string>;
  hidden?: string[];
  /** grid: rows grouped by this column. */
  group?: string;
  /** kanban: its status column; calendar: its date column. */
  by?: string;
};
/** A tab over a table: a grid, a board (kanban) by a status, or a calendar by a date. */
export type LibraryView = { id: string; name: string; type: "grid" | "kanban" | "calendar" | "cards"; config: LibraryViewConfig };
export type LibraryComment = {
  id: string;
  who: "you" | "coo" | "autopilot";
  text: string;
  at: ISODate;
  /** The owner asked the COO to act on it; status says how that went. */
  ask: boolean;
  status: "asked" | "answered" | "failed" | null;
};
export type LibraryFileInfo = { name: string; kind: string };

/**
 * A book the owner teaches the COO (books.py): studying (the COO is reading it), ready (ideas wait
 * for the owner), learned (all answered), paused (its skills taken away for now) or failed.
 */
export type Book = {
  id: string;
  title: string;
  author: string;
  why: string;
  chapters: number;
  words: number;
  status: "studying" | "ready" | "learned" | "paused" | "failed";
  /** While studying, in plain words: "Reading chapter 4 of 12". */
  progress: string | null;
  /** Why it failed, in plain words. */
  error: string | null;
  added: ISODate;
  studied: ISODate | null;
  /** Ideas waiting for the owner, and ones they added. */
  waiting: number;
  approved: number;
};
/** What the COO proposes after studying a book. A skill's body is markdown; a routine's and a goal's are fields. */
export type BookIdea = {
  id: string;
  kind: "skill" | "routine" | "goal";
  name: string;
  summary: string;
  /** Where in the book: "ch. 3". */
  source: string;
  body: string | Record<string, unknown>;
  status: "waiting" | "approved" | "declined";
  /** What adding it did: "Added to your goals." */
  note: string | null;
};
/**
 * A dashboard over the library (dashboards.py): charts the engine counts from library tables, made by
 * the COO when asked or by the owner in the Library. A widget is a description, never code: what it
 * counts (a table, filters like a view's, a measure) and how it's shown.
 */
export type DashboardWidgetType = "number" | "bars" | "trend" | "list" | "progress";
export type DashboardMeasure = "count" | "sum" | "average" | "min" | "max";
export type DashboardWidgetSpec = {
  type: DashboardWidgetType;
  title?: string;
  /** The table's id (or name, when writing one). */
  table: string;
  /** Column: value, like a view's filters ("" = empty). */
  where?: Record<string, string>;
  /** Not for list. sum/average/min/max need a number column. */
  measure?: DashboardMeasure;
  column?: string;
  /** A date column, or "added" (when each row was added). */
  date?: string;
  /** number and progress: only this period (number also shows the one before). */
  period?: "week" | "month" | "quarter" | "year";
  /** trend: one bar per day, week or month, the last `last` of them. */
  every?: "day" | "week" | "month";
  last?: number;
  /** bars: the column they're by, and how many. list: how many rows. */
  by?: string;
  limit?: number;
  /** list: its order (newest first without) and up to 4 columns. */
  sort?: string;
  dir?: "asc" | "desc";
  show?: string[];
  /** progress: the number it's working toward. */
  goal?: number;
  /** The whole width (trend and list are, unless false). */
  wide?: boolean;
};
/** What a widget shows now; which fields depends on its type. */
export type DashboardWidgetData = {
  /** A number column's unit (like "$") when the measure sums or averages one. */
  unit?: string;
  /** number, progress */
  value?: number | null;
  previous?: number | null;
  goal?: number;
  /** bars: each value of `by` (filter: that value for the table's grid, "" for empty) */
  items?: { label: string; value: number | null; filter: string }[];
  by?: string;
  more?: number;
  /** trend: each day, week or month by its first day */
  points?: { start: string; value: number | null }[];
  /** list */
  columns?: { name: string; type: LibraryColumnType; unit?: string }[];
  rows?: { id: string; cells: Record<string, CellValue> }[];
  total?: number;
  related?: Record<string, string>;
};
export type DashboardWidget = DashboardWidgetSpec & {
  id: string;
  title: string;
  tableName: string | null;
  data?: DashboardWidgetData;
  /** Its table or a column is gone: what to fix, in plain words. */
  error?: string;
};
export type DashboardSummary = {
  id: string;
  name: string;
  description: string;
  widgets: number;
  /** The first few charts' titles, for the Library's cards. */
  titles: string[];
  createdAt: ISODate;
  updatedAt: ISODate;
  updatedBy: Actor;
};
/** A table a widget can count, with its columns (for the editor). */
export type DashboardSource = { id: string; name: string; columns: { name: string; type: LibraryColumnType; labels?: string[]; unit?: string }[] };
/** The owner's request to the COO for a dashboard (or a change to one), worked on in the background. */
export type DashboardAsk = {
  id: string;
  dashboardId: string | null;
  text: string;
  status: "asked" | "answered" | "failed";
  reply: string | null;
  /** The dashboard the COO saved for it. */
  made: string | null;
  at: ISODate;
};
export type DashboardDetail = Omit<DashboardSummary, "widgets"> & { widgets: DashboardWidget[]; sources: DashboardSource[]; asks: DashboardAsk[] };

/** A plan of the business (business plan, marketing plan...): one per subject, kept up to date (plans.py). */
export type Plan = {
  id: string;
  title: string;
  /** business, marketing, sales, financial, operations, hiring, product, launch, customer or other. */
  kind: string;
  /** The current version's number; every save adds one. */
  version: number;
  createdAt: ISODate;
  updatedAt: ISODate;
  updatedBy: Actor;
  /** Why the last version was saved, in a sentence. */
  note: string;
  /** Its first line of text. */
  summary: string;
  words: number;
};

export type PlanVersion = { n: number; at: ISODate; who: Actor; note: string; restoredFrom?: number | null };
export type PlanDetail = Plan & { body: string; versions: PlanVersion[] };
/** One line of what a version changed; "skip" folds unchanged lines away. */
export type PlanChange = { op: "same" | "add" | "del"; text: string } | { op: "skip"; count: number };
export type PlanVersionDetail = PlanVersion & { body: string; changes: PlanChange[] };

export type BookPassage = { book: string; bookId: string; chapter: number; chapterTitle: string; passage: string };
export type BookDetail = Book & {
  proposals: BookIdea[];
  /** The COO's notes, chapter by chapter (markdown). */
  notes: string;
  /** Chapter titles, in order. */
  contents: string[];
  /** With a search: matching passages, the words marked [like this]. */
  passages: BookPassage[];
};

export type LibraryQuery = {
  /** Every word must appear in a text cell. */
  q?: string;
  sort?: string;
  dir?: "asc" | "desc";
  /** Column name → value it must equal ("" for empty). */
  where?: Record<string, string>;
  archived?: boolean;
  /** Rows ordered by this column first, with a count per value in LibraryPage.groups. */
  group?: string;
  /** A date column and an inclusive range, YYYY-MM-DD (the calendar's weeks). */
  between?: [string, string, string];
  offset?: number;
  limit?: number;
};
export type LibraryPage = {
  table: { id: string; name: string; description: string };
  columns: LibraryColumn[];
  /** Rows matching the query, all pages. */
  total: number;
  rows: LibraryRow[];
  /** Number columns' sums over every matching row. */
  sums: Record<string, number>;
  /** Related rows' labels, by id. */
  related: Record<string, string>;
  /** The table's views, in tab order (always at least one). */
  views: LibraryView[];
  /** With query.group: each value and how many matching rows have it, in order. */
  groups: { value: CellValue; count: number }[];
  /** Attached files' names, by id. */
  files: Record<string, LibraryFileInfo>;
};
/** who: "you" (the owner, in the app), "coo" (the chat) or "autopilot" (a routine). */
export type LibraryRowDetail = LibraryRow & {
  history: { who: "you" | "coo" | "autopilot"; what: string; at: ISODate }[];
  comments: LibraryComment[];
  files: Record<string, LibraryFileInfo>;
};

/** What one run changed in one table, a page of rows at a time (GET /v1/runs/<run>/changes). */
export type RunChanges = {
  tables: TableChanges[];
  table: {
    id: string;
    name: string;
    /** The columns worth showing: what identifies a row, and every column the run set. */
    columns: { name: string; type: string }[];
    /** `before` is there only on cells the run changed (not on new rows). Relations come as words. */
    rows: { id: string; change: "added" | "changed" | "archived" | "restored"; cells: Record<string, { value: CellValue; before?: CellValue }> }[];
    /** Pass as `after` for the next page; null on the last. */
    next: number | null;
    /** False once old values are past the engine's keeping (90 days): only counts are left. */
    details: boolean;
  } | null;
};

/** A routine's own page: everything on its card, its steps, and its recent runs. */
/** Items that reached each step of a flow chart, by step index ("2": 150); steps that didn't say aren't there. */
export type FlowCounts = Record<string, number>;
export type FlowProgress = { step: number; done: number; total: number | null };

export type RoutineDetail = Routine & {
  /** Null until its steps are written down. */
  flow: FlowStep[] | null;
  /** The COO is writing its steps down now. */
  flowPending: boolean;
  /** Its code, for the code view (a toggle on the steps). */
  code?: string;
  /** For each step in flow, the [first, last] line ranges of code that do it; null until worked out. */
  codeMap?: [number, number][][] | null;
  /** Which lines do each step is being worked out now. */
  codeMapPending?: boolean;
  /** Newest first. */
  runs: RoutineRun[];
  /** It's being set up (built) right now: what the COO has done so far, in plain words. */
  building?: { since: ISODate; steps: string[]; /** An approved change to a running routine, not a new one. */ change?: string };
  /**
   * It's running right now; step is the index in flow it's on, when the routine reports it. counts: how
   * many items reached each step so far (by step index), for the flow chart's arrows; progress: how far
   * it's got through a list in a step (total null when it can't tell).
   */
  runningNow?: { since: ISODate; step: number | null; counts?: FlowCounts; progress?: FlowProgress };
  /** How many items reached each step in its last run, until the next one starts. */
  lastFlow?: { at: ISODate; counts: FlowCounts };
  /** Built and tried in a practice run, waiting for the owner to look (the decision's id), maybe as a change. */
  ready?: { trace: string; decision: string; change?: string };
  /** It's watched: runs so far, clean ones in a row, and how many clean ones before the COO asks to stop. */
  watch?: { since: ISODate; runs: number; clean: number; needed: number; /** Why it's watched: new, owner, problem or fixed. */ why?: "new" | "owner" | "problem" | "fixed" };
  /** How it's done lately (live routines): runs and problems in the last `days`, things held back, its last problem, since when it's on its own. */
  record?: { days: number; runs: number; problems: number; held: number; lastProblem: ISODate | null; onItsOwnSince: ISODate | null };
};

/** Something only the owner has that the COO asked for (a private link, a key). Never the value itself. */
export type ValueRequest = {
  name: string;
  /** What it is, in the owner's words: "your Reddit inbox link". */
  label: string;
  why: string | null;
  /** Where they find it. */
  url: string | null;
  hint: string | null;
  saved: boolean;
};

export type Todo = {
  id: string;
  title: string;
  owner: "you" | "coo";
  due?: ISODate;
  done: boolean;
  goal?: string;
};

export type ProjectStatus = "planned" | "in-progress" | "waiting-on-you" | "blocked" | "done";

export type Project = {
  id: string;
  title: string;
  status: ProjectStatus;
  owner: "you" | "coo" | "autopilot";
  /** What "done" looks like, in one line. */
  doneWhen: string;
  /** For the goals timeline: when it started, when it's due, and when it was finished. */
  startedAt?: ISODate;
  due?: ISODate;
  finishedAt?: ISODate;
};

export type Goal = {
  id: string;
  title: string;
  why: string;
  metric: { label: string; current: number; target: number; unit?: "$" | "%" | "" };
  /** When it was set. With `due`, the goals timeline compares progress with the time used. */
  startedAt?: ISODate;
  due?: ISODate;
  pace: "ahead" | "on-track" | "behind";
  projects: Project[];
};

export type ChatMessage = {
  id: string;
  /** "divider": where the owner started a new conversation (no text). The COO's memory of the thread starts there. */
  from: "you" | "coo" | "divider";
  /** Markdown, from the COO. */
  text: string;
  at: ISODate;
  /** What the COO did on the way to this reply, and what it said as it went. */
  steps?: ChatStep[];
  /** Pictures and files the owner attached (the engine's scripts/files.py keeps them). */
  files?: ChatFile[];
  /** What the COO made or changed in the library while writing this reply, shown with it. */
  artifacts?: ChatArtifacts;
};

/**
 * A chat turn's "artifacts": the same plans and tables as in the Library, not copies. `run` names the
 * turn for runChanges(); `changes`: rows it added, changed or archived per table; `plans`: the plans
 * it saved, at the version it saved (created: it wrote the first version).
 */
export type ChatArtifacts = {
  run: string;
  changes?: TableChanges[];
  plans?: { id: string; title: string; version: number; note: string; created?: boolean }[];
  /** The reply proposes something worth testing before the owner acts on it (the engine's checks.py), and which test fits. */
  check?: { kind: CheckKind };
};

/**
 * The tests a proposal can get. customers: customers go through it (a page, an offer, an email);
 * numbers: every figure recomputed; week: an ordinary week run through it; pushback: the strongest objections.
 */
export type CheckKind = "customers" | "numbers" | "week" | "pushback";

/**
 * A test of a chat reply that proposed something: one AI call with fixed points of view. A finding
 * names a concrete moment (and, for customers and pushback, two voices hit it); edits are exact
 * replacements in the proposal, `applies` when its text is there. With `plan`, the test was of that
 * plan at that version, and applyCheck() saves the picked edits as a new version; planChanged: it
 * has changed since, so it can be tested again. `page`: a live page it went through in a real browser.
 */
export type Check =
  | { status: "none" }
  | { status: "running"; kind: CheckKind; title: string; plan?: { id: string; version: number } }
  | { status: "failed"; kind: CheckKind; title: string; error: string }
  | {
      status: "done";
      kind: CheckKind;
      title: string;
      finishedAt: ISODate;
      plan?: { id: string; version: number };
      planChanged?: boolean;
      page?: string;
      applied?: string[];
      result: CheckResult;
    };

export type CheckResult = {
  /** One or two sentences: did it hold up, and the one thing to change if any. */
  summary: string;
  /** Who went through it, what happened, and where they got stuck ("" if nowhere). */
  voices: { who: string; went: string; stuck: string }[];
  findings: { id: string; moment: string; problem: string; voices: string[]; fix: string }[];
  /** What worked and should stay. */
  held: string[];
  edits: { id: string; finding: string; find: string; replace: string; why: string; applies: boolean }[];
};

/**
 * A page of the conversation, oldest first: the latest messages, or those before, after or
 * around one. hasEarlier/hasLater: there's more beyond it. reset: the message asked about wasn't
 * found, so this is the latest page instead.
 */
export type ChatPage = { messages: ChatMessage[]; hasEarlier: boolean; hasLater: boolean; reset?: boolean };

export type ChatPageQuery = { before?: string; after?: string; around?: string; limit?: number };

/** A file attached in the chat. Its bytes come from CompanyBackend.file(id). */
export type ChatFile = {
  id: string;
  name: string;
  kind: "image" | "pdf" | "text" | "other";
  size: number;
};

/** A file's bytes, with how to serve it: pictures inline, everything else as a download. */
export type FileContent = { data: ArrayBuffer; contentType: string; disposition: string };

/**
 * One line of the COO at work: something it did, in plain words ("Reading your notes"), or
 * {say}: what it said in passing ("Let me check last month's orders first.").
 */
export type ChatStep = string | { say: string };

/** The reply the COO is working on: whether it is, and what it has done so far. */
export type ChatActivity = {
  working: boolean;
  steps: ChatStep[];
};

/**
 * One of the COO's helpers working in the background, for the status panel behind the health
 * line. From the engine's run log and notes (agent_api.py status()): routines (heartbeat runs),
 * chat, setting up routines (builder.py), fixing problems (incident.py), and its own jobs.
 */
export type Helper = {
  id: string;
  name: string;
  /** working: busy right now. needsYou: waiting on the owner (in Decisions). */
  state: "working" | "idle" | "attention" | "needsYou";
  /** One plain sentence, e.g. "Running “Remind cafes to reorder” now". */
  summary: string;
  /** When it last did something, if ever. */
  lastAt: string | null;
};

export type BackgroundStatus = {
  /** The engine's clock when it answered, for "5 min ago" without reading the browser's. */
  now: string;
  helpers: Helper[];
};

/** The COO's first conversation with the owner: learning the business, then proposing a first routine. */
export type Onboarding = {
  done: boolean;
  /** The COO has opened the conversation (or it's done). */
  started: boolean;
};

export type Overview = {
  company: Company;
  health: Health;
  brief: Brief;
  spend: Spend;
  stats: { doneThisWeek: number; hoursSavedThisWeek: number };
};

/**
 * One customer's company. The mock backend implements it in memory; the real one (agent.ts)
 * calls the agent API inside the customer's container, which returns these same shapes.
 */
export interface CompanyBackend {
  overview(): Promise<Overview>;
  decisions(): Promise<Decision[]>;
  /** Small decisions settled for the owner this week (when they let the COO decide small things); newest first. */
  settledDecisions?(): Promise<SettledDecision[]>;
  /** Take one back: it returns to their decisions. */
  undoSettled?(id: string): Promise<void>;
  /** What the owner authorized by signing, newest first. */
  signedDecisions?(): Promise<SignedDecision[]>;
  /** Take a signature back: the routine is switched off, or watched again. */
  undoSigned?(id: string): Promise<void>;
  /** The owner's choices about how the COO works with them. */
  preferences?(): Promise<Preferences>;
  setPreferences?(changes: Partial<Preferences>): Promise<Preferences>;
  /** `note`: the owner's words, for an option with `input`. */
  decide(decisionId: string, optionId: string, note?: string): Promise<TimelineEvent>;
  timeline(limit?: number): Promise<TimelineEvent[]>;
  routines(): Promise<Routine[]>;
  /** What the COO asked the owner for, by name (the decision's "Add …" button opens it). */
  valueRequest(name: string): Promise<ValueRequest | null>;
  /** The owner gives it. Kept private; routines read it, no AI does. */
  saveValue(name: string, value: string): Promise<void>;
  /** One routine with its steps and recent runs, or null if there's no such routine. */
  routine(routineId: string): Promise<RoutineDetail | null>;
  setRoutinePaused(routineId: string, paused: boolean): Promise<void>;
  /** Run it once now, as its schedule would ("Run now"); the schedule stays as it was. */
  runRoutine(routineId: string): Promise<void>;
  /** Watch its runs (check what it can't undo first), or let it run on its own. */
  watchRoutine(routineId: string, watch: boolean): Promise<void>;
  /** A practice or watched run, step by step; null when it's gone (kept 30 days). */
  trace(traceId: string): Promise<Trace | null>;
  /** A picture from a trace (TraceEvent.shot). */
  traceShot(traceId: string, shot: string): Promise<FileContent>;
  /** The library's tables, most recently changed first; `archived`: the archived ones instead. */
  library(options?: { archived?: boolean }): Promise<LibraryTableSummary[]>;
  /** A page of one table (by id or name); null if there's no such table. */
  libraryTable(tableId: string, query?: LibraryQuery): Promise<LibraryPage | null>;
  libraryRow(tableId: string, rowId: string): Promise<LibraryRowDetail | null>;
  /** Add a row (rowId null) or change some of its cells (null clears one). Values are checked; a bad one throws in plain words. */
  saveLibraryRow(tableId: string, rowId: string | null, cells: Record<string, CellValue>): Promise<LibraryRow>;
  setLibraryRowArchived(tableId: string, rowId: string, archived: boolean): Promise<void>;
  /** A whole table out of the Library, or back. Nothing in it is deleted; an archived table doesn't open. */
  setLibraryTableArchived(tableId: string, archived: boolean): Promise<void>;
  /** Add a view (viewId null) or change its name or settings. */
  saveLibraryView(tableId: string, viewId: string | null, view: { name?: string; type?: LibraryView["type"]; config?: LibraryViewConfig }): Promise<LibraryView>;
  /** Remove a view (never the last one; the rows stay). */
  deleteLibraryView(tableId: string, viewId: string): Promise<void>;
  /** A comment on a row; ask: the COO acts on it and answers under it (and in the chat). */
  commentLibraryRow(tableId: string, rowId: string, text: string, ask: boolean): Promise<LibraryComment>;
  /** The rows a query shows, as a spreadsheet. */
  exportLibraryTable(tableId: string, query: LibraryQuery, format: "csv" | "xlsx"): Promise<FileContent>;
  /** A CSV or Excel file as a new table (title, else the file's name) or added to the table `into`. */
  importLibrary(name: string, data: ArrayBuffer, options?: { into?: string; title?: string }): Promise<{ table: { id: string; name: string }; added: number; skipped: number }>;
  /** Dashboards over the library, most recently changed first. */
  dashboards(): Promise<DashboardSummary[]>;
  /** A dashboard with what each chart shows now, the tables it can count, and requests to the COO about it. */
  dashboard(dashboardId: string): Promise<DashboardDetail | null>;
  /** Recent requests to the COO for new dashboards (being worked on, or answered today). */
  dashboardAsks(): Promise<DashboardAsk[]>;
  /** An empty dashboard; a taken name is refused. */
  createDashboard(name: string): Promise<{ id: string }>;
  saveDashboard(dashboardId: string, change: { name?: string; description?: string }): Promise<void>;
  removeDashboard(dashboardId: string): Promise<void>;
  /** Add a chart (widgetId null, at the end) or change one in place. */
  saveDashboardWidget(dashboardId: string, widgetId: string | null, widget: DashboardWidgetSpec): Promise<{ id: string }>;
  changeDashboardWidget(dashboardId: string, widgetId: string, action: "remove" | "up" | "down"): Promise<void>;
  /** Ask the COO for a dashboard, or a change to this one; it works on it in the background (and in the chat). */
  askForDashboard(text: string, dashboardId?: string): Promise<DashboardAsk>;
  /** The business's plans, most recently changed first. */
  plans(): Promise<Plan[]>;
  plan(planId: string): Promise<PlanDetail | null>;
  /** One version of a plan: its text and what it changed from the one before. */
  planVersion(planId: string, version: number): Promise<PlanVersionDetail | null>;
  /** The owner's edit: a new version. */
  savePlan(planId: string, body: string, note?: string): Promise<void>;
  /** An earlier version made current again, as a new version. */
  restorePlan(planId: string, version: number): Promise<void>;
  removePlan(planId: string): Promise<void>;
  /** Books the owner taught the COO, newest first. */
  books(): Promise<Book[]>;
  /** One book; with q, the passages matching it. Null if there's no such book. */
  book(bookId: string, q?: string): Promise<BookDetail | null>;
  /** Passages of every book matching q. */
  searchBooks(q: string): Promise<BookPassage[]>;
  /** A book from a file uploaded through the host's chatFilesUrl (EPUB, PDF, Word, text); the COO starts studying it. */
  teachBook(fileId: string, why: string): Promise<Book>;
  /** Add one of the COO's ideas from a book (a skill, a routine, a goal) or skip it. */
  answerBookIdea(bookId: string, ideaId: string, approve: boolean): Promise<void>;
  setBookPaused(bookId: string, paused: boolean): Promise<void>;
  retryBook(bookId: string): Promise<void>;
  /** Forget a book: its skills, text and ideas (routines and goals it led to stay). */
  removeBook(bookId: string): Promise<void>;
  /** What a run (RoutineRun.id, TimelineEvent.run) changed in the library: one table (the first by default), a page of rows. */
  runChanges(runId: string, query?: { table?: string; after?: number; limit?: number }): Promise<RunChanges>;
  todos(): Promise<Todo[]>;
  toggleTodo(todoId: string): Promise<void>;
  goals(): Promise<Goal[]>;
  chat(): Promise<ChatMessage[]>;
  /** The COO's reply, or null if it's still being written (it appears in chat() when ready). */
  /** `files`: ids from uploadFile(), up to 10. */
  send(text: string, files?: string[]): Promise<ChatMessage | null>;
  /** A page of the conversation, for long threads: scrolling up, what's new, a message in context. */
  chatPage(query?: ChatPageQuery): Promise<ChatPage>;
  /** Messages in the whole history containing every word of `query`, newest first (up to 50). */
  searchChat(query: string): Promise<ChatMessage[]>;
  /** Keep a file the owner attaches (up to 20 MB), for a message to name. */
  uploadFile(name: string, data: ArrayBuffer): Promise<ChatFile>;
  file(id: string): Promise<FileContent>;
  /** The test of a COO reply (by message id): none yet, running, failed or done. */
  check(messageId: string): Promise<Check>;
  /** Start testing a reply (the kind it was offered unless given); a finished test comes back as it is unless its plan changed. */
  startCheck(messageId: string, kind?: CheckKind): Promise<Check>;
  /** The owner's picks of a finished test's edits, saved as a new version of the plan it tested. */
  applyCheck(messageId: string, editIds: string[]): Promise<{ plan: string; version: number; applied: string[]; skipped: string[] }>;
  /** Start a fresh conversation: the COO forgets the thread so far (not the business), and the history stays, with a divider. */
  newConversation(): Promise<void>;
  /** What the COO is doing for the reply it's working on, to show while the owner waits. */
  chatActivity(): Promise<ChatActivity>;
  /** What's running in the background, for the status panel. */
  status(): Promise<BackgroundStatus>;
  onboarding(): Promise<Onboarding>;
  /** The COO opens the onboarding conversation, unless it already has. Returns its first message, or null. */
  startOnboarding(): Promise<ChatMessage | null>;
}

/** How the owner wants the COO to work with them (the engine's .cache/preferences.json). */
export type Preferences = {
  /** "Decide small things for me": small questions that are easy to undo are settled with the COO's pick. */
  decideSmall: boolean;
};

/** A small decision the COO settled for the owner (the engine's small_decisions.py). */
export type SettledDecision = { id: string; question: string; chosen: string; why: string; at: ISODate };
