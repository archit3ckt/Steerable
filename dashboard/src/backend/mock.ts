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
        id: "d-refund",
        kind: "problem",
        urgent: true,
        title: "A cafe was charged the retail price instead of wholesale",
        context:
          "Copper Kettle Cafe's order this morning used retail prices, so they paid $46 too much. I found the cause, a price list that didn't update, and already fixed it so it can't happen again. They haven't noticed yet.",
        recommendation: {
          optionId: "refund-and-apologize",
          why: "They're your third-biggest wholesale account. Getting ahead of it keeps the trust.",
        },
        options: [
          { id: "refund-and-apologize", label: "Refund and send the apology", outcome: "Refunds $46 today and sends the note below", tone: "primary" },
          { id: "refund-only", label: "Refund quietly", outcome: "Refunds $46 without a message", tone: "neutral" },
          { id: "hold", label: "I'll handle it myself", tone: "quiet" },
        ],
        facts: [
          { label: "Refund", value: "$46.00" },
          { label: "Customer", value: "Copper Kettle Cafe" },
          { label: "Fix", value: "Already in place" },
        ],
        draft: {
          label: "The apology I drafted",
          body: `Hi Dana,\n\nQuick heads-up: this morning's order was billed at our retail prices by mistake. We've refunded the $46 difference, and it should show up in 2–3 days. Sorry about that, and thanks for being such a great partner.\n\n${company.ownerFirstName}, ${company.name}`,
        },
        goal: "40 cafe accounts",
        createdAt: ago(42 * MIN),
      },
      {
        id: "d-newsletter",
        kind: "approval",
        urgent: false,
        title: "Start a weekly 'Plant of the Week' email",
        context:
          "1,240 past customers have said yes to emails, but we haven't written to them in 5 months. I'd send one short email each Thursday: one plant, one care tip, and one offer. I'd write each one and show it to you first for the first month.",
        recommendation: {
          optionId: "approve",
          why: "Repeat customers are your cheapest sales. Shops like yours usually get 3–5% of readers ordering again.",
        },
        options: [
          { id: "approve", label: "Yes, start it", outcome: "First email ready for your review on Thursday", tone: "primary" },
          { id: "later", label: "Not now", tone: "quiet" },
        ],
        facts: [
          { label: "Your time", value: "2 min a week" },
          { label: "Could bring", value: "$400–700 / month" },
        ],
        goal: "$8k monthly revenue",
        createdAt: ago(5 * HOUR),
      },
      {
        id: "d-practice",
        kind: "approval",
        urgent: false,
        title: "See what \u201cFollow up with new wholesale leads\u201d will do, then switch it on",
        context:
          "Each morning it reads new wholesale enquiries, skips cafes you've already written to, and sends the rest a short intro with the price sheet. In the practice run it would have written to 2 cafes and skipped 1 you'd already contacted. Nothing was sent in the practice run.",
        recommendation: { optionId: "", why: "Look at what I noticed first: you can switch it on anyway, or tell me what to change." },
        options: [
          { id: "switch_on", label: "Switch it on", outcome: "Runs every morning. Its first runs are watched: anything it can't undo is checked before it happens", tone: "primary" },
          { id: "change", label: "Change something", outcome: "I'll change it and show you a new practice run", tone: "neutral", input: { placeholder: "What should it do differently?" } },
          { id: "drop", label: "Don't build it", outcome: "It's taken off your list", tone: "quiet" },
        ],
        facts: [
          { label: "Would do", value: "2 things it can't undo" },
          { label: "Your records", value: "2 new" },
        ],
        concerns: ["If a cafe replies \u201cnot interested\u201d, it doesn't seem to notice, so it could write to them again next month."],
        trace: "sample-practice",
        goal: "40 cafe accounts",
        createdAt: ago(20 * MIN),
      },
      {
        id: "d-pricing",
        kind: "choice",
        urgent: false,
        title: "How should we handle the supplier's 8% price rise?",
        context:
          "Greenhouse Direct raises prices on May 1. If we change nothing, we earn about $310 less each month. I looked at three ways to handle it.",
        recommendation: {
          optionId: "raise-wholesale",
          why: "Cafes compare us with prices 15% above ours, so a small rise is safe. Retail customers notice prices more.",
        },
        options: [
          { id: "raise-wholesale", label: "Raise wholesale prices 6%", outcome: "Recovers about $260 a month. I'll tell cafes 30 days ahead.", tone: "primary" },
          { id: "raise-all", label: "Raise all prices 4%", outcome: "Recovers about $300 a month, with some risk to online sales", tone: "neutral" },
          { id: "absorb", label: "Keep prices, absorb it", outcome: "About $310 less profit each month", tone: "quiet" },
        ],
        facts: [
          { label: "Starts", value: "May 1" },
          { label: "At stake", value: "$310 / month" },
        ],
        goal: "$8k monthly revenue",
        createdAt: ago(1 * DAY + 3 * HOUR),
      },
    ],
    timeline: [
      { id: "t1", at: ago(38 * MIN), kind: "fixed", actor: "coo", title: "Fixed the wholesale price list", detail: "The price list for cafes hadn't updated after Monday's change. It now updates on its own, and I added a check that catches it if it slips.", goal: "40 cafe accounts", costUsd: 0.41 },
      { id: "t2", at: ago(2 * HOUR), kind: "done", actor: "autopilot", title: "Sent 9 order confirmations", goal: "$8k monthly revenue" },
      { id: "t3", at: ago(4 * HOUR), kind: "done", actor: "autopilot", title: "Followed up with 6 cafes that haven't reordered in 3 weeks", detail: "Two have already replied. Juniper & Co wants 12 pothos for Friday.", goal: "40 cafe accounts", costUsd: 0.02 },
      { id: "t4", at: ago(9 * HOUR), kind: "learned", actor: "coo", title: "Learned how you like customer emails written", detail: "Short, warm, first names, signed by you. I'll write them that way from now on." },
      { id: "t5", at: ago(1 * DAY + 2 * HOUR), kind: "milestone", actor: "coo", title: "Reached 31 cafe accounts", detail: "Juniper & Co and The Daily Grind signed this week.", goal: "40 cafe accounts" },
      { id: "t6", at: ago(1 * DAY + 6 * HOUR), kind: "decided", actor: "you", title: "You approved the cafe reorder reminders", detail: "They're running every Monday now." },
      { id: "t7", at: ago(2 * DAY), kind: "heads-up", actor: "coo", title: "Online orders were slower this week", detail: "Down 12% from last week. Probably the long weekend. I'll keep an eye on it and tell you if it continues." },
      { id: "t8", at: ago(2 * DAY + 5 * HOUR), kind: "done", actor: "autopilot", title: "Updated stock counts from the shop", detail: "Low on monstera (3 left) and snake plants (5 left). Added to Thursday's supplier order." },
      { id: "t9", at: ago(3 * DAY), kind: "done", actor: "coo", title: "Answered 14 customer questions", detail: "Mostly care questions and delivery times. Two needed you, and I put them on your list." },
      { id: "t10", at: ago(4 * DAY), kind: "milestone", actor: "coo", title: "Monthly revenue passed $6,000", detail: "For the first time. Wholesale is now 41% of sales.", goal: "$8k monthly revenue" },
    ],
    routines: [
      { id: "r-orders", name: "Order confirmations", description: "Sends each online order a confirmation with care tips for the plants they bought.", schedule: "As orders come in", status: "running", lastRun: { at: ago(2 * HOUR), ok: true, summary: "Sent 9 confirmations" }, goal: "$8k monthly revenue", monthlyCostUsd: 0, hoursSavedPerWeek: 2 },
      { id: "r-reorders", name: "Cafe reorder reminders", description: "Finds cafes that haven't ordered in 3 weeks and sends them a friendly nudge.", schedule: "Every Monday", status: "running", lastRun: { at: ago(4 * HOUR), ok: true, summary: "Followed up with 6 cafes" }, goal: "40 cafe accounts", monthlyCostUsd: 0.8, hoursSavedPerWeek: 1.5, watching: true },
      { id: "r-stock", name: "Stock check", description: "Reads the shop's stock counts and adds low items to the next supplier order.", schedule: "Every evening", status: "running", lastRun: { at: ago(2 * DAY + 5 * HOUR), ok: true, summary: "2 items running low" }, monthlyCostUsd: 0, hoursSavedPerWeek: 2 },
      { id: "r-questions", name: "Customer questions", description: "Answers common questions by email and brings you the ones that need you.", schedule: "Every hour", status: "running", lastRun: { at: ago(25 * MIN), ok: true, summary: "Nothing new" }, monthlyCostUsd: 2.6, hoursSavedPerWeek: 3 },
      { id: "r-reviews", name: "Review requests", description: "Asks happy customers for a Google review a week after delivery.", schedule: "Every day", status: "paused", lastRun: { at: ago(6 * DAY), ok: false, summary: "Paused: Google changed their review link" }, goal: "$8k monthly revenue", monthlyCostUsd: 0.3, hoursSavedPerWeek: 0.5 },
      { id: "r-newsletter", name: "Plant of the Week email", description: "A short weekly email to past customers: one plant, one tip, one offer.", schedule: "Every Thursday", status: "needs-approval", goal: "$8k monthly revenue", monthlyCostUsd: 3, hoursSavedPerWeek: 1 },
    ],
    todos: [
      { id: "todo-1", title: "Reply to Juniper & Co about Friday's delivery window", owner: "you", due: ahead(1 * DAY), done: false, goal: "40 cafe accounts" },
      { id: "todo-2", title: "Send the new wholesale catalog photos", owner: "you", due: ahead(3 * DAY), done: false },
      { id: "todo-3", title: "Draft the spring wholesale price sheet", owner: "coo", due: ahead(2 * DAY), done: false, goal: "40 cafe accounts" },
      { id: "todo-4", title: "Find 10 new cafes within 5 miles to contact", owner: "coo", due: ahead(5 * DAY), done: false, goal: "40 cafe accounts" },
      { id: "todo-5", title: "Set up the Telegram app for daily updates", owner: "you", done: true },
    ],
    goals: [
      {
        id: "g-revenue",
        title: "$8k monthly revenue",
        why: "Enough to hire a part-time helper for the shop on weekends.",
        metric: { label: "This month so far", current: 6120, target: 8000, unit: "$" },
        startedAt: ago(40 * DAY),
        due: ahead(84 * DAY),
        pace: "on-track",
        projects: [
          { id: "p1", title: "Win back past customers by email", status: "waiting-on-you", owner: "coo", doneWhen: "A weekly email is going out and bringing repeat orders", startedAt: ago(30 * DAY), due: ahead(20 * DAY) },
          { id: "p2", title: "Ask happy customers for reviews", status: "blocked", owner: "autopilot", doneWhen: "50 Google reviews (now 23)", startedAt: ago(25 * DAY), due: ahead(35 * DAY) },
          { id: "p3", title: "Handle the supplier price rise", status: "waiting-on-you", owner: "coo", doneWhen: "Margins back where they were by May 1", startedAt: ago(6 * DAY), due: ahead(10 * DAY) },
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
          "I'd keep it to four parts, in this order:\n\n1. **What they get**: \"Plants that stay green, swapped before they fade\", with a photo of a real cafe\n2. **Proof**: two cafes you already supply, with their words\n3. **Price**: $49 a month for 6 plants, care included\n4. **One button**: \"Book a free visit\"\n\nLeave out the full catalog: cafes want it handled, not a choice of 80 plants.",
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
          headline: "A good week. Cafes are ahead of plan, and one billing slip is already fixed.",
          points: [
            "Two cafes signed, so you're at 31 of 40.",
            "Online orders dipped 12%, probably the long weekend.",
            "The supplier price rise needs a decision before May 1.",
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
          summary: "It mostly holds up. Two of the three cafe owners couldn't tell whether $49 covers replacing plants, so say it next to the price.",
          voices: [
            { who: "Maya, runs a busy cafe, on her phone between orders", went: "Liked the photo and the promise straight away. Scrolled to the price and paused: does \"care included\" mean you replace plants that die?", stuck: "Whether dead plants are replaced" },
            { who: "Tom, compares three suppliers before deciding", went: "Read the proof first, then the price. Wanted to know if there's a contract before booking a visit.", stuck: "Whether dead plants are replaced, and if there's a contract" },
            { who: "Priya, opening her second cafe", went: "Booked a visit right away. The short page suited her.", stuck: "" },
          ],
          findings: [
            { id: "f1", moment: "At the price", problem: "\"Care included\" doesn't say whether plants that fade are replaced, which is what they care about most.", voices: ["Maya", "Tom"], fix: "Say plainly that faded plants are swapped free." },
          ],
          held: ["Four short parts, in that order", "One button, no catalog"],
          edits: [
            { id: "e1", finding: "f1", find: "$49 a month for 6 plants, care included", replace: "$49 a month for 6 plants: watering, care, and any plant that fades swapped free. No contract.", why: "Say faded plants are swapped free", applies: true },
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
        summary: "Each morning it reads new wholesale enquiries, skips cafes you've already written to, and sends the rest a short intro with the price sheet.",
        concerns: ["If a cafe replies \u201cnot interested\u201d, it doesn't seem to notice, so it could write to them again next month."],
      },
      events: [
        { n: 1, at: at(24), kind: "step", title: "Read new enquiries" },
        { n: 2, at: at(24), kind: "step", title: "Skip cafes already contacted" },
        { n: 3, at: at(23), kind: "record", title: "Update a row in Leads", detail: "Name: Green Leaf\nStatus: Contacted" },
        { n: 4, at: at(23), kind: "step", title: "Send an intro" },
        { n: 5, at: at(23), kind: "would", title: "Email Café Luna an intro with the price sheet", detail: "To: hello@cafeluna.example\nSubject: Plants for Café Luna" },
        { n: 6, at: at(23), kind: "record", title: "Add a row to Leads", detail: "Name: Café Luna\nStatus: Contacted" },
        { n: 7, at: at(22), kind: "would", title: "Email Northside Bakery an intro with the price sheet", detail: "To: orders@northside.example\nSubject: Plants for Northside Bakery" },
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
