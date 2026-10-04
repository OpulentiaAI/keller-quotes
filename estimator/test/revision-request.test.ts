import { experimental_evaluate } from "ai";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { assertEstimateRequest, estimate } from "../src/estimate.js";
import { JevClient } from "../src/jev.js";
import { assertOrderRequest, buildPricedOrder, renderOrderMarkdown } from "../src/order.js";
import { QuoteRegister } from "../src/register.js";
import type { Candidate, QuoteRow } from "../src/types.js";

vi.mock("@ai-sdk/gateway", () => ({
  createGateway: vi.fn(() => ({ evaluationModel: vi.fn(() => ({})) })),
}));
vi.mock("ai", () => ({ experimental_evaluate: vi.fn() }));

function row(quote_no: string, rev: string, unit_price: number): QuoteRow {
  return {
    quote_no, item_no: "", assembly_no: "", quote_date: "2022-01-01", date_stamp: "",
    customer_id: "SYNTHETIC-CUSTOMER", customer: "Synthetic", part_no: "PANEL-70", description: "BEACON PANEL",
    rev, drawing_no: "FRAME-71", rfq_no: "", buyer_name: "", salesperson: "", quote_letter: "", letter_date: "",
    quantity: 40, unit_price, unit_cost: null, extended_price: null, markup: null, del_seq: null, material: "",
    status: "open", won_date: "", to_quote: "", user_quote: "", newsellpri: null, comment: "",
  };
}

const request = {
  order_id: "SYNTHETIC-ORDER", quote_date: "2024-01-01", customer: "Synthetic", customer_id: "SYNTHETIC-CUSTOMER",
  parts: [{ line_id: "panel", part_no: "PANEL-70", description: "BEACON PANEL", quantity: 40,
    revision: "B", drawing_ref: "FRAME-71" }], charges: { shipping: 0, tax: 0 },
};

describe("revision request consumers", () => {
  beforeEach(() => vi.clearAllMocks());

  it("validates revision as an optional string in both estimator and order requests", () => {
    expect(() => assertEstimateRequest(request)).not.toThrow();
    expect(() => assertOrderRequest(request)).not.toThrow();
    const invalid = { ...request, parts: [{ ...request.parts[0]!, revision: 7 }] };
    expect(() => assertEstimateRequest(invalid)).toThrow(/revision must be a string/);
    expect(() => assertOrderRequest(invalid)).toThrow(/revision must be a nonblank string/);
  });

  it("propagates the supplied revision and drawing through priced orders and review output", async () => {
    const result = await buildPricedOrder(new QuoteRegister([row("old-revision", "A", 9), row("requested-revision", "B", 27)]),
      request, { registerSha256: "a".repeat(64) });
    expect(result.request.parts[0]!).toMatchObject({ revision: "B", drawing_ref: "FRAME-71" });
    expect(result.lines[0]!.part).toMatchObject({ revision: "B", drawing_ref: "FRAME-71" });
    expect(result.lines[0]!.analogs.map((analog) => analog.quote_no)).toEqual(["requested-revision"]);
    expect(result.lines[0]!.unit_price).toBe(27);
    expect(result.state).toBe("PRICED_REQUIRES_REVIEW");
    expect(result.requires_human_review).toBe(true);
    expect(renderOrderMarkdown(result)).toContain('&quot;revision&quot;:&quot;B&quot;');
  });

  it("holds an order whose only known revision conflicts with the requested revision", async () => {
    const result = await buildPricedOrder(new QuoteRegister([row("old-revision", "A", 9)]), request,
      { registerSha256: "a".repeat(64) });
    expect(result.state).toBe("BLOCKED");
    expect(result.total).toBeNull();
    expect(result.lines[0]!.unit_price).toBeNull();
    expect(result.lines[0]!.part.revision).toBe("B");
    expect(result.lines[0]!.warnings.join(" ")).toMatch(/revision conflict/);
  });

  it("retains revision on direct estimates and does not grant exact privilege to unknown revisions", async () => {
    const source = row("unknown-revision", "", 27);
    const seen: Candidate[][] = [];
    const client = {
      enabled: false,
      rankAnalogs: async (_part: unknown, candidates: Candidate[]) => {
        seen.push(candidates);
        return { rankedIds: candidates.map((candidate) => candidate.row.quote_no), probabilities: {}, source: "fallback" as const };
      },
      screenCandidate: async () => "admit" as const,
      chooseStrategy: async () => "median_won" as const,
    } as unknown as JevClient;
    const result = await estimate(new QuoteRegister([source]),
      { customer_id: request.customer_id, parts: [request.parts[0]!] }, { jev: client });
    expect(seen[0]![0]!.reasons).not.toContain("exact part_no");
    expect(result.lines[0]!.part.revision).toBe("B");
    expect(result.lines[0]!.unit_price).toBe(27);
    expect(result.lines[0]!.proposal_status).toBe("NUMERIC_PROVISIONAL");
  });

  it("presents revision and drawing identity to all Jev request consumers without a provider call", async () => {
    vi.mocked(experimental_evaluate)
      .mockResolvedValueOnce({ answers: { best_analog: { type: "choice", choice: "c0" } } } as never)
      .mockResolvedValueOnce({ answers: { is_analog: { type: "boolean", probability: 0.9 } } } as never)
      .mockResolvedValueOnce({ answers: { strategy: { type: "choice", choice: "latest" } } } as never);
    const source = row("matching", "B", 27);
    const candidate: Candidate = { row: source, breaks: [source], score: 1, reasons: ["exact part_no"] };
    const client = new JevClient("synthetic-test-key");
    const part = request.parts[0]!;
    await client.rankAnalogs(part, [candidate]);
    await client.screenCandidate(part, candidate);
    await client.chooseStrategy(part, [candidate]);
    expect(experimental_evaluate).toHaveBeenCalledTimes(3);
    for (const [call] of vi.mocked(experimental_evaluate).mock.calls) {
      expect(call.state).toMatchObject({ requested_part: { revision: "B", drawing_ref: "FRAME-71" } });
    }
    const ranking = vi.mocked(experimental_evaluate).mock.calls[0]![0];
    const screening = vi.mocked(experimental_evaluate).mock.calls[1]![0];
    expect(JSON.stringify(ranking.questions)).toContain("revision B");
    expect(JSON.stringify(ranking.questions)).toContain("drawing FRAME-71");
    expect(JSON.stringify(screening.state)).toContain("revision B");
    expect(JSON.stringify(screening.state)).toContain("drawing FRAME-71");
  });
});
