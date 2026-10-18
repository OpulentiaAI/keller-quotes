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
export interface BlankDimension { value: number; unit: "mm" | "in" }
export interface RectangularBlank {
  length: BlankDimension;
  width: BlankDimension;
  thickness: BlankDimension;
  density_kg_m3: number;
}
export interface CostComponent extends SupportedCost {
  category: Exclude<Category, "routing">;
  allocation: Allocation;
  rate_kind: "cost" | "sell";
  original_unit: string;
  quantity_unit: string;
  quantity: number;
  /** For finished_piece quantities below the line quantity; not stock/mass/lot units. */
  partial_quantity_reason?: string;
  /** Supply exactly one conversion form, BEFORE yield; never round a recurring ratio. */
  original_units_per_quantity_unit?: number;
  conversion_ratio?: { original_units: number; quantity_units: number };
  /** Derives kg/lb per blank instead of a manually supplied conversion. */
  rectangular_blank?: RectangularBlank;
  yield_fraction: number;
  minimum_quantity: number;
  /** Purchase a multiple of this many original priced units, after yield and minimum quantity. */
  purchase_increment?: number;
  unit_cost: CostRange;
  minimum_charge: CostRange;
}

export interface CostRate { rate_kind: "cost" | "sell"; unit: "USD/hour"; values: CostRange }
export type RunTime =
  | { unit: "minutes_per_piece" | "seconds_per_piece" | "hours_per_piece" | "pieces_per_hour"; values: CostRange }
  | { unit: "minutes_per_cycle" | "seconds_per_cycle" | "hours_per_cycle" | "cycles_per_hour"; values: CostRange; cycles_per_piece: number };
