import { createHash } from "node:crypto";
import { lstatSync, readFileSync, realpathSync } from "node:fs";
import { basename, join, resolve, sep } from "node:path";
import type { OrderRequest, PricedOrder } from "../estimator/src/order.js";

export type Check = "identity" | "lines" | "prices" | "amounts" | "charges" | "state" | "markdown" | "provenance" | "cutoff" | "validation";
export interface Criterion { id: string; title: string; check: Check; deliverables: ("order.json" | "order.md")[] }
export interface Task {
  schema_version: 1;
  id: string;
  title: string;
  category: string;
  outcome: "order" | "validation";
  deliverables: { "order.json": "order.json"; "order.md": "order.md" };
  criteria: Criterion[];
  expected: {
    lines?: { line_id: string; quantity: number; unit_price: number | null; extended_price: number | null; pricing_source: PricedOrder["lines"][number]["pricing_source"] }[];
    priced_subtotal?: number; subtotal?: number | null; total?: number | null;
    state?: PricedOrder["state"];
    error_includes?: string;
    analog_quote_no?: string;
  };
}
export interface Grade { id: string; title: string; outcome: Task["outcome"]; score: 0 | 1; all_pass: boolean; n_criteria: number; n_passed: number; criteria_results: { id: string; title: string; verdict: "pass" | "fail"; reason: string }[] }

const checks = new Set<Check>(["identity", "lines", "prices", "amounts", "charges", "state", "markdown", "provenance", "cutoff", "validation"]);
const digest = (bytes: string | Buffer) => createHash("sha256").update(bytes).digest("hex");

export function safeFile(root: string, path: string): string {
  if (lstatSync(root).isSymbolicLink()) throw new Error(`symlink not permitted: ${root}`);
  const base = realpathSync(root);
  const target = resolve(root, path);
  if (target !== base && !target.startsWith(base + sep)) throw new Error(`path escapes task directory: ${path}`);
  const relative = target.slice(base.length).split(sep).filter(Boolean);
  let cursor = base;
  for (const segment of relative) {
    cursor = join(cursor, segment);
    if (lstatSync(cursor).isSymbolicLink()) throw new Error(`symlink not permitted: ${cursor}`);
  }
  if (realpathSync(target) !== target || !lstatSync(target).isFile()) throw new Error(`not a regular task file: ${target}`);
  return target;
}

export function loadTask(dir: string): { task: Task; request: OrderRequest; registerPath: string; hashes: { task: string; request: string; register: string } } {
  const manifestPath = safeFile(dir, "task.json");
  const raw = readFileSync(manifestPath);
  const task = JSON.parse(raw.toString("utf8")) as Task;
  if (!task || task.schema_version !== 1 || typeof task.id !== "string" || !/^[a-z0-9][a-z0-9-]*$/.test(task.id) || basename(resolve(dir)) !== task.id || !task.title ||
    typeof task.category !== "string" || !/^[a-z_]+$/.test(task.category) ||
    !["order", "validation"].includes(task.outcome) || JSON.stringify(task.deliverables) !== JSON.stringify({ "order.json": "order.json", "order.md": "order.md" }) ||
    !Array.isArray(task.criteria) || !task.criteria.length || !task.expected || typeof task.expected !== "object") throw new Error(`invalid task manifest: ${dir}`);
  const ids = new Set<string>();
  for (const c of task.criteria) {
    if (typeof c.id !== "string" || !/^C-\d{3}$/.test(c.id) || ids.has(c.id) || typeof c.title !== "string" || !c.title.trim() ||
      !checks.has(c.check) || !Array.isArray(c.deliverables) || !c.deliverables.length || c.deliverables.some((d) => !Object.hasOwn(task.deliverables, d))) {
      throw new Error(`invalid criterion in ${dir}: ${JSON.stringify(c)}`);
    }
    ids.add(c.id);
  }
  const required: [string, Check][] = task.outcome === "validation" ? [["C-001", "validation"]] : [
    ["C-001", "identity"], ["C-002", "lines"], ["C-003", "prices"], ["C-004", "amounts"],
    ["C-005", "charges"], ["C-006", "state"], ["C-007", "markdown"], ["C-008", "provenance"],
    ...(task.expected.analog_quote_no ? [["C-009", "cutoff"] as [string, Check]] : []),
  ];
  if (required.some(([id, check]) => !task.criteria.some((c) => c.id === id && c.check === check))) throw new Error(`missing required criterion in ${dir}`);
  if (task.criteria.some((c) => !c.deliverables.includes("order.json") ||
    (["markdown", "validation"].includes(c.check) && !c.deliverables.includes("order.md")))) throw new Error(`criterion lacks scoped deliverables in ${dir}`);
  if ((task.outcome === "order" && (!Array.isArray(task.expected.lines) || !task.expected.lines.length || !task.expected.state)) ||
    (task.outcome === "validation" && !task.expected.error_includes)) throw new Error(`incomplete expectations: ${dir}`);
  const requestPath = safeFile(dir, "request.json");
  const registerPath = safeFile(dir, "register.csv");
  const request = JSON.parse(readFileSync(requestPath, "utf8")) as OrderRequest;
  return { task, request, registerPath, hashes: { task: digest(raw), request: digest(JSON.stringify(request)), register: digest(readFileSync(registerPath)) } };
}

