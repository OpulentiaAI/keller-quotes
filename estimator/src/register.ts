import { readFileSync } from "node:fs";
import { parse } from "csv-parse/sync";
import type { PriceEvidence, QuoteRow } from "./types.js";

const INTERNAL: PriceEvidence = { price_basis: "internal_quote_calculation" };

function validDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    !Number.isNaN(Date.parse(`${value}T00:00:00Z`)) &&
    new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}

function validateEvidence(value: unknown, row: QuoteRow): PriceEvidence {
  if (value === undefined) return INTERNAL;
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`invalid price evidence for quote ${row.quote_no}`);
  const evidence = value as Record<string, unknown>;
  if (evidence.price_basis === "internal_quote_calculation") {
    if (Object.keys(evidence).some((key) => key !== "price_basis")) throw new Error(`internal price has document metadata for quote ${row.quote_no}`);
    return INTERNAL;
  }
  if (evidence.price_basis !== "customer_quote_pdf") throw new Error(`invalid price basis for quote ${row.quote_no}`);
  const path = evidence.source_document;
  if (typeof path !== "string" || !path.toLowerCase().endsWith(".pdf") || path.startsWith("/") || path.includes("\\") ||
    path.includes(":") || path.split("/").some((segment) => !segment || segment === "." || segment === ".." || /[\x00-\x1f\x7f]/.test(segment))) {
    throw new Error(`unsafe source document path for quote ${row.quote_no}`);
  }
  for (const key of ["source_document_sha256", "source_transcript_sha256"] as const) {
    if (typeof evidence[key] !== "string" || !/^[a-f0-9]{64}$/i.test(evidence[key])) {
      throw new Error(`invalid ${key} for quote ${row.quote_no}`);
    }
  }
  if (evidence.source_price_field !== "PRICE" && evidence.source_price_field !== "QUOTEPRICE") {
    throw new Error(`invalid source_price_field for quote ${row.quote_no}`);
  }
  if (Object.keys(evidence).some((key) => !["price_basis", "source_document", "source_document_sha256", "source_transcript_sha256", "source_price_field"].includes(key))) {
    throw new Error(`unexpected price evidence for quote ${row.quote_no}`);
  }
  if (!row.quote_letter.trim() || !validDate(row.letter_date) || !validDate(row.quote_date)) {
    throw new Error(`document price requires quote letter and valid dates for quote ${row.quote_no}`);
  }
  return {
    ...evidence,
    source_document_sha256: (evidence.source_document_sha256 as string).toLowerCase(),
    source_transcript_sha256: (evidence.source_transcript_sha256 as string).toLowerCase(),
  } as PriceEvidence;
}

