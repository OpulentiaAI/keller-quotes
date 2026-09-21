import type { Candidate, PartRequest } from "./types.js";
import {
  QuoteRegister,
  descTokens,
  normalizeCustomer,
  normalizePartNo,
  type QuoteGroup,
} from "./register.js";

function bigrams(s: string): Set<string> {
  const out = new Set<string>();
  for (let i = 0; i < s.length - 1; i++) out.add(s.slice(i, i + 2));
  return out;
}

function dice(a: string, b: string): number {
  if (!a || !b) return 0;
  const A = bigrams(a);
  const B = bigrams(b);
  if (!A.size || !B.size) return a === b ? 1 : 0;
  let inter = 0;
  for (const x of A) if (B.has(x)) inter++;
  return (2 * inter) / (A.size + B.size);
}

function jaccard(a: string[], b: string[]): number {
  const A = new Set(a);
  const B = new Set(b);
  if (!A.size || !B.size) return 0;
  let inter = 0;
  for (const x of A) if (B.has(x)) inter++;
  return inter / (A.size + B.size);
}

function materialMatch(want: string | undefined, rowMaterial: string, comment: string): boolean {
  if (!want) return false;
  const w = want.toUpperCase();
  const hay = (rowMaterial + " " + comment).toUpperCase();
  return descTokens(w).some((t) => hay.includes(t));
}

export function retrieve(
  reg: QuoteRegister,
  part: PartRequest,
  opts: {
    customer?: string;
    customerId?: string;
    limit?: number;
    /** quote_no prefixes to exclude (leave-one-out evals). */
    exclude?: Set<string>;
  } = {},
): Candidate[] {
  const limit = opts.limit ?? 12;
  const excluded = (g: QuoteGroup) =>
    opts.exclude !== undefined &&
    [...opts.exclude].some((p) => g.quote_no.split("|")[0] === p);
  const wantPn = part.part_no ? normalizePartNo(part.part_no) : "";
  const wantToks = descTokens(
    [part.description, part.material, part.finish, part.notes].filter(Boolean).join(" "),
  );
  const wantCust = opts.customer ? normalizeCustomer(opts.customer) : "";
  const scored = new Map<QuoteGroup, { score: number; reasons: string[] }>();

  const bump = (g: QuoteGroup, s: number, reason: string) => {
    const cur = scored.get(g);
    if (cur) {
      cur.score += s;
      cur.reasons.push(reason);
    } else {
      scored.set(g, { score: s, reasons: [reason] });
    }
  };

  // 1. Part-number matching
  if (wantPn) {
    for (const g of reg.exactPart(part.part_no!)) {
      bump(g, 1.0, "exact part_no");
    }
    if (scored.size < 200) {
      for (const g of reg.groups) {
        if (scored.has(g)) continue;
        const pn = normalizePartNo(g.head.part_no);
        if (!pn) continue;
        if (pn.startsWith(wantPn) || wantPn.startsWith(pn)) {
          bump(g, 0.75, "part_no prefix");
        } else {
          const d = dice(wantPn, pn);
          if (d >= 0.8) bump(g, d * 0.8, `part_no fuzzy ${d.toFixed(2)}`);
        }
      }
    }
  }

  // 1b. Drawing-number match (the "visualization" link: customer drawings ↔ quoted drawings)
  const wantDwg = part.drawing_ref ? normalizePartNo(part.drawing_ref) : "";
  if (wantDwg) {
    for (const g of reg.groups) {
      const dw = normalizePartNo(g.head.drawing_no);
      if (dw && (dw === wantDwg || dw.startsWith(wantDwg) || wantDwg.startsWith(dw))) {
        bump(g, 0.85, "drawing_no match");
      }
    }
  }

  // 2. Description-token candidates
  if (wantToks.length) {
    for (const { group, hits } of reg.tokenCandidates(wantToks).slice(0, 400)) {
      const j = jaccard(wantToks, descTokens(group.head.description));
      const s = Math.min(0.9, hits / wantToks.length) * 0.5 + j * 0.5;
      if (s >= 0.15) bump(group, s * 0.9, `desc tokens ${hits}/${wantToks.length}`);
    }
  }

  // 3. Customer and material bonuses
  for (const [g, cur] of scored) {
    if (opts.customerId && g.head.customer_id === opts.customerId) {
      bump(g, 0.15, "same customer_id");
    } else if (wantCust && normalizeCustomer(g.head.customer) === wantCust) {
      bump(g, 0.15, "same customer");
    }
    if (materialMatch(part.material, g.head.material, g.head.comment)) {
      bump(g, 0.1, "material match");
    }
    if (g.head.status === "won") bump(g, 0.08, "won quote");
  }

  return [...scored.entries()]
    .filter(([g]) => !excluded(g))
    .map(([g, s]) => ({ row: g.head, breaks: g.breaks, score: Math.min(1, s.score), reasons: s.reasons }))
    .sort((a, b) => b.score - a.score || b.row.quote_date.localeCompare(a.row.quote_date))
    .slice(0, limit);
}
