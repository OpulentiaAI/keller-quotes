import { describe, expect, it, vi } from "vitest";
import { estimate } from "../src/estimate.js";
import { JevClient } from "../src/jev.js";
import { price } from "../src/price.js";
import { QuoteRegister } from "../src/register.js";
import { retrieve } from "../src/retrieve.js";
import type { Candidate, PartRequest, QuoteRow } from "../src/types.js";

function row(partial: Partial<QuoteRow>): QuoteRow {
  return {
    quote_no: "", item_no: "", assembly_no: "", quote_date: "2022-01-01", date_stamp: "",
    customer_id: "", customer: "", part_no: "", description: "", rev: "", drawing_no: "",
    rfq_no: "", buyer_name: "", salesperson: "", quote_letter: "", letter_date: "",
    quantity: 40, unit_price: 36, unit_cost: null, extended_price: null, markup: null,
    del_seq: null, material: "", status: "open", won_date: "", to_quote: "", user_quote: "",
    newsellpri: null, comment: "", ...partial,
  };
}

function mockJev(verdict: "admit" | "quarantine" | "reject" = "admit", preferred?: string) {
  const hooks = {
    enabled: true,
    rankAnalogs: vi.fn(async (_part: PartRequest, candidates: Candidate[]) => ({
      rankedIds: preferred ? [preferred, ...candidates.filter((candidate) => candidate.row.quote_no !== preferred)
        .map((candidate) => candidate.row.quote_no)] : candidates.map((candidate) => candidate.row.quote_no),
      probabilities: {}, source: "jev" as const,
    })),
    screenCandidate: vi.fn(async () => verdict),
    chooseStrategy: vi.fn(async (_part: PartRequest, _candidates: Candidate[]) => "median_won" as const),
  };
  return { hooks, client: hooks as unknown as JevClient };
}

function expectNoPartPrivilege(candidate: Candidate) {
  expect(candidate.reasons).not.toContain("exact part_no");
  expect(candidate.reasons.some((reason) => reason.startsWith("part_no"))).toBe(false);
}

const part: PartRequest = { part_no: "SYN-4721", description: "BEACON ENCLOSURE PANEL", quantity: 40 };
const namespace = { customerId: "CUSTOMER-ALPHA" };
const collision = row({ quote_no: "collision", part_no: "SYN4721", customer_id: "CUSTOMER-BETA",
  description: "FLAT WASHER", quantity: 90, unit_price: 0.85 });
const related = row({ quote_no: "related", part_no: "BEACON-900", customer_id: "CUSTOMER-GAMMA",
  description: "BEACON ENCLOSURE PANEL" });

