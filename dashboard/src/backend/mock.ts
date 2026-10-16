import type {
  BackgroundStatus,
  ChatFile,
  Check,
  DashboardAsk,
  ChatPage,
  ChatMessage,
  Company,
  CompanyBackend,
  Decision,
  Goal,
  Routine,
  RoutineRun,
  RoutineStage,
  FlowStep,
  Trace,
  TimelineEvent,
  Todo,
} from "./types";
import { AgentError } from "./agent";
import { libraryOps, sampleLibrary } from "./mock-library";
import { bookOps, sampleBooks } from "./mock-books";
import { planOps, samplePlans } from "./mock-plans";
import { dashboardOps, sampleDashboards } from "./mock-dashboards";

/**
 * In-memory sample company for building the UI: a small plant shop with an online store
 * and wholesale cafe customers (the demo is Bloom & Root). Every company gets its own
 * copy, under its own name, until its engine container exists. State lives on globalThis
 * so it survives hot reloads, and resets when the dev server restarts.
 */

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

type State = {
  decisions: Decision[];
  timeline: TimelineEvent[];
  routines: Routine[];
  todos: Todo[];
  goals: Goal[];
  chat: ChatMessage[];
  spentUsd: number;
  /** Files attached in the chat, kept in memory like everything else here. */
  files: Map<string, { file: ChatFile; data: ArrayBuffer }>;
  library: ReturnType<typeof sampleLibrary>;
  books: ReturnType<typeof sampleBooks>;
  plans: ReturnType<typeof samplePlans>;
  dashboards: ReturnType<typeof sampleDashboards>;
  dashboardAsks: DashboardAsk[];
  /** Tests of replies, by message id. */
  checks: Map<string, Check>;
};

