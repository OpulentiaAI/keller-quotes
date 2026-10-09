import { beforeEach, describe, expect, it, vi } from "vitest";
import { experimental_evaluate } from "ai";
import { assertEstimateRequest, estimate } from "../src/estimate.js";
import { candidateKey, compareEvidence, evidencePacket, MAX_EVIDENCE_BREAKS } from "../src/evidence.js";
import { JevClient } from "../src/jev.js";
import { price } from "../src/price.js";
import { QuoteRegister } from "../src/register.js";
import type { Candidate, PartRequest, PriceEvidence, QuoteRow, RequestCustomer } from "../src/types.js";

vi.mock("@ai-sdk/gateway", () => ({
  createGateway: vi.fn(() => ({ evaluationModel: vi.fn(() => ({})) })),
}));
vi.mock("ai", () => ({ experimental_evaluate: vi.fn() }));

const pdf: PriceEvidence = {
  price_basis: "customer_quote_pdf", source_document: "synthetic/private-source.pdf",
  source_document_sha256: "a".repeat(64), source_transcript_sha256: "b".repeat(64), source_price_field: "PRICE",
};
function row(p: Partial<QuoteRow> = {}): QuoteRow {
  return {
    quote_no: "SYN-Q1", item_no: "1", assembly_no: "", quote_date: "2024-01-01", date_stamp: "",
    customer_id: "SYN-C1", customer: "Synthetic customer", part_no: "SYN-P1", description: "SYNTHETIC BRACKET",
    rev: "", drawing_no: "", rfq_no: "", buyer_name: "", salesperson: "", quote_letter: "SYN-L1", letter_date: "2024-01-01",
    quantity: 10, unit_price: 12.345678, unit_cost: null, extended_price: null, markup: null, del_seq: null,
    material: "", status: "unknown", won_date: "", to_quote: "", user_quote: "", newsellpri: null, comment: "", ...p,
  };
}
function candidate(p: Partial<QuoteRow> = {}): Candidate {
  const r = row(p);
  return { row: r, breaks: [r], score: 1, reasons: ["exact part_no"] };
}
const part: PartRequest = { part_no: "SYN-P1", quantity: 10 };
const field = (packet: ReturnType<typeof evidencePacket>, name: string) => packet.comparisons.find((f) => f.field === name)!;
const offline = () => new JevClient("");
function mockJev(strategy: "latest" | "median_won" = "median_won") {
  const rankAnalogs = vi.fn(async (_p: PartRequest, candidates: Candidate[], _max: number, _customer: RequestCustomer) => ({
    rankedIds: candidates.map((c) => c.row.quote_no), rankedKeys: candidates.map(candidateKey),
    probabilities: {}, source: "jev" as const,
  }));
  const screenCandidate = vi.fn(async (_p: PartRequest, _c: Candidate, _customer: RequestCustomer): Promise<"admit" | "quarantine" | "reject" | "unavailable"> => "admit");
  const chooseStrategy = vi.fn(async (_p: PartRequest, _c: Candidate[], _customer: RequestCustomer) => strategy);
  return { rankAnalogs, screenCandidate, chooseStrategy, enabled: true };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(experimental_evaluate).mockReset();
});

