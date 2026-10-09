/** A bounded prospective worksheet, not a source authenticator or actual-job ledger. */
export interface CostRange { low: number; base: number; high: number }
export interface CostSource {
  source_class: "supplier_quote" | "supplier_po" | "cost_record" | "routing_estimate" | "operator_estimate";
  sha256: string;
  locator: string;
  source_date: string;
  captured_date?: string;
  status: "historical" | "current" | "approved_estimate";
  effective_date?: string;
  expires_date?: string;
  applicability: "supported" | "assumed" | "conflict";
  basis: string;
  approval?: { reviewer: string; date: string; reason: string };
}

interface SupportedCost {
  id: string;
  sources: CostSource[];
  assumptions: string[];
  engineering_fact_ids?: string[];
  /** Describe labor/machine/overhead, minimums and other inclusions; never add them twice. */
  charge_inclusion: string;
  zero_reason?: string;
}

type Allocation = "material_per_unit" | "outside_per_unit" | "setup_total";
type Category = "material" | "outside" | "other" | "routing";
export interface CostComponent extends SupportedCost {
  category: Exclude<Category, "routing">;
  allocation: Allocation;
  rate_kind: "cost" | "sell";
  original_unit: string;
  quantity_unit: string;
  quantity: number;
  /** Supply exactly one conversion form, BEFORE yield; never round a recurring ratio. */
  original_units_per_quantity_unit?: number;
  conversion_ratio?: { original_units: number; quantity_units: number };
  yield_fraction: number;
  minimum_quantity: number;
  /** Purchase a multiple of this many original priced units, after yield and minimum quantity. */
  purchase_increment?: number;
  unit_cost: CostRange;
  minimum_charge: CostRange;
}

export interface CostRate { rate_kind: "cost" | "sell"; unit: "USD/hour"; values: CostRange }
export interface CostRouting extends SupportedCost {
  setup_occurrences: number;
  setup_time: { unit: "minutes" | "hours"; values: CostRange };
  run_time: { unit: "minutes_per_piece" | "seconds_per_piece" | "pieces_per_hour"; values: CostRange };
  process_quantity: number;
  setup_rate: CostRate;
  run_rate: CostRate;
}

export interface CostBasis {
  schema_version: 1;
  currency: "USD";
  /** All worksheet entries exclude freight, tax and separately charged order items. */
  order_charges: "excluded";
  components: CostComponent[];
  routing: CostRouting[];
  /** An absent category is not zero without an explicit, sourced disposition. */
  not_applicable: { category: Category; reason: string; sources: CostSource[] }[];
  unresolved_assumptions: string[];
}

export interface FlatCosts {
  material_per_unit: number;
  labor_per_unit: number;
  outside_per_unit: number;
  setup_total: number;
}

export interface CostBreakdown {
  assertion_status: "supplied_not_authenticated";
  scope: "production_line_excluding_freight_tax_and_order_charges";
  rounding: "half_up_flat_unit_4dp_setup_2dp_cost_report_4dp_margin_2dp";
  supplied_basis: CostBasis;
  reconciled_flat: FlatCosts;
  components: { id: string; category: CostComponent["category"]; allocation: Allocation;
    priced_quantity: number; total_cost: CostRange;
    purchase_rounding?: { original_unit: string; quantity_before_increment: number; increment: number } }[];
  routing: { id: string; setup_occurrences: number; setup_minutes: CostRange;
    run_minutes_per_piece: CostRange; process_quantity: number; setup_cost: CostRange; run_cost: CostRange }[];
  estimated_line_cost: CostRange;
  /** Low margin uses HIGH cost, and vice versa, against displayed line revenue. */
  estimated_line_margin_pct: CostRange | null;
  warnings: string[];
}

