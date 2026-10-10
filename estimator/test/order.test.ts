import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";
import { QuoteRegister } from "../src/register.js";
import { buildPricedOrder, renderOrderMarkdown } from "../src/order.js";
import type { QuoteRow } from "../src/types.js";

const sha = "a".repeat(64);
const opts = { registerSha256: sha };
const reg = new QuoteRegister([]);
const base = () => ({
  order_id: "ORD-1", quote_date: "2024-06-01", customer: "Demo", charges: { shipping: 0, tax: 0 },
  parts: [{ line_id: "1", part_no: "P-1", quantity: 3,
    pricing: { method: "unit_price", unit_price: 0.3333, reason: "operator supplied" } }],
});

function row(partial: Partial<QuoteRow>): QuoteRow {
  return {
    quote_no: "", item_no: "", assembly_no: "", quote_date: "", date_stamp: "", customer_id: "",
    customer: "", part_no: "", description: "", rev: "", drawing_no: "", rfq_no: "", buyer_name: "",
    salesperson: "", quote_letter: "", letter_date: "", quantity: null, unit_price: null,
    unit_cost: null, extended_price: null, markup: null, del_seq: null, material: "", status: "open",
    won_date: "", to_quote: "", user_quote: "", newsellpri: null, comment: "", ...partial,
  };
}