const equal = (actual: unknown, expected: unknown) => JSON.stringify(actual) === JSON.stringify(expected);

export function gradeTask(dir: string, artifactDir: string): Grade {
  const { task, request, hashes } = loadTask(dir);
  let order: any;
  let markdown: string | undefined;
  try { order = JSON.parse(readFileSync(safeFile(artifactDir, "order.json"), "utf8")); } catch { order = undefined; }
  try { markdown = readFileSync(safeFile(artifactDir, "order.md"), "utf8"); } catch { markdown = undefined; }
  const expected = task.expected;
  const actualLines: any[] = Array.isArray(order?.lines) ? order.lines : [];
  const lineIds = new Set(actualLines.map((line) => line?.line_id));
  const match = (value: boolean, failure: string) => ({ verdict: value ? "pass" as const : "fail" as const, reason: value ? "Exact deterministic check passed" : failure });
  const escapeMd = (value: string) => value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/([\\`*_{}\[\]()#+.!|~-])/g, "\\$1");
  const results = task.criteria.map((criterion) => {
    let result: ReturnType<typeof match>;
    if (criterion.deliverables.some((d) => d === "order.json" && order === undefined || d === "order.md" && markdown === undefined)) {
      result = match(false, `Missing or corrupt ${criterion.deliverables.join(", ")}`);
    } else try {
      switch (criterion.check) {
        case "identity": result = match(order?.schema_version === 1 && order.order_id === request.order_id && order.quote_date === request.quote_date && order.customer === request.customer && order.currency === "USD", "Order identity/schema differs from input"); break;
        case "lines": result = match(actualLines.length === request.parts.length && lineIds.size === request.parts.length && request.parts.every((part, i) => {
          const line = actualLines[i];
          return line?.line_id === part.line_id && equal(line?.part, Object.fromEntries(Object.entries(part).filter(([key]) => key !== "line_id" && key !== "pricing"))) && line?.part?.quantity === part.quantity;
        }), "Missing, reordered, duplicate or altered lines"); break;
        case "prices": result = match(expected.lines!.length === actualLines.length && expected.lines!.every((line, i) => {
          const actual = actualLines[i];
          return actual?.line_id === line.line_id && actual.unit_price === line.unit_price && actual.extended_price === line.extended_price && actual.pricing_source === line.pricing_source;
        }), "Line price, extension or source differs from expected independent fixture"); break;
        case "amounts": result = match(order?.priced_subtotal === expected.priced_subtotal && order?.subtotal === expected.subtotal && order?.total === expected.total &&
          Math.round(actualLines.reduce((sum, line) => sum + (line?.extended_price ?? 0), 0) * 100) === Math.round((order?.priced_subtotal ?? NaN) * 100) &&
          (order?.total === null || Math.round((order?.subtotal + order?.charges?.shipping + order?.charges?.tax + order?.additional_charges?.reduce((sum: number, charge: any) => sum + charge?.amount, 0)) * 100) === Math.round(order?.total * 100)),
          "Subtotal/total differs from expected fixture or arithmetic"); break;
        case "charges": result = match(equal(order?.charges, { shipping: request.charges?.shipping ?? null, tax: request.charges?.tax ?? null }) &&
          equal(order?.additional_charges, request.additional_charges ?? []), "Charges omitted or altered"); break;
        case "state": {
          const hasUnknown = actualLines.some((line) => typeof line?.unit_price !== "number" || !Number.isFinite(line.unit_price) || line.unit_price <= 0 ||
            typeof line?.extended_price !== "number" || !Number.isFinite(line.extended_price) || line.extended_price < 0) ||
            typeof order?.charges?.shipping !== "number" || !Number.isFinite(order.charges.shipping) ||
            typeof order?.charges?.tax !== "number" || !Number.isFinite(order.charges.tax);
          result = match(order?.state === expected.state && order?.requires_human_review === true && Array.isArray(order.blockers) &&
            (expected.state === "BLOCKED" ? order.blockers.length > 0 && order.total === null :
              order.blockers.length === 0 && !hasUnknown && typeof order.total === "number" && Number.isFinite(order.total)) &&
            (!hasUnknown || order.total === null && order.state === "BLOCKED") &&
            !["READY", "APPROVED", "RELEASED"].includes(order.state), "Incorrect state, unknown inputs, blockers, total, or review gate"); break;
        }
        case "markdown": result = match(!!markdown && markdown.includes(`# Priced order ${escapeMd(request.order_id)}`) && markdown.includes(`State: ${escapeMd(expected.state!)}`) &&
          markdown.includes("human review required") && expected.lines!.every((line, i) => {
            const part = request.parts[i]!;
            return markdown!.includes(`| ${escapeMd(line.line_id)} | ${escapeMd(part.part_no ?? part.description!)} | ${line.quantity} | ${line.unit_price === null ? "—" : `$${line.unit_price.toFixed(4)}`} | ${line.extended_price === null ? "—" : `$${line.extended_price.toFixed(2)}`} |`);
          }) && markdown.includes(`Subtotal (lines): ${expected.subtotal === null ? "—" : `$${expected.subtotal?.toFixed(2)}`}`) &&
          markdown.includes(`Shipping: ${request.charges?.shipping == null ? "—" : `$${request.charges.shipping.toFixed(2)}`}`) &&
          markdown.includes(`Tax: ${request.charges?.tax == null ? "—" : `$${request.charges.tax.toFixed(2)}`}`) &&
          (request.additional_charges ?? []).every((charge) => markdown!.includes(`${escapeMd(charge.label)}: $${charge.amount.toFixed(2)}`)) &&
          (order?.total === null ? markdown.includes("Total: —") : typeof order?.total === "number" && markdown.includes(`Total: $${order.total.toFixed(2)}`)), "Markdown omits or misstates identity, lines, charges, total, or human-review gate"); break;
        case "provenance": result = match(equal(order?.provenance, { request_sha256: hashes.request, register_sha256: hashes.register, as_of: request.quote_date, mode: "offline" }), "Provenance hashes, cutoff, or offline mode differ"); break;
        case "cutoff": result = match(actualLines.some((line) => line?.analogs?.some((analog: any) => analog.quote_no === expected.analog_quote_no)) &&
          actualLines.every((line) => Array.isArray(line.analogs) && line.analogs.every((analog: any) => typeof analog.quote_date === "string" && analog.quote_date < request.quote_date)), "Expected historical analog missing or future/same-day analog leaked"); break;
        case "validation": result = match(task.outcome === "validation" && order?.status === "validation_rejected" && typeof order.error === "string" && order.error.includes(expected.error_includes!) &&
          !order.lines && !order.total && markdown?.includes("Validation rejected") === true, "Malformed request was not rejected without producing an order"); break;
      }
    } catch (error) {
      result = match(false, `Malformed artifact: ${error instanceof Error ? error.message : String(error)}`);
    }
    return { id: criterion.id, title: criterion.title, ...result };
  });
  const n_passed = results.filter((r) => r.verdict === "pass").length;
  return { id: task.id, title: task.title, outcome: task.outcome, score: n_passed === results.length ? 1 : 0, all_pass: n_passed === results.length, n_criteria: results.length, n_passed, criteria_results: results };
}

if (process.argv[1]?.endsWith("order-grader.ts")) {
  const args = process.argv.slice(2);
  if (args.length !== 4 || args[0] !== "--task" || args[2] !== "--artifacts") throw new Error("Usage: order-grader.ts --task TASK_DIRECTORY --artifacts ARTIFACT_DIRECTORY");
  const result = gradeTask(args[1]!, args[3]!);
  console.log(JSON.stringify(result, null, 2));
  if (!result.all_pass) process.exitCode = 1;
}
