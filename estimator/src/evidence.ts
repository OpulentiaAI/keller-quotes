import { createHash } from "node:crypto";
import type {
  Candidate, CandidateEvidencePacket, CompatibilityField, EvidenceComparison,
  PartRequest, QuoteRow, RequestCustomer,
} from "./types.js";

export const MAX_EVIDENCE_BREAKS = 24;
const MAX_FIELD_LENGTH = 256;

/** Literal field comparison only: no shared-token or punctuation-stripped equivalence. */
function text(value: string | undefined): string | null {
  return value?.trim() || null;
}
function canonical(value: string): string {
  return value.trim().replace(/\s+/g, " ").toUpperCase();
}
export function drawingNumber(value: string | undefined): string | null {
  const v = text(value);
  return v && !/[\\/:\x00-\x1f\x7f]/.test(v) &&
    !/\.(pdf|png|jpe?g|tiff?|dwg|dxf|step|stp|igs|iges)$/i.test(v) ? v : null;
}

/** Hash an unambiguous tuple, including source identity; do not expose private source paths. */
export function candidateKey(candidate: Candidate | QuoteRow): string {
  const r = "row" in candidate ? candidate.row : candidate;
  const e = r.price_evidence;
  const source = e?.price_basis === "customer_quote_pdf"
    ? [e.price_basis, e.source_document, e.source_document_sha256.toLowerCase(),
      e.source_transcript_sha256.toLowerCase(), e.source_price_field]
    : ["internal_quote_calculation"];
  const identity = [r.quote_no, r.item_no, r.assembly_no, r.quote_letter,
    r.quote_date, r.letter_date, r.date_stamp, r.customer_id, r.customer, r.part_no,
    r.rev, r.drawing_no, r.drawing_revision, r.material, r.finish].map((v) => v ?? "");
  return `candidate:${createHash("sha256").update(JSON.stringify([identity, source])).digest("hex")}`;
}

/** The legacy register can group multiple assemblies under one quote/item. Keep their curves separate. */
export function splitCandidateIdentities(candidates: Candidate[]): Candidate[] {
  return candidates.flatMap((candidate) => {
    const groups = new Map<string, QuoteRow[]>();
    for (const row of candidate.breaks) {
      const key = candidateKey(row);
      const rows = groups.get(key) ?? [];
      rows.push(row);
      groups.set(key, rows);
    }
    return [...groups.values()].map((breaks) => ({
      ...candidate, row: breaks.find(hasUsableBreak) ?? breaks[0]!, breaks,
    }));
  });
}

export function hasUsableBreak(row: { quantity: number | null; unit_price: number | null }): boolean {
  return row.quantity !== null && Number.isFinite(row.quantity) && row.quantity > 0 &&
    row.unit_price !== null && Number.isFinite(row.unit_price) && row.unit_price > 0;
}

export function compareEvidence(
  part: PartRequest, c: Candidate, customer: RequestCustomer = {},
): EvidenceComparison[] {
  const r = c.row;
  const fields: [CompatibilityField, string | undefined, string | undefined][] = [
    ["customer_id", customer.customer_id, r.customer_id], ["customer", customer.customer, r.customer],
    ["part_no", part.part_no, r.part_no], ["revision", part.revision, r.rev],
    ["drawing_no", drawingNumber(part.drawing_no) ?? undefined, drawingNumber(r.drawing_no) ?? undefined],
    ["drawing_revision", part.drawing_revision, r.drawing_revision],
    ["material", part.material, r.material], ["finish", part.finish, r.finish],
  ];
  const key = candidateKey(c);
  return fields.map<EvidenceComparison>(([field, requested, source]) => {
    const want = text(requested), have = text(source);
    return {
      field, requested: want?.slice(0, MAX_FIELD_LENGTH) ?? null,
      source: have?.slice(0, MAX_FIELD_LENGTH) ?? null,
      status: want === null || have === null ? "unknown" : canonical(want) === canonical(have) ? "match" : "conflict",
      source_origin: have === null ? "unavailable" : "register_field",
      source_ref: key,
      truncated: (want?.length ?? 0) > MAX_FIELD_LENGTH || (have?.length ?? 0) > MAX_FIELD_LENGTH,
    };
  });
}