// Decimal inputs are bounded to six places. Rational arithmetic avoids binary drift,
// including hour conversions and minimum/yield allocation. No source formulas execute.
interface Fraction { n: bigint; d: bigint }
type Range = { [K in keyof CostRange]: Fraction };
const keys = ["low", "base", "high"] as const;
const flatKeys = ["material_per_unit", "labor_per_unit", "outside_per_unit", "setup_total"] as const;
const zero: Fraction = { n: 0n, d: 1n };
const whole = (n: number): Fraction => ({ n: BigInt(n), d: 1n });
function fraction(n: bigint, d: bigint): Fraction {
  let a = n < 0n ? -n : n;
  let b = d;
  while (b) [a, b] = [b, a % b];
  return { n: n / a, d: d / a };
}
const add = (a: Fraction, b: Fraction) => fraction(a.n * b.d + b.n * a.d, a.d * b.d);
const mul = (a: Fraction, b: Fraction) => fraction(a.n * b.n, a.d * b.d);
function div(a: Fraction, b: Fraction): Fraction {
  if (b.n <= 0n) throw new Error("cost_basis has a zero or negative divisor");
  return fraction(a.n * b.d, a.d * b.n);
}
const compare = (a: Fraction, b: Fraction) => a.n * b.d - b.n * a.d;
const max = (a: Fraction, b: Fraction) => compare(a, b) >= 0n ? a : b;
const mapRange = (a: Range, fn: (v: Fraction, key: keyof CostRange) => Fraction): Range => ({
  low: fn(a.low, "low"), base: fn(a.base, "base"), high: fn(a.high, "high"),
});
const sumRange = (a: Range, b: Range) => mapRange(a, (v, k) => add(v, b[k]));
const zeroRange = (): Range => ({ low: zero, base: zero, high: zero });

