import { AgentError } from "./agent";
import type { Book, BookDetail, BookIdea, BookPassage } from "./types";

/** The sample company's one book, in memory: what books.py keeps for a real one. */
type SampleBook = Omit<BookDetail, "passages"> & { text: { chapter: number; chapterTitle: string; passage: string }[] };

export function sampleBooks(now: number): SampleBook[] {
  const at = (days: number) => new Date(now - days * 86_400_000).toISOString();
  const idea = (id: string, kind: BookIdea["kind"], name: string, summary: string, source: string, body: BookIdea["body"], status: BookIdea["status"] = "waiting"): BookIdea => ({
    id,
    kind,
    name,
    summary,
    source,
    body,
    status,
    note: status === "approved" ? "Juno uses it from now on." : null,
  });
  return [
    {
      id: "b5a3c1e0",
      title: "Built to Run (sample)",
      author: "A sample author",
      why: "It helped me stop doing everything myself.",
      chapters: 3,
      words: 41_000,
      status: "ready",
      progress: null,
      error: null,
      added: at(2),
      studied: at(2),
      waiting: 2,
      approved: 1,
      contents: ["Systems, not heroics", "The weekly scorecard", "Hiring for the role"],
      notes: "## Systems, not heroics\n- Write down any task done twice, so someone else can do it.\n\n## The weekly scorecard\n- Five to fifteen numbers, each with an owner, reviewed every week.",
      proposals: [
        idea("p1a2b3c4", "skill", "Write a process", "Turn any task done twice into a written process.", "ch. 1", "When a task repeats, write the steps, the tools and what done looks like. Keep it to one page.", "approved"),
        idea("p2b3c4d5", "routine", "Weekly scorecard", "Every Monday, your key numbers on one page.", "ch. 2", { description: "Builds the weekly scorecard every Monday", every: "weekly", saves: 1 }),
        idea("p3c4d5e6", "goal", "Run a week without you", "Hand off the daily work so the shop runs without you.", "ch. 1", { goal: "The shop runs a week without the owner", metric: "days away", target: "7" }),
      ],
      text: [
        { chapter: 1, chapterTitle: "Systems, not heroics", passage: "Write down how every [repeated] task is done, so anyone can do it." },
        { chapter: 2, chapterTitle: "The weekly scorecard", passage: "Pick five to fifteen [numbers] and review them every week." },
      ],
    },
  ];
}

export function bookOps(list: () => SampleBook[]) {
  const find = (id: string) => list().find((b) => b.id === id);
  const plain = (b: SampleBook): Book => ({
    id: b.id,
    title: b.title,
    author: b.author,
    why: b.why,
    chapters: b.chapters,
    words: b.words,
    status: b.status,
    progress: b.progress,
    error: b.error,
    added: b.added,
    studied: b.studied,
    waiting: b.proposals.filter((p) => p.status === "waiting").length,
    approved: b.proposals.filter((p) => p.status === "approved").length,
  });
  const search = (q: string, b: SampleBook): BookPassage[] =>
    b.text
      .filter((t) => q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => t.passage.toLowerCase().includes(w)))
      .map((t) => ({ ...t, book: b.title, bookId: b.id }));
  return {
    async books(): Promise<Book[]> {
      return list().map(plain);
    },
    async book(bookId: string, q?: string): Promise<BookDetail | null> {
      const b = find(bookId);
      if (!b) return null;
      return { ...b, ...plain(b), passages: q ? search(q, b) : [] };
    },
    async searchBooks(q: string): Promise<BookPassage[]> {
      return list().flatMap((b) => search(q, b));
    },
    async teachBook(): Promise<Book> {
      throw new AgentError("The sample company can't learn new books. In your own company, Juno would start reading it now.", 400);
    },
    async answerBookIdea(bookId: string, ideaId: string, approve: boolean) {
      const idea = find(bookId)?.proposals.find((p) => p.id === ideaId);
      if (!idea || idea.status !== "waiting") throw new AgentError("That one's already been answered.", 400);
      idea.status = approve ? "approved" : "declined";
      idea.note = approve ? { skill: "Juno uses it from now on.", routine: "Approved: Juno is setting it up (see Work).", goal: "Added to your goals." }[idea.kind] : null;
      const b = find(bookId)!;
      if (!b.proposals.some((p) => p.status === "waiting")) b.status = "learned";
    },
    async setBookPaused(bookId: string, paused: boolean) {
      const b = find(bookId);
      if (b) b.status = paused ? "paused" : b.proposals.some((p) => p.status === "waiting") ? "ready" : "learned";
    },
    async retryBook() {},
    async removeBook(bookId: string) {
      const all = list();
      const i = all.findIndex((b) => b.id === bookId);
      if (i >= 0) all.splice(i, 1);
    },
  };
}