describe("customer-qualified part identity", () => {
  it("does not promote a foreign normalized ID or let it suppress described analogs", async () => {
    const register = new QuoteRegister([collision, related]);
    const candidates = retrieve(register, part, namespace);
    expect(candidates.map((candidate) => candidate.row.quote_no)).toEqual(["related"]);
    expectNoPartPrivilege(candidates[0]!);

    const result = await estimate(register, { customer_id: namespace.customerId, parts: [part] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).toBe(36);
    expect(result.lines[0]!.analogs.map((analog) => analog.quote_no)).toEqual(["related"]);
    expect(result.lines[0]!.proposal_status).toBe("NUMERIC_PROVISIONAL");
    expect(result.lines[0]!.next_action).toMatch(/Human review required/);
  });

  it.each(["admit", "quarantine", "reject"] as const)(
    "cannot restore the unrelated normalized collision when Jev would %s it", async (verdict) => {
      const { client, hooks } = mockJev(verdict);
      const result = await estimate(new QuoteRegister([collision, related]),
        { customer_id: namespace.customerId, parts: [part] }, { jev: client });
      expect(hooks.rankAnalogs.mock.calls[0]![1].map((candidate) => candidate.row.quote_no)).toEqual(["related"]);
      expect(result.lines[0]!.unit_price).toBe(36);
      expect(result.lines[0]!.analogs.map((analog) => analog.quote_no)).toEqual(["related"]);
    },
  );

  it("holds when a foreign ID-only collision is the sole source", async () => {
    const { client, hooks } = mockJev("reject");
    const result = await estimate(new QuoteRegister([collision]),
      { customer_id: namespace.customerId, parts: [part] }, { jev: client });
    expect(hooks.rankAnalogs.mock.calls[0]![1]).toEqual([]);
    expect(hooks.screenCandidate).not.toHaveBeenCalled();
    expect(result.lines[0]!).toMatchObject({ unit_price: null, extended_price: null,
      proposal_status: "MISSING", evidence_status: "NONE", analogs: [] });
    expect(result.lines[0]!.warnings.join(" ")).not.toMatch(/retained highest-ranked/);
  });

  it("keeps independently described foreign analogs without exact narrowing or priority", async () => {
    const register = new QuoteRegister([
      row({ ...collision, description: part.description!, quote_date: "2023-01-01" }), related,
    ]);
    const candidates = retrieve(register, part, namespace);
    expect(candidates.map((candidate) => candidate.row.quote_no)).toEqual(["collision", "related"]);
    candidates.forEach(expectNoPartPrivilege);
    const { client, hooks } = mockJev("admit", "related");
    const result = await estimate(register, { customer_id: namespace.customerId, parts: [part] },
      { jev: client, screenTopN: 1 });
    expect(hooks.rankAnalogs.mock.calls[0]![1]).toHaveLength(2);
    expect(hooks.chooseStrategy.mock.calls[0]![1].map((candidate) => candidate.row.quote_no)).toEqual(["related"]);
    expect(result.lines[0]!.unit_price).toBe(36);
  });

  it("allows a foreign analog supported by a known drawing, without part-identity privilege", async () => {
    const request = { part_no: "SYN-4721", drawing_ref: "FRAME-71", quantity: 40 };
    const register = new QuoteRegister([row({ ...collision, drawing_no: "FRAME-71" })]);
    const candidates = retrieve(register, request, namespace);
    expect(candidates).toHaveLength(1);
    expect(candidates[0]!.reasons).toContain("drawing_no match");
    expectNoPartPrivilege(candidates[0]!);
    const result = await estimate(register, { customer_id: namespace.customerId, parts: [request] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).toBe(0.85);
    expect(result.lines[0]!.proposal_status).toBe("NUMERIC_PROVISIONAL");
  });

  it("does not use a foreign prefix or a shared material alone as compatibility proof", () => {
    const register = new QuoteRegister([row({ ...collision, part_no: "SYN-472", material: "304 SS", comment: "304 SS" })]);
    expect(retrieve(register, { ...part, material: "304 SS" }, namespace)).toEqual([]);
  });

  it("keeps a partial foreign description as a provisional analog without part-identity privilege", async () => {
    const register = new QuoteRegister([row({ ...collision, part_no: "OTHER-PLATE", description: "MOUNT PLATE" })]);
    const request = { part_no: "REQUEST-PLATE", description: "SUPPORT PLATE", quantity: 40 };
    const candidate = retrieve(register, request, namespace)[0]!;
    expectNoPartPrivilege(candidate);
    expect(candidate.incompatibilities).toEqual([]);
    expect(candidate.reasons.some((reason) => reason.startsWith("desc tokens "))).toBe(true);
    const result = await estimate(register, { customer_id: namespace.customerId, parts: [request] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).toBeGreaterThan(0);
    expect(result.lines[0]!.proposal_status).toBe("NUMERIC_PROVISIONAL");
    expect(result.lines[0]!.next_action).toMatch(/Human review required/);
  });

  it("uses explicit customer-ID equality even when display names differ", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "exact", customer_id: namespace.customerId, customer: "FORMER DISPLAY NAME",
        part_no: "SYN4721", description: part.description! }),
      related,
    ]);
    const candidates = retrieve(register, part, { ...namespace, customer: "NEW DISPLAY NAME" });
    expect(candidates[0]!.reasons).toContain("exact part_no");
    expect(candidates[0]!.reasons).toContain("same customer_id");
    const { client, hooks } = mockJev();
    const result = await estimate(register,
      { customer_id: namespace.customerId, customer: "NEW DISPLAY NAME", parts: [part] }, { jev: client });
    expect(hooks.rankAnalogs.mock.calls[0]![1].map((candidate) => candidate.row.quote_no)).toEqual(["exact"]);
    expect(result.lines[0]!.unit_price).toBe(36);
  });

  it("never strips customer-ID punctuation or lets name equality override a different explicit ID", () => {
    const register = new QuoteRegister([row({ quote_no: "other", customer_id: "CUSTOMERALPHA", customer: "Shared Name",
      part_no: part.part_no!, description: part.description! })]);
    const candidate = retrieve(register, part, { ...namespace, customer: "Shared Name" })[0]!;
    expectNoPartPrivilege(candidate);
    expect(candidate.reasons).not.toContain("same customer_id");
    expect(candidate.reasons).not.toContain("same customer");
  });
});