describe("bounded historical evidence", () => {
  it("preserves separate part/drawing revisions and never asserts an asset reference as a drawing number", async () => {
    const request = { parts: [{ ...part, revision: "B", drawing_no: "DRAW-8", drawing_revision: "C", drawing_ref: "/private/synthetic/asset.pdf" }] };
    assertEstimateRequest(request);
    const line = (await estimate(new QuoteRegister([row({ rev: "B", drawing_no: "DRAW-8", drawing_revision: "C" })]), request, { jev: offline() })).lines[0]!;
    expect(line.part).toEqual(request.parts[0]);
    expect(field(line.analogs[0]!.evidence!, "revision")).toMatchObject({ source: "B", requested: "B", status: "match" });
    expect(field(line.analogs[0]!.evidence!, "drawing_revision")).toMatchObject({ source: "C", requested: "C", status: "match" });
    const assetOnly = evidencePacket({ ...part, drawing_ref: "DRAW-8" }, candidate({ drawing_no: "DRAW-8" }));
    expect(field(assetOnly, "drawing_no")).toMatchObject({ requested: null, status: "unknown" });
    expect(() => assertEstimateRequest({ parts: [{ ...part, drawing_no: "/private/asset.pdf" }] })).toThrow(/drawing number/);
    expect(() => assertEstimateRequest({ parts: [{ ...part, drawing_revision: 2 }] })).toThrow(/drawing_revision/);
    const assetDiscovery = await estimate(new QuoteRegister([row({ drawing_no: "DRAW-8" })]),
      { parts: [{ quantity: 10, drawing_ref: "DRAW-8" }] }, { jev: offline() });
    expect(assetDiscovery.lines[0]!.analogs).toEqual([]);
  });

  it("does not promote descriptions/comments or a verified PDF price into material/finish/revision verification", () => {
    const c = candidate({ description: "316 STAINLESS PAINT REV B", comment: "material 316; finish paint; revision B", price_evidence: pdf });
    const packet = evidencePacket({ ...part, material: "316 stainless", finish: "paint", revision: "B" }, c);
    for (const name of ["material", "finish", "revision"]) {
      expect(field(packet, name)).toMatchObject({ status: "unknown", source: null, source_origin: "unavailable" });
    }
    expect(packet.outcome).toEqual({ recorded_status: "unknown", basis: "unknown", actual_cost: "unknown" });
    expect(JSON.stringify(packet)).not.toContain("private-source.pdf");
    expect(packet.next_read).toEqual([{ kind: "source_document_sha256", ref: "a".repeat(64) }]);
    expect(evidencePacket(part, candidate({ status: "won", unit_cost: 1 })).outcome)
      .toMatchObject({ basis: "unverified_register_status", actual_cost: "unknown" });
  });

  it("compares literal fields conservatively and retains explicit no-finish and revision conflicts", () => {
    const packet = evidencePacket({ ...part, material: "316 stainless steel", finish: "paint", revision: "A", drawing_revision: "B" },
      candidate({ material: "304 stainless steel", finish: "none", rev: "B", drawing_revision: "A" }));
    for (const name of ["material", "finish", "revision", "drawing_revision"]) expect(field(packet, name).status).toBe("conflict");
    const comparisons = compareEvidence({ ...part, material: "  316   STAINLESS " }, candidate({ material: "316 stainless" }));
    expect(comparisons.find((f) => f.field === "material")!.status).toBe("match");
  });

  it("retains original numeric break precision, bounds display, and computes using all breaks", () => {
    const c = candidate();
    c.breaks = Array.from({ length: MAX_EVIDENCE_BREAKS + 5 }, (_, i) => row({ quantity: i + 1, unit_price: 40.123456 - i }));
    const packet = evidencePacket({ ...part, quantity: c.breaks.length }, c);
    expect(packet.breaks).toHaveLength(MAX_EVIDENCE_BREAKS);
    expect(packet.breaks[0]!.unit_price).toBe(40.123456);
    expect(packet).toMatchObject({ break_count: c.breaks.length, breaks_truncated: true });
    expect(packet.quantity_support).toEqual({ requested: c.breaks.length, min: 1, max: c.breaks.length, kind: "exact" });
    const priced = price(c.breaks.length, [c], { strategy: "latest" });
    expect(priced.unit_price).toBeCloseTo(c.breaks.at(-1)!.unit_price!);
    expect(evidencePacket({ ...part, quantity: 1.5 }, c).quantity_support.kind).toBe("interpolated");
    expect(evidencePacket({ ...part, quantity: 100 }, c).quantity_support.kind).toBe("extrapolated");
    expect(evidencePacket({ ...part, quantity: 20 }, candidate()).quantity_support.kind).toBe("single_break");
    expect(evidencePacket(part, candidate({ unit_price: 0 })).quantity_support.kind).toBe("unavailable");
    const long = evidencePacket({ ...part, material: "x".repeat(1000) }, candidate({ material: "y".repeat(1000) }));
    expect(field(long, "material")).toMatchObject({ status: "conflict", truncated: true });
    expect(field(long, "material").source).toHaveLength(256);
  });
});