export interface CostRouting extends SupportedCost {
  setup_occurrences: number;
  setup_time: { unit: "minutes" | "hours"; values: CostRange };
  run_time: RunTime;
  process_quantity: number;
  /** Required when process_quantity is below the line quantity. */
  partial_quantity_reason?: string;
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

interface PartialQuantity { quantity: number; line_quantity: number; reason: string }

export interface CostBreakdown {
  assertion_status: "supplied_not_authenticated";
  scope: "production_line_excluding_freight_tax_and_order_charges";
  rounding: "half_up_flat_unit_4dp_setup_2dp_cost_report_4dp_margin_2dp";
  supplied_basis: CostBasis;
  reconciled_flat: FlatCosts;
  components: { id: string; category: CostComponent["category"]; allocation: Allocation;
    priced_quantity: number; total_cost: CostRange; partial_quantity?: PartialQuantity;
    consumption?: { method: "rectangular_blank"; mass_per_blank: number; mass_unit: "kg" | "lb"; blank_count: number };
    purchase_rounding?: { original_unit: string; quantity_before_increment: number; increment: number } }[];
  routing: { id: string; setup_occurrences: number; setup_minutes: CostRange;
    run_minutes_per_piece: CostRange; cycles_per_piece?: number;
    process_quantity: number; setup_cost: CostRange; run_cost: CostRange; partial_quantity?: PartialQuantity }[];
  estimated_line_cost: CostRange;
  /** Low margin uses HIGH cost, and vice versa, against displayed line revenue. */
  estimated_line_margin_pct: CostRange | null;
  /** Exact BASE cost versus displayed revenue; independent of rounded margin reports. */
  base_margin_target: { requested_pct: number; status: "met" | "below_target" | "not_assessable" } | null;
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
function materialConversion(c: Record<string, unknown>, p: string): Fraction {
  if (!("rectangular_blank" in c)) {
    if ((c.original_units_per_quantity_unit === undefined) === (c.conversion_ratio === undefined)) {
      throw new Error(`${p} requires exactly one of original_units_per_quantity_unit or conversion_ratio`);
    }
    if (c.conversion_ratio === undefined) return number(c.original_units_per_quantity_unit, `${p}.original_units_per_quantity_unit`, true);
    const ratio = record(c.conversion_ratio, `${p}.conversion_ratio`, ["original_units", "quantity_units"]);
    const conversion = div(number(ratio.original_units, `${p}.conversion_ratio.original_units`, true),
      number(ratio.quantity_units, `${p}.conversion_ratio.quantity_units`, true));
    if (compare(conversion, whole(1e9)) > 0n) throw new Error(`${p}.conversion_ratio must be <= 1e9`);
    return conversion;
  }
  if ("original_units_per_quantity_unit" in c || "conversion_ratio" in c) {
    throw new Error(`${p} must supply rectangular_blank OR original_units_per_quantity_unit/conversion_ratio, not both`);
  }
  choice(c.category, `${p}.category for rectangular_blank`, ["material"]);
  choice(c.original_unit, `${p}.original_unit for rectangular_blank`, ["kg", "lb"]);
  choice(c.quantity_unit, `${p}.quantity_unit for rectangular_blank`, ["blank"]);
  count(c.quantity, `${p}.quantity in blanks`, 10_000_000, 1);
  const path = `${p}.rectangular_blank`;
  const blank = record(c.rectangular_blank, path, ["length", "width", "thickness", "density_kg_m3"]);
  let mass = number(blank.density_kg_m3, `${path}.density_kg_m3`, true);
  for (const key of ["length", "width", "thickness"] as const) {
    const dimension = record(blank[key], `${path}.${key}`, ["value", "unit"]);
    choice(dimension.unit, `${path}.${key}.unit`, ["mm", "in"]);
    const metres = mul(number(dimension.value, `${path}.${key}.value`, true),
      dimension.unit === "mm" ? fraction(1n, 1000n) : fraction(127n, 5000n));
    mass = mul(mass, metres);
  }
  // Exact international avoirdupois pound; never round mass before multiplying cost.
  return c.original_unit === "kg" ? mass : div(mass, fraction(45359237n, 100000000n));
}
function range(value: unknown, path: string): Range {
  const r = record(value, path, keys);
  const result = { low: number(r.low, `${path}.low`), base: number(r.base, `${path}.base`), high: number(r.high, `${path}.high`) };
  if (compare(result.low, result.base) > 0n || compare(result.base, result.high) > 0n) throw new Error(`${path} must satisfy low <= base <= high`);
  return result;
}
function runTimeMinutes(value: unknown, path: string): { minutes: Range; cycles_per_piece?: number } {
  const time = record(value, path, ["unit", "values", "cycles_per_piece"]);
  const cycleUnits = ["minutes_per_cycle", "seconds_per_cycle", "hours_per_cycle", "cycles_per_hour"];
  choice(time.unit, `${path}.unit`, ["minutes_per_piece", "seconds_per_piece", "hours_per_piece", "pieces_per_hour", ...cycleUnits]);
  const cycles = cycleUnits.includes(time.unit as string)
    ? count(time.cycles_per_piece, `${path}.cycles_per_piece`, 1_000_000, 1) : undefined;
  if (cycles === undefined && "cycles_per_piece" in time) throw new Error(`${path}.cycles_per_piece requires a per-cycle unit, not a finished-piece unit`);
  const values = range(time.values, `${path}.values`);
  const minutes = time.unit === "pieces_per_hour" || time.unit === "cycles_per_hour"
    ? { low: div(whole(60), values.high), base: div(whole(60), values.base), high: div(whole(60), values.low) }
    : mapRange(values, v => time.unit === "hours_per_piece" || time.unit === "hours_per_cycle"
      ? mul(v, whole(60)) : div(v, whole(time.unit === "seconds_per_piece" || time.unit === "seconds_per_cycle" ? 60 : 1)));
  return { minutes: mapRange(minutes, v => mul(v, whole(cycles ?? 1))), ...(cycles === undefined ? {} : { cycles_per_piece: cycles }) };
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

function sources(value: unknown, path: string, asOf: string, warnings: string[]): void {
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
    if (typeof s.expires_date === "string" && s.expires_date < asOf) {
      warnings.push(`Source validity: ${p} expired on ${s.expires_date}; quote_date ${asOf}; retained as ${s.status}, not current-cost authority`);
    }
    if (typeof s.effective_date === "string" && s.effective_date > asOf) {
      warnings.push(`Source validity: ${p} not effective until ${s.effective_date}; quote_date ${asOf}; retained as ${s.status}, not current-cost authority`);
    }
  }
}

const supportKeys = ["id", "sources", "assumptions", "charge_inclusion", "zero_reason", "engineering_fact_ids"];
function support(obj: Record<string, unknown>, path: string, asOf: string, ids: Set<string>, warnings: string[]): void {
  text(obj.id, `${path}.id`);
  if (ids.has(obj.id)) throw new Error(`${path} has a duplicate component/operation id`);
  ids.add(obj.id);
  sources(obj.sources, `${path}.sources`, asOf, warnings);
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
// Unscaled per-piece entries can silently understate line cost before margin pricing.
function justifyPartial(obj: Record<string, unknown>, path: string, covered: Fraction, lineQuantity: number): PartialQuantity | undefined {
  if (compare(covered, whole(lineQuantity)) < 0n) {
    text(obj.partial_quantity_reason, `${path}.partial_quantity_reason (covers fewer pieces than the line quantity; per-piece entries must be scaled to the line)`);
    return { quantity: display(covered, 6, path), line_quantity: lineQuantity, reason: obj.partial_quantity_reason };
  } else if (obj.partial_quantity_reason !== undefined) throw new Error(`${path}.partial_quantity_reason requires a quantity below the line quantity`);
}
function costKind(value: unknown, path: string): void {
  if (value !== "cost") throw new Error(`${path} must be cost; SELL rates cannot enter cost_plus (double margin)`);
}

/**
 * Validate and reconcile BASE worksheet amounts to explicitly supplied flat inputs.
 * Should-cost pricing uses exact worksheet totals instead of these rounded reports.
 * Component total = max(priced_quantity * unit_cost, minimum_charge); priced_quantity applies
 * yield, minimum quantity, then an optional original-unit purchase increment rounded upward.
 * Route total = occurrences * setup_minutes / 60 * setup_rate + process_quantity * run_minutes_per_piece / 60 * run_rate.
 * All ranges are scenario bounds, not probabilities or guarantees. No files are opened.
 */
export function reconcileCostBasis(value: unknown, quantity: number, asOf: string, flat: FlatCosts, lineRevenue?: number, targetMarginPct?: number): CostBreakdown {
  return calculateCostBasis(value, quantity, asOf, flat, lineRevenue, targetMarginPct).breakdown;
}

export function deriveCostBasis(value: unknown, quantity: number, asOf: string, lineRevenue?: number, targetMarginPct?: number): CostBreakdown {
  return calculateCostBasis(value, quantity, asOf, undefined, lineRevenue, targetMarginPct).breakdown;
}

function retainedCostFraction(marginPct: number): Fraction {
  if (!Number.isFinite(marginPct) || marginPct < 0 || marginPct >= 100) throw new Error("cost_basis.margin_pct must be between 0 and 100 (exclusive)");
  const margin = decimal(marginPct);
  return fraction(100n * margin.d - margin.n, 100n * margin.d);
}

/** Apply gross margin to exact BASE line cost, returning half-up 1/10000-dollar unit-price ticks. */
export function priceCostBasisUnit4(value: unknown, quantity: number, asOf: string, marginPct: number): bigint {
  const retained = retainedCostFraction(marginPct);
  const { baseLineCost } = calculateCostBasis(value, quantity, asOf);
  return rounded(div(div(baseLineCost, whole(quantity)), retained), 4);
}

function calculateCostBasis(value: unknown, quantity: number, asOf: string, flat?: FlatCosts, lineRevenue?: number, targetMarginPct?: number): { breakdown: CostBreakdown; baseLineCost: Fraction } {
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
  const sourceWarnings: string[] = [];
  const ids = new Set<string>();
  const present = new Set<Category>();
  for (const [i, item] of list(root.components, "cost_basis.components", 64).entries()) {
    const p = `cost_basis.components[${i}]`;
    const c = record(item, p, [...supportKeys, "category", "allocation", "rate_kind", "original_unit", "quantity_unit", "quantity", "partial_quantity_reason", "original_units_per_quantity_unit", "conversion_ratio", "rectangular_blank", "yield_fraction", "minimum_quantity", "purchase_increment", "unit_cost", "minimum_charge"]);
    support(c, p, asOf, ids, sourceWarnings);
    choice(c.category, `${p}.category`, ["material", "outside", "other"]);
    choice(c.allocation, `${p}.allocation`, ["material_per_unit", "outside_per_unit", "setup_total"]);
    if ((c.category === "material" && c.allocation !== "material_per_unit") || (c.category === "outside" && c.allocation !== "outside_per_unit")) throw new Error(`${p}.allocation conflicts with category`);
    costKind(c.rate_kind, `${p}.rate_kind`);
    text(c.original_unit, `${p}.original_unit`);
    text(c.quantity_unit, `${p}.quantity_unit`);
    const q = number(c.quantity, `${p}.quantity`, true);
    const comparableQuantity = c.allocation !== "setup_total" && c.quantity_unit === "finished_piece";
    const partialQuantity = comparableQuantity ? justifyPartial(c, p, q, quantity) : undefined;
    if (!comparableQuantity && c.partial_quantity_reason !== undefined) throw new Error(`${p}.partial_quantity_reason requires a finished_piece quantity and per-unit allocation, not setup_total`);
    const conversion = materialConversion(c, p);
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
      ...("rectangular_blank" in c ? { consumption: { method: "rectangular_blank" as const,
        mass_per_blank: display(conversion, 8, p), mass_unit: c.original_unit as "kg" | "lb", blank_count: c.quantity as number } } : {}),
      ...(partialQuantity ? { partial_quantity: partialQuantity } : {}),
      ...(increment ? { purchase_rounding: { original_unit: c.original_unit as string,
        quantity_before_increment: display(quantityBeforeIncrement, 6, p), increment: c.purchase_increment as number } } : {}) });
  }
  for (const [i, item] of list(root.routing, "cost_basis.routing", 64).entries()) {
    const p = `cost_basis.routing[${i}]`;
    const r = record(item, p, [...supportKeys, "setup_occurrences", "setup_time", "run_time", "process_quantity", "partial_quantity_reason", "setup_rate", "run_rate"]);
    support(r, p, asOf, ids, sourceWarnings);
    const occurrences = count(r.setup_occurrences, `${p}.setup_occurrences`, 10_000);
    const processQuantity = count(r.process_quantity, `${p}.process_quantity`, 10_000_000);
    const partialQuantity = justifyPartial(r, p, whole(processQuantity), quantity);
    const setupTime = record(r.setup_time, `${p}.setup_time`, ["unit", "values"]);
    choice(setupTime.unit, `${p}.setup_time.unit`, ["minutes", "hours"]);
    const setupMinutes = mapRange(range(setupTime.values, `${p}.setup_time.values`), v => mul(v, whole(setupTime.unit === "hours" ? 60 : 1)));
    const runTime = runTimeMinutes(r.run_time, `${p}.run_time`);
    const runMinutes = runTime.minutes;
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
      ...(runTime.cycles_per_piece === undefined ? {} : { cycles_per_piece: runTime.cycles_per_piece }),
      ...(partialQuantity ? { partial_quantity: partialQuantity } : {}),
      setup_cost: displayRange(setup, 4, p), run_cost: displayRange(run, 4, p) });
  }
  for (const [i, item] of list(root.not_applicable, "cost_basis.not_applicable", 4).entries()) {
    const p = `cost_basis.not_applicable[${i}]`;
    const n = record(item, p, ["category", "reason", "sources"]);
    choice(n.category, `${p}.category`, ["material", "outside", "other", "routing"]);
    if (present.has(n.category as Category)) throw new Error(`${p} duplicates or contradicts a present category`);
    text(n.reason, `${p}.reason`);
    sources(n.sources, `${p}.sources`, asOf, sourceWarnings);
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
  const retained = targetMarginPct === undefined ? undefined : retainedCostFraction(targetMarginPct);
  const target: CostBreakdown["base_margin_target"] = targetMarginPct === undefined ? null
    : { requested_pct: targetMarginPct, status: "not_assessable" };
  if (lineRevenue !== undefined) {
    const revenue = number(lineRevenue, "cost_basis.line_revenue", true);
    const marginAt = (cost: Fraction) => mul(div(add(revenue, { n: -cost.n, d: cost.d }), revenue), whole(100));
    margin = displayRange({ low: marginAt(lineCost.high), base: marginAt(lineCost.base), high: marginAt(lineCost.low) }, 2, "cost_basis.estimated_line_margin_pct");
    if (target && retained) target.status = compare(mul(revenue, retained), lineCost.base) >= 0n ? "met" : "below_target";
  }
  const breakdown: CostBreakdown = {
    assertion_status: "supplied_not_authenticated", scope: "production_line_excluding_freight_tax_and_order_charges",
    rounding: "half_up_flat_unit_4dp_setup_2dp_cost_report_4dp_margin_2dp",
    supplied_basis: value as CostBasis, reconciled_flat: reconciled, components, routing,
    estimated_line_cost: displayRange(lineCost, 4, "cost_basis.estimated_line_cost"), estimated_line_margin_pct: margin,
    base_margin_target: target,
    warnings: [
      ...(routing.some(r => r.cycles_per_piece !== undefined) ? ["Cycle-based routing uses supplied repetitions per piece; verify cycle scope, process quantity and COST-rate inclusions to avoid omitted or duplicated work"] : []),
      ...(components.some(c => c.consumption) ? ["Rectangular blank mass uses supplied dimensions and density, not verified finished geometry or nesting; yield and purchase minimums are applied separately"] : []),
      "Worksheet sources, hashes, applicability and estimate approvals are supplied assertions, not authenticated evidence",
      "Historical and approved estimates support prospective review, not guaranteed actual costs or current buy prices",
      "Estimated production-line margin excludes freight, tax and separate order charges; no whole-order margin is claimed",
      "Cost ranges are scenario bounds, not statistical confidence; human approval is still required before customer release",
      ...(target?.status === "below_target" ? [
        `Displayed line revenue is below the requested ${target.requested_pct}% gross margin at exact BASE worksheet cost; review pricing even if rounded margin appears on target`,
      ] : []),
      ...(target?.status === "not_assessable" ? ["BASE-cost margin target cannot be assessed without positive displayed line revenue"] : []),
      ...sourceWarnings,
    ],
  };
  return { breakdown, baseLineCost: lineCost.base };
}
