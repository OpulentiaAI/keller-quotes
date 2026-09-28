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
  /** Optional reference to a customer drawing/visualization (path or id). */
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
  /** All qty/price breaks for that quote_no. */
  breaks: QuoteRow[];
  /** Deterministic similarity score in [0,1]. */
  score: number;
  reasons: string[];
}

export interface JevVerdict {
  rankedIds: string[];
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
}

export interface LineEstimate {
  part: PartRequest;
  unit_price: number | null;
  extended_price: number | null;
  price_low: number | null;
  price_high: number | null;
  confidence: number;
  method: string;
  status_basis: string;
  analogs: {
    quote_no: string;
    quote_date: string;
    customer: string;
    part_no: string;
    description: string;
    status: string;
    score: number;
    jev_probability?: number;
    price_evidence: PriceEvidence;
    quote_letter: string;
    letter_date: string;
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
