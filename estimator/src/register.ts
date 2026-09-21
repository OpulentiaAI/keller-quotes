import { readFileSync } from "node:fs";
import { parse } from "csv-parse/sync";
import type { QuoteRow } from "./types.js";

export function normalizePartNo(p: string): string {
  return p.toUpperCase().replace(/[^A-Z0-9]/g, "");
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
      const key = r.quote_no + "|" + (r.item_no || "");
      const arr = byQuote.get(key);
      if (arr) arr.push(r);
      else byQuote.set(key, [r]);
    }
    for (const [key, rs] of byQuote) {
      rs.sort((a, b) => (a.quantity ?? 0) - (b.quantity ?? 0));
      const head = rs.find((r) => r.unit_price !== null) ?? rs[0]!;
      const g: QuoteGroup = { quote_no: key, head, breaks: rs };
      const idx = this.groups.length;
      this.groups.push(g);
      const pn = normalizePartNo(g.head.part_no);
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