describe("composite identities and actual pricing participation", () => {
  it("distinguishes item, assembly, letter, source and delimiter collisions without exposing private paths", () => {
    const original = candidate({ price_evidence: pdf });
    const variants = [original, candidate({ item_no: "2", price_evidence: pdf }), candidate({ assembly_no: "A", price_evidence: pdf }),
      candidate({ quote_letter: "SYN-L2", price_evidence: pdf }), candidate(),
      candidate({ price_evidence: { ...pdf, source_document_sha256: "c".repeat(64) } }),
      candidate({ quote_no: "A|B", item_no: "C" }), candidate({ quote_no: "A", item_no: "B|C" })];
    expect(new Set(variants.map(candidateKey)).size).toBe(variants.length);
    expect(candidateKey(original)).toMatch(/^candidate:[a-f0-9]{64}$/);
    expect(candidateKey({ ...original, breaks: [...original.breaks].reverse() })).toBe(candidateKey(original));
  });

  it("uses full keys for probability weights, never a shared quote number", () => {
    const first = candidate({ item_no: "1", unit_price: 10 });
    const second = candidate({ item_no: "2", unit_price: 20 });
    const result = price(10, [first, second], { strategy: "median_won", now: Date.parse("2024-01-01"),
      jevProbabilities: { [candidateKey(first)]: 0, [candidateKey(second)]: 1, "SYN-Q1": 0.5 } });
    expect(result.points.map((p) => p.weight)).toEqual([0.25, 1.25]);
    expect(result.points.map((p) => p.candidate_key)).toEqual([candidateKey(first), candidateKey(second)]);
    expect(result.points.every((p) => p.used_for_unit_price)).toBe(true);
    expect(result.unit_price).toBe(20);
  });

  it("screens the selected item of a shared quote using its full ranked key", async () => {
    const jev = mockJev();
    jev.rankAnalogs.mockImplementation(async (_p, candidates) => ({
      rankedIds: candidates.map((c) => c.row.quote_no),
      rankedKeys: [...candidates].reverse().map(candidateKey),
      probabilities: { [candidateKey(candidates[1]!)]: 0.9 }, source: "jev" as const,
    }));
    const register = new QuoteRegister([row({ item_no: "1", unit_price: 10 }), row({ item_no: "2", unit_price: 20 })]);
    const line = (await estimate(register, { parts: [part] }, { jev: jev as unknown as JevClient, screenTopN: 1 })).lines[0]!;
    expect(jev.screenCandidate.mock.calls[0]![1].row.item_no).toBe("2");
    expect(line.unit_price).toBe(20);
    expect(line.analogs[0]).toMatchObject({ jev_probability: 0.9, evidence: { identity: { item_no: "2" }, pricing: { used_for_unit_price: true } } });
    expect(line.evidence_candidates![0]).toMatchObject({ identity: { item_no: "1" }, screening: { reason: "SCREEN_BUDGET" } });
  });

  it("separates assemblies merged by the legacy quote/item register", async () => {
    const register = new QuoteRegister([row({ assembly_no: "A", unit_price: 10 }), row({ assembly_no: "B", unit_price: 20 })]);
    const line = (await estimate(register, { parts: [part] }, { jev: offline() })).lines[0]!;
    expect(line.analogs).toHaveLength(2);
    expect(new Set(line.analogs.map((a) => a.evidence!.candidate_key)).size).toBe(2);
    expect(line.analogs.map((a) => a.evidence!.breaks[0]!.unit_price)).toEqual([10, 20]);
  });

  it("reports latest-only participation and does not label an unused PDF as the numeric price basis", async () => {
    const register = new QuoteRegister([
      row({ item_no: "1", price_evidence: pdf, quote_date: "2023-01-01", letter_date: "2023-01-01", unit_price: 10 }),
      row({ item_no: "2", unit_price: 20 }),
    ]);
    const jev = mockJev("latest");
    const line = (await estimate(register, { parts: [part] }, { jev: jev as unknown as JevClient })).lines[0]!;
    expect(line.unit_price).toBe(20);
    expect(line.evidence_status).toBe("HISTORICAL_INTERNAL_CALCULATION");
    const byItem = new Map(line.analogs.map((a) => [a.evidence!.identity.item_no, a.evidence!.pricing]));
    expect(byItem.get("1")).toMatchObject({ evaluated: true, used_for_unit_price: false, unit_price_at_quantity: 10 });
    expect(byItem.get("2")).toMatchObject({ evaluated: true, used_for_unit_price: true, unit_price_at_quantity: 20, method: "latest" });
    const mixed = (await estimate(register, { parts: [part] }, { jev: offline() })).lines[0]!;
    expect(mixed.evidence_status).toBe("MIXED_HISTORICAL");
    expect(mixed.analogs.every((a) => a.evidence!.pricing.used_for_unit_price)).toBe(true);
  });
});