/** Different part numbers/customers can be comparison analogs; explicit engineering conflicts cannot. */
export function hasEngineeringConflict(comparisons: EvidenceComparison[]): boolean {
  return comparisons.some((f) => f.status === "conflict" &&
    ["revision", "drawing_no", "drawing_revision", "material", "finish"].includes(f.field));
}

export function customerCompatibility(comparisons: EvidenceComparison[]): "match" | "conflict" | "unknown" {
  const id = comparisons.find((f) => f.field === "customer_id")!;
  const name = comparisons.find((f) => f.field === "customer")!;
  // Neither a similar name nor a matching ID silently erases an explicit conflict.
  if (id.status === "conflict" || name.status === "conflict") return "conflict";
  return id.status === "match" || name.status === "match" ? "match" : "unknown";
}

export function evidencePacket(
  part: PartRequest, c: Candidate, customer: RequestCustomer = {},
  screening: CandidateEvidencePacket["screening"] = { status: "not_screened", reason: "NOT_SCREENED" },
): CandidateEvidencePacket {
  const key = candidateKey(c);
  const e = c.row.price_evidence;
  const pdf = e?.price_basis === "customer_quote_pdf" ? e : null;
  const quantities = c.breaks.filter(hasUsableBreak).map((b) => b.quantity!);
  const min = quantities.length ? Math.min(...quantities) : null;
  const max = quantities.length ? Math.max(...quantities) : null;
  const kind = min === null || max === null ? "unavailable"
    : quantities.includes(part.quantity) ? "exact"
      : min === max ? "single_break"
        : part.quantity < min || part.quantity > max ? "extrapolated" : "interpolated";
  const finite = (n: number | null) => n !== null && Number.isFinite(n) ? n : null;
  return {
    candidate_key: key,
    identity: {
      quote_no: (c.row.quote_no ?? "").slice(0, MAX_FIELD_LENGTH),
      item_no: (c.row.item_no ?? "").slice(0, MAX_FIELD_LENGTH),
      assembly_no: (c.row.assembly_no ?? "").slice(0, MAX_FIELD_LENGTH),
      quote_letter: (c.row.quote_letter ?? "").slice(0, MAX_FIELD_LENGTH),
      truncated: [c.row.quote_no, c.row.item_no, c.row.assembly_no, c.row.quote_letter]
        .some((v) => (v?.length ?? 0) > MAX_FIELD_LENGTH),
    },
    comparisons: compareEvidence(part, c, customer),
    source: {
      price_basis: pdf ? "customer_quote_pdf" : "internal_quote_calculation",
      quote_date: (c.row.quote_date ?? "").slice(0, MAX_FIELD_LENGTH),
      date_stamp: (c.row.date_stamp ?? "").slice(0, MAX_FIELD_LENGTH),
      letter_date: (c.row.letter_date ?? "").slice(0, MAX_FIELD_LENGTH),
      source_document_sha256: pdf?.source_document_sha256 ?? null,
      source_transcript_sha256: pdf?.source_transcript_sha256 ?? null,
      source_price_field: pdf?.source_price_field ?? null,
    },
    outcome: {
      recorded_status: (c.row.status ?? "unknown").slice(0, MAX_FIELD_LENGTH),
      basis: !c.row.status || c.row.status === "unknown" ? "unknown" : "unverified_register_status",
      actual_cost: "unknown",
    },
    breaks: c.breaks.slice(0, MAX_EVIDENCE_BREAKS).map((b) => ({
      quantity: finite(b.quantity), unit_price: finite(b.unit_price), usable: hasUsableBreak(b),
    })),
    break_count: c.breaks.length,
    breaks_truncated: c.breaks.length > MAX_EVIDENCE_BREAKS,
    quantity_support: { requested: part.quantity, min, max, kind },
    screening,
    pricing: { evaluated: false, used_for_unit_price: false, unit_price_at_quantity: null, weight: null, method: null },
    next_read: pdf ? [{ kind: "source_document_sha256", ref: pdf.source_document_sha256 }]
      : [{ kind: "candidate_key", ref: key }],
    limitations: [
      "Historical register fields are not independently verified PDF specifications; comments and descriptions are not assertions of compatibility.",
      "Recorded prices do not establish issuance, acceptance, payment, current prices or actual job cost; human review is required.",
      "Missing fields remain unknown; numeric breaks preserve register precision, not original decimal text.",
    ],
  };
}
