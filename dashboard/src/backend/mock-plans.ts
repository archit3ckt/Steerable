import type { Actor, Plan, PlanChange, PlanDetail, PlanVersion, PlanVersionDetail } from "./types";

/** The sample company's plans, in memory: what plans.py keeps for a real one. */
type SamplePlan = Omit<Plan, "version" | "updatedAt" | "updatedBy" | "note" | "summary" | "words"> & {
  versions: (PlanVersion & { body: string })[];
};

const MARKETING_1 = `# Marketing plan

Goal: 10 new cafe customers by December.

## Who we sell to
Independent cafes within 5 km that care about how they look.

## Channels
- Instagram, twice a week: before-and-after photos of cafes we've styled
- Visit 5 cafes a week with a sample plant

## Time
About 3 hours a week, mostly visits.
`;

const MARKETING_2 = MARKETING_1.replace("Goal: 10 new cafe customers", "Goal: 12 new cafe customers").replace(
  "- Visit 5 cafes a week with a sample plant\n",
  "- Visit 5 cafes a week with a sample plant\n- A tasting morning each month, with Riverside Roasters\n",
);

const MARKETING_3 = MARKETING_2.replace("About 3 hours a week, mostly visits.", "About 4 hours a week: visits, and the tasting mornings.");

const BUSINESS_1 = `# Business plan

Bloom & Root sells and looks after plants for cafes and small offices.

## What we sell
- Plants, chosen for the space and the light
- Care visits every two weeks

## Growth
Most of our work is looking after plants for cafes and offices every two weeks. The aim is to look after 60 places by next summer.
`;

export function samplePlans(now: number): SamplePlan[] {
  const at = (days: number) => new Date(now - days * 86_400_000).toISOString();
  const v = (n: number, days: number, who: Actor, note: string, body: string, restoredFrom: number | null = null) => ({ n, at: at(days), who, note, body, restoredFrom });
  return [
    {
      id: "pl1a2b3c4d",
      title: "Marketing plan",
      kind: "marketing",
      createdAt: at(20),
      versions: [
        v(1, 20, "coo", "First draft, from our first chat", MARKETING_1),
        v(2, 9, "coo", "Raised the goal to 12 and added tasting mornings with Riverside Roasters", MARKETING_2),
        v(3, 2, "you", "The tasting mornings need coffee too", MARKETING_3),
      ],
    },
    { id: "pl5e6f7a8b", title: "Business plan", kind: "business", createdAt: at(18), versions: [v(1, 18, "coo", "First draft", BUSINESS_1)] },
  ];
}

/** Line by line, what changed from old to new (as plans.changes does), with unchanged stretches folded. */
export function lineChanges(old: string, next: string, context = 2): PlanChange[] {
  const a = old.split("\n");
  const b = next.split("\n");
  // Longest common subsequence, fine for a plan's few hundred lines.
  const lcs = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--) lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  const all: { op: "same" | "add" | "del"; text: string }[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      all.push({ op: "same", text: a[i++] });
      j++;
    } else if (j < b.length && (i >= a.length || lcs[i][j + 1] >= lcs[i + 1][j])) all.push({ op: "add", text: b[j++] });
    else all.push({ op: "del", text: a[i++] });
  }
  const near = all.map((_, k) => all.slice(Math.max(0, k - context), k + context + 1).some((x) => x.op !== "same"));
  const out: PlanChange[] = [];
  for (let k = 0; k < all.length; k++) {
    if (all[k].op !== "same" || near[k]) out.push(all[k]);
    else if (out.at(-1)?.op === "skip") (out.at(-1) as { count: number }).count++;
    else out.push({ op: "skip", count: 1 });
  }
  return out.some((x) => x.op !== "same" && x.op !== "skip") ? out : [];
}

export function planOps(list: () => SamplePlan[]) {
  const find = (id: string) => list().find((p) => p.id === id);
  const plain = (p: SamplePlan): Plan => {
    const last = p.versions.at(-1)!;
    const first = last.body.split("\n").find((l) => l.trim() && !l.startsWith("#")) ?? "";
    return {
      id: p.id,
      title: p.title,
      kind: p.kind,
      createdAt: p.createdAt,
      version: last.n,
      updatedAt: last.at,
      updatedBy: last.who,
      note: last.note,
      summary: first.slice(0, 200),
      words: last.body.split(/\s+/).filter(Boolean).length,
    };
  };
  const add = (p: SamplePlan, body: string, who: Actor, note: string, restoredFrom: number | null = null) =>
    p.versions.push({ n: p.versions.length + 1, at: new Date().toISOString(), who, note, body, restoredFrom });
  return {
    async plans(): Promise<Plan[]> {
      return list()
        .map(plain)
        .sort((x, y) => y.updatedAt.localeCompare(x.updatedAt));
    },
    async plan(planId: string): Promise<PlanDetail | null> {
      const p = find(planId);
      if (!p) return null;
      const versions = [...p.versions].reverse().map((v) => ({ n: v.n, at: v.at, who: v.who, note: v.note, restoredFrom: v.restoredFrom }));
      return { ...plain(p), body: p.versions.at(-1)!.body, versions };
    },
    async planVersion(planId: string, version: number): Promise<PlanVersionDetail | null> {
      const p = find(planId);
      const v = p?.versions.find((x) => x.n === version);
      if (!p || !v) return null;
      const before = p.versions.find((x) => x.n === version - 1)?.body ?? "";
      return { ...v, changes: lineChanges(before, v.body) };
    },
    async savePlan(planId: string, body: string, note?: string) {
      const p = find(planId);
      if (!p) throw new Error("There's no such plan.");
      const text = body.trim() + "\n";
      if (text.trim() && text !== p.versions.at(-1)!.body) add(p, text, "you", note?.trim() || "Edited by you");
    },
    async restorePlan(planId: string, version: number) {
      const p = find(planId);
      const v = p?.versions.find((x) => x.n === version);
      if (!p || !v) throw new Error("There's no such version.");
      if (version === p.versions.at(-1)!.n) throw new Error("That's already the current version.");
      add(p, v.body, "you", `Back to version ${version}`, version);
    },
    async removePlan(planId: string) {
      const all = list();
      const k = all.findIndex((p) => p.id === planId);
      if (k < 0) throw new Error("There's no such plan.");
      all.splice(k, 1);
    },
  };
}
