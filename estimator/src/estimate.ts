import type {
  EstimateRequest,
  CandidateEvidencePacket,
  LineEstimate,
  PartRequest,
  QuoteEstimate,
} from "./types.js";
import { QuoteRegister, normalizePartNo } from "./register.js";
import { retrieve } from "./retrieve.js";
import { JevClient } from "./jev.js";
import { price } from "./price.js";
import {
  candidateKey, customerCompatibility, drawingNumber, evidencePacket,
  hasEngineeringConflict, hasUsableBreak, splitCandidateIdentities,
} from "./evidence.js";

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
    for (const field of ["part_no", "description", "material", "finish", "revision", "drawing_no", "drawing_revision", "drawing_ref", "notes"]) {
      if (part[field] !== undefined && typeof part[field] !== "string") {
        throw new Error(`request.parts[${i}].${field} must be a string`);
      }
    }
    if (typeof part.drawing_no === "string" && part.drawing_no.trim() && !drawingNumber(part.drawing_no)) {
      throw new Error(`request.parts[${i}].drawing_no must be a drawing number, not an asset path`);
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
  // retrieve's legacy drawing_ref input is a discovery hook only. Pass the explicit
  // drawing number there, never the request's asset reference.
  let candidates = splitCandidateIdentities(retrieve(reg, {
    ...part, drawing_ref: drawingNumber(part.drawing_no) ?? undefined,
  }, {
    customer: req.customer,
    customerId: req.customer_id,
    limit: 12,
    exclude: opts.exclude,
    asOf: opts.asOf,
  }));
  const historicalEvidencePresent = candidates.length > 0;
  const packets = new Map<string, CandidateEvidencePacket>();
  const omitted: CandidateEvidencePacket[] = [];
  const packet = (c: typeof candidates[number]) => {
    const key = candidateKey(c);
    let value = packets.get(key);
    if (!value) {
      value = evidencePacket(part, c, req);
      packets.set(key, value);
    }
    return value;
  };
  candidates = candidates.filter((c) => {
    const evidence = packet(c);
    const conflict = hasEngineeringConflict(evidence.comparisons);
    if (conflict || !c.breaks.some(hasUsableBreak)) {
      evidence.screening = conflict ? { status: "incompatible", reason: "EXPLICIT_CONFLICT" }
        : { status: "unpriceable", reason: "NO_USABLE_PRICE" };
      omitted.push(evidence);
      return false;
    }
    return true;
  });
  const partNo = normalizePartNo(part.part_no ?? "");
  const wantsCustomer = Boolean(req.customer_id?.trim() || req.customer?.trim());
  if (partNo) {
    const exact = candidates.filter((c) => normalizePartNo(c.row.part_no) === partNo &&
      (!wantsCustomer || customerCompatibility(packet(c).comparisons) === "match"));
    if (exact.length) {
      for (const c of candidates) if (!exact.includes(c)) {
        const evidence = packet(c);
        evidence.screening = { status: "not_screened", reason: "EXACT_PREFERENCE" };
        omitted.push(evidence);
      }
      candidates = exact;
    }
  }
  // A cross-customer exact ID must not consume the whole screening budget ahead
  // of a candidate with a nonconflicting customer namespace.
  candidates.sort((a, b) => Number(customerCompatibility(packet(a).comparisons) === "conflict") -
    Number(customerCompatibility(packet(b).comparisons) === "conflict"));
  const verdict = await jev.rankAnalogs(part, candidates, opts.rankLimit, req);
  if (verdict.source === "jev") {
    // Legacy mock/consumer IDs are usable only when unambiguous. Never join two items by quote_no.
    const keys = verdict.rankedKeys ?? verdict.rankedIds.flatMap((id) => {
      const matches = candidates.filter((c) => c.row.quote_no === id);
      return matches.length === 1 ? [candidateKey(matches[0]!)] : [];
    });
    const order = new Map(keys.map((id, i) => [id, i]));
    candidates = [...candidates].sort(
      (a, b) => (order.get(candidateKey(a)) ?? Number.MAX_SAFE_INTEGER) -
        (order.get(candidateKey(b)) ?? Number.MAX_SAFE_INTEGER),
    );
  }

  const screeningBudget = Math.min(opts.screenTopN, opts.rankLimit, 12);
  if (candidates.length > screeningBudget) {
    const skipped = candidates.length - screeningBudget;
    warnings.push(`screening budget skipped ${skipped} analog${skipped === 1 ? "" : "s"}`);
  }
  for (const c of candidates.slice(screeningBudget)) {
    const evidence = packet(c);
    evidence.screening = { status: "not_screened", reason: "SCREEN_BUDGET" };
    omitted.push(evidence);
  }
  const screened: typeof candidates = [];
  for (const c of candidates.slice(0, screeningBudget)) {
    const v = await jev.screenCandidate(part, c, req);
    const evidence = packet(c);
    if (v !== "admit") {
      evidence.screening = { status: v === "reject" ? "rejected" : "quarantined",
        reason: v === "unavailable" ? "SCREEN_UNAVAILABLE" : v === "reject" ? "REJECTED" : "QUARANTINED" };
      omitted.push(evidence);
      warnings.push(`${v === "reject" ? "rejected" : "quarantined"} analog ${c.row.quote_no}`);
      continue;
    }
    evidence.screening = { status: "admitted", reason: "ADMITTED" };
    screened.push(c);
  }
  candidates = screened;

  const strategy = await jev.chooseStrategy(part, candidates, req);
  const priced = price(part.quantity, candidates, {
    strategy,
    jevProbabilities: verdict.probabilities,
    customerId: req.customer_id,
    customer: req.customer,
    now: opts.asOf ? Date.parse(`${opts.asOf}T00:00:00Z`) : undefined,
  });

  const pointsByKey = new Map(priced.points.map((point) => [point.candidate_key, point]));
  for (const c of candidates) {
    const point = pointsByKey.get(candidateKey(c));
    if (point) packet(c).pricing = {
      evaluated: true, used_for_unit_price: point.used_for_unit_price === true,
      unit_price_at_quantity: point.unit_price, weight: point.weight, method: priced.method,
    };
  }
  const contributors = candidates.filter((c) => pointsByKey.get(candidateKey(c))?.used_for_unit_price);
  if (omitted.length > 12) warnings.push(`evidence packet omitted ${omitted.length - 12} non-admitted candidates`);

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
  if (!candidates.length) warnings.push("no admitted historical analogs found");
  if (priced.points.length && priced.points.every((p) => p.status !== "won")) {
    warnings.push(priced.points.some((p) => p.status !== "open")
      ? "no recorded won-quote analogs — outcomes include unknown/unverified history"
      : "no won-quote analogs — all references are open history");
  }
  const hasInternal = contributors.some((c) => c.row.price_evidence?.price_basis !== "customer_quote_pdf");
  const hasPdf = contributors.some((c) => c.row.price_evidence?.price_basis === "customer_quote_pdf");
  if (priced.unit_price !== null && hasInternal) {
    warnings.push(hasPdf ? "price uses mixed recorded PDF prices and internal quote calculations"
      : "price uses internal quote calculations, not verified issued customer-quote prices");
  }
  if (priced.points.some((point) => point.status === "won")) {
    warnings.push("legacy won-status weighting is retained; register status is not verified commercial success");
  }

  const evidence_status = priced.unit_price !== null
    ? hasPdf && hasInternal ? "MIXED_HISTORICAL" as const
      : hasPdf ? "VERIFIED_CUSTOMER_PDF" as const
        : "HISTORICAL_INTERNAL_CALCULATION" as const
    : historicalEvidencePresent
      ? "PRESENT_BUT_NO_USABLE_PRICE" as const
      : "NONE" as const;
  const proposal_status = priced.unit_price !== null ? "NUMERIC_PROVISIONAL" as const : "MISSING" as const;
  const uncertainties = priced.unit_price !== null
    ? evidence_status === "VERIFIED_CUSTOMER_PDF"
      ? ["Historical recorded PDF price has unverified issuance and outcome", "Historical price is not current-cost proof"]
      : ["Historical nominal price is not current-cost proof"]
    : evidence_status === "PRESENT_BUT_NO_USABLE_PRICE"
      ? ["Evidence is present but no admitted usable price supports this proposal"]
      : ["No admissible evidence or operator-supported amount exists"];
  if (contributors.some((c) => packet(c).comparisons.some((f) => f.requested !== null && f.status !== "match"))) {
    uncertainties.push("Historical scope has differing or unknown fields; comparison is not approval for reuse");
  }

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
    evidence_candidates: omitted.slice(0, 12),
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
      jev_probability: verdict.probabilities[candidateKey(c)],
      price_evidence: c.row.price_evidence ?? { price_basis: "internal_quote_calculation" },
      quote_letter: c.row.quote_letter,
      letter_date: c.row.letter_date,
      evidence: packet(c),
    })),
    warnings,
  };
}
