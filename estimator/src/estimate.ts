import type {
  EstimateRequest,
  LineEstimate,
  PartRequest,
  QuoteEstimate,
} from "./types.js";
import { QuoteRegister, normalizePartNo } from "./register.js";
import { retrieve } from "./retrieve.js";
import { JevClient } from "./jev.js";
import { price } from "./price.js";
import type { Candidate } from "./types.js";

function hasUsableBreak(candidate: Candidate): boolean {
  return candidate.breaks.some((b) =>
    b.quantity !== null && Number.isFinite(b.quantity) && b.quantity > 0 &&
    b.unit_price !== null && Number.isFinite(b.unit_price) && b.unit_price > 0);
}

export interface EstimateOptions {
  jev?: JevClient;
  /** Max candidates passed to Jev ranking per part. */
  rankLimit?: number;
  /** Max top-ranked candidates to screen per part; only admitted candidates can be priced (0 holds). */
  screenTopN?: number;
  /** quote_no values to exclude from analogs (eval leave-one-out). */
  exclude?: Set<string>;
  asOf?: string;
}

export function assertEstimateRequest(req: unknown): asserts req is EstimateRequest {
  if (typeof req !== "object" || req === null || Array.isArray(req)) {
    throw new Error("request must be an object");
  }
  const request = req as Record<string, unknown>;
  if (!Array.isArray(request.parts) || request.parts.length === 0) {
    throw new Error("request.parts must be a nonempty array");
  }
  for (const field of ["customer", "customer_id", "rfq_no", "notes"]) {
    if (request[field] !== undefined && typeof request[field] !== "string") {
      throw new Error(`request.${field} must be a string`);
    }
  }
  for (const [i, value] of request.parts.entries()) {
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      throw new Error(`request.parts[${i}] must be an object`);
    }
    const part = value as Record<string, unknown>;
    if (typeof part.quantity !== "number" || !Number.isFinite(part.quantity) || part.quantity <= 0) {
      throw new Error(`request.parts[${i}].quantity must be a finite positive number`);
    }
    for (const field of ["part_no", "description", "material", "finish", "drawing_ref", "notes"]) {
      if (part[field] !== undefined && typeof part[field] !== "string") {
        throw new Error(`request.parts[${i}].${field} must be a string`);
      }
    }
  }
}

export async function estimate(
  reg: QuoteRegister,
  req: EstimateRequest,
  opts: EstimateOptions = {},
): Promise<QuoteEstimate> {
  assertEstimateRequest(req);
  if (opts.asOf !== undefined && (!/^\d{4}-\d{2}-\d{2}$/.test(opts.asOf) ||
    Number.isNaN(Date.parse(`${opts.asOf}T00:00:00Z`)) ||
    new Date(`${opts.asOf}T00:00:00Z`).toISOString().slice(0, 10) !== opts.asOf)) {
    throw new Error("asOf must be a valid YYYY-MM-DD date");
  }
  const jev = opts.jev ?? new JevClient();
  const rankLimit = opts.rankLimit ?? 8;
  const screenTopN = opts.screenTopN ?? 3;
  if (!Number.isSafeInteger(rankLimit) || rankLimit <= 0) {
    throw new Error("rankLimit must be a positive integer");
  }
  if (!Number.isSafeInteger(screenTopN) || screenTopN < 0) {
    throw new Error("screenTopN must be a nonnegative integer");
  }
  const lines: LineEstimate[] = [];

  for (const part of req.parts) {
    lines.push(
      await estimatePart(reg, jev, req, part, {
        rankLimit,
        screenTopN,
        exclude: opts.exclude,
        asOf: opts.asOf,
      }),
    );
  }

  const total = lines.reduce((s, l) => s + (l.extended_price ?? 0), 0);
  return {
    request: req,
    currency: "USD",
    lines,
    total: Math.round(total * 100) / 100,
    generated_at: new Date().toISOString(),
    register_rows: reg.rowCount,
    jev: jev.enabled ? "enabled" : "disabled",
  };
}