describe("priced orders", () => {
  it("rejects asset paths as drawing numbers even for operator-priced lines", async () => {
    for (const pricing of [base().parts[0]!.pricing, { method: "cost_plus", material_per_unit: 1,
      labor_per_unit: 0, outside_per_unit: 0, setup_total: 0, margin_pct: 20, reason: "synthetic" }]) {
      await expect(buildPricedOrder(reg, { ...base(), parts: [{ ...base().parts[0], pricing,
        drawing_no: "uploads/drawing.pdf" }] }, opts)).rejects.toThrow(/drawing number/);
      const order = await buildPricedOrder(reg, { ...base(), parts: [{ ...base().parts[0], pricing,
        drawing_no: "DWG-1", drawing_revision: "A", revision: "B", drawing_ref: "uploads/drawing.pdf" }] }, opts);
      expect(order.lines[0]!.part).toMatchObject({ drawing_no: "DWG-1", drawing_revision: "A", revision: "B" });
    }
  });

  it("blocks completion for unreferenced explicit engineering conflicts on historical and operator proposals", async () => {
    const source = new QuoteRegister([row({ quote_no: "Q", part_no: "P-1",
      quote_date: "2020-01-01", quantity: 3, unit_price: 2 })]);
    for (const pricing of [base().parts[0]!.pricing, undefined,
      { method: "cost_plus", material_per_unit: 1, labor_per_unit: 0, outside_per_unit: 0,
        setup_total: 0, margin_pct: 20, reason: "synthetic" }]) {
      const order = await buildPricedOrder(source, { ...base(), parts: [{ ...base().parts[0], pricing,
        geometry: [{ id: "revision", field: "drawing_revision", value: "Unresolved explicit revision conflict",
          source_ids: [], applicability: "conflict" }] }] }, opts);
      expect(order.lines[0]!.unit_price).toBeGreaterThan(0); // Retain the comparison/proposal, never adopt it.
      expect(order.state).toBe("BLOCKED");
      expect(order.total).toBeNull();
      expect(order.blockers.join(" ")).toMatch(/explicit engineering conflict.*drawing_revision/);
      expect(order.lines[0]!.next_action).toMatch(/Resolve explicit engineering conflict/);
    }
  });

  it("preserves non-admitted specification evidence in operator order holds", async () => {
    const source = new QuoteRegister([row({ quote_no: "Q", part_no: "P-1", rev: "A",
      quote_date: "2020-01-01", quantity: 3, unit_price: 2 })]);
    const order = await buildPricedOrder(source, { ...base(), parts: [{ line_id: "1", part_no: "P-1",
      quantity: 3, revision: "B" }] }, opts);
    expect(order.state).toBe("BLOCKED");
    expect(order.lines[0]!.analogs).toEqual([]);
    expect(order.lines[0]!.evidence_candidates).toHaveLength(1);
    expect(order.lines[0]!.evidence_candidates![0]!.screening.status).toBe("incompatible");
    expect(order.lines[0]!.evidence_candidates![0]!.identity.quote_no).toBe("Q");
  });

  it("reconciles multiple lines from displayed unit prices with HALF-UP cents and explicit zero charges", async () => {
    const request = {
      ...base(), parts: [base().parts[0],
        { line_id: "2", part_no: "P-2", quantity: 2,
          pricing: { method: "unit_price", unit_price: 1.005, reason: "approved cost input" } }],
      additional_charges: [{ label: "Handling", amount: 0.25 }],
    };
    const order = await buildPricedOrder(reg, request, opts);
    expect(order.lines.map((line) => line.extended_price)).toEqual([1, 2.01]);
    expect(order.priced_subtotal).toBe(3.01);
    expect(order.subtotal).toBe(3.01);
    expect(order.total).toBe(3.26);
    expect(order.charges).toEqual({ shipping: 0, tax: 0 });
    expect(order.state).toBe("PRICED_REQUIRES_REVIEW");
    expect(order.requires_human_review).toBe(true);
    expect(order.lines[0]!.warnings).toContain("Operator-supplied unit price is a proposal, not approval");
    expect(order.lines[0]).toMatchObject({ proposal_status: "NUMERIC_PROVISIONAL", evidence_status: "OPERATOR_INPUT" });
    expect(order.request).toEqual(request);
    expect(order.provenance).toEqual({ request_sha256: createHash("sha256").update(JSON.stringify(request)).digest("hex"),
      register_sha256: sha, as_of: "2024-06-01", mode: "offline" });
  });

  it("retains separate lines for the same part and blocks null or missing charges", async () => {
    const request = { ...base(), charges: { shipping: null }, parts: [base().parts[0],
      { ...base().parts[0], line_id: "2", quantity: 2 }] };
    const order = await buildPricedOrder(reg, request, opts);
    expect(order.lines.map((line) => line.line_id)).toEqual(["1", "2"]);
    expect(order.lines.map((line) => line.extended_price)).toEqual([1, 0.67]);
    expect(order.priced_subtotal).toBe(1.67);
    expect(order.subtotal).toBe(1.67);
    expect(order.total).toBeNull();
    expect(order.blockers).toEqual(["shipping is missing", "tax is missing"]);
  });

  it("blocks unmatched historical parts without inventing a price or total", async () => {
    const order = await buildPricedOrder(reg, { ...base(), parts: [{ line_id: "lost", part_no: "UNKNOWN", quantity: 2 }],
      charges: { shipping: 1, tax: 0 } }, opts);
    expect(order.state).toBe("BLOCKED");
    expect(order.lines[0]).toMatchObject({ unit_price: null, extended_price: null,
      pricing_source: "unpriced", analogs: [], proposal_status: "MISSING", evidence_status: "NONE" });
    expect(order.priced_subtotal).toBe(0);
    expect(order.subtotal).toBeNull();
    expect(order.total).toBeNull();
    expect(order.blockers).toEqual(["line lost is unpriced"]);
  });

  it("keeps a partial priced diagnostic but no subtotal or total for mixed priced and unpriced lines", async () => {
    const request = { ...base(), parts: [base().parts[0], { line_id: "unknown", part_no: "NO-MATCH", quantity: 1 }] };
    const order = await buildPricedOrder(reg, request, opts);
    expect(order.lines.map((line) => line.extended_price)).toEqual([1, null]);
    expect(order.priced_subtotal).toBe(1);
    expect(order.subtotal).toBeNull();
    expect(order.total).toBeNull();
    expect(order.state).toBe("BLOCKED");
    expect(order.blockers).toEqual(["line unknown is unpriced"]);
  });

  it("rounds cost-plus unit to four decimals before extension", async () => {
    const order = await buildPricedOrder(reg, { ...base(), parts: [{ line_id: "cost", description: "PART", quantity: 3,
      pricing: { method: "cost_plus", material_per_unit: 1, labor_per_unit: 0.1,
        outside_per_unit: 0, setup_total: 1, margin_pct: 20, reason: "cost sheet" } }] }, opts);
    expect(order.lines[0]).toMatchObject({ unit_price: 1.7917, extended_price: 5.38,
      pricing_source: "cost_build_up", pricing_reason: "cost sheet", confidence: null, analogs: [] });
    expect(order.total).toBe(5.38);
    expect(order.request.parts[0]!.pricing).toMatchObject({ method: "cost_plus", setup_total: 1, margin_pct: 20 });
    expect(order.lines[0]!.warnings.join(" ")).toContain("not approval");
  });

  it.each([
    [0.0001, 49, 0], [0.0001, 50, 0.01], [0.0049, 1, 0], [0.005, 1, 0.01],
    [0.0051, 1, 0.01], [0.0003, 16, 0], [0.0003, 17, 0.01],
  ])("preserves %s × %s while holding only zero-cent extensions", async (unit_price, quantity, extension) => {
    for (const pricing of [
      { method: "unit_price", unit_price, reason: "Synthetic operator proposal" },
      { method: "cost_plus", material_per_unit: unit_price, labor_per_unit: 0, outside_per_unit: 0,
        setup_total: 0, margin_pct: 0, reason: "Synthetic cost estimate; explicit zero excluded costs" },
    ]) {
      const request = { ...base(), parts: [{ ...base().parts[0], quantity, pricing }] };
      const original = JSON.stringify(request);
      const order = await buildPricedOrder(reg, request, opts);
      expect(order.lines[0]).toMatchObject({ unit_price, extended_price: extension, proposal_status: "NUMERIC_PROVISIONAL" });
      expect(order.priced_subtotal).toBe(extension);
      expect(order.subtotal).toBe(extension);
      expect(order.total).toBe(extension === 0 ? null : extension);
      expect(order.state).toBe(extension === 0 ? "BLOCKED" : "PRICED_REQUIRES_REVIEW");
      expect(order.requires_human_review).toBe(true);
      expect(JSON.stringify(order.request)).toBe(original);
      expect(order.provenance.request_sha256).toBe(createHash("sha256").update(original).digest("hex"));
      expect(order.blockers.some(blocker => blocker.includes("zero-cent"))).toBe(extension === 0);
      expect(order.lines[0]!.next_action.includes("zero-cent")).toBe(extension === 0);
      expect(order.lines[0]!.warnings.some(warning => warning.includes("zero-cent"))).toBe(extension === 0);
      expect(order.warnings.some(warning => warning.includes("zero-cent"))).toBe(extension === 0);
    }
  });

  it("holds a zero-cent line despite other revenue and keeps independent blockers", async () => {
    const order = await buildPricedOrder(reg, { ...base(), parts: [base().parts[0]!, {
      line_id: "tiny", description: "Synthetic tiny line", quantity: 1,
      pricing: { method: "unit_price", unit_price: 0.0001, reason: "Synthetic proposal" },
      geometry: [{ id: "rev", field: "revision", value: "Conflicting revisions", source_ids: [], applicability: "conflict" }],
    }], charges: { shipping: 10 }, additional_charges: [{ label: "Handling", amount: 50 }] }, opts);
    expect(order.lines.map(line => line.extended_price)).toEqual([1, 0]);
    expect(order.subtotal).toBe(1);
    expect(order.total).toBeNull();
    expect(order.state).toBe("BLOCKED");
    expect(order.blockers).toHaveLength(3);
    expect(order.blockers.join(" ")).toMatch(/engineering conflict.*zero-cent.*tax is missing/);
    expect(order.lines[1]!.next_action).toMatch(/zero-cent.*engineering conflict/);
    expect(renderOrderMarkdown(order)).toContain("BLOCKED");
  });

  it("retains a tiny historical proposal and its analog while blocking zero-cent completion", async () => {
    const source = new QuoteRegister([row({ quote_no: "SYNTHETIC-TINY", part_no: "TINY",
      quote_date: "2020-01-01", quantity: 1, unit_price: 0.0001 })]);
    const order = await buildPricedOrder(source, { ...base(), parts: [{ line_id: "tiny", part_no: "TINY", quantity: 1 }] }, opts);
    expect(order.lines[0]).toMatchObject({ unit_price: 0.0001, extended_price: 0, pricing_source: "historical_analog",
      proposal_status: "NUMERIC_PROVISIONAL" });
    expect(order.lines[0]!.analogs.map(analog => analog.quote_no)).toEqual(["SYNTHETIC-TINY"]);
    expect(order.state).toBe("BLOCKED");
    expect(order.total).toBeNull();
    expect(order.blockers.join(" ")).toContain("zero-cent");
  });

  it("uses only pre-cutoff register history, offline even with gateway credentials", async () => {
    const history = new QuoteRegister([
      row({ quote_no: "past", part_no: "MATCH", quote_date: "2020-01-01", quantity: 3, unit_price: 2.0001, status: "won" }),
      row({ quote_no: "future", part_no: "MATCH", quote_date: "2025-01-01", quantity: 3, unit_price: 500, status: "won" }),
    ]);
    const previousKey = process.env.AI_GATEWAY_API_KEY;
    process.env.AI_GATEWAY_API_KEY = "must-not-be-used";
    try {
      const order = await buildPricedOrder(history, { ...base(), parts: [{ line_id: "history", part_no: "MATCH", quantity: 3 }] }, opts);
      expect(order.lines[0]).toMatchObject({ pricing_source: "historical_analog", unit_price: 2.0001,
        extended_price: 6, confidence: expect.any(Number), proposal_status: "NUMERIC_PROVISIONAL",
        evidence_status: "HISTORICAL_INTERNAL_CALCULATION" });
      expect(order.lines[0]!.analogs.map((analog) => analog.quote_no)).toEqual(["past"]);
      expect(order.lines[0]!.pricing_reason).toContain("fallback:");
      expect(order.lines[0]!.warnings.join(" ")).toContain("nominal as-quoted dollars");
    } finally {
      if (previousKey === undefined) delete process.env.AI_GATEWAY_API_KEY;
      else process.env.AI_GATEWAY_API_KEY = previousKey;
    }
  });

  it("rejects malformed fields, precision, duplicate identities, and unsafe totals", async () => {
    const invalid: unknown[] = [
      { ...base(), order_id: " " }, { ...base(), quote_date: "2024-02-30" },
      { ...base(), parts: [{ ...base().parts[0], quantity: 1.5 }] },
      { ...base(), parts: [{ ...base().parts[0], quantity: Number.MAX_SAFE_INTEGER + 1 }] },
      { ...base(), parts: [{ ...base().parts[0], part_no: " ", description: "" }] },
      { ...base(), parts: [base().parts[0], base().parts[0]] },
      { ...base(), parts: [{ ...base().parts[0], pricing: { method: "guess", reason: "x" } }] },
      { ...base(), parts: [{ ...base().parts[0], pricing: { method: "unit_price", unit_price: 1.00001, reason: "x" } }] },
      { ...base(), parts: [{ ...base().parts[0], pricing: { method: "unit_price", unit_price: 0, reason: "x" } }] },
      { ...base(), parts: [{ ...base().parts[0], pricing: { method: "unit_price", unit_price: 1, reason: " " } }] },
      { ...base(), parts: [{ ...base().parts[0], pricing: { method: "cost_plus", material_per_unit: 1.00001,
        labor_per_unit: 0, outside_per_unit: 0, setup_total: 0, margin_pct: 20, reason: "x" } }] },
      { ...base(), parts: [{ ...base().parts[0], pricing: { method: "cost_plus", material_per_unit: 1,
        labor_per_unit: 0, outside_per_unit: 0, setup_total: 0, margin_pct: 100, reason: "x" } }] },
      { ...base(), charges: { shipping: -1, tax: 0 } },
      { ...base(), additional_charges: [{ label: "fee", amount: 0.001 }] },
      { ...base(), parts: [{ ...base().parts[0], quantity: Number.MAX_SAFE_INTEGER,
        pricing: { method: "unit_price", unit_price: 2, reason: "x" } }] },
    ];
    for (const request of invalid) await expect(buildPricedOrder(reg, request, opts)).rejects.toThrow();
    await expect(buildPricedOrder(reg, base(), { registerSha256: "bad" })).rejects.toThrow(/registerSha256/);
  });

  it("rejects cent outputs that lose precision even when their BigInt cents fit a safe integer", async () => {
    const price = { method: "unit_price", unit_price: 0.01, reason: "arithmetic boundary" };
    const huge = { ...base(), parts: [{ line_id: "huge", part_no: "P", quantity: Number.MAX_SAFE_INTEGER, pricing: price }] };
    await expect(buildPricedOrder(reg, huge, opts)).rejects.toThrow(/cannot be represented/);
    const combined = { ...base(), parts: [
      { line_id: "a", part_no: "P", quantity: 4503599627370495, pricing: price },
      { line_id: "b", part_no: "P", quantity: 4503599627370496, pricing: price },
    ] };
    await expect(buildPricedOrder(reg, combined, opts)).rejects.toThrow(/cannot be represented/);
    const costs = { ...base(), parts: [base().parts[0]], additional_charges: [
      { label: "fee 1", amount: 90071992547409 }, { label: "fee 2", amount: 0.91 },
    ] };
    await expect(buildPricedOrder(reg, costs, opts)).rejects.toThrow(/safe arithmetic range|cannot be represented/);
  });

  it("escapes customer-controlled Markdown and labels", async () => {
    const order = await buildPricedOrder(reg, { ...base(), customer: "<script>|*bad*", order_id: "# suspicious",
      parts: [{ ...base().parts[0], line_id: "a|b", part_no: "<img>" }],
      additional_charges: [{ label: "<b>|fee", amount: 1 }] }, opts);
    const markdown = renderOrderMarkdown(order);
    expect(markdown).not.toContain("<script>");
    expect(markdown).not.toContain("<img>");
    expect(markdown).toContain("a\\|b");
    expect(markdown).toContain("NUMERIC\\_PROVISIONAL");
    expect(markdown).toContain("OPERATOR\\_INPUT");
    expect(markdown).toContain("&lt;script&gt;");
  });
});

const estimatorRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const tmp = mkdtempSync(join(tmpdir(), "order-cli-test-"));
afterAll(() => rmSync(tmp, { recursive: true, force: true }));

describe("order CLI", () => {
  it("writes a complete artifact once, refuses overwrite, and exits 3 for a blocked artifact", () => {
    const request = join(tmp, "request.json");
    const register = join(tmp, "register.csv");
    const output = join(tmp, "new-order");
    writeFileSync(register, "quote_no,part_no,quote_date,quantity,unit_price\n");
    writeFileSync(request, JSON.stringify(base()));
    const run = (out: string, req = request) => spawnSync(process.execPath,
      [join(estimatorRoot, "node_modules/tsx/dist/cli.mjs"), join(estimatorRoot, "src/order-cli.ts"), req,
        "--register", register, "--out", out], { encoding: "utf8" });
    const first = run(output);
    expect(first.status, first.stderr).toBe(0);
    expect(JSON.parse(first.stdout)).toMatchObject({ state: "PRICED_REQUIRES_REVIEW", total: 1 });
    const artifact = JSON.parse(readFileSync(join(output, "order.json"), "utf8"));
    expect(artifact.provenance.register_sha256).toBe(createHash("sha256").update(readFileSync(register)).digest("hex"));
    expect(readFileSync(join(output, "order.md"), "utf8")).toContain("Priced order");
    expect(run(output).status).toBe(2);
    expect(readFileSync(join(output, "order.json"), "utf8")).toBe(JSON.stringify(artifact, null, 2) + "\n");

    const blocked = join(tmp, "blocked.json");
    writeFileSync(blocked, JSON.stringify({ ...base(), charges: { shipping: null, tax: 0 } }));
    const result = run(join(tmp, "blocked-output"), blocked);
    expect(result.status, result.stderr).toBe(3);
    expect(JSON.parse(readFileSync(join(tmp, "blocked-output", "order.json"), "utf8")).total).toBeNull();
    const bad = join(tmp, "invalid.json");
    writeFileSync(bad, JSON.stringify({ ...base(), order_id: "" }));
    const invalid = run(join(tmp, "no-output"), bad);
    expect(invalid.status).toBe(2);
    expect(invalid.stdout).toBe("");
    expect(() => readFileSync(join(tmp, "no-output", "order.json"))).toThrow();
  });

  it("prices fully supplied source and compiled CLI requests without a default historical register", () => {
    const request = join(estimatorRoot, "examples/order-request.json");
    const build = spawnSync(process.execPath, [join(estimatorRoot, "node_modules/typescript/bin/tsc")], {
      cwd: estimatorRoot, encoding: "utf8",
    });
    expect(build.status, build.stdout + build.stderr).toBe(0);
    for (const [name, command] of [
      ["source", [join(estimatorRoot, "node_modules/tsx/dist/cli.mjs"), join(estimatorRoot, "src/order-cli.ts")]],
      ["compiled", [join(estimatorRoot, "dist/src/order-cli.js")]],
    ] as const) {
      const output = join(tmp, `default-${name}`);
      const result = spawnSync(process.execPath, [...command, request, "--out", output], {
        cwd: tmp, encoding: "utf8",
      });
      expect(result.status, result.stderr).toBe(0);
      expect(JSON.parse(result.stdout)).toMatchObject({ state: "PRICED_REQUIRES_REVIEW", total: 285.96 });
      const order = JSON.parse(readFileSync(join(output, "order.json"), "utf8"));
      expect(order.provenance.register_sha256).toBeNull();
    }
  }, 30_000);
});