function record(value: unknown, path: string, allowed: readonly string[]): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value) ||
    ![Object.prototype, null].includes(Object.getPrototypeOf(value))) throw new Error(`${path} must be a plain object`);
  const obj = value as Record<string, unknown>;
  for (const key of Object.keys(obj)) if (!allowed.includes(key)) throw new Error(`${path}.${key} is not supported`);
  return obj;
}
function text(value: unknown, path: string): asserts value is string {
  if (typeof value !== "string" || !value.trim() || value.length > 2048) throw new Error(`${path} must be nonblank text (max 2048 characters)`);
}
function list(value: unknown, path: string, maximum: number, minimum = 0): unknown[] {
  if (!Array.isArray(value) || value.length < minimum || value.length > maximum) throw new Error(`${path} must contain ${minimum}..${maximum} entries`);
  return value;
}
function choice(value: unknown, path: string, allowed: readonly string[]): void {
  if (typeof value !== "string" || !allowed.includes(value)) throw new Error(`${path} must be one of ${allowed.join(", ")}`);
}
function date(value: unknown, path: string): asserts value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
    Number.isNaN(Date.parse(`${value}T00:00:00Z`)) || new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) !== value) {
    throw new Error(`${path} must be a valid YYYY-MM-DD date`);
  }
}
function decimal(value: number): Fraction {
  const m = /^(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i.exec(value.toString())!;
  const exponent = Number(m[3] ?? 0) - (m[2]?.length ?? 0);
  const digits = BigInt(m[1]! + (m[2] ?? ""));
  return exponent >= 0 ? fraction(digits * 10n ** BigInt(exponent), 1n) : fraction(digits, 10n ** BigInt(-exponent));
}
function number(value: unknown, path: string, positive = false): Fraction {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1e9 || (positive && value === 0)) {
    throw new Error(`${path} must be a ${positive ? "positive" : "nonnegative"} finite number <= 1e9`);
  }
  const f = decimal(value);
  if (f.n * 1_000_000n % f.d) throw new Error(`${path} supports at most six decimal places`);
  return f;
}
function count(value: unknown, path: string, maximum: number, minimum = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${path} must be an integer in ${minimum}..${maximum}`);
  }
  return value;
}
function range(value: unknown, path: string): Range {
  const r = record(value, path, keys);
  const result = { low: number(r.low, `${path}.low`), base: number(r.base, `${path}.base`), high: number(r.high, `${path}.high`) };
  if (compare(result.low, result.base) > 0n || compare(result.base, result.high) > 0n) throw new Error(`${path} must satisfy low <= base <= high`);
  return result;
}
function rounded(value: Fraction, places: number): bigint {
  const sign = value.n < 0n ? -1n : 1n;
  const n = value.n * sign * 10n ** BigInt(places);
  return sign * ((2n * n + value.d) / (2n * value.d));
}
function display(value: Fraction, places: number, path: string): number {
  const units = rounded(value, places);
  if (units > BigInt(Number.MAX_SAFE_INTEGER) || units < -BigInt(Number.MAX_SAFE_INTEGER)) throw new Error(`${path} exceeds safe arithmetic range`);
  const result = Number(units) / 10 ** places;
  const check = decimal(Math.abs(result));
  if (check.n * 10n ** BigInt(places) !== (units < 0n ? -units : units) * check.d) throw new Error(`${path} cannot represent output precision`);
  return result;
}
const displayRange = (r: Range, places: number, path: string): CostRange => ({
  low: display(r.low, places, path), base: display(r.base, places, path), high: display(r.high, places, path),
});

function sources(value: unknown, path: string, asOf: string): void {
  for (const [i, item] of list(value, path, 8, 1).entries()) {
    const p = `${path}[${i}]`;
    const s = record(item, p, ["source_class", "sha256", "locator", "source_date", "captured_date", "status", "effective_date", "expires_date", "applicability", "basis", "approval"]);
    choice(s.source_class, `${p}.source_class`, ["supplier_quote", "supplier_po", "cost_record", "routing_estimate", "operator_estimate"]);
    if (typeof s.sha256 !== "string" || !/^[a-f\d]{64}$/i.test(s.sha256)) throw new Error(`${p}.sha256 must be a 64-character hex digest (supplied assertion only)`);
    text(s.locator, `${p}.locator`);
    text(s.basis, `${p}.basis`);
    choice(s.applicability, `${p}.applicability`, ["supported", "assumed"]);
    choice(s.status, `${p}.status`, ["historical", "current", "approved_estimate"]);
    date(s.source_date, `${p}.source_date`);
    if (s.source_date > asOf) throw new Error(`${p}.source_date is after quote_date`);
    for (const key of ["captured_date", "effective_date", "expires_date"] as const) if (s[key] !== undefined) date(s[key], `${p}.${key}`);
    if (typeof s.effective_date === "string" && typeof s.expires_date === "string" && s.effective_date > s.expires_date) throw new Error(`${p} has reversed effective dates`);
    if (s.status === "current") {
      date(s.effective_date, `${p}.effective_date`);
      date(s.expires_date, `${p}.expires_date`);
      if (s.effective_date > asOf || s.expires_date < asOf) throw new Error(`${p} current claim is not effective on quote_date (expired or future)`);
    }
    if (s.status === "approved_estimate") {
      const approval = record(s.approval, `${p}.approval`, ["reviewer", "date", "reason"]);
      text(approval.reviewer, `${p}.approval.reviewer`);
      text(approval.reason, `${p}.approval.reason`);
      date(approval.date, `${p}.approval.date`);
      if (approval.date < s.source_date) throw new Error(`${p}.approval.date is before source_date`);
      if (approval.date > asOf) throw new Error(`${p}.approval.date is after quote_date`);
    } else if (s.approval !== undefined) throw new Error(`${p}.approval requires approved_estimate status`);
  }
}

const supportKeys = ["id", "sources", "assumptions", "charge_inclusion", "zero_reason", "engineering_fact_ids"];
function support(obj: Record<string, unknown>, path: string, asOf: string, ids: Set<string>): void {
  text(obj.id, `${path}.id`);
  if (ids.has(obj.id)) throw new Error(`${path} has a duplicate component/operation id`);
  ids.add(obj.id);
  sources(obj.sources, `${path}.sources`, asOf);
  for (const v of list(obj.assumptions, `${path}.assumptions`, 16, 1)) text(v, `${path}.assumptions`);
  if (obj.engineering_fact_ids !== undefined) {
    const ids = list(obj.engineering_fact_ids, `${path}.engineering_fact_ids`, 32, 1);
    for (const id of ids) text(id, `${path}.engineering_fact_ids`);
    if (new Set(ids).size !== ids.length) throw new Error(`${path}.engineering_fact_ids must be unique`);
  }
  text(obj.charge_inclusion, `${path}.charge_inclusion`);
  if (obj.zero_reason !== undefined) text(obj.zero_reason, `${path}.zero_reason`);
}
function justifyZero(obj: Record<string, unknown>, path: string, hasZero: boolean): void {
  if (hasZero) text(obj.zero_reason, `${path}.zero_reason (explicit zero requires support)`);
}
function costKind(value: unknown, path: string): void {
  if (value !== "cost") throw new Error(`${path} must be cost; SELL rates cannot enter cost_plus (double margin)`);
}

/**
 * Validate and reconcile BASE worksheet amounts to supplied flat inputs. The order's
 * existing bigint gross-margin math remains authoritative for the sell price.
 * Component total = max(priced_quantity * unit_cost, minimum_charge); priced_quantity applies
 * yield, minimum quantity, then an optional original-unit purchase increment rounded upward.
 * Route total = occurrences * setup_minutes / 60 * setup_rate + process_quantity * run_minutes_per_piece / 60 * run_rate.
 * All ranges are scenario bounds, not probabilities or guarantees. No files are opened.
 */
export function reconcileCostBasis(value: unknown, quantity: number, asOf: string, flat: FlatCosts, lineRevenue?: number): CostBreakdown {
  return calculateCostBasis(value, quantity, asOf, flat, lineRevenue);
}

export function deriveCostBasis(value: unknown, quantity: number, asOf: string, lineRevenue?: number): CostBreakdown {
  return calculateCostBasis(value, quantity, asOf, undefined, lineRevenue);
}

function calculateCostBasis(value: unknown, quantity: number, asOf: string, flat?: FlatCosts, lineRevenue?: number): CostBreakdown {
  count(quantity, "cost_basis.line_quantity", 10_000_000, 1);
  date(asOf, "cost_basis.quote_date");
  const root = record(value, "cost_basis", ["schema_version", "currency", "order_charges", "components", "routing", "not_applicable", "unresolved_assumptions"]);
  if (root.schema_version !== 1 || root.currency !== "USD" || root.order_charges !== "excluded") {
    throw new Error("cost_basis requires schema_version 1, USD and order_charges excluded (including freight)");
  }
  for (const v of list(root.unresolved_assumptions, "cost_basis.unresolved_assumptions", 32)) text(v, "cost_basis.unresolved_assumptions");
  const totals: Record<keyof FlatCosts, Range> = { material_per_unit: zeroRange(), outside_per_unit: zeroRange(), labor_per_unit: zeroRange(), setup_total: zeroRange() };
  const components: CostBreakdown["components"] = [];
  const routing: CostBreakdown["routing"] = [];
  const ids = new Set<string>();
  const present = new Set<Category>();
  for (const [i, item] of list(root.components, "cost_basis.components", 64).entries()) {
    const p = `cost_basis.components[${i}]`;
    const c = record(item, p, [...supportKeys, "category", "allocation", "rate_kind", "original_unit", "quantity_unit", "quantity", "original_units_per_quantity_unit", "conversion_ratio", "yield_fraction", "minimum_quantity", "purchase_increment", "unit_cost", "minimum_charge"]);
    support(c, p, asOf, ids);
    choice(c.category, `${p}.category`, ["material", "outside", "other"]);
    choice(c.allocation, `${p}.allocation`, ["material_per_unit", "outside_per_unit", "setup_total"]);
    if ((c.category === "material" && c.allocation !== "material_per_unit") || (c.category === "outside" && c.allocation !== "outside_per_unit")) throw new Error(`${p}.allocation conflicts with category`);
    costKind(c.rate_kind, `${p}.rate_kind`);
    text(c.original_unit, `${p}.original_unit`);
    text(c.quantity_unit, `${p}.quantity_unit`);
    const q = number(c.quantity, `${p}.quantity`, true);
    if ((c.original_units_per_quantity_unit === undefined) === (c.conversion_ratio === undefined)) {
      throw new Error(`${p} requires exactly one of original_units_per_quantity_unit or conversion_ratio`);
    }
    let conversion: Fraction;
    if (c.conversion_ratio === undefined) {
      conversion = number(c.original_units_per_quantity_unit, `${p}.original_units_per_quantity_unit`, true);
    } else {
      const ratio = record(c.conversion_ratio, `${p}.conversion_ratio`, ["original_units", "quantity_units"]);
      conversion = div(number(ratio.original_units, `${p}.conversion_ratio.original_units`, true),
        number(ratio.quantity_units, `${p}.conversion_ratio.quantity_units`, true));
      if (compare(conversion, whole(1e9)) > 0n) throw new Error(`${p}.conversion_ratio must be <= 1e9`);
    }
    const yieldFraction = number(c.yield_fraction, `${p}.yield_fraction`, true);
    if (compare(yieldFraction, whole(1)) > 0n) throw new Error(`${p}.yield_fraction must be <= 1`);
    const minimum = number(c.minimum_quantity, `${p}.minimum_quantity`);
    const increment = c.purchase_increment === undefined ? undefined : number(c.purchase_increment, `${p}.purchase_increment`, true);
    const costs = range(c.unit_cost, `${p}.unit_cost`);
    const charge = range(c.minimum_charge, `${p}.minimum_charge`);
    justifyZero(c, p, costs.low.n === 0n);
    const quantityBeforeIncrement = max(div(mul(q, conversion), yieldFraction), minimum);
    let pricedQuantity = quantityBeforeIncrement;
    if (increment) {
      const multiples = div(pricedQuantity, increment);
      pricedQuantity = mul(increment, fraction((multiples.n + multiples.d - 1n) / multiples.d, 1n));
    }
    const total = mapRange(costs, (v, k) => max(mul(pricedQuantity, v), charge[k]));
    const allocation = c.allocation as Allocation;
    totals[allocation] = sumRange(totals[allocation], total);
    present.add(c.category as Category);
    components.push({ id: c.id as string, category: c.category as CostComponent["category"], allocation,
      priced_quantity: display(pricedQuantity, 6, p), total_cost: displayRange(total, 4, p),
      ...(increment ? { purchase_rounding: { original_unit: c.original_unit as string,
        quantity_before_increment: display(quantityBeforeIncrement, 6, p), increment: c.purchase_increment as number } } : {}) });
  }
  for (const [i, item] of list(root.routing, "cost_basis.routing", 64).entries()) {
    const p = `cost_basis.routing[${i}]`;
    const r = record(item, p, [...supportKeys, "setup_occurrences", "setup_time", "run_time", "process_quantity", "setup_rate", "run_rate"]);
    support(r, p, asOf, ids);
    const occurrences = count(r.setup_occurrences, `${p}.setup_occurrences`, 10_000);
    const processQuantity = count(r.process_quantity, `${p}.process_quantity`, 10_000_000);
    const setupTime = record(r.setup_time, `${p}.setup_time`, ["unit", "values"]);
    choice(setupTime.unit, `${p}.setup_time.unit`, ["minutes", "hours"]);
    const setupMinutes = mapRange(range(setupTime.values, `${p}.setup_time.values`), v => mul(v, whole(setupTime.unit === "hours" ? 60 : 1)));
    const runTime = record(r.run_time, `${p}.run_time`, ["unit", "values"]);
    choice(runTime.unit, `${p}.run_time.unit`, ["minutes_per_piece", "seconds_per_piece", "pieces_per_hour"]);
    const runValues = range(runTime.values, `${p}.run_time.values`);
    const runMinutes = runTime.unit === "pieces_per_hour"
      ? { low: div(whole(60), runValues.high), base: div(whole(60), runValues.base), high: div(whole(60), runValues.low) }
      : mapRange(runValues, v => div(v, whole(runTime.unit === "seconds_per_piece" ? 60 : 1)));
    const rate = (input: unknown, path: string): Range => {
      const v = record(input, path, ["rate_kind", "unit", "values"]);
      costKind(v.rate_kind, `${path}.rate_kind`);
      if (v.unit !== "USD/hour") throw new Error(`${path}.unit must be USD/hour`);
      return range(v.values, `${path}.values`);
    };
    const setupRate = rate(r.setup_rate, `${p}.setup_rate`);
    const runRate = rate(r.run_rate, `${p}.run_rate`);
    justifyZero(r, p, occurrences === 0 || processQuantity === 0 || [setupMinutes, runMinutes, setupRate, runRate].some(v => v.low.n === 0n));
    const setup = mapRange(setupMinutes, (v, k) => div(mul(mul(whole(occurrences), v), setupRate[k]), whole(60)));
    const run = mapRange(runMinutes, (v, k) => div(mul(mul(whole(processQuantity), v), runRate[k]), whole(60)));
    totals.setup_total = sumRange(totals.setup_total, setup);
    totals.labor_per_unit = sumRange(totals.labor_per_unit, run);
    present.add("routing");
    routing.push({ id: r.id as string, setup_occurrences: occurrences, process_quantity: processQuantity,
      setup_minutes: displayRange(setupMinutes, 6, p), run_minutes_per_piece: displayRange(runMinutes, 6, p),
      setup_cost: displayRange(setup, 4, p), run_cost: displayRange(run, 4, p) });
  }
  for (const [i, item] of list(root.not_applicable, "cost_basis.not_applicable", 4).entries()) {
    const p = `cost_basis.not_applicable[${i}]`;
    const n = record(item, p, ["category", "reason", "sources"]);
    choice(n.category, `${p}.category`, ["material", "outside", "other", "routing"]);
    if (present.has(n.category as Category)) throw new Error(`${p} duplicates or contradicts a present category`);
    text(n.reason, `${p}.reason`);
    sources(n.sources, `${p}.sources`, asOf);
    present.add(n.category as Category);
  }
  for (const category of ["material", "outside", "other", "routing"] as const) if (!present.has(category)) throw new Error(`cost_basis missing ${category} costs or sourced not_applicable disposition; unknown is not zero`);
  const reconciled = {} as FlatCosts;
  let lineCost = zeroRange();
  for (const key of flatKeys) {
    lineCost = sumRange(lineCost, totals[key]);
    const places = key === "setup_total" ? 2 : 4;
    const base = key === "setup_total" ? totals[key].base : div(totals[key].base, whole(quantity));
    reconciled[key] = display(base, places, `cost_basis.${key}`);
    if (flat) {
      const supplied = number(flat[key], `cost_basis.flat.${key}`);
      if (supplied.n * 10n ** BigInt(places) % supplied.d || compare(supplied, decimal(reconciled[key])) !== 0n) {
        throw new Error(`cost_basis does not reconcile ${key} to flat cost_plus at ${places} decimal places`);
      }
    }
  }
  let margin: CostRange | null = null;
  if (lineRevenue !== undefined) {
    const revenue = number(lineRevenue, "cost_basis.line_revenue", true);
    const marginAt = (cost: Fraction) => mul(div(add(revenue, { n: -cost.n, d: cost.d }), revenue), whole(100));
    margin = displayRange({ low: marginAt(lineCost.high), base: marginAt(lineCost.base), high: marginAt(lineCost.low) }, 2, "cost_basis.estimated_line_margin_pct");
  }
  return {
    assertion_status: "supplied_not_authenticated", scope: "production_line_excluding_freight_tax_and_order_charges",
    rounding: "half_up_flat_unit_4dp_setup_2dp_cost_report_4dp_margin_2dp",
    supplied_basis: value as CostBasis, reconciled_flat: reconciled, components, routing,
    estimated_line_cost: displayRange(lineCost, 4, "cost_basis.estimated_line_cost"), estimated_line_margin_pct: margin,
    warnings: [
      "Worksheet sources, hashes, applicability and estimate approvals are supplied assertions, not authenticated evidence",
      "Historical and approved estimates support prospective review, not guaranteed actual costs or current buy prices",
      "Estimated production-line margin excludes freight, tax and separate order charges; no whole-order margin is claimed",
      "Cost ranges are scenario bounds, not statistical confidence; human approval is still required before customer release",
    ],
  };
}