function seed(company: Company, now: number): State {
  const ago = (ms: number) => new Date(now - ms).toISOString();
  const ahead = (ms: number) => new Date(now + ms).toISOString();

  return {
    spentUsd: 6.4,
    files: new Map(),
    library: sampleLibrary(now),
    books: sampleBooks(now),
    plans: samplePlans(now),
    dashboards: sampleDashboards(now),
    dashboardAsks: [],
    checks: new Map(),
    decisions: [
      {
        id: "d-hotel",
        kind: "choice",
        urgent: true,
        title: "The Linden Hotel would like plants for its lobby",
        context:
          "Their manager, Dana, wrote this morning: they're refreshing the lobby and 12 guest rooms and loved the plants at Café Luna. She'd like someone to come and look at the space this week. I drafted a reply offering Thursday or Friday morning, when the van is free.",
        recommendation: {
          optionId: "reply-and-visit",
          why: "It's the kind of place that brings more like it, and she asked for this week.",
        },
        options: [
          { id: "reply-and-visit", label: "Send the reply and book a visit", outcome: "Sends the note below and holds Thursday 10am in your calendar", tone: "primary" },
          { id: "other-time", label: "Offer other times", outcome: "I'll ask which days suit you first", tone: "neutral" },
          { id: "hold", label: "I'll reply myself", tone: "quiet" },
        ],
        facts: [
          { label: "From", value: "The Linden Hotel" },
          { label: "Space", value: "Lobby and 12 rooms" },
          { label: "Found us through", value: "Café Luna" },
        ],
        draft: {
          label: "The reply I drafted",
          body: `Hi Dana,\n\nThank you, that's lovely to hear! We'd be glad to come and see the lobby. Would Thursday or Friday at 10am work? We'll bring a few plants that do well in low light so you can see them in the space.\n\n${company.ownerFirstName}, ${company.name}`,
        },
        goal: "200 regular customers",
        createdAt: ago(42 * MIN),
      },
      {
        id: "d-newsletter",
        kind: "approval",
        urgent: false,
        title: "Start a weekly 'Plant of the Week' email",
        context:
          "1,240 past customers have said yes to emails, but we haven't written to them in 5 months. I'd send one short email each Thursday: one plant, one care tip, and a photo from the shop. I'd write each one and show it to you first for the first month.",
        recommendation: {
          optionId: "approve",
          why: "People who hear from you come back. Most shops like yours see past customers return within a few weeks.",
        },
        options: [
          { id: "approve", label: "Yes, start it", outcome: "First email ready for your review on Thursday", tone: "primary" },
          { id: "later", label: "Not now", tone: "quiet" },
        ],
        facts: [
          { label: "Your time", value: "2 min a week" },
          { label: "Readers", value: "1,240 customers" },
        ],
        goal: "200 regular customers",
        createdAt: ago(5 * HOUR),
      },
      {
        id: "d-practice",
        kind: "approval",
        urgent: false,
        title: "See what \u201cFollow up with new wholesale leads\u201d will do, then switch it on",
        context:
          "Each morning it reads new enquiries from cafes, skips the ones you've already written to, and sends the rest a short hello with photos of cafes we look after. In the practice run it would have written to 2 cafes and skipped 1 you'd already contacted. Nothing was sent in the practice run.",
        recommendation: { optionId: "switch_on", why: "The practice run did what it's for." },
        options: [
          { id: "switch_on", label: "Switch it on", outcome: "Runs every morning. Its first runs are watched: anything it can't undo is checked before it happens", tone: "primary" },
          { id: "change", label: "Change something", outcome: "I'll change it and show you a new practice run", tone: "neutral", input: { placeholder: "What should it do differently?" } },
          { id: "drop", label: "Don't build it", outcome: "It's taken off your list", tone: "quiet" },
        ],
        facts: [
          { label: "Would do", value: "Write to 2 cafes" },
          { label: "Your records", value: "2 new" },
        ],
        trace: "sample-practice",
        goal: "40 cafe accounts",
        createdAt: ago(20 * MIN),
      },
      {
        id: "d-workshop",
        kind: "choice",
        urgent: false,
        title: "When should the first plant care workshop be?",
        context:
          "18 customers have asked for a hands-on care workshop since spring. The shop fits 12 people around the big table. I looked at when your regulars usually visit.",
        recommendation: {
          optionId: "saturday",
          why: "Most of the people who asked come in on weekends, and Saturday mornings are calm before noon.",
        },
        options: [
          { id: "saturday", label: "Saturday morning", outcome: "I'll invite the 18 who asked, then open the last spots to everyone", tone: "primary" },
          { id: "wednesday", label: "Wednesday evening", outcome: "After work, for people who can't come on weekends", tone: "neutral" },
          { id: "later", label: "Not yet", tone: "quiet" },
        ],
        facts: [
          { label: "Asked for it", value: "18 customers" },
          { label: "Room for", value: "12 people" },
        ],
        goal: "200 regular customers",
        createdAt: ago(1 * DAY + 3 * HOUR),
      },
    ],
    timeline: [
      { id: "t1", at: ago(38 * MIN), kind: "done", actor: "coo", title: "Drafted a reply to The Linden Hotel", detail: "They'd like plants for the lobby and 12 rooms. It's waiting in Decisions for your OK.", goal: "200 regular customers", costUsd: 0.04 },
      { id: "t2", at: ago(2 * HOUR), kind: "done", actor: "autopilot", title: "Sent 9 order confirmations with care tips", goal: "200 regular customers" },
      { id: "t3", at: ago(4 * HOUR), kind: "done", actor: "autopilot", title: "Followed up with 6 cafes that haven't reordered in 3 weeks", detail: "Two have already replied. Juniper & Co wants 12 pothos for Friday.", goal: "40 cafe accounts", costUsd: 0.02 },
      { id: "t4", at: ago(9 * HOUR), kind: "learned", actor: "coo", title: "Learned how you like customer emails written", detail: "Short, warm, first names, signed by you. I'll write them that way from now on." },
      { id: "t5", at: ago(1 * DAY + 2 * HOUR), kind: "milestone", actor: "coo", title: "Reached 31 cafe accounts", detail: "Juniper & Co and The Daily Grind signed this week.", goal: "40 cafe accounts" },
      { id: "t6", at: ago(1 * DAY + 6 * HOUR), kind: "decided", actor: "you", title: "You approved the cafe reorder reminders", detail: "They're running every Monday now." },
      { id: "t7", at: ago(2 * DAY), kind: "heads-up", actor: "coo", title: "Lots of people are asking about care", detail: "Care questions doubled this week as spring plants arrive. A workshop could answer many at once: it's in Decisions." },
      { id: "t8", at: ago(2 * DAY + 5 * HOUR), kind: "done", actor: "autopilot", title: "Updated stock counts from the shop", detail: "Monstera and snake plants are popular this week. Added more to Thursday's supplier order." },
      { id: "t9", at: ago(3 * DAY), kind: "done", actor: "coo", title: "Answered 14 customer questions", detail: "Mostly care questions and delivery times. Two needed you, and I put them on your list." },
      { id: "t10", at: ago(4 * DAY), kind: "milestone", actor: "coo", title: "Passed 140 regular customers", detail: "People who've bought from you three times or more. Up from 112 in the summer.", goal: "200 regular customers" },
    ],
    routines: [
      { id: "r-orders", name: "Order confirmations", description: "Sends each online order a confirmation with care tips for the plants they bought.", schedule: "As orders come in", status: "running", lastRun: { at: ago(2 * HOUR), ok: true, summary: "Sent 9 confirmations" }, goal: "200 regular customers", monthlyCostUsd: 0, hoursSavedPerWeek: 2 },
      { id: "r-reorders", name: "Cafe reorder reminders", description: "Finds cafes that haven't ordered in 3 weeks and sends them a friendly nudge.", schedule: "Every Monday", status: "running", lastRun: { at: ago(4 * HOUR), ok: true, summary: "Followed up with 6 cafes" }, goal: "40 cafe accounts", monthlyCostUsd: 0.8, hoursSavedPerWeek: 1.5, watching: true },
      { id: "r-stock", name: "Stock check", description: "Reads the shop's stock counts and adds low items to the next supplier order.", schedule: "Every evening", status: "running", lastRun: { at: ago(2 * DAY + 5 * HOUR), ok: true, summary: "2 items running low" }, monthlyCostUsd: 0, hoursSavedPerWeek: 2 },
      { id: "r-questions", name: "Customer questions", description: "Answers common questions by email and brings you the ones that need you.", schedule: "Every hour", status: "running", lastRun: { at: ago(25 * MIN), ok: true, summary: "Nothing new" }, monthlyCostUsd: 2.6, hoursSavedPerWeek: 3 },
      { id: "r-reviews", name: "Review requests", description: "Asks happy customers for a Google review a week after delivery.", schedule: "Every day", status: "paused", pausedBy: "you", lastRun: { at: ago(6 * DAY), ok: true, summary: "Asked 4 customers for a review" }, goal: "200 regular customers", monthlyCostUsd: 0.3, hoursSavedPerWeek: 0.5 },
      { id: "r-newsletter", name: "Plant of the Week email", description: "A short weekly email to past customers: one plant, one tip, one photo from the shop.", schedule: "Every Thursday", status: "needs-approval", goal: "200 regular customers", monthlyCostUsd: 3, hoursSavedPerWeek: 1 },
    ],
    todos: [
      { id: "todo-1", title: "Reply to Juniper & Co about Friday's delivery window", owner: "you", due: ahead(1 * DAY), done: false, goal: "40 cafe accounts" },
      { id: "todo-2", title: "Send the new wholesale catalog photos", owner: "you", due: ahead(3 * DAY), done: false },
      { id: "todo-3", title: "Draft the spring cafe catalog", owner: "coo", due: ahead(2 * DAY), done: false, goal: "40 cafe accounts" },
      { id: "todo-4", title: "Find 10 new cafes within 5 miles to contact", owner: "coo", due: ahead(5 * DAY), done: false, goal: "40 cafe accounts" },
      { id: "todo-5", title: "Set up the Telegram app for daily updates", owner: "you", done: true },
    ],
    goals: [
      {
        id: "g-regulars",
        title: "200 regular customers",
        why: "Regulars come back every season and bring their friends.",
        metric: { label: "Regular customers", current: 148, target: 200, unit: "" },
        startedAt: ago(40 * DAY),
        due: ahead(84 * DAY),
        pace: "on-track",
        projects: [
          { id: "p1", title: "Keep in touch with past customers by email", status: "waiting-on-you", owner: "coo", doneWhen: "A weekly email is going out and people are coming back", startedAt: ago(30 * DAY), due: ahead(20 * DAY) },
          { id: "p2", title: "Ask happy customers for reviews", status: "in-progress", owner: "autopilot", doneWhen: "50 Google reviews (now 23)", startedAt: ago(25 * DAY), due: ahead(35 * DAY) },
          { id: "p3", title: "Run a plant care workshop", status: "waiting-on-you", owner: "coo", doneWhen: "A first workshop held, with 12 people", startedAt: ago(6 * DAY), due: ahead(10 * DAY) },
        ],
      },
      {
        id: "g-cafes",
        title: "40 cafe accounts",
        why: "Wholesale orders are steady and repeat every month.",
        metric: { label: "Active cafe accounts", current: 31, target: 40, unit: "" },
        startedAt: ago(60 * DAY),
        due: ahead(56 * DAY),
        pace: "ahead",
        projects: [
          { id: "p4", title: "Remind cafes to reorder", status: "done", owner: "autopilot", doneWhen: "Every quiet cafe hears from us within 3 weeks", startedAt: ago(55 * DAY), finishedAt: ago(20 * DAY) },
          { id: "p5", title: "Reach 10 new cafes nearby", status: "in-progress", owner: "coo", doneWhen: "10 cafes contacted, 3 tastings booked", startedAt: ago(14 * DAY), due: ahead(21 * DAY) },
          { id: "p6", title: "Spring wholesale catalog", status: "planned", owner: "you", doneWhen: "New catalog sent to every cafe", startedAt: ahead(7 * DAY), due: ahead(45 * DAY) },
        ],
      },
      {
        id: "g-time",
        title: "Get 10 hours a week back",
        why: "So you can spend Saturdays in the shop instead of on admin.",
        metric: { label: "Hours saved per week", current: 9, target: 10, unit: "" },
        startedAt: ago(30 * DAY),
        pace: "ahead",
        projects: [
          { id: "p7", title: "Answer common customer questions", status: "done", owner: "autopilot", doneWhen: "Most questions answered without you", startedAt: ago(28 * DAY), finishedAt: ago(9 * DAY) },
          { id: "p8", title: "Automate the supplier order", status: "in-progress", owner: "coo", doneWhen: "The weekly order is drafted for a one-tap OK", startedAt: ago(3 * DAY), due: ahead(25 * DAY) },
        ],
      },
    ],
    chat: [
      { id: "c1", from: "coo", at: ago(3 * HOUR), text: `Morning ${company.ownerFirstName}! Quiet night. Two cafes replied to the reorder reminder, and one wants 12 pothos for Friday. I put it on your list.` },
      { id: "c2", from: "you", at: ago(2 * HOUR + 50 * MIN), text: "Great. Can we deliver Friday morning?" },
      {
        id: "c3",
        from: "coo",
        at: ago(2 * HOUR + 49 * MIN),
        text: "**Yes**, the van is free until 11. Friday so far:\n\n- 8:00 pick up the pothos\n- 9–10 deliver to the cafe\n- 10:30 back for the market stall\n\nWant me to confirm 9–10am with them?",
        steps: [{ say: "Let me check what's on for Friday first." }, "Reading your notes", "Reading the task list", "Using Google Calendar: list events"],
      },
      { id: "c4", from: "you", at: ago(40 * MIN), text: "How should I lay out the wholesale page for cafes?" },
      {
        id: "c5",
        from: "coo",
        at: ago(39 * MIN),
        text:
          "I'd keep it to four parts, in this order:\n\n1. **What they get**: \"Plants that stay green, swapped before they fade\", with a photo of a real cafe\n2. **Proof**: two cafes you already look after, in their words\n3. **How it works**: 6 plants, chosen for the light, cared for every two weeks\n4. **One button**: \"Book a free visit\"\n\nLeave out the full catalog: cafes want it handled, not a choice of 80 plants.",
        artifacts: { run: "sample-chat", check: { kind: "customers" } },
      },
    ],
  };
}

