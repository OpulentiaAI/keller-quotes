import { createHash } from "node:crypto";
import { estimate } from "./estimate.js";
import { JevClient } from "./jev.js";
import type { QuoteRegister } from "./register.js";
import type { EvidenceStatus, LineEstimate, PartRequest, ProposalStatus } from "./types.js";

export type OrderPricing =
  | { method: "unit_price"; unit_price: number; reason: string }
  | { method: "cost_plus"; material_per_unit: number; labor_per_unit: number; outside_per_unit: number; setup_total: number; margin_pct: number; reason: string };

export interface OrderLineRequest extends PartRequest {
  line_id: string;
  pricing?: OrderPricing;
}

export interface OrderRequest {
  order_id: string;
  quote_date: string;
  customer: string;
  customer_id?: string;
  rfq_no?: string;
  parts: OrderLineRequest[];
  charges?: { shipping?: number | null; tax?: number | null };
  additional_charges?: { label: string; amount: number }[];
  notes?: string;
}

export interface PricedOrderLine {
  line_id: string;
  part: PartRequest;
  unit_price: number | null;
  extended_price: number | null;
  pricing_source: "historical_analog" | "explicit_unit_price" | "cost_build_up" | "unpriced";
  pricing_reason: string;
  confidence: number | null;
  analogs: LineEstimate["analogs"];
  warnings: string[];
  proposal_status: ProposalStatus;
  evidence_status: EvidenceStatus;
  next_action: string;
  uncertainties: string[];
}

export interface PricedOrder {
  schema_version: 1;
  request: OrderRequest;
  order_id: string;
  quote_date: string;
  customer: string;
  currency: "USD";
  state: "PRICED_REQUIRES_REVIEW" | "BLOCKED";
  requires_human_review: true;
  lines: PricedOrderLine[];
  charges: { shipping: number | null; tax: number | null };
  additional_charges: { label: string; amount: number }[];
  priced_subtotal: number;
  subtotal: number | null;
  total: number | null;
  blockers: string[];
  warnings: string[];
  provenance: { request_sha256: string; register_sha256: string; as_of: string; mode: "offline" };
}

function object(value: unknown, path: string, keys: string[]): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(`${path} must be an object`);
  const record = value as Record<string, unknown>;
  for (const key of Object.keys(record)) if (!keys.includes(key)) throw new Error(`${path}.${key} is not supported`);
  return record;
}

function text(value: unknown, path: string, required = false): void {
  if (value === undefined && !required) return;
  if (typeof value !== "string" || (required && !value.trim())) throw new Error(`${path} must be a nonblank string`);
}

function date(value: unknown): asserts value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
    Number.isNaN(Date.parse(`${value}T00:00:00Z`)) ||
    new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) !== value) {
    throw new Error("request.quote_date must be a valid YYYY-MM-DD date");
  }
}

function decimal(value: number): { numerator: bigint; denominator: bigint } {
  const match = /^(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i.exec(value.toString());
  if (!match) throw new Error("invalid decimal number");
  const exponent = Number(match[3] ?? 0) - (match[2]?.length ?? 0);
  const digits = BigInt(match[1]! + (match[2] ?? ""));
  return exponent >= 0
    ? { numerator: digits * 10n ** BigInt(exponent), denominator: 1n }
    : { numerator: digits, denominator: 10n ** BigInt(-exponent) };
}

function scaled(value: unknown, path: string, places: number, positive = false): bigint {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || (positive && value === 0)) {
    throw new Error(`${path} must be a ${positive ? "positive" : "nonnegative"} finite number`);
  }
  const { numerator, denominator } = decimal(value);
  const units = numerator * 10n ** BigInt(places);
  if (units % denominator !== 0n || units / denominator > BigInt(Number.MAX_SAFE_INTEGER)) {
    throw new Error(`${path} must have at most ${places} decimal places and fit a safe integer`);
  }
  return units / denominator;
}

