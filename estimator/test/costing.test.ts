import { describe, expect, it } from "vitest";
import { deriveCostBasis, reconcileCostBasis, type CostBasis, type CostRange, type CostSource, type FlatCosts } from "../src/costing.js";
import { assertOrderRequest, buildPricedOrder, renderOrderMarkdown, type OrderRequest } from "../src/order.js";
import { QuoteRegister } from "../src/register.js";

// Entirely synthetic: hashes and locators assert fixture provenance, not real source authenticity.
const asOf = "2024-06-01";
const sha = "a".repeat(64);
const reg = new QuoteRegister([]);
const options = { registerSha256: sha };
const range = (base: number, low = base, high = base): CostRange => ({ low, base, high });
const source = (): CostSource => ({
  source_class: "operator_estimate", sha256: sha, locator: "synthetic-worksheet:row-1",
  source_date: "2020-01-01", captured_date: "2024-05-01", status: "approved_estimate",
  applicability: "assumed", basis: "Synthetic prospective assumptions to be checked before release",
  approval: { reviewer: "Synthetic reviewer", date: "2024-05-31", reason: "Approved estimate only, not release" },
});
const flat = (): FlatCosts => ({ material_per_unit: 1.25, labor_per_unit: 2.4, outside_per_unit: 2.5, setup_total: 60 });
function basis(): CostBasis {
  return {
    schema_version: 1, currency: "USD", order_charges: "excluded",
    components: [
      { id: "material", category: "material", allocation: "material_per_unit", rate_kind: "cost",
        original_unit: "sheet", quantity_unit: "finished_piece", quantity: 10,
        original_units_per_quantity_unit: 0.1, yield_fraction: 0.8, minimum_quantity: 0,
        unit_cost: range(10, 8, 12), minimum_charge: range(0), sources: [source()],
        assumptions: ["80% yield; fractional sheets allocated to this line; no supplier quantity minimum"],
        charge_inclusion: "Material only, no labor, freight, tax or order charges" },
      { id: "outside", category: "outside", allocation: "outside_per_unit", rate_kind: "cost",
        original_unit: "piece", quantity_unit: "finished_piece", quantity: 10,
        original_units_per_quantity_unit: 1, yield_fraction: 1, minimum_quantity: 0,
        unit_cost: range(2, 1, 3), minimum_charge: range(25), sources: [source()],
        assumptions: ["All shipped pieces treated, no outside scrap; one lot minimum inclusive of processing"],
        charge_inclusion: "Outside treatment including supplier setup; no separate setup or freight" },
    ],
    routing: [{ id: "operation", sources: [source()], assumptions: ["Two setups for two releases; process twelve pieces including two scrap pieces"],
      charge_inclusion: "Loaded labor and machine cost; do not add a second overhead charge; excludes freight and tax",
      setup_occurrences: 2, setup_time: { unit: "minutes", values: range(30, 20, 40) },
      run_time: { unit: "minutes_per_piece", values: range(2, 1, 3) }, process_quantity: 12,
      setup_rate: { rate_kind: "cost", unit: "USD/hour", values: range(60) },
      run_rate: { rate_kind: "cost", unit: "USD/hour", values: range(60) } }],
    not_applicable: [{ category: "other", reason: "No additional production scope in this synthetic estimate", sources: [source()] }],
    unresolved_assumptions: ["Confirm release count before customer approval"],
  };
}
function request(costBasis: CostBasis | undefined = basis(), costs = flat(), quantity = 10): OrderRequest {
  return {
    order_id: "SYNTHETIC-ORDER", customer: "Synthetic customer", quote_date: asOf,
    parts: [{ line_id: "1", description: "Synthetic part", quantity,
      pricing: { method: "cost_plus", ...costs, margin_pct: 20, reason: "Reviewed prospective worksheet", ...(costBasis ? { cost_basis: costBasis } : {}) } }],
    charges: { shipping: 7, tax: 0 }, additional_charges: [{ label: "Separate order charge", amount: 3 }],
  };
}

function reconcile(b = basis(), costs = flat(), quantity = 10) {
  return reconcileCostBasis(b, quantity, asOf, costs);
}