const store = globalThis as unknown as { __steerableMock?: Map<string, State> };

function stateFor(company: Company): State {
  store.__steerableMock ??= new Map();
  let s = store.__steerableMock.get(company.id);
  if (!s) store.__steerableMock.set(company.id, (s = seed(company, Date.now())));
  return s;
}

const id = () => Math.random().toString(36).slice(2, 10);

const COO_REPLIES = [
  "On it. I'll come back to you here when it's done.",
  "Good question. Short answer: yes, and it fits in your plan. Want me to put together a plan?",
  "Noted. I'll keep it in mind and add it to tomorrow's brief.",
];

const SAMPLE_FLOWS: Record<string, FlowStep[]> = {
  "r-orders": [
    { kind: "trigger", label: "A new online order", service: "Shopify" },
    { kind: "read", label: "Look up the plants bought" },
    { kind: "write", label: "Write care tips for them" },
    { kind: "send", label: "Send the confirmation", service: "Gmail" },
  ],
  "r-reorders": [
    { kind: "trigger", label: "Every Monday at 9:00" },
    { kind: "read", label: "Read last month's orders", service: "Shopify" },
    { kind: "think", label: "Find cafes 3 weeks quiet", detail: "Skips cafes that said they're closed for the season." },
    { kind: "write", label: "Draft a friendly nudge each" },
    { kind: "send", label: "Send the nudges", service: "Gmail" },
    { kind: "save", label: "Note who was reminded" },
  ],
  "r-stock": [
    { kind: "trigger", label: "Every evening at 19:00" },
    { kind: "read", label: "Read stock counts", service: "Shopify" },
    { kind: "think", label: "Spot what's running low" },
    { kind: "save", label: "Add it to the supplier order" },
  ],
  "r-questions": [
    { kind: "trigger", label: "Every hour" },
    { kind: "read", label: "Read new customer emails", service: "Gmail" },
    { kind: "think", label: "Sort common from tricky" },
    { kind: "send", label: "Answer the common ones", service: "Gmail" },
    { kind: "ask", label: "Bring you the tricky ones" },
  ],
  "r-reviews": [
    { kind: "trigger", label: "Every day" },
    { kind: "read", label: "Find orders delivered a week ago", service: "Shopify" },
    { kind: "write", label: "Write a short thank-you" },
    { kind: "send", label: "Ask for a Google review", service: "Gmail" },
  ],
};

