import type { Candidate, PartRequest } from "./types.js";
import {
  QuoteRegister,
  descTokens,
  normalizeCustomer,
  normalizePartNo,
  partBigrams,
  type QuoteGroup,
} from "./register.js";

function dice(a: string, A: ReadonlySet<string>, b: string, B: ReadonlySet<string>): number {
  if (!a || !b) return 0;
  if (!A.size || !B.size) return a === b ? 1 : 0;
  let inter = 0;
  for (const x of A) if (B.has(x)) inter++;
  return (2 * inter) / (A.size + B.size);
}

function jaccard(a: readonly string[], b: readonly string[]): number {
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
    asOf?: string;
  } = {},
): Candidate[] {
  const limit = opts.limit ?? 12;
  const beforeCutoff = (date: string) => Boolean(opts.asOf && /^\d{4}-\d{2}-\d{2}$/.test(date) &&
    !Number.isNaN(Date.parse(`${date}T00:00:00Z`)) &&
    new Date(`${date}T00:00:00Z`).toISOString().slice(0, 10) === date && date < opts.asOf);
  const exclusion = new Map<QuoteGroup, boolean>();
  const excluded = (g: QuoteGroup) => {
    const cached = exclusion.get(g);
    if (cached !== undefined) return cached;
    const result = (opts.exclude?.has(g.head.quote_no) ?? false) ||
      (opts.asOf !== undefined && g.breaks.some((b) =>
        !beforeCutoff(b.quote_date) ||
        (b.date_stamp !== "" && !beforeCutoff(b.date_stamp)) ||
        (b.letter_date !== "" && !beforeCutoff(b.letter_date))));
    exclusion.set(g, result);
    return result;
  };
  const wonAtCutoff = (g: QuoteGroup) => g.breaks.every((b) =>
    b.status === "won" && beforeCutoff(b.won_date));
  const wantPn = part.part_no ? normalizePartNo(part.part_no) : "";
  const wantToks = descTokens(
    [part.description, part.material, part.finish, part.notes].filter(Boolean).join(" "),
  );
  const wantCust = opts.customer ? normalizeCustomer(opts.customer) : "";
  const scored = new Map<QuoteGroup, { score: number; reasons: string[] }>();

  const bump = (g: QuoteGroup, s: number, reason: string) => {
    if (excluded(g)) return;
    const cur = scored.get(g);
    if (cur) {
      cur.score += s;
      cur.reasons.push(reason);
    } else {
      scored.set(g, { score: s, reasons: [reason] });
    }
  };

  // 1. Part-number matching
  if (wantPn && !/[?*]/.test(part.part_no ?? "")) {
    const wantBigrams = partBigrams(wantPn);
    for (const g of reg.exactPart(part.part_no!)) {
      if (/[?*]/.test(g.head.part_no)) continue;
      bump(g, 1.0, "exact part_no");
    }
    if (scored.size < 200) {
      for (const g of reg.groups) {
        if (scored.has(g)) continue;
        if (/[?*]/.test(g.head.part_no)) continue;
        const { partNo: pn, partBigrams: pnBigrams } = g.search;
        if (!pn) continue;
        if (pn.startsWith(wantPn) || wantPn.startsWith(pn)) {
          bump(g, 0.75, "part_no prefix");
        } else {
          const d = dice(wantPn, wantBigrams, pn, pnBigrams);
          if (d >= 0.8) bump(g, d * 0.8, `part_no fuzzy ${d.toFixed(2)}`);
        }
      }
    }
  }

  // 1b. Drawing-number match (the "visualization" link: customer drawings ↔ quoted drawings)
  const wantDwg = part.drawing_ref ? normalizePartNo(part.drawing_ref) : "";
  if (wantDwg) {
    for (const g of reg.groups) {
      const dw = g.search.drawingNo;
      if (dw && (dw === wantDwg || dw.startsWith(wantDwg) || wantDwg.startsWith(dw))) {
        bump(g, 0.85, "drawing_no match");
      }
    }
  }

  // 2. Description-token candidates
  if (wantToks.length) {
    for (const { group, hits } of reg.tokenCandidates(wantToks).slice(0, 400)) {
      const j = jaccard(wantToks, group.search.descriptionTokens);
      const s = Math.min(0.9, hits / wantToks.length) * 0.5 + j * 0.5;
      if (s >= 0.15) bump(group, s * 0.9, `desc tokens ${hits}/${wantToks.length}`);
    }
  }

  // 3. Customer and material bonuses
  for (const [g, cur] of scored) {
    if (opts.customerId && g.head.customer_id === opts.customerId) {
      bump(g, 0.15, "same customer_id");
    } else if (!opts.asOf && wantCust && normalizeCustomer(g.head.customer) === wantCust) {
      bump(g, 0.15, "same customer");
    }
    if (materialMatch(part.material,
      !opts.asOf || beforeCutoff(g.head.letter_date) ? g.head.material : "",
      g.head.comment)) {
      bump(g, 0.1, "material match");
    }
    if (g.head.status === "won" && (!opts.asOf || wonAtCutoff(g))) {
      bump(g, 0.08, "won quote");
    }
  }

  return [...scored.entries()]
    .map(([g, s]) => {
      const status = wonAtCutoff(g) ? "won" : g.breaks.every((row) => row.status === "unknown") ? "unknown" : "open";
      const redact = (row: typeof g.head) => ({
        ...row,
        status,
        won_date: status === "won" ? row.won_date : "",
        customer: "",
        material: beforeCutoff(row.letter_date) ? row.material : "",
      });
      return {
        row: opts.asOf ? redact(g.head) : g.head,
        breaks: opts.asOf ? g.breaks.map(redact) : g.breaks,
        score: Math.min(1, s.score),
        reasons: s.reasons,
      };
    })
    .sort((a, b) => b.score - a.score || b.row.quote_date.localeCompare(a.row.quote_date))
    .slice(0, limit);
}
