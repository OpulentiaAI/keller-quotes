import type { Candidate, PartRequest } from "./types.js";
import {
  ambiguousPartSources,
  customerNamespace,
  independentAttributesMatch,
  matchingDrawing,
  requestedDrawing,
  searchableIdentifier,
  sourceIncompatibilities,
} from "./compatibility.js";
import {
  QuoteRegister,
  descTokens,
  normalizeCustomer,
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

/** Part-number prefix/fuzzy credit requires substantial IDs, never bare fragments like "-1". */
function meaningfulPartNo(pn: string): boolean {
  return pn.length >= 4 && /[A-Z0-9]{4}/.test(pn);
}

function sharedPrefixLength(a: string, b: string): number {
  const max = Math.min(a.length, b.length);
  let i = 0;
  while (i < max && a[i] === b[i]) i++;
  return i;
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
  const sourceRow = (row: QuoteGroup["head"]) => opts.asOf
    ? { ...row, material: beforeCutoff(row.letter_date) ? row.material : "" }
    : row;
  const wantPn = searchableIdentifier(part.part_no);
  const wantToks = descTokens(
    [part.description, part.material, part.finish, part.notes].filter(Boolean).join(" "),
  );
  const wantCust = opts.customer ? normalizeCustomer(opts.customer) : "";
  const wantCustomerId = searchableIdentifier(opts.customerId) ? opts.customerId!.trim() : "";
  const exactGroups = wantPn ? reg.exactPart(wantPn).filter((group) =>
    !excluded(group) && searchableIdentifier(group.head.part_no)) : [];
  const ambiguousIdentity = !wantCustomerId && ambiguousPartSources(exactGroups.map((group) => sourceRow(group.head)));
  const drawingResolvesIdentity = Boolean(requestedDrawing(part)) && !ambiguousPartSources(exactGroups
    .filter((group) => matchingDrawing(part, group.head) && !sourceIncompatibilities(part, group.breaks.map(sourceRow)).length)
    .map((group) => sourceRow(group.head)));
  const compatibility = new Map<QuoteGroup, { partNumber: boolean; exact: boolean; conflicts: string[] }>();
  const assess = (g: QuoteGroup) => {
    const cached = compatibility.get(g);
    if (cached) return cached;
    const namespace = customerNamespace(g.head, opts);
    const independent = independentAttributesMatch(part, g.head);
    const sourceId = searchableIdentifier(g.head.customer_id);
    const literalMatch = part.part_no?.trim().toUpperCase() === g.head.part_no.trim().toUpperCase();
    const unscopedMatch = !wantCustomerId && !sourceId;
    const ambiguousMatch = ambiguousIdentity && g.search.partNo === wantPn;
    const conflicts = sourceIncompatibilities(part, g.breaks.map(sourceRow));
    const partNumber = namespace === "same" || (namespace === "unknown" &&
      !(wantCustomerId && !sourceId) && (!ambiguousMatch || independent) &&
      (literalMatch || unscopedMatch || independent));
    const exact = partNumber && !conflicts.length &&
      (namespace === "same" || literalMatch || unscopedMatch || matchingDrawing(part, g.head)) &&
      (!ambiguousMatch || (drawingResolvesIdentity && matchingDrawing(part, g.head))) &&
      (!searchableIdentifier(part.revision) || Boolean(searchableIdentifier(g.head.rev))) &&
      (!requestedDrawing(part) || matchingDrawing(part, g.head));
    if (namespace === "unknown" && g.search.partNo === wantPn && !independent &&
      (ambiguousMatch || (!literalMatch && !unscopedMatch))) {
      conflicts.push("unresolved part identity");
    }
    const result = { partNumber, exact, conflicts };
    compatibility.set(g, result);
    return result;
  };
  const scored = new Map<QuoteGroup, { score: number; reasons: string[] }>();

  const bump = (g: QuoteGroup, s: number, reason: string) => {
    if (excluded(g)) return;
    const namespace = customerNamespace(g.head, opts);
    const describedSearch = reason.startsWith("desc tokens ") && descTokens(part.description ?? "").some((token) =>
      /[A-Z]/.test(token) && g.search.descriptionTokens.includes(token));
    if ((namespace === "different" || (namespace === "unknown" && wantCustomerId && !searchableIdentifier(g.head.customer_id))) &&
      !independentAttributesMatch(part, g.head) && !scored.has(g) && !describedSearch) return;
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
    const wantBigrams = partBigrams(wantPn);
    for (const g of exactGroups) {
      if (assess(g).exact) bump(g, 1.0, "exact part_no");
      else bump(g, 0, "normalized part_no search");
    }
    if (scored.size < 200) {
      for (const g of reg.groups) {
        if (scored.has(g)) continue;
        if (/[?*]/.test(g.head.part_no)) continue;
        const { partNo: pn, partBigrams: pnBigrams } = g.search;
        if (!pn || !meaningfulPartNo(wantPn) || !meaningfulPartNo(pn)) continue;
        if (sharedPrefixLength(wantPn, pn) < 4) continue;
        if (!assess(g).partNumber || pn === wantPn) continue;
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
  const wantDwg = requestedDrawing(part);
  if (wantDwg) {
    for (const g of reg.groups) {
      const dw = g.search.drawingNo;
      if (dw && searchableIdentifier(g.head.drawing_no) && (dw === wantDwg || dw.startsWith(wantDwg) || wantDwg.startsWith(dw))) {
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
    if (wantCustomerId && g.head.customer_id.trim() === wantCustomerId) {
      bump(g, 0.15, "same customer_id");
    } else if (!wantCustomerId && !opts.asOf && wantCust && normalizeCustomer(g.head.customer) === wantCust) {
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
        ...sourceRow(row),
        status,
        won_date: status === "won" ? row.won_date : "",
        customer: "",
      });
      return {
        row: opts.asOf ? redact(g.head) : g.head,
        breaks: opts.asOf ? g.breaks.map(redact) : g.breaks,
        score: Math.min(1, s.score),
        reasons: s.reasons,
        incompatibilities: assess(g).conflicts,
      };
    })
    .sort((a, b) => Number(Boolean(a.incompatibilities.length)) - Number(Boolean(b.incompatibilities.length)) ||
      b.score - a.score || b.row.quote_date.localeCompare(a.row.quote_date))
    .slice(0, limit);
}