describe("eligibility before screening", () => {
  it("partitions unusable generic candidates before spending screening budget and retains their evidence", async () => {
    const jev = mockJev();
    const register = new QuoteRegister([row({ quote_no: "UNPRICED", unit_price: 0 }), row({ quote_no: "PRICED", unit_price: 5 })]);
    const line = (await estimate(register, { parts: [{ quantity: 10, description: "SYNTHETIC BRACKET" }] },
      { jev: jev as unknown as JevClient, screenTopN: 1 })).lines[0]!;
    expect(jev.screenCandidate.mock.calls.map(([, c]) => c.row.quote_no)).toEqual(["PRICED"]);
    expect(line.unit_price).toBe(5);
    expect(line.evidence_candidates![0]).toMatchObject({ screening: { status: "unpriceable", reason: "NO_USABLE_PRICE" }, pricing: { evaluated: false, used_for_unit_price: false } });
  });

  it.each([
    { customer_id: "OTHER" }, { rev: "B" }, { material: "304 steel" }, { drawing_no: "OTHER-DRAW" },
    { drawing_revision: "B" }, { finish: "none" },
  ])("does not narrow to a conflicting normalized exact match: %j", async (conflict) => {
    const compatible = { customer_id: "SYN-C1", rev: "A", material: "316 steel", drawing_no: "DRAW", drawing_revision: "A", finish: "paint" };
    const register = new QuoteRegister([
      row({ ...compatible, ...conflict, quote_no: "BAD-EXACT", part_no: "SYN-P1", unit_price: 999 }),
      row({ ...compatible, quote_no: "GOOD-RELATED", part_no: "SYN-P2", unit_price: 7 }),
    ]);
    const request = { customer_id: "SYN-C1", parts: [{ ...part, description: "SYNTHETIC BRACKET", revision: "A", material: "316 steel", drawing_no: "DRAW", drawing_revision: "A", finish: "paint" }] };
    const line = (await estimate(register, request, { jev: offline(), screenTopN: 1 })).lines[0]!;
    expect(line.unit_price).toBe(7);
    expect(line.analogs.map((a) => a.quote_no)).toEqual(["GOOD-RELATED"]);
    expect(line.evidence_candidates!.some((p) => p.comparisons.some((c) => c.status === "conflict"))).toBe(true);
  });

  it.each(["reject", "quarantine", "unavailable"] as const)("preserves %s status and never prices unscreened history", async (decision) => {
    const jev = mockJev();
    jev.screenCandidate.mockResolvedValue(decision);
    const line = (await estimate(new QuoteRegister([row(), row({ quote_no: "TAIL", unit_price: 4 })]), { parts: [part] },
      { jev: jev as unknown as JevClient, screenTopN: 1 })).lines[0]!;
    if (decision === "unavailable") {
      expect(line.unit_price).toBeNull();
      expect(line.analogs).toEqual([]);
      expect(jev.chooseStrategy.mock.calls[0]![1]).toEqual([]);
    } else {
      expect(line.unit_price).toBe(12.3457);
      expect(line.analogs.map((a) => a.quote_no)).toEqual(["SYN-Q1"]);
      expect(line.analogs[0]!.evidence!.screening.status).toBe(decision === "reject" ? "rejected" : "quarantined");
      expect(line.analogs[0]!.evidence!.pricing.used_for_unit_price).toBe(true);
      expect(line.uncertainties).toContain("Jev admitted no high-confidence analog; retained candidate is a provisional human-review fallback");
    }
    expect(line.evidence_candidates!.every((p) => !p.pricing.used_for_unit_price)).toBe(true);
    expect(line.evidence_candidates!.map((p) => p.screening.reason)).toContain("SCREEN_BUDGET");
    if (decision === "unavailable") expect(line.evidence_candidates!.map((p) => p.screening.reason)).toContain("SCREEN_UNAVAILABLE");
  });

  it("keeps screenTopN zero on hold without model screening", async () => {
    const jev = mockJev();
    const line = (await estimate(new QuoteRegister([row()]), { parts: [part] },
      { jev: jev as unknown as JevClient, screenTopN: 0 })).lines[0]!;
    expect(line.unit_price).toBeNull();
    expect(jev.screenCandidate).not.toHaveBeenCalled();
    expect(line.evidence_candidates![0]!.screening.reason).toBe("SCREEN_BUDGET");
  });

  it("never restores explicit engineering conflicts as a provisional fallback", async () => {
    const jev = mockJev();
    jev.screenCandidate.mockResolvedValue("reject");
    const line = (await estimate(new QuoteRegister([row({ material: "316" })]),
      { parts: [{ ...part, material: "304" }] }, { jev: jev as unknown as JevClient })).lines[0]!;
    expect(line.unit_price).toBeNull();
    expect(jev.screenCandidate).not.toHaveBeenCalled();
    expect(line.evidence_candidates![0]!.screening.status).toBe("incompatible");
  });

  it("does not restore excluded or future records into auxiliary evidence", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "EXCLUDED" }), row({ quote_no: "FUTURE", quote_date: "2030-01-01" }), row({ quote_no: "SAFE" }),
    ]);
    const line = (await estimate(register, { parts: [part] }, { jev: offline(), asOf: "2025-01-01", exclude: new Set(["EXCLUDED"]) })).lines[0]!;
    expect(line.analogs.map((a) => a.quote_no)).toEqual(["SAFE"]);
    expect(JSON.stringify(line)).not.toContain("EXCLUDED");
    expect(JSON.stringify(line)).not.toContain("FUTURE");
  });
});