export function normalizePartNo(p: string): string {
  return p.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

export function partBigrams(s: string): ReadonlySet<string> {
  const out = new Set<string>();
  for (let i = 0; i < s.length - 1; i++) out.add(s.slice(i, i + 2));
  return out;
}

const STOP = new Set([
  "THE", "A", "AN", "OF", "FOR", "AND", "WITH", "TO", "IN", "ON", "PER",
  "ASSY", "ASSEMBLY", "PART", "NO", "PCS", "EA",
]);

export function descTokens(s: string): string[] {
  return s
    .toUpperCase()
    .split(/[^A-Z0-9.]+/)
    .filter((t) => t.length > 1 && !STOP.has(t));
}

export function normalizeCustomer(s: string): string {
  return s
    .toUpperCase()
    .replace(/[^A-Z0-9 ]/g, " ")
    .replace(/\b(INC|LLC|CO|CORP|CORPORATION|COMPANY|LTD|MFG|MANUFACTURING)\b/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function num(v: unknown): number | null {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export interface QuoteGroup {
  quote_no: string;
  /** One row per quote after collapsing qty breaks — representative fields. */
  head: QuoteRow;
  breaks: QuoteRow[];
  readonly search: {
    readonly partNo: string;
    readonly partBigrams: ReadonlySet<string>;
    readonly drawingNo: string;
    readonly descriptionTokens: readonly string[];
  };
}

export class QuoteRegister {
  readonly groups: QuoteGroup[] = [];
  readonly rowCount: number;
  private byPartNo = new Map<string, QuoteGroup[]>();
  private byCustomerId = new Map<string, QuoteGroup[]>();
  private tokenIndex = new Map<string, Set<number>>();

  constructor(rows: QuoteRow[]) {
    this.rowCount = rows.length;
    const byQuote = new Map<string, QuoteRow[]>();
    for (const r of rows) {
      r.price_evidence = validateEvidence(r.price_evidence, r);
      const key = r.quote_no + "|" + (r.item_no || "");
      const arr = byQuote.get(key);
      if (arr) arr.push(r);
      else byQuote.set(key, [r]);
    }
    for (const [key, rs] of byQuote) {
      const documents = rs.map((r) => {
        const evidence = r.price_evidence!;
        return JSON.stringify(evidence.price_basis === "customer_quote_pdf" ? [
          evidence.price_basis, evidence.source_document, evidence.source_document_sha256,
          evidence.source_transcript_sha256, evidence.source_price_field,
          r.quote_date, r.quote_letter, r.letter_date,
        ] : [evidence.price_basis]);
      });
      if (documents.some((document) => document !== documents[0])) {
        throw new Error(`conflicting price evidence or dates in quote/item ${key}`);
      }
      rs.sort((a, b) => (a.quantity ?? 0) - (b.quantity ?? 0));
      const head = rs.find((r) => r.unit_price !== null) ?? rs[0]!;
      const pn = normalizePartNo(head.part_no);
      const g: QuoteGroup = {
        quote_no: key, head, breaks: rs,
        search: {
          partNo: pn,
          partBigrams: partBigrams(pn),
          drawingNo: normalizePartNo(head.drawing_no),
          descriptionTokens: descTokens(head.description),
        },
      };
      const idx = this.groups.length;
      this.groups.push(g);
      if (pn) {
        const l = this.byPartNo.get(pn);
        if (l) l.push(g);
        else this.byPartNo.set(pn, [g]);
      }
      if (g.head.customer_id) {
        const l = this.byCustomerId.get(g.head.customer_id);
        if (l) l.push(g);
        else this.byCustomerId.set(g.head.customer_id, [g]);
      }
      for (const t of new Set(descTokens(g.head.description + " " + g.head.comment))) {
        const s = this.tokenIndex.get(t);
        if (s) s.add(idx);
        else this.tokenIndex.set(t, new Set([idx]));
      }
    }
  }

  static fromCsv(path: string): QuoteRegister {
    const raw = readFileSync(path, "utf8");
    const recs = parse(raw, {
      columns: true,
      skip_empty_lines: true,
      relax_quotes: true,
      trim: true,
    }) as Record<string, string>[];
    const rows: QuoteRow[] = recs.map((r) => ({
      quote_no: r.quote_no ?? "",
      item_no: r.item_no ?? "",
      assembly_no: r.assembly_no ?? "",
      quote_date: r.quote_date ?? "",
      date_stamp: r.date_stamp ?? "",
      customer_id: r.customer_id ?? "",
      customer: r.customer ?? "",
      part_no: r.part_no ?? "",
      description: r.description ?? "",
      rev: r.rev ?? "",
      drawing_no: r.drawing_no ?? "",
      rfq_no: r.rfq_no ?? "",
      buyer_name: r.buyer_name ?? "",
      salesperson: r.salesperson ?? "",
      quote_letter: r.quote_letter ?? "",
      letter_date: r.letter_date ?? "",
      quantity: num(r.quantity),
      unit_price: num(r.unit_price),
      unit_cost: num(r.unit_cost),
      extended_price: num(r.extended_price),
      markup: num(r.markup),
      del_seq: num(r.del_seq),
      material: r.material ?? "",
      status: r.status ?? "open",
      won_date: r.won_date ?? "",
      to_quote: r.to_quote ?? "",
      user_quote: r.user_quote ?? "",
      newsellpri: num(r.newsellpri),
      comment: r.comment ?? "",
      price_evidence: csvEvidence(r),
    }));
    return new QuoteRegister(rows);
  }

  exactPart(pn: string): QuoteGroup[] {
    return this.byPartNo.get(normalizePartNo(pn)) ?? [];
  }

  customerGroups(customerId: string): QuoteGroup[] {
    return this.byCustomerId.get(customerId) ?? [];
  }

  /** Groups whose description/comment shares at least one token. */
  tokenCandidates(tokens: string[]): { group: QuoteGroup; hits: number }[] {
    const counts = new Map<number, number>();
    for (const t of tokens) {
      const s = this.tokenIndex.get(t);
      if (!s) continue;
      for (const i of s) counts.set(i, (counts.get(i) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([i, hits]) => ({ group: this.groups[i]!, hits }))
      .sort((a, b) => b.hits - a.hits);
  }
}

function csvEvidence(row: Record<string, string>): PriceEvidence {
  const basis = row.price_basis ?? "";
  const fields = ["source_document", "source_document_sha256", "source_transcript_sha256", "source_price_field"] as const;
  const hasDocumentMetadata = fields.some((field) => !!row[field]);
  if (!basis) {
    if (hasDocumentMetadata) throw new Error("document metadata requires price_basis");
    return INTERNAL;
  }
  if (basis === "internal_quote_calculation") {
    if (hasDocumentMetadata) throw new Error("internal price cannot have document metadata");
    return INTERNAL;
  }
  if (basis !== "customer_quote_pdf") throw new Error(`unknown price_basis: ${basis}`);
  return {
    price_basis: basis,
    source_document: row.source_document ?? "",
    source_document_sha256: row.source_document_sha256 ?? "",
    source_transcript_sha256: row.source_transcript_sha256 ?? "",
    source_price_field: row.source_price_field as "PRICE" | "QUOTEPRICE",
  };
}
