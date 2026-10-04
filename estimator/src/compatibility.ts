import { descTokens, normalizeCustomer, normalizePartNo } from "./register.js";
import type { PartRequest, QuoteRow } from "./types.js";

export interface CustomerIdentity {
  customer?: string;
  customerId?: string;
  asOf?: string;
}

export function searchableIdentifier(value: string | undefined): string {
  return value && !/[?*]/.test(value) ? normalizePartNo(value) : "";
}

export function requestedDrawing(part: PartRequest): string {
  const reference = part.drawing_ref ?? "";
  if (/^(?:[/\\]|\.\.?[/\\]|[A-Z]:[/\\]|[A-Z]+:\/\/)|\.(?:pdf|dxf|dwg|png|jpe?g|step|stp)$/i.test(reference.trim())) return "";
  return searchableIdentifier(reference);
}

export function customerNamespace(row: QuoteRow, opts: CustomerIdentity): "same" | "different" | "unknown" {
  const wantId = searchableIdentifier(opts.customerId) ? opts.customerId!.trim() : "";
  const sourceId = searchableIdentifier(row.customer_id) ? row.customer_id.trim() : "";
  if (wantId && sourceId) return wantId === sourceId ? "same" : "different";
  if (wantId || opts.asOf) return "unknown";
  const wantName = normalizeCustomer(opts.customer ?? "");
  const sourceName = normalizeCustomer(row.customer ?? "");
  if (wantName && sourceName && wantName !== sourceName) return "different";
  return "unknown";
}

export function matchingDrawing(part: PartRequest, row: QuoteRow): boolean {
  const drawing = requestedDrawing(part);
  return Boolean(drawing && drawing === searchableIdentifier(row.drawing_no));
}

export function independentAttributesMatch(part: PartRequest, row: QuoteRow): boolean {
  if (matchingDrawing(part, row)) return true;
  const wanted = new Set(descTokens(part.description ?? "").filter((token) => /[A-Z]/.test(token)));
  const source = new Set(descTokens((row.description ?? "") + " " + (row.comment ?? "")).filter((token) => /[A-Z]/.test(token)));
  const shared = [...wanted].filter((token) => source.has(token)).length;
  return wanted.size > 0 && shared >= Math.min(2, wanted.size);
}

export function ambiguousPartSources(rows: QuoteRow[]): boolean {
  for (const field of ["part_no", "description", "rev", "drawing_no", "material"] as const) {
    const values = new Set(rows.map((row) => field === "description"
      ? [...new Set(descTokens(row[field] ?? ""))].sort().join(" ")
      : (row[field] ?? "").trim().toUpperCase()).filter(Boolean));
    if (values.size > 1) return true;
  }
  return false;
}

export function sourceIncompatibilities(part: PartRequest, rows: QuoteRow[]): string[] {
  const conflicts: string[] = [];
  for (const field of ["customer_id", "part_no", "rev", "drawing_no", "material"] as const) {
    const values = new Set(rows.map((row) => field === "customer_id"
      ? (row[field] ?? "").trim() : (row[field] ?? "").trim().toUpperCase()).filter(Boolean));
    if (values.size > 1) conflicts.push(`ambiguous source ${field}`);
  }
  const revision = searchableIdentifier(part.revision) ? part.revision!.trim().toUpperCase() : "";
  const drawing = requestedDrawing(part);
  const partNo = searchableIdentifier(part.part_no);
  const wantedMaterial = descTokens(part.material ?? "");
  const wantedDescription = descTokens(part.description ?? "").filter((token) => /[A-Z]/.test(token));
  for (const row of rows) {
    if (revision && searchableIdentifier(row.rev) && revision !== row.rev.trim().toUpperCase()) {
      conflicts.push("revision conflict");
    }
    if (drawing && searchableIdentifier(row.drawing_no) && drawing !== searchableIdentifier(row.drawing_no)) {
      conflicts.push("drawing conflict");
    }
    const sourceMaterial = descTokens(row.material ?? "");
    if (wantedMaterial.length && sourceMaterial.length &&
      !wantedMaterial.every((token) => sourceMaterial.includes(token)) &&
      !sourceMaterial.every((token) => wantedMaterial.includes(token))) {
      conflicts.push("material conflict");
    }
    const sourceDescription = descTokens((row.description ?? "") + " " + (row.comment ?? "")).filter((token) => /[A-Z]/.test(token));
    if (partNo && partNo === searchableIdentifier(row.part_no) &&
      part.part_no?.trim().toUpperCase() !== row.part_no.trim().toUpperCase() &&
      wantedDescription.length && sourceDescription.length &&
      !wantedDescription.some((token) => sourceDescription.includes(token))) {
      conflicts.push("normalized part_no description conflict");
    }
  }
  return [...new Set(conflicts)];
}