describe("optional Jev evidence-only handoff", () => {
  it("propagates customer identity and distinct revisions, returning composite-key probabilities for colliding quotes", async () => {
    vi.mocked(experimental_evaluate).mockResolvedValue({ answers: { best_analog: {
      type: "choice", choice: "c1", probabilities: { c0: 0.1, c1: 0.9 },
    } } } as never);
    const client = new JevClient("synthetic-test-key");
    const first = candidate({ item_no: "1", price_evidence: pdf, comment: "PRIVATE COMMENT NOT FOR SERVICE" });
    const second = candidate({ item_no: "2", price_evidence: pdf });
    const request = { ...part, revision: "B", drawing_no: "DRAW", drawing_revision: "C", drawing_ref: "/private/asset.pdf" };
    const customer = { customer: "Synthetic customer", customer_id: "SYN-C1" };
    const verdict = await client.rankAnalogs(request, [first, second], 2, customer);
    expect(verdict.rankedKeys).toEqual([candidateKey(second), candidateKey(first)]);
    expect(verdict.probabilities).toEqual({ [candidateKey(first)]: 0.1, [candidateKey(second)]: 0.9 });
    const call = vi.mocked(experimental_evaluate).mock.calls[0]![0];
    expect(call.state).toMatchObject({ requested_part: { ...customer, revision: "B", drawing_no: "DRAW", drawing_revision: "C" } });
    const payload = JSON.stringify(call);
    for (const privateValue of ["PRIVATE COMMENT", "private-source.pdf", "/private/asset.pdf"]) expect(payload).not.toContain(privateValue);
    expect(payload).toContain("never invent costs or prices");
    expect(payload).toContain("Unknown outcome, acceptance, payment or actual cost alone is not grounds to reject");
  });

  it("accepts unknown-outcome historical comparisons and supplies basis/support to strategy choice", async () => {
    vi.mocked(experimental_evaluate)
      .mockResolvedValueOnce({ answers: { is_analog: { type: "boolean", probability: 0.9 } } } as never)
      .mockResolvedValueOnce({ answers: { strategy: { type: "choice", choice: "latest" } } } as never);
    const client = new JevClient("synthetic-test-key");
    const c = candidate({ price_evidence: pdf, status: "unknown", unit_cost: null });
    expect(await client.screenCandidate(part, c, { customer_id: "SYN-C1" })).toBe("admit");
    expect(await client.chooseStrategy(part, [c], { customer_id: "SYN-C1" })).toBe("latest");
    const state = vi.mocked(experimental_evaluate).mock.calls[1]![0].state;
    expect(state).toMatchObject({ requested_part: { customer_id: "SYN-C1" } });
    const analogs = (state as { analogs: string[] }).analogs;
    expect(JSON.parse(analogs[0]!)).toMatchObject({
      source: { price_basis: "customer_quote_pdf" }, outcome: { actual_cost: "unknown" },
      quantity_support: { kind: "exact" }, screening: { status: "admitted" },
    });
  });

  it("retains deterministic rank/strategy fallback but marks unavailable screening rather than admitting it", async () => {
    vi.mocked(experimental_evaluate).mockRejectedValue(new Error("synthetic unavailable"));
    const client = new JevClient("synthetic-test-key");
    const c = candidate();
    expect(await client.rankAnalogs(part, [c], 1, {})).toMatchObject({ rankedKeys: [candidateKey(c)], source: "fallback" });
    expect(await client.screenCandidate(part, c)).toBe("unavailable");
    expect(await client.chooseStrategy(part, [c])).toBe("median_won");
    expect(await offline().screenCandidate(part, c)).toBe("admit");
  });
});