describe("prospective cost-basis worksheet", () => {
  it("builds a should-cost proposal without analogs or manually copied flat costs", async () => {
    const req = request();
    req.parts[0]!.pricing = { method: "should_cost", cost_basis: basis(), margin_pct: 20, reason: "Synthetic reviewed engineering estimate" };
    const unchanged = JSON.stringify(req);
    const order = await buildPricedOrder(reg, req, options);
    const baseline = await buildPricedOrder(reg, request(), options);
    expect(order.total).toEqual(baseline.total);
    expect(order.lines[0]!.analogs).toEqual([]);
    expect(order.lines[0]!.cost_breakdown!.reconciled_flat).toEqual(flat());
    expect(deriveCostBasis(basis(), 10, asOf).reconciled_flat).toEqual(flat());
    expect(order.state).toBe("PRICED_REQUIRES_REVIEW");
    expect(order.requires_human_review).toBe(true);
    expect(order.lines[0]!.warnings.join(" ")).toContain("not historical analog transfer");
    expect(JSON.stringify(req)).toBe(unchanged);
  });

  it("rejects mixed should-cost overrides, unsupported benchmark sources and missing scope", () => {
    const req = request();
    req.parts[0]!.pricing = { method: "should_cost", cost_basis: basis(), margin_pct: 20, reason: "Synthetic" };
    expect(() => assertOrderRequest({ ...req, parts: [{ ...req.parts[0], pricing: { ...req.parts[0]!.pricing, material_per_unit: 0.01 } }] })).toThrow(/invalid should_cost/);
    const b = basis();
    (b.components[0]!.sources[0] as unknown as { source_class: string }).source_class = "market_benchmark";
    expect(() => deriveCostBasis(b, 10, asOf)).toThrow(/source_class/);
    b.components = [];
    expect(() => deriveCostBasis(b, 10, asOf)).toThrow(/missing material/);
  });

  it.each([
    { cost: 0.00014, margin: 30, unit: 0.0002, total: 20, status: "met" },
    { cost: 0.00004, margin: 25, unit: 0.0001, total: 10, status: "met" },
    { cost: 0.01004, margin: 25, unit: 0.0134, total: 1340, status: "met" },
    { cost: 1.23454, margin: 75, unit: 4.9382, total: 493820, status: "met" },
    { cost: 0.00015, margin: 0, unit: 0.0002, total: 20, status: "met" },
    { cost: 0.00014, margin: 0, unit: 0.0001, total: 10, status: "below_target" },
    { cost: 1.000001, margin: 0, unit: 1, total: 100000, status: "below_target" },
    { cost: 0.800001, margin: 20, unit: 1, total: 100000, status: "below_target" },
  ])("prices exact worksheet cost $cost before margin and final unit rounding", async ({ cost, margin, unit, total, status }) => {
    const b = basis();
    b.components = [{ ...b.components[0]!, quantity: 100000, original_units_per_quantity_unit: 1,
      yield_fraction: 1, unit_cost: range(cost) }];
    b.routing = [];
    b.not_applicable = (["outside", "other", "routing"] as const).map(category => ({ category, reason: "Synthetic material-only scope", sources: [source()] }));
    const req = request(b, flat(), 100000);
    req.parts[0]!.pricing = { method: "should_cost", cost_basis: b, margin_pct: margin, reason: "Synthetic precision regression" };
    req.charges = { shipping: 0, tax: 0 }; req.additional_charges = [];
    const order = await buildPricedOrder(reg, req, { registerSha256: null });
    expect(order.lines[0]).toMatchObject({ unit_price: unit, extended_price: total });
    expect(order.total).toBe(total);
    expect(order.lines[0]!.cost_breakdown!.estimated_line_cost.base).toBeCloseTo(cost * 100000, 4);
    expect(order.lines[0]!.cost_breakdown!.estimated_line_margin_pct!.base)
      .toBeCloseTo((1 - cost * 100000 / total) * 100, 2);
    expect(order.lines[0]!.cost_breakdown!.base_margin_target).toEqual({ requested_pct: margin, status });
    expect(order.warnings.some(w => w.includes("below the requested"))).toBe(status === "below_target");
    expect(renderOrderMarkdown(order)).toContain(status.replaceAll("_", "\\_"));
    expect(order.state).toBe("PRICED_REQUIRES_REVIEW");
    expect(order.requires_human_review).toBe(true);
    expect(order.request).toEqual(req);
  });

  it("compares exact BASE cost rather than rounded cost or downside scenarios", () => {
    const b = basis();
    b.components = [{ ...b.components[0]!, quantity: 1, original_units_per_quantity_unit: 1,
      yield_fraction: 1, unit_cost: range(1.000001, 1, 2) }];
    b.routing = [];
    b.not_applicable = (["outside", "other", "routing"] as const).map(category => ({ category, reason: "Synthetic material-only scope", sources: [source()] }));
    const result = deriveCostBasis(b, 1, asOf, 1, 0);
    expect(result.estimated_line_cost.base).toBe(1);
    expect(result.estimated_line_margin_pct!.base).toBe(0);
    expect(result.base_margin_target).toEqual({ requested_pct: 0, status: "below_target" });
    b.components[0]!.unit_cost.base = 1;
    const exact = deriveCostBasis(b, 1, asOf, 1, 0);
    expect(exact.base_margin_target!.status).toBe("met");
    expect(exact.estimated_line_margin_pct!.low).toBe(-100);
    expect(deriveCostBasis(b, 1, asOf, 1).base_margin_target).toBeNull();
    expect(deriveCostBasis(b, 1, asOf, undefined, 0).base_margin_target!.status).toBe("not_assessable");
    for (const invalid of [-1, 100, NaN, Infinity]) expect(() => deriveCostBasis(b, 1, asOf, 1, invalid)).toThrow(/margin_pct/);
  });

  it("marks a zero displayed extension's target as not assessable without repricing", async () => {
    const b = basis();
    b.components = [{ ...b.components[0]!, quantity: 1, original_units_per_quantity_unit: 1,
      yield_fraction: 1, unit_cost: range(0.0001) }];
    b.routing = [];
    b.not_applicable = (["outside", "other", "routing"] as const).map(category => ({ category, reason: "Synthetic material-only scope", sources: [source()] }));
    const req = request(b, flat(), 1);
    req.parts[0]!.pricing = { method: "should_cost", cost_basis: b, margin_pct: 25, reason: "Synthetic sub-cent extension" };
    const order = await buildPricedOrder(reg, req, options);
    expect(order.lines[0]).toMatchObject({ unit_price: 0.0001, extended_price: 0,
      cost_breakdown: { estimated_line_margin_pct: null, base_margin_target: { requested_pct: 25, status: "not_assessable" } } });
    expect(order.warnings.join(" ")).toContain("cannot be assessed");
  });

  it("keeps exact routing fractions and sub-cent setup until should-cost sell rounding", async () => {
    const b = basis();
    b.components = [];
    b.not_applicable = (["material", "outside", "other"] as const).map(category => ({ category, reason: "Synthetic route-only scope", sources: [source()] }));
    Object.assign(b.routing[0]!, { setup_occurrences: 1, process_quantity: 3,
      setup_time: { unit: "minutes", values: range(1.005) },
      run_time: { unit: "pieces_per_hour", values: range(7) } });
    const req = request(b, flat(), 3);
    req.parts[0]!.pricing = { method: "should_cost", cost_basis: b, margin_pct: 25, reason: "Synthetic fractional timing" };
    const order = await buildPricedOrder(reg, req, options);
    // Exact cost = 201/200 + 180/7; dividing by 3 and 3/4 gives 12469/1050 USD/piece.
    expect(order.lines[0]).toMatchObject({ unit_price: 11.8752, extended_price: 35.63 });
    expect(order.lines[0]!.cost_breakdown!.reconciled_flat).toEqual({ material_per_unit: 0, outside_per_unit: 0, labor_per_unit: 8.5714, setup_total: 1.01 });
    req.parts[0]!.pricing = { method: "cost_plus", ...order.lines[0]!.cost_breakdown!.reconciled_flat,
      cost_basis: b, margin_pct: 25, reason: "Deliberately supplied rounded flat costs" };
    const explicit = await buildPricedOrder(reg, req, options);
    expect(explicit.lines[0]).toMatchObject({ unit_price: 11.8774, extended_price: 35.63 });
    expect(explicit.lines[0]!.cost_breakdown!.base_margin_target).toEqual({ requested_pct: 25, status: "met" });
  });

  it("rejects should-cost invalid margin, expired current support and absent worksheets", () => {
    const req = request();
    for (const margin_pct of [-1, 100, NaN, Infinity]) {
      req.parts[0]!.pricing = { method: "should_cost", cost_basis: basis(), margin_pct, reason: "Synthetic" };
      expect(() => assertOrderRequest(req)).toThrow(/margin_pct/);
    }
    const b = basis();
    b.components[0]!.sources[0] = { ...source(), status: "current", effective_date: "2023-01-01", expires_date: "2023-12-31", approval: undefined };
    expect(() => deriveCostBasis(b, 10, asOf)).toThrow(/expired/);
    expect(() => deriveCostBasis(undefined, 10, asOf)).toThrow(/plain object/);
  });

  it("uses repeated setup plus processed quantity, material yield/conversion and outside lot minimum", () => {
    const result = reconcile();
    expect(result.reconciled_flat).toEqual(flat());
    expect(result.components[0]).toMatchObject({ priced_quantity: 1.25, total_cost: range(12.5, 10, 15) });
    expect(result.components[1]).toMatchObject({ priced_quantity: 10, total_cost: range(25, 25, 30) });
    expect(result.routing[0]).toMatchObject({ setup_occurrences: 2, process_quantity: 12,
      setup_minutes: range(30, 20, 40), run_minutes_per_piece: range(2, 1, 3),
      setup_cost: range(60, 40, 80), run_cost: range(24, 12, 36) });
    expect(result.estimated_line_cost).toEqual(range(121.5, 87, 161));
    expect(result.estimated_line_margin_pct).toBeNull();
  });

  it("allocates shared setup once rather than multiplying by finished pieces or deliveries implicitly", () => {
    const b = basis();
    b.routing[0]!.setup_occurrences = 1;
    b.routing[0]!.assumptions = ["One shared setup across both releases, explicitly approved as an estimate"];
    expect(reconcile(b, { ...flat(), setup_total: 30 }).routing[0]!.setup_cost).toEqual(range(30, 20, 40));
    expect(() => reconcile(b)).toThrow(/does not reconcile setup_total/);
  });

  it("spreads setup over the finished quantity but costs scrap at process quantity", async () => {
    const b = basis();
    b.components[0]!.quantity = 20;
    b.components[1]!.quantity = 20;
    b.routing[0]!.process_quantity = 24;
    const costs = { ...flat(), outside_per_unit: 2 };
    const order = await buildPricedOrder(reg, request(b, costs, 20), options);
    expect(order.lines[0]).toMatchObject({ unit_price: 10.8125, extended_price: 216.25 });
    expect(order.lines[0]!.cost_breakdown!.routing[0]).toMatchObject({ setup_cost: range(60, 40, 80), run_cost: range(48, 24, 72) });
    const noScrap = basis();
    noScrap.routing[0]!.process_quantity = 10;
    expect(reconcile(noScrap, { ...flat(), labor_per_unit: 2 }).routing[0]!.run_cost.base).toBe(20);
  });

  it("converts hours and parts/hour without reversing low/high runtime bounds", () => {
    const b = basis();
    b.routing[0]!.setup_time = { unit: "hours", values: range(0.5, 0.25, 1) };
    b.routing[0]!.run_time = { unit: "pieces_per_hour", values: range(30, 20, 60) };
    const result = reconcile(b);
    expect(result.routing[0]!.setup_minutes).toEqual(range(30, 15, 60));
    expect(result.routing[0]!.run_minutes_per_piece).toEqual(range(2, 1, 3));
    b.routing[0]!.run_time = { unit: "seconds_per_piece", values: range(120, 60, 180) };
    expect(reconcile(b).routing[0]!.run_cost).toEqual(range(24, 12, 36));
  });

  it("applies supplier minimum quantity in the original priced unit before minimum charge", () => {
    const b = basis();
    b.components[0]!.minimum_quantity = 2;
    const result = reconcile(b, { ...flat(), material_per_unit: 2 });
    expect(result.components[0]).toMatchObject({ priced_quantity: 2, total_cost: range(20, 16, 24) });
  });

  it("rounds purchased stock upward after yield and preserves the supplied unit and assumption", () => {
    const b = basis();
    b.components[0]!.purchase_increment = 1;
    b.components[0]!.assumptions.push("Purchase whole sheets; charge this line for the remainder, no inventory credit");
    const unchanged = JSON.stringify(b);
    const result = reconcile(b, { ...flat(), material_per_unit: 2 });
    expect(result.components[0]).toMatchObject({ priced_quantity: 2, total_cost: range(20, 16, 24),
      purchase_rounding: { original_unit: "sheet", quantity_before_increment: 1.25, increment: 1 } });
    expect(result.supplied_basis).toEqual(b);
    expect(JSON.stringify(b)).toBe(unchanged);
    expect(reconcile().components[0]).toMatchObject({ priced_quantity: 1.25, total_cost: range(12.5, 10, 15) });
    expect(reconcile().components[0]).not.toHaveProperty("purchase_rounding");
    expect(() => reconcile(b)).toThrow(/reconcile material_per_unit/);
  });

  it("applies minimum quantity before pack multiples and minimum money after them", () => {
    const b = basis();
    Object.assign(b.components[0]!, { minimum_quantity: 5, purchase_increment: 4, minimum_charge: range(75) });
    const result = reconcile(b, { ...flat(), material_per_unit: 8 });
    expect(result.components[0]).toMatchObject({ priced_quantity: 8, total_cost: range(80, 75, 96),
      purchase_rounding: { quantity_before_increment: 5, increment: 4 } });
  });

  it.each([
    [0.3, 1, 1, 0.1, 0.3],
    [0.07, 1, 1, 0.01, 0.07],
    [0.300001, 1, 1, 0.1, 0.4],
    [1, 1, 0.3, 0.1, 3.4],
    [0.3, 0.1, 1, 0.01, 0.03],
    [0.000001, 1, 1, 0.000001, 0.000001],
  ])("uses exact decimal multiples for quantity %s, conversion %s, yield %s, increment %s", (quantity, conversion, yieldFraction, increment, expected) => {
    const b = basis();
    Object.assign(b.components[0]!, { quantity, original_units_per_quantity_unit: conversion,
      yield_fraction: yieldFraction, purchase_increment: increment });
    expect(deriveCostBasis(b, 10, asOf).components[0]!.priced_quantity).toBe(expected);
  });

  it.each([0, -1, null, false, "1", NaN, Infinity, 1e9 + 1, 0.0000001])("rejects invalid purchase increment %s", increment => {
    const b = basis();
    (b.components[0] as unknown as Record<string, unknown>).purchase_increment = increment;
    expect(() => deriveCostBasis(b, 10, asOf)).toThrow(/purchase_increment/);
  });

  it("supports explicitly purchased outside-processing batches without rounding setup or route quantities", () => {
    const b = basis();
    b.components[1]!.purchase_increment = 6;
    const result = reconcile(b);
    expect(result.components[1]).toMatchObject({ priced_quantity: 12, total_cost: range(25, 25, 36),
      purchase_rounding: { original_unit: "piece", quantity_before_increment: 10, increment: 6 } });
    expect(result.routing).toEqual(reconcile().routing);
  });

  it("prices should-cost from rounded purchases and keeps margin and customer review honest", async () => {
    const b = basis();
    b.components[0]!.purchase_increment = 1;
    const req = request(b);
    req.parts[0]!.pricing = { method: "should_cost", cost_basis: b, margin_pct: 20, reason: "Reviewed whole-sheet purchase" };
    const order = await buildPricedOrder(reg, req, options);
    expect(order.lines[0]).toMatchObject({ unit_price: 16.125, extended_price: 161.25 });
    expect(order.lines[0]!.cost_breakdown).toMatchObject({
      assertion_status: "supplied_not_authenticated", estimated_line_cost: range(129, 93, 170),
      estimated_line_margin_pct: { low: -5.43, base: 20, high: 42.33 } });
    expect(order.state).toBe("PRICED_REQUIRES_REVIEW");
    expect(order.requires_human_review).toBe(true);
    expect(order.total).toBe(171.25);
  });

  it("allocates explicit other production costs without a new hidden flat component", () => {
    const b = basis();
    b.components.push({ ...b.components[1]!, id: "tooling", category: "other", allocation: "setup_total",
      quantity: 1, minimum_charge: range(0), unit_cost: range(5),
      charge_inclusion: "Single production tool, not included in any routing rate or order charge" });
    b.not_applicable = [];
    expect(reconcile(b, { ...flat(), setup_total: 65 }).estimated_line_cost).toEqual(range(126.5, 92, 166));
  });

  it("reconciles exact rational inputs at the existing half-up 4dp-unit/2dp-setup boundaries", () => {
    const b = basis();
    b.components = [];
    b.not_applicable = (["material", "outside", "other"] as const).map(category => ({ category, reason: "Synthetic routing-only scope", sources: [source()] }));
    b.routing[0]!.setup_occurrences = 1;
    b.routing[0]!.setup_time.values = range(1.005);
    b.routing[0]!.run_time.values = range(0.00105);
    b.routing[0]!.process_quantity = 3;
    const costs = { material_per_unit: 0, outside_per_unit: 0, labor_per_unit: 0.0011, setup_total: 1.01 };
    expect(reconcile(b, costs, 3)).toMatchObject({ reconciled_flat: costs, estimated_line_cost: range(1.0082) });
    expect(() => reconcile(b, { ...costs, setup_total: 1 }, 3)).toThrow(/reconcile setup_total/);
    expect(() => reconcile(b, { ...costs, labor_per_unit: 0.00105 }, 3)).toThrow(/reconcile labor_per_unit/);
  });

  it("does not require payment, accepted-order or actual-job evidence for an approved prospective estimate", async () => {
    const b = basis();
    b.components[0]!.sources[0]!.expires_date = "2020-02-01";
    b.components[0]!.sources[0]!.effective_date = "2020-01-01";
    const order = await buildPricedOrder(reg, request(b), options);
    expect(order.state).toBe("PRICED_REQUIRES_REVIEW");
    expect(order.requires_human_review).toBe(true);
    const line = order.lines[0]!;
    expect(line).toMatchObject({ unit_price: 15.1875, extended_price: 151.88,
      proposal_status: "NUMERIC_PROVISIONAL", evidence_status: "OPERATOR_INPUT" });
    expect(line.cost_breakdown!.supplied_basis).toEqual(b);
    expect(line.cost_breakdown!.assertion_status).toBe("supplied_not_authenticated");
    expect(line.cost_breakdown!.estimated_line_margin_pct).toEqual({ low: -6, base: 20, high: 42.72 });
    expect(line.uncertainties).toContain(b.unresolved_assumptions[0]);
    expect(line.warnings.join(" ")).toContain("not authenticated evidence");
    expect(order.total).toBe(161.88); // Shipping 7 and order charge 3, exactly once, not cost totals again.
    expect(order).not.toHaveProperty("estimated_margin_pct");
    const markdown = renderOrderMarkdown(order);
    expect(markdown).toContain("Prospective cost worksheet");
    expect(markdown).toContain("not guaranteed");
    expect(markdown).toContain("no whole-order margin claim");
  });

  it("keeps freight-cost absence explicit even when a shipping sell charge exists or is missing", async () => {
    const req = request();
    req.charges!.shipping = null;
    const order = await buildPricedOrder(reg, req, options);
    expect(order.total).toBeNull();
    expect(order.blockers).toContain("shipping is missing");
    expect(order.lines[0]!.cost_breakdown!.scope).toBe("production_line_excluding_freight_tax_and_order_charges");
    expect(order.lines[0]!.warnings.join(" ")).toContain("no whole-order margin is claimed");
  });

  it("supports historical status without pretending the archive is a current offer", () => {
    const b = basis();
    b.components[0]!.sources = [{ ...source(), status: "historical", approval: undefined,
      effective_date: "2020-01-01", expires_date: "2020-01-31" }];
    expect(reconcile(b).supplied_basis.components[0]!.sources[0]!.status).toBe("historical");
  });

  it.each(["components", "routing", "not_applicable"] as const)("rejects an estimate approval that predates its source in %s", group => {
    const b = basis();
    const s = b[group][0]!.sources[0]!;
    s.source_date = "2024-05-31";
    s.approval!.date = "2024-05-30";
    expect(() => deriveCostBasis(b, 10, asOf)).toThrow(/approval.date is before source_date/);
    expect(() => reconcile(b)).toThrow(/approval.date is before source_date/);
    const req = request(b);
    expect(() => assertOrderRequest(req)).toThrow(/approval.date is before source_date/);
    req.parts[0]!.pricing = { method: "should_cost", cost_basis: b, margin_pct: 20, reason: "Synthetic chronology check" };
    expect(() => assertOrderRequest(req)).toThrow(/approval.date is before source_date/);
  });

  it.each(["2024-05-31", asOf])("allows review on or after the source date, through quote date: %s", approvalDate => {
    const b = basis();
    for (const support of [...b.components, ...b.routing, ...b.not_applicable]) {
      for (const s of support.sources) {
        s.source_date = "2024-05-31";
        s.approval!.date = approvalDate;
      }
    }
    expect(reconcile(b).reconciled_flat).toEqual(flat());
    expect(deriveCostBasis(b, 10, asOf).reconciled_flat).toEqual(flat());
  });

  it("allows a reviewed historical estimate after expiry without reclassifying it as current", () => {
    const b = basis();
    const s = b.components[0]!.sources[0]!;
    Object.assign(s, { source_class: "supplier_quote", source_date: "2020-01-01", effective_date: "2020-01-01",
      expires_date: "2020-01-31", captured_date: "2026-10-09" });
    s.approval!.reason = "Synthetic approval of a historical estimating basis, not an executable current offer";
    const result = reconcile(b);
    expect(result.reconciled_flat).toEqual(flat());
    expect(result.supplied_basis.components[0]!.sources[0]).toEqual(s);
    expect(result.warnings.join(" ")).toContain("not guaranteed actual costs or current buy prices");
  });

  it("accepts a current assertion only inside its commercial date window", () => {
    const b = basis();
    b.components[0]!.sources = [{ ...source(), source_class: "supplier_quote", status: "current", approval: undefined,
      source_date: "2024-05-01", effective_date: "2024-05-01", expires_date: asOf }];
    expect(reconcile(b).reconciled_flat).toEqual(flat());
    b.components[0]!.sources[0]!.expires_date = "2024-05-31";
    b.components[0]!.sources[0]!.captured_date = asOf;
    expect(() => reconcile(b)).toThrow(/current claim.*expired/);
  });

  it("allows an explicit sourced zero for an included operation, but never defaults blank values to zero", () => {
    const b = basis();
    b.routing[0]!.setup_occurrences = 0;
    expect(() => reconcile(b, { ...flat(), setup_total: 0 })).toThrow(/zero_reason/);
    b.routing[0]!.zero_reason = "Setup already included in the outside lot charge, per supplied estimate";
    expect(reconcile(b, { ...flat(), setup_total: 0 }).routing[0]!.setup_cost).toEqual(range(0));
  });

  const invalid: [string, (b: CostBasis) => void, RegExp][] = [
    ["setup SELL rate", b => { b.routing[0]!.setup_rate.rate_kind = "sell"; }, /SELL rates/],
    ["run SELL rate", b => { b.routing[0]!.run_rate.rate_kind = "sell"; }, /SELL rates/],
    ["component SELL price", b => { b.components[0]!.rate_kind = "sell"; }, /SELL rates/],
    ["missing cost", b => { Reflect.deleteProperty(b.components[0]!, "unit_cost"); }, /unit_cost/],
    ["missing setup rate", b => { Reflect.deleteProperty(b.routing[0]!, "setup_rate"); }, /setup_rate/],
    ["missing range value", b => { Reflect.deleteProperty(b.routing[0]!.run_rate.values, "low"); }, /low/],
    ["nonfinite cost", b => { b.components[0]!.unit_cost.high = Infinity; }, /finite/],
    ["NaN cost", b => { b.routing[0]!.run_rate.values.base = NaN; }, /finite/],
    ["negative cost", b => { b.components[0]!.unit_cost.low = -1; }, /nonnegative/],
    ["unordered cost range", b => { b.components[0]!.unit_cost.low = 11; }, /low <= base <= high/],
    ["unordered time range", b => { b.routing[0]!.setup_time.values.high = 1; }, /low <= base <= high/],
    ["zero yield", b => { b.components[0]!.yield_fraction = 0; }, /positive/],
    ["yield over one", b => { b.components[0]!.yield_fraction = 1.1; }, /must be <= 1/],
    ["zero conversion", b => { b.components[0]!.original_units_per_quantity_unit = 0; }, /positive/],
    ["unsupported precision", b => { b.components[0]!.unit_cost.base = 10.0000001; }, /six decimal places/],
    ["negative setup count", b => { b.routing[0]!.setup_occurrences = -1; }, /integer/],
    ["fractional setup count", b => { b.routing[0]!.setup_occurrences = 1.5; }, /integer/],
    ["unreasonable setup count", b => { b.routing[0]!.setup_occurrences = 10001; }, /integer/],
    ["unreasonable process quantity", b => { b.routing[0]!.process_quantity = 10000001; }, /integer/],
    ["zero parts/hour divisor", b => { b.routing[0]!.run_time = { unit: "pieces_per_hour", values: range(0) }; }, /divisor/],
    ["unknown is not zero", b => { b.not_applicable = []; }, /missing other/],
    ["conflicting scope", b => { b.components[0]!.sources[0]!.applicability = "conflict"; }, /applicability/],
    ["absent provenance", b => { b.components[0]!.sources = []; }, /1\.\.8/],
    ["invalid hash", b => { b.components[0]!.sources[0]!.sha256 = "not-a-hash"; }, /hex digest/],
    ["missing estimate approval", b => { Reflect.deleteProperty(b.components[0]!.sources[0]!, "approval"); }, /approval/],
    ["future estimate approval", b => { b.components[0]!.sources[0]!.approval!.date = "2024-06-02"; }, /approval.date is after quote_date/],
    ["future source", b => { b.components[0]!.sources[0]!.source_date = "2024-06-02"; }, /after quote_date/],
    ["invalid date", b => { b.components[0]!.sources[0]!.source_date = "2024-02-30"; }, /valid YYYY/],
    ["no expiry for current claim", b => { b.components[0]!.sources = [{ ...source(), status: "current", approval: undefined, effective_date: "2024-01-01" }]; }, /expires_date/],
    ["future current window", b => { b.components[0]!.sources = [{ ...source(), status: "current", approval: undefined, effective_date: "2025-01-01", expires_date: "2025-02-01" }]; }, /not effective/],
    ["duplicate component/route identity", b => { b.routing[0]!.id = b.components[0]!.id; }, /duplicate/],
    ["contradictory not-applicable", b => { b.not_applicable.push({ category: "material", reason: "Contradicts material entry", sources: [source()] }); }, /contradicts/],
    ["oversized components", b => { b.components = Array.from({ length: 65 }, () => ({ ...b.components[0]! })); }, /0\.\.64/],
    ["oversized source list", b => { b.components[0]!.sources = Array.from({ length: 9 }, source); }, /1\.\.8/],
    ["overlong assertion", b => { b.components[0]!.charge_inclusion = "x".repeat(2049); }, /2048/],
  ];
  it.each(invalid)("rejects %s", (_name, mutate, message) => {
    const b = basis();
    mutate(b);
    expect(() => reconcile(b)).toThrow(message);
    expect(() => assertOrderRequest(request(b))).toThrow();
  });

  it("rejects extra/nested arbitrary input and cannot silently include order freight", () => {
    const b = basis();
    expect(() => reconcileCostBasis({ ...b, order_charges: "included" }, 10, asOf, flat())).toThrow(/excluded/);
    expect(() => reconcileCostBasis({ ...b, shipping: 7 }, 10, asOf, flat())).toThrow(/not supported/);
    expect(() => reconcileCostBasis({ ...b, components: [{ ...b.components[0], nested: { nested: b } }] }, 10, asOf, flat())).toThrow(/not supported/);
    const circular = basis();
    Reflect.set(circular.components[0]!, "unit_cost", circular);
    expect(() => reconcile(circular)).toThrow(/not supported/);
    expect(() => reconcile(b, flat(), 10000001)).toThrow(/line_quantity/);
  });

  it("rejects flat disagreement rather than replacing the operator price inputs", async () => {
    for (const key of ["material_per_unit", "labor_per_unit", "outside_per_unit", "setup_total"] as const) {
      const costs = flat();
      costs[key] += 1;
      await expect(buildPricedOrder(reg, request(basis(), costs), options)).rejects.toThrow(new RegExp(`reconcile ${key}`));
    }
  });

  it("preserves existing bare cost_plus and unit_price requests with no new output fields", async () => {
    const req = request();
    if (req.parts[0]!.pricing!.method === "cost_plus") delete req.parts[0]!.pricing!.cost_basis;
    const flatOrder = await buildPricedOrder(reg, req, options);
    expect(flatOrder.lines[0]).toMatchObject({ unit_price: 15.1875, extended_price: 151.88 });
    expect(flatOrder.lines[0]).not.toHaveProperty("cost_breakdown");
    req.parts[0]!.pricing = { method: "unit_price", unit_price: 1.005, reason: "Synthetic explicit proposal" };
    req.parts[0]!.quantity = 2;
    const unitOrder = await buildPricedOrder(reg, req, options);
    expect(unitOrder.lines[0]).toMatchObject({ unit_price: 1.005, extended_price: 2.01 });
    expect(unitOrder.lines[0]).not.toHaveProperty("cost_breakdown");
    Reflect.set(req.parts[0]!.pricing, "cost_basis", basis());
    expect(() => assertOrderRequest(req)).toThrow(/invalid unit_price fields/);
  });

  it("escapes supplied worksheet prose in Markdown", async () => {
    const b = basis();
    b.routing[0]!.id = "<script>|operation";
    b.components[0]!.sources[0]!.locator = "<script>|source";
    const md = renderOrderMarkdown(await buildPricedOrder(reg, request(b), options));
    expect(md).not.toContain("<script>");
    expect(md).toContain("&lt;script&gt;");
  });
});