function safe(value: bigint, path: string): number {
  if (value < 0n || value > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error(`${path} exceeds safe arithmetic range`);
  return Number(value);
}

function amount(value: bigint, places: 2 | 4, path: string): number {
  const result = safe(value, path) / 10 ** places;
  if (scaled(result, path, places) !== value) throw new Error(`${path} cannot be represented at ${places} decimal places`);
  return result;
}

function halfUp(numerator: bigint, denominator: bigint): bigint {
  return (numerator * 2n + denominator) / (denominator * 2n);
}

function extend(unit4: bigint, quantity: number, path: string): bigint {
  return BigInt(safe(halfUp(unit4 * BigInt(quantity), 100n), `${path}.extended_price`));
}

export function assertOrderRequest(request: unknown): asserts request is OrderRequest {
  const req = object(request, "request", ["order_id", "quote_date", "customer", "customer_id", "rfq_no", "parts", "charges", "additional_charges", "notes"]);
  text(req.order_id, "request.order_id", true);
  date(req.quote_date);
  text(req.customer, "request.customer", true);
  for (const key of ["customer_id", "rfq_no", "notes"]) text(req[key], `request.${key}`);
  if (!Array.isArray(req.parts) || req.parts.length === 0) throw new Error("request.parts must be a nonempty array");
  const ids = new Set<string>();
  for (const [i, item] of req.parts.entries()) {
    const path = `request.parts[${i}]`;
    const part = object(item, path, ["line_id", "part_no", "description", "quantity", "material", "finish", "drawing_ref", "notes", "pricing"]);
    text(part.line_id, `${path}.line_id`, true);
    if (ids.has(part.line_id as string)) throw new Error(`duplicate line_id: ${part.line_id}`);
    ids.add(part.line_id as string);
    for (const key of ["part_no", "description", "material", "finish", "drawing_ref", "notes"]) text(part[key], `${path}.${key}`);
    if (!(typeof part.part_no === "string" && part.part_no.trim()) &&
      !(typeof part.description === "string" && part.description.trim())) throw new Error(`${path} needs part_no or description`);
    if (!Number.isSafeInteger(part.quantity) || (part.quantity as number) <= 0) throw new Error(`${path}.quantity must be a positive safe integer`);
    if (part.pricing !== undefined) {
      const pricing = object(part.pricing, `${path}.pricing`, ["method", "unit_price", "material_per_unit", "labor_per_unit", "outside_per_unit", "setup_total", "margin_pct", "reason"]);
      text(pricing.reason, `${path}.pricing.reason`, true);
      if (pricing.method === "unit_price") {
        if (Object.keys(pricing).some((key) => !["method", "unit_price", "reason"].includes(key))) throw new Error(`${path}.pricing has invalid unit_price fields`);
        scaled(pricing.unit_price, `${path}.pricing.unit_price`, 4, true);
      } else if (pricing.method === "cost_plus") {
        if (Object.keys(pricing).some((key) => !["method", "material_per_unit", "labor_per_unit", "outside_per_unit", "setup_total", "margin_pct", "reason"].includes(key))) throw new Error(`${path}.pricing has invalid cost_plus fields`);
        for (const key of ["material_per_unit", "labor_per_unit", "outside_per_unit"] as const) scaled(pricing[key], `${path}.pricing.${key}`, 4);
        scaled(pricing.setup_total, `${path}.pricing.setup_total`, 2);
        if (typeof pricing.margin_pct !== "number" || !Number.isFinite(pricing.margin_pct) || pricing.margin_pct < 0 || pricing.margin_pct >= 100) {
          throw new Error(`${path}.pricing.margin_pct must be finite and between 0 and 100 (exclusive)`);
        }
      } else throw new Error(`${path}.pricing.method is not supported`);
    }
  }
  if (req.charges !== undefined) {
    const charges = object(req.charges, "request.charges", ["shipping", "tax"]);
    for (const key of ["shipping", "tax"]) if (charges[key] !== undefined && charges[key] !== null) scaled(charges[key], `request.charges.${key}`, 2);
  }
  if (req.additional_charges !== undefined) {
    if (!Array.isArray(req.additional_charges)) throw new Error("request.additional_charges must be an array");
    for (const [i, charge] of req.additional_charges.entries()) {
      const path = `request.additional_charges[${i}]`;
      const item = object(charge, path, ["label", "amount"]);
      text(item.label, `${path}.label`, true);
      scaled(item.amount, `${path}.amount`, 2);
    }
  }
}

export async function buildPricedOrder(reg: QuoteRegister, request: unknown, options: { registerSha256: string }): Promise<PricedOrder> {
  assertOrderRequest(request);
  if (!options || typeof options.registerSha256 !== "string" || !/^[a-f\d]{64}$/i.test(options.registerSha256)) {
    throw new Error("registerSha256 must be a 64-character hex digest");
  }
  const requestSha = createHash("sha256").update(JSON.stringify(request)).digest("hex");
  const lines: PricedOrderLine[] = [];
  const blockers: string[] = [];
  const warnings: string[] = [];
  let pricedCents = 0n;
  for (const { line_id, pricing, ...part } of request.parts) {
    let unit4: bigint | null = null;
    let pricing_source: PricedOrderLine["pricing_source"] = "unpriced";
    let pricing_reason = "No usable historical price; operator pricing required";
    let confidence: number | null = null;
    let analogs: LineEstimate["analogs"] = [];
    let lineWarnings: string[] = [];
    let proposal_status: ProposalStatus = "MISSING";
    let evidence_status: EvidenceStatus = "NONE";
    let next_action = "No defensible basis; obtain operator-supported pricing or hold";
    let uncertainties = ["No admissible evidence or operator-supported amount exists"];
    if (pricing?.method === "unit_price") {
      unit4 = scaled(pricing.unit_price, `line ${line_id}.unit_price`, 4, true);
      pricing_source = "explicit_unit_price";
      pricing_reason = pricing.reason;
      lineWarnings = ["Operator-supplied unit price is a proposal, not approval"];
      proposal_status = "NUMERIC_PROVISIONAL";
      evidence_status = "OPERATOR_INPUT";
      next_action = "Human review required before approval; verify operator price basis and assumptions";
      uncertainties = ["Operator amount is not verified current cost or approval"];
    } else if (pricing?.method === "cost_plus") {
      const costs = scaled(pricing.material_per_unit, "material_per_unit", 4) + scaled(pricing.labor_per_unit, "labor_per_unit", 4) + scaled(pricing.outside_per_unit, "outside_per_unit", 4);
      const setup = scaled(pricing.setup_total, "setup_total", 2);
      const margin = decimal(pricing.margin_pct);
      const denominator = BigInt(part.quantity) * (100n * margin.denominator - margin.numerator);
      unit4 = halfUp((costs * BigInt(part.quantity) + setup * 100n) * 100n * margin.denominator, denominator);
      safe(unit4, `line ${line_id}.unit_price`);
      if (unit4 === 0n) throw new Error(`line ${line_id} cost build-up produces a zero price`);
      pricing_source = "cost_build_up";
      pricing_reason = pricing.reason;
      lineWarnings = ["Operator-supplied cost inputs and margin are a proposal, not approval"];
      proposal_status = "NUMERIC_PROVISIONAL";
      evidence_status = "OPERATOR_INPUT";
      next_action = "Human review required before approval; verify operator costs, margin, and assumptions";
      uncertainties = ["Operator cost inputs and margin are not verified current costs or approval"];
    } else {
      const result = await estimate(reg, { customer: request.customer, customer_id: request.customer_id, rfq_no: request.rfq_no, parts: [part] }, {
        jev: new JevClient(""), asOf: request.quote_date,
      });
      const line = result.lines[0]!;
      analogs = line.analogs;
      lineWarnings = line.warnings;
      evidence_status = line.evidence_status;
      next_action = line.next_action;
      uncertainties = line.uncertainties;
      if (line.unit_price !== null && Number.isFinite(line.unit_price) && line.unit_price > 0) {
        unit4 = scaled(line.unit_price, `line ${line_id}.historical_unit_price`, 4, true);
        pricing_source = "historical_analog";
        pricing_reason = `Offline historical analog (${line.method}; ${line.status_basis})`;
        confidence = line.confidence;
        lineWarnings = [...lineWarnings, "Historical analog prices are nominal as-quoted dollars, not current-cost estimates"];
        proposal_status = "NUMERIC_PROVISIONAL";
      }
    }
    const cents = unit4 === null ? null : extend(unit4, part.quantity, `line ${line_id}`);
    if (cents !== null) pricedCents = BigInt(safe(pricedCents + cents, "priced_subtotal"));
    else blockers.push(`line ${line_id} is unpriced`);
    warnings.push(...lineWarnings.map((warning) => `line ${line_id}: ${warning}`));
    lines.push({ line_id, part, unit_price: unit4 === null ? null : amount(unit4, 4, `line ${line_id}.unit_price`),
      extended_price: cents === null ? null : amount(cents, 2, `line ${line_id}.extended_price`), pricing_source, pricing_reason,
      confidence, analogs, warnings: lineWarnings, proposal_status, evidence_status, next_action, uncertainties });
  }
  const shipping = request.charges?.shipping ?? null;
  const tax = request.charges?.tax ?? null;
  if (shipping === null) blockers.push("shipping is missing");
  if (tax === null) blockers.push("tax is missing");
  let chargeCents = 0n;
  for (const charge of request.additional_charges ?? []) chargeCents = BigInt(safe(chargeCents + scaled(charge.amount, `additional charge ${charge.label}`, 2), "additional_charges"));
  const subtotal = lines.every((line) => line.extended_price !== null) ? amount(pricedCents, 2, "subtotal") : null;
  const total = blockers.length ? null : amount(pricedCents + chargeCents + scaled(shipping, "shipping", 2) + scaled(tax, "tax", 2), 2, "total");
  return {
    schema_version: 1, request, order_id: request.order_id, quote_date: request.quote_date, customer: request.customer,
    currency: "USD", state: blockers.length ? "BLOCKED" : "PRICED_REQUIRES_REVIEW", requires_human_review: true,
    lines, charges: { shipping, tax }, additional_charges: request.additional_charges ?? [],
    priced_subtotal: amount(pricedCents, 2, "priced_subtotal"), subtotal, total, blockers, warnings,
    provenance: { request_sha256: requestSha, register_sha256: options.registerSha256.toLowerCase(), as_of: request.quote_date, mode: "offline" },
  };
}

function md(value: unknown): string {
  return String(value ?? "—").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/([\\`*_{}\[\]()#+.!|~-])/g, "\\$1")
    .replace(/\r\n|\r|\n/g, "<br>");
}

export function renderOrderMarkdown(order: PricedOrder): string {
  const money = (value: number | null) => value === null ? "—" : `$${value.toFixed(2)}`;
  const lines = [
    `# Priced order ${md(order.order_id)}`, "",
    `Customer: ${md(order.customer)}  `, `Quote date: ${md(order.quote_date)}  `,
    `Customer ID: ${md(order.request.customer_id)}  `,
    `RFQ: ${md(order.request.rfq_no)}  `,
    `Order notes: ${md(order.request.notes)}  `,
    `State: ${md(order.state)} — human review required`, "",
    "| Line | Part / description | Qty | Unit price | Extended | Source | Proposal | Evidence | Next action |",
    "| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |",
    ...order.lines.map((line) => `| ${md(line.line_id)} | ${md(line.part.part_no ?? line.part.description)} | ${line.part.quantity} | ${line.unit_price === null ? "—" : `$${line.unit_price.toFixed(4)}`} | ${money(line.extended_price)} | ${md(line.pricing_source)} | ${md(line.proposal_status)} | ${md(line.evidence_status)} | ${md(line.next_action)} |`),
    "", `Priced subtotal (partial diagnostic): ${money(order.priced_subtotal)}  `,
    `Subtotal (lines): ${money(order.subtotal)}  `, `Shipping: ${money(order.charges.shipping)}  `,
    `Tax: ${money(order.charges.tax)}  `,
    ...order.additional_charges.map((charge) => `${md(charge.label)}: ${money(charge.amount)}  `),
    `Total: ${money(order.total)}`, "",
    "## Review details", "",
    ...order.lines.flatMap((line) => [
      `### ${md(line.line_id)}`, "",
      `Request line: ${md(JSON.stringify(order.request.parts.find((part) => part.line_id === line.line_id)))}  `,
      `Pricing reason: ${md(line.pricing_reason)}  `,
      `Proposal status: ${md(line.proposal_status)}; evidence status: ${md(line.evidence_status)}  `,
      `Next action: ${md(line.next_action)}  `,
      ...line.uncertainties.map((uncertainty) => `- Uncertainty: ${md(uncertainty)}`),
      ...line.warnings.map((warning) => `- Warning: ${md(warning)}`),
      ...line.analogs.map((analog) => `- Analog ${md(analog.quote_no)} (${md(analog.quote_date)}): ${md(analog.part_no)}; ${md(analog.description)}; ${md(analog.customer)}; ${md(analog.status)}; score ${analog.score}; price basis ${md(analog.price_evidence.price_basis)}${analog.price_evidence.price_basis === "customer_quote_pdf"
        ? `; source ${md(analog.price_evidence.source_document)}; PDF SHA-256 ${md(analog.price_evidence.source_document_sha256)}; transcript SHA-256 ${md(analog.price_evidence.source_transcript_sha256)}; source field ${md(analog.price_evidence.source_price_field)}; quote letter ${md(analog.quote_letter)}; letter date ${md(analog.letter_date)}` : ""}`),
      "",
    ]),
    "## Blockers", "", ...(order.blockers.length ? order.blockers.map((blocker) => `- ${md(blocker)}`) : ["None"]), "",
    "## Warnings", "", ...(order.warnings.length ? order.warnings.map((warning) => `- ${md(warning)}`) : ["None"]), "",
    "## Provenance", "",
    `Request SHA-256 (JSON.stringify canonical serialization): ${order.provenance.request_sha256}  `,
    `Register SHA-256: ${order.provenance.register_sha256}  `,
    `As of: ${md(order.provenance.as_of)}; mode: ${order.provenance.mode}`, "",
  ];
  return lines.join("\n");
}
