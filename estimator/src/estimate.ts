import type {
  EstimateRequest,
  LineEstimate,
  PartRequest,
  QuoteEstimate,
} from "./types.js";
import { QuoteRegister } from "./register.js";
import { retrieve } from "./retrieve.js";
import { JevClient } from "./jev.js";
import { price } from "./price.js";

export interface EstimateOptions {
  jev?: JevClient;
  /** Max candidates passed to Jev ranking per part. */
  rankLimit?: number;
  /** Run Jev screening on the top-N ranked analogs. */
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

  const verdict = await jev.rankAnalogs(part, candidates, opts.rankLimit);
  if (verdict.source === "jev") {
    const order = new Map(verdict.rankedIds.map((id, i) => [id, i]));
    candidates = [...candidates].sort(
      (a, b) => (order.get(a.row.quote_no) ?? 999) - (order.get(b.row.quote_no) ?? 999),
    );
  }

  // Screen the top few; drop rejects.
  const screened: typeof candidates = [];
  for (const [i, c] of candidates.entries()) {
    if (i >= opts.screenTopN) {
      screened.push(c);
      continue;
    }
    const v = await jev.screenCandidate(part, c);
    if (v === "reject") {
      warnings.push(`rejected analog ${c.row.quote_no}`);
      continue;
    }
    screened.push(c);
  }
  candidates = screened;

  const strategy = await jev.chooseStrategy(part, candidates);
  const priced = price(part.quantity, candidates.slice(0, opts.rankLimit), {
    strategy,
    jevProbabilities: verdict.probabilities,
    customerId: req.customer_id,
    customer: req.customer,
    now: opts.asOf ? Date.parse(`${opts.asOf}T00:00:00Z`) : undefined,
  });

  if (priced.unit_price === null) {
    warnings.push("no usable price breaks in analogs — manual pricing needed");
  }
  if (!candidates.length) warnings.push("no historical analogs found");
  if (priced.points.length && priced.points.every((p) => p.status !== "won")) {
    warnings.push("no won-quote analogs — all references are open history");
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
    analogs: candidates.slice(0, 5).map((c) => ({
      quote_no: c.row.quote_no,
      quote_date: c.row.quote_date,
      customer: c.row.customer.trim(),
      part_no: c.row.part_no,
      description: c.row.description,
      status: c.row.status,
      score: Math.round(c.score * 100) / 100,
      jev_probability: verdict.probabilities[c.row.quote_no],
    })),
    warnings,
  };
}