export function mockBackend(company: Company): CompanyBackend {
  const state = () => stateFor(company);
  return {
    ...libraryOps(() => state().library),
    ...bookOps(() => (state().books ??= sampleBooks(Date.now()))),
    ...planOps(() => (state().plans ??= samplePlans(Date.now()))),
    ...dashboardOps(
      () => state().library,
      () => (state().dashboards ??= sampleDashboards(Date.now())),
      () => (state().dashboardAsks ??= []),
    ),
    async overview() {
      const s = state();
      const weekAgo = Date.now() - 7 * DAY;
      const urgent = s.decisions.some((d) => d.urgent);
      const paused = s.routines.filter((r) => r.status === "paused").length;
      return {
        company,
        health: urgent
          ? { state: "problem", summary: "One thing needs you today" }
          : paused
            ? { state: "attention", summary: `${paused} routine${paused === 1 ? "" : "s"} paused, and I'm on it` }
            : { state: "good", summary: "Everything's running smoothly" },
        brief: {
          headline: "A great week. Two new cafes signed, and a hotel wants plants for its lobby.",
          points: [
            "Two cafes signed, so you're at 31 of 40.",
            "18 customers asked for a plant care workshop.",
            "The Linden Hotel would like a visit this week: your reply is drafted.",
          ],
        },
        spend: { monthToDateUsd: s.spentUsd, monthlyCapUsd: 40 },
        stats: {
          doneThisWeek: s.timeline.filter((e) => Date.parse(e.at) > weekAgo).length + 23,
          hoursSavedThisWeek: s.routines
            .filter((r) => r.status === "running")
            .reduce((sum, r) => sum + r.hoursSavedPerWeek, 0),
        },
      };
    },

    async decisions() {
      return [...state().decisions].sort(
        (a, b) => Number(b.urgent) - Number(a.urgent) || Date.parse(b.createdAt) - Date.parse(a.createdAt),
      );
    },

    async decide(decisionId, optionId, note) {
      const s = state();
      const decision = s.decisions.find((d) => d.id === decisionId);
      const option = decision?.options.find((o) => o.id === optionId);
      if (!decision || !option) throw new Error("That decision is no longer open.");
      if (option.input && !option.input.optional && !note?.trim()) throw new AgentError("Say what you'd like changed.", 400);
      s.decisions = s.decisions.filter((d) => d.id !== decisionId);
      if (decision.id === "d-newsletter") {
        const routine = s.routines.find((r) => r.id === "r-newsletter");
        if (routine) routine.status = optionId === "approve" ? "running" : "paused";
      }
      const event: TimelineEvent = {
        id: id(),
        at: new Date().toISOString(),
        kind: "decided",
        actor: "you",
        title: `You decided: ${option.label}`,
        detail: decision.title,
        goal: decision.goal,
      };
      s.timeline.unshift(event);
      return event;
    },

    async timeline(limit = 50) {
      return state().timeline.slice(0, limit);
    },

    async routines() {
      return state().routines.map((r) => ({ ...r, stage: stageOf(r) }));
    },

    async routine(routineId) {
      const routine = state().routines.find((r) => r.id === routineId);
      if (!routine) return null;
      // A few earlier runs like the last one, a day apart.
      const runs: RoutineRun[] = routine.lastRun
        ? [0, 1, 2, 3, 4].map((n) => ({ ...routine.lastRun!, at: new Date(Date.parse(routine.lastRun!.at) - n * DAY).toISOString(), ok: n === 0 ? routine.lastRun!.ok : true }))
        : [];
      if (runs[0]?.ok) Object.assign(runs[0], { id: `sample-${routineId}`, changes: [{ table: "Leads", tableId: "t_leads", added: 2, changed: 1 }] });
      if (routine.watching && runs[0]) runs[0].trace = "sample-watched";
      const watch = routine.watching ? { since: new Date(Date.now() - 9 * DAY).toISOString(), runs: 2, clean: 1, needed: 3 } : undefined;
      const stage = stageOf(routine);
      const record =
        stage === "watched" || stage === "trusted"
          ? { days: 30, runs: routine.watching ? 2 : 24, problems: routine.status === "paused" ? 1 : 0, held: routine.watching ? 1 : 0,
              lastProblem: routine.status === "paused" ? routine.lastRun?.at ?? null : null,
              onItsOwnSince: routine.watching ? null : new Date(Date.now() - 40 * DAY).toISOString() }
          : undefined;
      return { ...routine, stage, flow: SAMPLE_FLOWS[routineId] ?? null, flowPending: false, runs, ...(watch ? { watch } : {}), ...(record ? { record } : {}) };
    },

    async valueRequest(name) {
      return { name, label: name.replace(/_/g, " ").toLowerCase(), why: null, url: null, hint: null, saved: false };
    },

    async saveValue() {},

    async runChanges(runId) {
      if (!runId.startsWith("sample-")) return { tables: [], table: null };
      const columns = [{ name: "Name", type: "text" }, { name: "Status", type: "status" }, { name: "Value", type: "number" }];
      return {
        tables: [{ table: "Leads", tableId: "t_leads", added: 2, changed: 1 }],
        table: {
          id: "t_leads", name: "Leads", columns, next: null, details: true,
          rows: [
            { id: "r1", change: "added", cells: { Name: { value: "Café Luna" }, Status: { value: "New" }, Value: { value: 1200 } } },
            { id: "r2", change: "added", cells: { Name: { value: "Northside Bakery" }, Status: { value: "New" }, Value: { value: 800 } } },
            { id: "r3", change: "changed", cells: { Name: { value: "Green Leaf" }, Status: { value: "Contacted", before: "New" }, Value: { value: 950 } } },
          ],
        },
      };
    },

    async runRoutine(routineId) {
      const r = state().routines.find((x) => x.id === routineId);
      if (!r || r.status !== "running") throw new AgentError("Only a routine that's switched on can be run now.", 409);
      r.lastRun = { at: new Date().toISOString(), ok: true, summary: "Ran just now, as you asked" };
    },

    async watchRoutine(routineId, watch) {
      const routine = state().routines.find((r) => r.id === routineId);
      if (routine) routine.watching = watch || undefined;
    },

    async trace(traceId) {
      return sampleTrace(traceId);
    },

    async traceShot() {
      throw new AgentError("The sample company has no pictures.", 404);
    },

    async setRoutinePaused(routineId, paused) {
      const routine = state().routines.find((r) => r.id === routineId);
      if (routine && routine.status !== "needs-approval") routine.status = paused ? "paused" : "running";
    },

    async todos() {
      return state().todos;
    },

    async toggleTodo(todoId) {
      const todo = state().todos.find((t) => t.id === todoId);
      if (todo) todo.done = !todo.done;
    },

    async goals() {
      return state().goals;
    },

    async chat() {
      return state().chat;
    },

    // The sample company is already set up.
    async onboarding() {
      return { done: true, started: true };
    },

    async startOnboarding() {
      return null;
    },

    async send(text, fileIds = []) {
      const s = state();
      const files = fileIds.map((f) => s.files.get(f)?.file).filter((f): f is ChatFile => !!f);
      s.chat.push({ id: id(), from: "you", text, at: new Date().toISOString(), ...(files.length ? { files } : {}) });
      const reply: ChatMessage = {
        id: id(),
        from: "coo",
        text: COO_REPLIES[s.chat.length % COO_REPLIES.length],
        at: new Date().toISOString(),
      };
      s.chat.push(reply);
      return reply;
    },

    async check(messageId) {
      return (state().checks ??= new Map()).get(messageId) ?? { status: "none" };
    },

    async startCheck(messageId, kind) {
      const s = state();
      const found = (s.checks ??= new Map()).get(messageId);
      if (found && found.status !== "none" && found.status !== "failed") return found;
      const message = s.chat.find((m) => m.id === messageId && m.from === "coo");
      if (!message) throw new AgentError("That message isn't in the conversation any more.", 404);
      const done: Check = {
        status: "done",
        kind: kind ?? message.artifacts?.check?.kind ?? "customers",
        title: "",
        finishedAt: new Date().toISOString(),
        result: {
          summary: "It mostly holds up. Two of the three cafe owners couldn't tell whether plants that fade are replaced, so say it plainly.",
          voices: [
            { who: "Maya, runs a busy cafe, on her phone between orders", went: "Liked the photo and the promise straight away. Paused at how it works: does \"cared for\" mean you replace plants that fade?", stuck: "Whether faded plants are replaced" },
            { who: "Tom, compares three suppliers before deciding", went: "Read the proof first. Wanted to know how often you come by before booking a visit.", stuck: "Whether faded plants are replaced, and how often you visit" },
            { who: "Priya, opening her second cafe", went: "Booked a visit right away. The short page suited her.", stuck: "" },
          ],
          findings: [
            { id: "f1", moment: "At how it works", problem: "\"Cared for\" doesn't say whether plants that fade are replaced, which is what they care about most.", voices: ["Maya", "Tom"], fix: "Say plainly that faded plants are swapped free." },
          ],
          held: ["Four short parts, in that order", "One button, no catalog"],
          edits: [
            { id: "e1", finding: "f1", find: "6 plants, chosen for the light, cared for every two weeks", replace: "6 plants, chosen for the light, cared for every two weeks, and any plant that fades swapped for a fresh one", why: "Say faded plants are swapped free", applies: true },
          ],
        },
      };
      s.checks.set(messageId, done);
      return done;
    },

    async applyCheck() {
      throw new AgentError("This reply has no plan to change. Ask in the chat instead.", 400);
    },

    async newConversation() {
      const s = state();
      if (s.chat.length && s.chat.at(-1)?.from !== "divider") s.chat.push({ id: id(), from: "divider", text: "", at: new Date().toISOString() });
    },

    async chatActivity() {
      return { working: false, steps: [] };
    },

    async chatPage({ before, after, around, limit = 50 } = {}): Promise<ChatPage> {
      const all = state().chat;
      const at = (id?: string) => (id ? all.findIndex((m) => m.id === id) : -1);
      const target = before || after || around;
      if (target && at(target) < 0) return { ...(await this.chatPage({ limit })), reset: true };
      if (after) return { messages: all.slice(at(after) + 1), hasEarlier: true, hasLater: false };
      if (around) {
        const i = at(around), half = Math.floor(limit / 2);
        return { messages: all.slice(Math.max(0, i - half), i + half + 1), hasEarlier: i - half > 0, hasLater: i + half + 1 < all.length };
      }
      const end = before ? at(before) : all.length;
      return { messages: all.slice(Math.max(0, end - limit), end), hasEarlier: end - limit > 0, hasLater: false };
    },

    async searchChat(query) {
      const words = query.toLowerCase().split(/\s+/).filter(Boolean);
      if (!words.length) return [];
      return state()
        .chat.filter((m) => m.from !== "divider")
        .filter((m) => {
          const hay = `${m.text} ${(m.files ?? []).map((f) => f.name).join(" ")}`.toLowerCase();
          return words.every((w) => hay.includes(w));
        })
        .reverse()
        .slice(0, 50);
    },

    async uploadFile(name, data) {
      const ext = name.toLowerCase().split(".").pop() ?? "";
      const kind = ["png", "jpg", "jpeg", "gif", "webp"].includes(ext) ? "image" : ext === "pdf" ? "pdf" : ["txt", "md", "csv"].includes(ext) ? "text" : "other";
      const file: ChatFile = { id: id(), name, kind, size: data.byteLength };
      state().files.set(file.id, { file, data });
      return file;
    },

    async file(fileId) {
      const kept = state().files.get(fileId);
      if (!kept) throw new AgentError("That file isn't here any more.", 404);
      const types: Record<string, string> = { png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif", webp: "image/webp", pdf: "application/pdf" };
      const ext = kept.file.name.toLowerCase().split(".").pop() ?? "";
      return {
        data: kept.data,
        contentType: types[ext] ?? "application/octet-stream",
        disposition: `${kept.file.kind === "image" ? "inline" : "attachment"}; filename*=UTF-8''${encodeURIComponent(kept.file.name)}`,
      };
    },

    async status() {
      const now = Date.now();
      const ago = (ms: number) => new Date(now - ms).toISOString();
      return {
        now: new Date(now).toISOString(),
        helpers: [
          { id: "routines", name: "Routines", state: "working", summary: "Running \u201cRemind cafes to reorder\u201d now", lastAt: ago(4 * MIN) },
          { id: "chat", name: "Chat", state: "idle", summary: "Ready when you are", lastAt: ago(3 * HOUR) },
          { id: "builder", name: "Setting up routines", state: "idle", summary: "Nothing to set up", lastAt: ago(2 * DAY) },
          { id: "fixer", name: "Fixing problems", state: "idle", summary: "Nothing needs fixing", lastAt: ago(5 * DAY) },
          { id: "learn", name: "Learning from the day", state: "idle", summary: "Once a day", lastAt: ago(14 * HOUR) },
          { id: "curate_skills", name: "Tidying up what it knows", state: "idle", summary: "Once a week", lastAt: ago(3 * DAY) },
        ],
      } satisfies BackgroundStatus;
    },
  };
}

function stageOf(r: Routine): RoutineStage {
  if (r.status === "needs-approval") return "proposed";
  if (r.status === "setting-up") return "building";
  return r.watching ? "watched" : "trusted";
}

/** The sample company's practice and watched runs (no pictures: those come from a real browser). */
function sampleTrace(traceId: string): Trace | null {
  const at = (min: number) => new Date(Date.now() - min * MIN).toISOString();
  if (traceId === "sample-practice") {
    return {
      id: traceId, routineId: "r-leads", routine: "Follow up with new wholesale leads", kind: "practice",
      startedAt: at(24), finishedAt: at(22), ok: true, summary: "Would write to 2 cafes",
      review: {
        summary: "Each morning it reads new enquiries from cafes, skips the ones you've already written to, and sends the rest a short hello with photos of cafes we look after.",
        concerns: [],
      },
      events: [
        { n: 1, at: at(24), kind: "step", title: "Read new enquiries" },
        { n: 2, at: at(24), kind: "step", title: "Skip cafes already contacted" },
        { n: 3, at: at(23), kind: "record", title: "Update a row in Leads", detail: "Name: Green Leaf\nStatus: Contacted" },
        { n: 4, at: at(23), kind: "step", title: "Send an intro" },
        { n: 5, at: at(23), kind: "would", title: "Email Café Luna a hello with photos", detail: "To: hello@cafeluna.example\nSubject: Plants for Café Luna" },
        { n: 6, at: at(23), kind: "record", title: "Add a row to Leads", detail: "Name: Café Luna\nStatus: Contacted" },
        { n: 7, at: at(22), kind: "would", title: "Email Northside Bakery a hello with photos", detail: "To: orders@northside.example\nSubject: Plants for Northside Bakery" },
        { n: 8, at: at(22), kind: "record", title: "Add a row to Leads", detail: "Name: Northside Bakery\nStatus: Contacted" },
        { n: 9, at: at(22), kind: "message", title: "Tell you", detail: "**Wrote to 2 new cafes** (added to Leads):\n- [Café Luna](https://example.com/cafe-luna), on Main Street\n- [Northside Bakery](https://example.com/northside), opening in May" },
      ],
    };
  }
  if (traceId === "sample-watched") {
    return {
      id: traceId, routineId: "r-reorders", routine: "Cafe reorder reminders", kind: "watched",
      startedAt: at(250), finishedAt: at(240), ok: true, summary: "Followed up with 6 cafes", review: null,
      events: [
        { n: 1, at: at(250), kind: "step", title: "Find quiet cafes" },
        { n: 2, at: at(248), kind: "did", title: "Email Copper Kettle Cafe a reorder reminder", why: "It's been 4 weeks since their last order, and nothing says they were reminded." },
        { n: 3, at: at(246), kind: "held", title: "Email Juniper & Co a reorder reminder", why: "Their order from yesterday is in your records, so a reminder now would look odd." },
      ],
    };
  }
  return null;
}
