export type PriceEvidence =
  | { price_basis: "internal_quote_calculation" }
  | {
    price_basis: "customer_quote_pdf";
    source_document: string;
    source_document_sha256: string;
    source_transcript_sha256: string;
    source_price_field: "PRICE" | "QUOTEPRICE";
  };

export interface QuoteRow {
  quote_no: string;
  item_no: string;
  assembly_no: string;
  quote_date: string;
  date_stamp: string;
  customer_id: string;
  customer: string;
  part_no: string;
  description: string;
  rev: string;
  drawing_no: string;
  /** Optional explicit register fields, never inferred from comments or a PDF price. */
  drawing_revision?: string;
  finish?: string;
  rfq_no: string;
  buyer_name: string;
  salesperson: string;
  quote_letter: string;
  letter_date: string;
  quantity: number | null;
  unit_price: number | null;
  unit_cost: number | null;
  extended_price: number | null;
  markup: number | null;
  del_seq: number | null;
  material: string;
  status: string;
  won_date: string;
  to_quote: string;
  user_quote: string;
  newsellpri: number | null;
  comment: string;
  price_evidence?: PriceEvidence;
}

export interface PartRequest {
  part_no?: string;
  description?: string;
  quantity: number;
  material?: string;
  finish?: string;
  /** Part revision, distinct from the drawing revision. */
  revision?: string;
  drawing_no?: string;
  drawing_revision?: string;
  /** Asset reference only; not an asserted drawing number (path or id). */
  drawing_ref?: string;
  notes?: string;
}

export interface EstimateRequest {
  customer?: string;
  customer_id?: string;
  rfq_no?: string;
  parts: PartRequest[];
  notes?: string;
}

export interface Candidate {
  /** Representative register row (best break) for this historical quote. */
  row: QuoteRow;
  /** All qty/price breaks for this candidate's composite identity. */
  breaks: QuoteRow[];
  /** Deterministic similarity score in [0,1]. */
  score: number;
  reasons: string[];
}

export type RequestCustomer = Pick<EstimateRequest, "customer" | "customer_id">;

export interface JevVerdict {
  /** Legacy display IDs; may repeat. Use rankedKeys for identity joins. */
  rankedIds: string[];
  rankedKeys?: string[];
  /** Keyed by candidateKey(), never by quote_no. */
  probabilities: Record<string, number>;
  source: "jev" | "fallback";
}

export interface PricePoint {
  quantity: number;
  unit_price: number;
  quote_no: string;
  quote_date: string;
  status: string;
  weight: number;
  candidate_key?: string;
  /** True only when this point participated in the executed unit-price strategy. */
  used_for_unit_price?: boolean;
}

export type CompatibilityField =
  | "customer_id" | "customer" | "part_no" | "revision"
  | "drawing_no" | "drawing_revision" | "material" | "finish";

export interface EvidenceComparison {
  field: CompatibilityField;
  requested: string | null;
  source: string | null;
  status: "match" | "conflict" | "unknown";
  source_origin: "register_field" | "unavailable";
  /** Matching register text is not PDF specification verification. */
  source_ref: string;
  truncated: boolean;
}

export interface CandidateEvidencePacket {
  candidate_key: string;
  identity: { quote_no: string; item_no: string; assembly_no: string; quote_letter: string; truncated: boolean };
  comparisons: EvidenceComparison[];
  source: {
    price_basis: PriceEvidence["price_basis"];
    quote_date: string;
    date_stamp: string;
    letter_date: string;
    source_document_sha256: string | null;
    source_transcript_sha256: string | null;
    source_price_field: "PRICE" | "QUOTEPRICE" | null;
  };
  outcome: {
    recorded_status: string;
    basis: "unknown" | "unverified_register_status";
    actual_cost: "unknown";
  };
  /** Original numeric register precision, not newly rounded prices or raw decimal lexemes. */
  breaks: { quantity: number | null; unit_price: number | null; usable: boolean }[];
  break_count: number;
  breaks_truncated: boolean;
  quantity_support: {
    requested: number;
    min: number | null;
    max: number | null;
    kind: "exact" | "interpolated" | "extrapolated" | "single_break" | "unavailable";
  };
  screening: {
    status: "admitted" | "rejected" | "quarantined" | "not_screened" | "unpriceable" | "incompatible";
    reason: "ADMITTED" | "REJECTED" | "QUARANTINED" | "SCREEN_UNAVAILABLE" | "SCREEN_BUDGET"
      | "EXACT_PREFERENCE" | "NO_USABLE_PRICE" | "EXPLICIT_CONFLICT" | "NOT_SCREENED";
  };
  pricing: {
    evaluated: boolean;
    used_for_unit_price: boolean;
    unit_price_at_quantity: number | null;
    weight: number | null;
    method: string | null;
  };
  /** Opaque bounded read hints; never private paths, comments, or document bodies. */
  next_read: { kind: "source_document_sha256" | "candidate_key"; ref: string }[];
  limitations: string[];
}

export type ProposalStatus = "NUMERIC_PROVISIONAL" | "MISSING";

export type EvidenceStatus =
  | "VERIFIED_CUSTOMER_PDF"
  | "MIXED_HISTORICAL"
  | "HISTORICAL_INTERNAL_CALCULATION"
  | "OPERATOR_INPUT"
  | "PRESENT_BUT_NO_USABLE_PRICE"
  | "NONE";

export interface LineEstimate {
  part: PartRequest;
  unit_price: number | null;
  extended_price: number | null;
  price_low: number | null;
  price_high: number | null;
  confidence: number;
  method: string;
  status_basis: string;
  proposal_status: ProposalStatus;
  evidence_status: EvidenceStatus;
  next_action: string;
  uncertainties: string[];
  /** Non-admitted retrieved evidence, including unpriceable specification context; never priced. */
  evidence_candidates?: CandidateEvidencePacket[];
  analogs: {
    quote_no: string;
    quote_date: string;
    date_stamp?: string;
    rev?: string;
    customer: string;
    part_no: string;
    description: string;
    status: string;
    score: number;
    jev_probability?: number;
    price_evidence: PriceEvidence;
    quote_letter: string;
    letter_date: string;
    evidence?: CandidateEvidencePacket;
  }[];
  warnings: string[];
}

export interface QuoteEstimate {
  request: EstimateRequest;
  currency: "USD";
  lines: LineEstimate[];
  total: number;
  generated_at: string;
  register_rows: number;
  jev: "enabled" | "disabled";
}