describe("missing and ambiguous identities", () => {
  it.each(["", "---", "???"])("does not treat source customer ID %s as an explicit namespace match", async (customer_id) => {
    const register = new QuoteRegister([row({ quote_no: "unknown", customer_id, customer: "Shared Name",
      part_no: part.part_no!, description: part.description! })]);
    const candidates = retrieve(register, part, { ...namespace, customer: "Shared Name" });
    expect(candidates).toHaveLength(1);
    expectNoPartPrivilege(candidates[0]!);
    expect(candidates[0]!.reasons).not.toContain("same customer_id");
    const result = await estimate(register, { customer_id: namespace.customerId, parts: [part] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).toBe(36);
    expect(retrieve(register, { part_no: part.part_no, quantity: 40 }, namespace)).toEqual([]);
  });

  it("keeps a missing-request-identity normalized lookup for inspection but cannot price it alone", async () => {
    const register = new QuoteRegister([collision]);
    const request = { part_no: part.part_no, quantity: 40 };
    const candidate = retrieve(register, request)[0]!;
    expectNoPartPrivilege(candidate);
    expect(candidate.incompatibilities).toContain("unresolved part identity");
    const { client, hooks } = mockJev("reject");
    const result = await estimate(register, { parts: [request] }, { jev: client });
    expect(hooks.rankAnalogs.mock.calls[0]![1]).toEqual([]);
    expect(result.lines[0]!).toMatchObject({ unit_price: null, evidence_status: "NONE", analogs: [] });
  });

  it("retains an independently described analog when request customer identity is missing", async () => {
    const register = new QuoteRegister([row({ ...collision, description: part.description! })]);
    const candidate = retrieve(register, part)[0]!;
    expectNoPartPrivilege(candidate);
    expect(candidate.incompatibilities).toEqual([]);
    const result = await estimate(register, { parts: [part] }, { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).toBe(0.85);
    expect(result.lines[0]!.next_action).toMatch(/Human review required/);
  });

  it("does not claim exact identity among conflicting source specifications without a customer", async () => {
    const register = new QuoteRegister([
      row({ ...collision, part_no: part.part_no! }),
      row({ ...related, part_no: part.part_no! }),
    ]);
    const candidates = retrieve(register, { part_no: part.part_no, quantity: 40 });
    expect(candidates).toHaveLength(2);
    candidates.forEach(expectNoPartPrivilege);
    expect(candidates.every((candidate) => candidate.incompatibilities?.includes("unresolved part identity"))).toBe(true);
    const hold = await estimate(register, { parts: [{ part_no: part.part_no, quantity: 40 }] },
      { jev: new JevClient("") });
    expect(hold.lines[0]!.unit_price).toBeNull();
    const described = await estimate(register, { parts: [part] }, { jev: new JevClient("") });
    expect(described.lines[0]!.unit_price).toBe(36);
    expect(described.lines[0]!.analogs.map((analog) => analog.quote_no)).toEqual(["related"]);
  });

  it.each(["admit", "quarantine", "reject"] as const)(
    "keeps literal-equal consistent records provisional when Jev would %s them", async (verdict) => {
      const specification = { part_no: part.part_no!, description: part.description!, rev: "B",
        drawing_no: "FRAME-71", material: "304 SS" };
      const register = new QuoteRegister([
        row({ ...specification, quote_no: "namespace-alpha", customer_id: "CUSTOMER-ALPHA" }),
        row({ ...specification, quote_no: "namespace-beta", customer_id: "CUSTOMER-BETA" }),
      ]);
      const request = { part_no: part.part_no, quantity: 40 };
      const candidates = retrieve(register, request);
      expect(candidates).toHaveLength(2);
      expect(candidates.every((candidate) => !candidate.incompatibilities?.length)).toBe(true);
      expect(candidates.every((candidate) => !candidate.reasons.includes("same customer_id"))).toBe(true);
      const { client, hooks } = mockJev(verdict);
      const result = await estimate(register, { parts: [request] }, { jev: client });
      expect(hooks.rankAnalogs.mock.calls[0]![1]).toHaveLength(2);
      expect(hooks.screenCandidate).toHaveBeenCalledTimes(2);
      expect(result.lines[0]!).toMatchObject({ unit_price: 36, proposal_status: "NUMERIC_PROVISIONAL" });
      expect(result.lines[0]!.warnings.join(" ")).toMatch(/unresolved customer namespace/);
      expect(result.lines[0]!.next_action).toMatch(/Human review required/);
      expect(result.request.customer_id).toBeUndefined();
      const offline = await estimate(register, { parts: [request] }, { jev: new JevClient("") });
      expect(offline.lines[0]!.unit_price).toBe(36);
      expect(offline.lines[0]!.proposal_status).toBe("NUMERIC_PROVISIONAL");
      expect(offline.lines[0]!.warnings.join(" ")).toMatch(/unresolved customer namespace/);
    },
  );

  it.each([{ description: part.description }, { drawing_ref: "FRAME-71" }])(
    "keeps independently supported literal records across namespaces provisional: %j", async (attributes) => {
      const specification = { part_no: part.part_no!, description: part.description!, rev: "B",
        drawing_no: "FRAME-71", material: "304 SS" };
      const register = new QuoteRegister([
        row({ ...specification, quote_no: "namespace-alpha", customer_id: "CUSTOMER-ALPHA" }),
        row({ ...specification, quote_no: "namespace-beta", customer_id: "CUSTOMER-BETA" }),
      ]);
      const request = { part_no: part.part_no, quantity: 40, ...attributes };
      const candidates = retrieve(register, request);
      expect(candidates).toHaveLength(2);
      expect(candidates.every((candidate) => !candidate.reasons.includes("same customer_id"))).toBe(true);
      expect(candidates.every((candidate) => !candidate.incompatibilities?.length)).toBe(true);
      const result = await estimate(register, { parts: [request] }, { jev: new JevClient("") });
      expect(result.lines[0]!.unit_price).toBe(36);
      expect(result.lines[0]!.analogs).toHaveLength(2);
      expect(result.lines[0]!.proposal_status).toBe("NUMERIC_PROVISIONAL");
      expect(result.lines[0]!.warnings.join(" ")).toMatch(/unresolved customer namespace/);
      expect(result.lines[0]!.next_action).toMatch(/Human review required/);
      expect(result.request.customer_id).toBeUndefined();
    },
  );

  it("does not infer a requested customer from a drawing that selects one namespace", async () => {
    const register = new QuoteRegister([
      row({ ...related, quote_no: "namespace-alpha", customer_id: "CUSTOMER-ALPHA",
        part_no: part.part_no!, drawing_no: "FRAME-71" }),
      row({ ...related, quote_no: "namespace-beta", customer_id: "CUSTOMER-BETA",
        part_no: part.part_no!, drawing_no: "FRAME-72" }),
    ]);
    const request = { part_no: part.part_no, quantity: 40, drawing_ref: "FRAME-71" };
    const candidates = retrieve(register, request);
    expect(candidates.every((candidate) => !candidate.reasons.includes("same customer_id"))).toBe(true);
    const { client, hooks } = mockJev();
    const result = await estimate(register, { parts: [request] }, { jev: client });
    expect(hooks.rankAnalogs.mock.calls[0]![1].map((candidate) => candidate.row.quote_no)).toEqual(["namespace-alpha"]);
    expect(hooks.rankAnalogs.mock.calls[0]![1][0]!.reasons).not.toContain("same customer_id");
    expect(result.lines[0]!.unit_price).toBe(36);
    expect(result.lines[0]!.proposal_status).toBe("NUMERIC_PROVISIONAL");
    expect(result.lines[0]!.warnings.join(" ")).toMatch(/unresolved customer namespace/);
    expect(result.lines[0]!.next_action).toMatch(/Human review required/);
    expect(result.request.customer_id).toBeUndefined();
  });

  it("holds consistent normalized aliases across known namespaces without request identity", async () => {
    const specification = { part_no: "SYN4721", description: part.description!, rev: "B",
      drawing_no: "FRAME-71", material: "304 SS" };
    const register = new QuoteRegister([
      row({ ...specification, quote_no: "namespace-alpha", customer_id: "CUSTOMER-ALPHA" }),
      row({ ...specification, quote_no: "namespace-beta", customer_id: "CUSTOMER-BETA" }),
    ]);
    const request = { part_no: part.part_no, quantity: 40 };
    const candidates = retrieve(register, request);
    expect(candidates).toHaveLength(2);
    candidates.forEach(expectNoPartPrivilege);
    expect(candidates.every((candidate) => candidate.incompatibilities?.includes("unresolved part identity"))).toBe(true);
    const { client, hooks } = mockJev("reject");
    const result = await estimate(register, { parts: [request] }, { jev: client });
    expect(hooks.rankAnalogs.mock.calls[0]![1]).toEqual([]);
    expect(result.lines[0]!).toMatchObject({ unit_price: null, proposal_status: "MISSING", analogs: [] });
    expect(result.lines[0]!.warnings.join(" ")).toMatch(/unresolved customer namespace/);
    expect(result.lines[0]!.warnings.join(" ")).not.toMatch(/retained highest-ranked/);
  });

  it.each([undefined, "", "   ", "---", "???", "CUSTOMER-*"])(
    "warns when the request customer ID %s cannot establish a namespace", async (customer_id) => {
      const register = new QuoteRegister([row({ quote_no: "unscoped", part_no: part.part_no!, description: part.description! })]);
      const result = await estimate(register, { customer: "Synthetic Display Name", customer_id, parts: [part] },
        { jev: new JevClient("") });
      expect(result.lines[0]!.unit_price).toBe(36);
      expect(result.lines[0]!.proposal_status).toBe("NUMERIC_PROVISIONAL");
      expect(result.lines[0]!.warnings.join(" ")).toMatch(/unresolved customer namespace/);
      expect(result.lines[0]!.warnings.join(" ")).toMatch(/do not establish customer-qualified manufacturing identity/);
      expect(result.lines[0]!.next_action).toMatch(/Human review required/);
    },
  );

  it("does not warn that a supplied usable customer ID is missing", async () => {
    const register = new QuoteRegister([row({ quote_no: "known", part_no: part.part_no!,
      description: part.description!, customer_id: namespace.customerId })]);
    const result = await estimate(register, { customer_id: namespace.customerId, parts: [part] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).toBe(36);
    expect(result.lines[0]!.warnings.join(" ")).not.toMatch(/unresolved customer namespace/);
  });

  it("preserves an unambiguous unscoped lookup as a provisional reviewed proposal", async () => {
    const register = new QuoteRegister([row({ quote_no: "unscoped", part_no: "SYN4721" })]);
    const request = { part_no: part.part_no, quantity: 40 };
    expect(retrieve(register, request)[0]!.reasons).toContain("exact part_no");
    const result = await estimate(register, { parts: [request] }, { jev: new JevClient("") });
    expect(result.lines[0]!).toMatchObject({ unit_price: 36, proposal_status: "NUMERIC_PROVISIONAL" });
    expect(result.lines[0]!.next_action).toMatch(/Human review required/);
  });

  it("cannot claim unscoped normalized equivalence when the supplied descriptions disagree", async () => {
    const register = new QuoteRegister([row({ ...collision, customer_id: "" })]);
    const candidate = retrieve(register, part)[0]!;
    expectNoPartPrivilege(candidate);
    expect(candidate.incompatibilities).toContain("normalized part_no description conflict");
    const { client, hooks } = mockJev("reject");
    const result = await estimate(register, { parts: [part] }, { jev: client });
    expect(hooks.rankAnalogs.mock.calls[0]![1]).toEqual([]);
    expect(result.lines[0]!.unit_price).toBeNull();
    expect(result.lines[0]!.analogs).toEqual([]);
  });

  it("does not let a shared drawing erase unresolved revision ambiguity between sources", () => {
    const register = new QuoteRegister([
      row({ ...related, quote_no: "revision-a", part_no: part.part_no!, rev: "A", drawing_no: "FRAME-71" }),
      row({ ...related, quote_no: "revision-b", part_no: part.part_no!, rev: "B", drawing_no: "FRAME-71" }),
    ]);
    const candidates = retrieve(register, { ...part, drawing_ref: "FRAME-71" });
    expect(candidates).toHaveLength(2);
    candidates.forEach(expectNoPartPrivilege);
    const resolved = retrieve(register, { ...part, drawing_ref: "FRAME-71", revision: "B" });
    expect(resolved.find((candidate) => candidate.row.quote_no === "revision-b")!.reasons).toContain("exact part_no");
    expect(resolved.find((candidate) => candidate.row.quote_no === "revision-a")!.incompatibilities).toContain("revision conflict");
  });

  it("does not price ID-only prefix evidence in an unknown requested customer namespace", async () => {
    const register = new QuoteRegister([row({ ...collision, part_no: "SYN-472" })]);
    const request = { part_no: part.part_no, quantity: 40 };
    expect(retrieve(register, request)).toEqual([]);
    const { client } = mockJev("reject");
    const result = await estimate(register, { parts: [request] }, { jev: client });
    expect(result.lines[0]!.unit_price).toBeNull();
  });

  it.each(["---", "???", "SYN-47*", ""])("never grants identifier privilege to request %s", async (part_no) => {
    const register = new QuoteRegister([row({ ...related, part_no })]);
    const candidates = retrieve(register, { ...part, part_no }, namespace);
    expect(candidates).toHaveLength(1);
    expectNoPartPrivilege(candidates[0]!);
    const result = await estimate(register, { customer_id: namespace.customerId, parts: [{ ...part, part_no }] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).toBe(36);
  });
});

describe("source-compatibility and fallback guards", () => {
  it.each(["latest", "median_won", "curve_fit", "conservative"] as const)(
    "cannot price search-only incompatible evidence through the direct %s strategy", (strategy) => {
      const register = new QuoteRegister([row({ quote_no: "wrong-revision", customer_id: namespace.customerId,
        part_no: part.part_no!, description: part.description!, rev: "A" })]);
      const candidates = retrieve(register, { ...part, revision: "B" }, namespace);
      expect(candidates[0]!.incompatibilities).toContain("revision conflict");
      expect(price(part.quantity, candidates, { strategy })).toMatchObject({ unit_price: null, points: [] });
    },
  );

  it.each([
    ["revision conflict", { revision: "B" }, { rev: "A" }],
    ["revision conflict", { revision: "A-1" }, { rev: "A1" }],
    ["drawing conflict", { drawing_ref: "FRAME-71" }, { drawing_no: "FRAME-72" }],
    ["drawing conflict", { drawing_ref: "FRAME-71" }, { drawing_no: "FRAME-710" }],
    ["material conflict", { material: "304 SS" }, { material: "316 SS" }],
  ] as const)("excludes an explicit %s before ranking even when Jev rejects everything", async (reason, requestFields, sourceFields) => {
    const request = { ...part, ...requestFields };
    const register = new QuoteRegister([row({ quote_no: "incompatible", customer_id: namespace.customerId,
      part_no: part.part_no!, description: part.description!, ...sourceFields })]);
    const candidates = retrieve(register, request, namespace);
    expect(candidates).toHaveLength(1);
    expect(candidates[0]!.reasons).not.toContain("exact part_no");
    expect(candidates[0]!.incompatibilities).toContain(reason);
    const { client, hooks } = mockJev("reject");
    const result = await estimate(register, { customer_id: namespace.customerId, parts: [request] }, { jev: client });
    expect(hooks.rankAnalogs.mock.calls[0]![1]).toEqual([]);
    expect(hooks.screenCandidate).not.toHaveBeenCalled();
    expect(hooks.chooseStrategy.mock.calls[0]![1]).toEqual([]);
    expect(result.lines[0]!).toMatchObject({ unit_price: null, proposal_status: "MISSING", evidence_status: "NONE", analogs: [] });
    expect(result.lines[0]!.warnings.join(" ")).toContain(reason);
    expect(result.lines[0]!.warnings.join(" ")).not.toMatch(/retained highest-ranked/);
  });

  it.each([
    ["customer_id", "CUSTOMER-BETA"], ["part_no", "SYN4721"], ["rev", "B"],
    ["drawing_no", "FRAME-72"], ["material", "316 SS"],
  ])("rejects an ambiguous %s across all breaks rather than pricing the matching head", async (field, value) => {
    const source = row({ quote_no: "mixed", customer_id: namespace.customerId, part_no: part.part_no!,
      description: part.description!, rev: "A", drawing_no: "FRAME-71", material: "304 SS", unit_price: 0 });
    const register = new QuoteRegister([source, row({ ...source, quantity: 80, unit_price: 54, [field]: value })]);
    const { client, hooks } = mockJev("reject");
    const result = await estimate(register, { customer_id: namespace.customerId,
      parts: [{ ...part, revision: "A", drawing_ref: "FRAME-71", material: "304 SS" }] }, { jev: client });
    expect(hooks.rankAnalogs.mock.calls[0]![1]).toEqual([]);
    expect(result.lines[0]!.unit_price).toBeNull();
    expect(result.lines[0]!.analogs).toEqual([]);
    expect(result.lines[0]!.warnings.join(" ")).toContain(`ambiguous source ${field}`);
  });

  it("does not let incompatible high-scoring sources consume the retrieval limit", async () => {
    const register = new QuoteRegister([
      ...Array.from({ length: 13 }, (_, index) => row({ quote_no: `wrong-${index}`, part_no: part.part_no!,
        customer_id: namespace.customerId, description: part.description!, rev: "A", quote_date: "2023-01-01" })),
      row({ ...related, rev: "B" }),
    ]);
    const { client, hooks } = mockJev("reject");
    const result = await estimate(register, { customer_id: namespace.customerId, parts: [{ ...part, revision: "B" }] },
      { jev: client, screenTopN: 1 });
    expect(hooks.rankAnalogs.mock.calls[0]![1].map((candidate) => candidate.row.quote_no)).toEqual(["related"]);
    expect(result.lines[0]!.unit_price).toBe(36);
    expect(result.lines[0]!.analogs.map((analog) => analog.quote_no)).toEqual(["related"]);
  });

  it("does not interpret a drawing file path as a conflicting manufacturing drawing ID", async () => {
    const register = new QuoteRegister([row({ ...related, drawing_no: "FRAME-71" })]);
    const request = { ...part, drawing_ref: "requests/beacon-panel.pdf" };
    const candidate = retrieve(register, request, namespace)[0]!;
    expect(candidate.incompatibilities).toEqual([]);
    const result = await estimate(register, { customer_id: namespace.customerId, parts: [request] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).toBe(36);
    expect(result.lines[0]!.part.drawing_ref).toBe(request.drawing_ref);
  });

  it.each(["---", "FRAME-7?"])("does not use placeholder drawing %s to qualify foreign identity", async (drawing_ref) => {
    const register = new QuoteRegister([row({ ...collision, drawing_no: drawing_ref })]);
    const request = { part_no: part.part_no, quantity: 40, drawing_ref };
    expect(retrieve(register, request, namespace)).toEqual([]);
    const result = await estimate(register, { customer_id: namespace.customerId, parts: [request] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).toBeNull();
  });

  it("never restores excluded, future, touched or letter-dated sources through the enabled fallback", async () => {
    const source = { part_no: part.part_no!, description: part.description!, customer_id: namespace.customerId, rev: "B" };
    const register = new QuoteRegister([
      row({ ...source, quote_no: "excluded" }),
      row({ ...source, quote_no: "future", quote_date: "2024-01-01" }),
      row({ ...source, quote_no: "touched", date_stamp: "2024-01-01" }),
      row({ ...source, quote_no: "letter", letter_date: "2024-01-01" }),
      row({ ...source, quote_no: "mixed-date" }),
      row({ ...source, quote_no: "mixed-date", quantity: 80, quote_date: "2024-01-01" }),
      row({ ...source, quote_no: "safe" }),
    ]);
    const { client, hooks } = mockJev("reject");
    const result = await estimate(register, { customer_id: namespace.customerId, parts: [{ ...part, revision: "B" }] },
      { jev: client, exclude: new Set(["excluded"]), asOf: "2024-01-01" });
    expect(hooks.rankAnalogs.mock.calls[0]![1].map((candidate) => candidate.row.quote_no)).toEqual(["safe"]);
    expect(result.lines[0]!.analogs.map((analog) => analog.quote_no)).toEqual(["safe"]);
    expect(result.lines[0]!.unit_price).toBe(36);
  });

  it("does not let excluded or future collisions make eligible unscoped history ambiguous", async () => {
    const register = new QuoteRegister([
      row({ quote_no: "safe", part_no: "SYN4721" }),
      row({ ...collision, quote_no: "future", quote_date: "2024-01-01" }),
      row({ ...collision, quote_no: "excluded" }),
    ]);
    const request = { part_no: part.part_no, quantity: 40 };
    const result = await estimate(register, { parts: [request] },
      { jev: new JevClient(""), exclude: new Set(["excluded"]), asOf: "2024-01-01" });
    expect(result.lines[0]!.unit_price).toBe(36);
    expect(result.lines[0]!.analogs.map((analog) => analog.quote_no)).toEqual(["safe"]);
  });

  it("does not use unavailable letter material to assert source ambiguity at a cutoff", () => {
    const register = new QuoteRegister([
      row({ quote_no: "first", part_no: "SYN4721", material: "304 SS" }),
      row({ quote_no: "second", part_no: "SYN4721", material: "316 SS" }),
    ]);
    const candidates = retrieve(register, { part_no: part.part_no, quantity: 40 }, { asOf: "2024-01-01" });
    expect(candidates).toHaveLength(2);
    expect(candidates.every((candidate) => candidate.reasons.includes("exact part_no"))).toBe(true);
    expect(candidates.every((candidate) => candidate.row.material === "" && !candidate.incompatibilities?.length)).toBe(true);
  });

  it("uses only usable exact breaks to narrow, preserving evidence-present holds", async () => {
    const exact = row({ quote_no: "no-price", customer_id: namespace.customerId, part_no: part.part_no!,
      description: part.description!, unit_price: null });
    const register = new QuoteRegister([exact, related]);
    const result = await estimate(register, { customer_id: namespace.customerId, parts: [part] },
      { jev: new JevClient("") });
    expect(result.lines[0]!.unit_price).toBe(36);
    expect(result.lines[0]!.analogs.map((analog) => analog.quote_no)).toEqual(["related"]);
    const hold = await estimate(new QuoteRegister([exact]), { customer_id: namespace.customerId, parts: [part] },
      { jev: new JevClient("") });
    expect(hold.lines[0]!).toMatchObject({ unit_price: null, proposal_status: "MISSING",
      evidence_status: "PRESENT_BUT_NO_USABLE_PRICE", analogs: [] });
  });
});