async function estimatePart(
  reg: QuoteRegister,
  jev: JevClient,
  req: EstimateRequest,
  part: PartRequest,
  opts: { rankLimit: number; screenTopN: number; exclude?: Set<string>; asOf?: string },
): Promise<LineEstimate> {
  const warnings: string[] = [];
  let candidates = retrieve(reg, part, {
    customer: req.customer,
    customerId: req.customer_id,
    limit: 12,
    exclude: opts.exclude,
    asOf: opts.asOf,
  });
  const historicalEvidencePresent = candidates.length > 0;
  const partNo = normalizePartNo(part.part_no ?? "");
  if (partNo) {
    const priceable = (c: typeof candidates[number]) => c.breaks.some((b) =>
      b.quantity !== null && Number.isFinite(b.quantity) && b.quantity > 0 &&
      b.unit_price !== null && Number.isFinite(b.unit_price) && b.unit_price > 0);
    const exact = candidates.filter((c) => normalizePartNo(c.row.part_no) === partNo && priceable(c));
    if (exact.length) {
      candidates = exact;
    } else {
      candidates = candidates.filter((c) => normalizePartNo(c.row.part_no) !== partNo || priceable(c));
    }
  }

  const verdict = await jev.rankAnalogs(part, candidates, opts.rankLimit);
  if (verdict.source === "jev") {
    const order = new Map(verdict.rankedIds.map((id, i) => [id, i]));
    const partNo = normalizePartNo(part.part_no ?? "");
    const partPriority = (candidate: Candidate) => {
      const candidatePartNo = normalizePartNo(candidate.row.part_no);
      if (!partNo || !candidatePartNo) return 0;
      if (candidatePartNo === partNo) return 2;
      return candidatePartNo.startsWith(partNo) || partNo.startsWith(candidatePartNo) ? 1 : 0;
    };
    candidates = [...candidates].sort(
      (a, b) => partPriority(b) - partPriority(a) ||
        (order.get(a.row.quote_no) ?? 999) - (order.get(b.row.quote_no) ?? 999),
    );
  }
  const preScreenCandidates = candidates;

  const screeningBudget = Math.min(opts.screenTopN, opts.rankLimit);
  if (candidates.length > screeningBudget) {
    const skipped = candidates.length - screeningBudget;
    warnings.push(`screening budget skipped ${skipped} analog${skipped === 1 ? "" : "s"}`);
  }
  const screened: typeof candidates = [];
  for (const c of candidates.slice(0, screeningBudget)) {
    const v = await jev.screenCandidate(part, c);
    if (v !== "admit") {
      warnings.push(`${v === "reject" ? "rejected" : "quarantined"} analog ${c.row.quote_no}`);
      continue;
    }
    screened.push(c);
  }
  const noAdmittedCandidates = screened.length === 0;
  const provisionalFallback = jev.enabled && noAdmittedCandidates
    ? preScreenCandidates.find(hasUsableBreak)
    : undefined;
  candidates = provisionalFallback ? [provisionalFallback] : screened;
  if (provisionalFallback) {
    warnings.push(
      `Jev admitted no high-confidence analog; retained highest-ranked usable candidate ${provisionalFallback.row.quote_no} as a provisional human-review fallback`,
    );
  }

  const strategy = await jev.chooseStrategy(part, candidates);
  const priced = price(part.quantity, candidates, {
    strategy,
    jevProbabilities: verdict.probabilities,
    customerId: req.customer_id,
    customer: req.customer,
    now: opts.asOf ? Date.parse(`${opts.asOf}T00:00:00Z`) : undefined,
  });

  const ranges = candidates.slice(0, opts.rankLimit).map((c) => c.breaks
    .filter((b) => b.quantity !== null && Number.isFinite(b.quantity) && b.quantity > 0 &&
      b.unit_price !== null && Number.isFinite(b.unit_price) && b.unit_price > 0)
    .map((b) => b.quantity!)).filter((quantities) => quantities.length);
  if (ranges.length && ranges.every((quantities) =>
    part.quantity < Math.min(...quantities) || part.quantity > Math.max(...quantities))) {
    warnings.push("requested quantity outside all usable analog price-break ranges — manual review needed");
  }

  if (priced.unit_price === null) {
    warnings.push("no usable price breaks in analogs — manual pricing needed");
  }
  if (noAdmittedCandidates) warnings.push("no admitted historical analogs found");
  if (priced.points.length && priced.points.every((p) => p.status !== "won")) {
    warnings.push(priced.points.some((p) => p.status !== "open")
      ? "no verified won-quote analogs — outcomes include unknown/unverified history"
      : "no won-quote analogs — all references are open history");
  }
  if (priced.unit_price !== null && priced.points.some((point) =>
    candidates.some((candidate) => candidate.row.quote_no === point.quote_no &&
      candidate.row.price_evidence?.price_basis !== "customer_quote_pdf"))) {
    warnings.push("price uses internal quote calculations, not verified issued customer-quote prices");
  }

  const evidence_status = priced.unit_price !== null
    ? priced.points.some((point) => candidates.some((candidate) =>
      candidate.row.quote_no === point.quote_no && candidate.row.price_evidence?.price_basis === "customer_quote_pdf"))
      ? "VERIFIED_CUSTOMER_PDF" as const
      : "HISTORICAL_INTERNAL_CALCULATION" as const
    : historicalEvidencePresent
      ? "PRESENT_BUT_NO_USABLE_PRICE" as const
      : "NONE" as const;
  const proposal_status = priced.unit_price !== null ? "NUMERIC_PROVISIONAL" as const : "MISSING" as const;
  const uncertainties = priced.unit_price !== null
    ? [
      ...(evidence_status === "VERIFIED_CUSTOMER_PDF"
        ? ["Historical issued price has unknown outcome"]
        : ["Historical nominal price is not current-cost proof"]),
      ...(provisionalFallback
        ? ["Jev admitted no high-confidence analog; retained candidate is a provisional human-review fallback"]
        : []),
    ]
    : evidence_status === "PRESENT_BUT_NO_USABLE_PRICE"
      ? ["Evidence is present but no usable unit price was found"]
      : ["No admissible evidence or operator-supported amount exists"];

  return {
    part,
    unit_price: priced.unit_price !== null ? Math.round(priced.unit_price * 10000) / 10000 : null,
    extended_price:
      priced.unit_price !== null
        ? Math.round(priced.unit_price * part.quantity * 100) / 100
        : null,
    price_low: priced.low,
    price_high: priced.high,
    confidence: priced.confidence,
    method: priced.method,
    status_basis: verdict.source === "jev" ? `jev+${strategy}` : `fallback:${strategy}`,
    proposal_status,
    evidence_status,
    next_action: priced.unit_price !== null
      ? "Human review required before approval; verify current costs and assumptions"
      : evidence_status === "PRESENT_BUT_NO_USABLE_PRICE"
        ? "Operator follow-up: provide an explicit unit price or supported cost-plus inputs"
        : "No defensible basis; obtain operator-supported pricing or hold",
    uncertainties,
    analogs: candidates.map((c) => ({
      quote_no: c.row.quote_no,
      quote_date: c.row.quote_date,
      date_stamp: c.row.date_stamp,
      rev: c.row.rev,
      customer: c.row.customer.trim(),
      part_no: c.row.part_no,
      description: c.row.description,
      status: c.row.status,
      score: Math.round(c.score * 100) / 100,
      jev_probability: verdict.probabilities[c.row.quote_no],
      price_evidence: c.row.price_evidence ?? { price_basis: "internal_quote_calculation" },
      quote_letter: c.row.quote_letter,
      letter_date: c.row.letter_date,
    })),
    warnings,
  };
}
