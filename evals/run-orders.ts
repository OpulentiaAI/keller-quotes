import { mkdirSync, readdirSync, writeFileSync, lstatSync, realpathSync, readFileSync, existsSync } from "node:fs";
import { join, resolve, sep } from "node:path";
import { createHash } from "node:crypto";
import { QuoteRegister } from "../estimator/src/register.js";
import { buildPricedOrder, renderOrderMarkdown } from "../estimator/src/order.js";
import { gradeTask, loadTask, type Grade } from "./order-grader.js";

const argv = process.argv.slice(2);
if (argv.length !== 4 || argv[0] !== "--tasks" || argv[2] !== "--out" || !argv[1] || !argv[3]) {
  throw new Error("Usage: run-orders.ts --tasks TASK_DIRECTORY --out NEW_OUTPUT_DIRECTORY");
}
if (lstatSync(argv[1]!).isSymbolicLink()) throw new Error("Tasks directory cannot be a symlink");
const tasksDir = realpathSync(argv[1]!);
const out = resolve(argv[3]!);
if (existsSync(out)) throw new Error("Output directory already exists; refusing to overwrite");
if (out === tasksDir || out.startsWith(tasksDir + sep) || tasksDir.startsWith(out + sep)) throw new Error("Output must be separate from task directory");
if (lstatSync(tasksDir).isSymbolicLink() || !lstatSync(tasksDir).isDirectory()) throw new Error("Tasks path must be a regular directory");
const entries = readdirSync(tasksDir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name));
if (!entries.length || entries.some((entry) => !entry.isDirectory() || entry.isSymbolicLink())) throw new Error("Tasks must contain only task directories, without symlinks");
const loaded = entries.map((entry) => loadTask(join(tasksDir, entry.name)));
if (new Set(loaded.map(({ task }) => task.id)).size !== loaded.length) throw new Error("Duplicate task IDs");
mkdirSync(out);
const results: Grade[] = [];
for (const { task, request, registerPath, hashes } of loaded) {
  const destination = join(out, task.id);
  mkdirSync(destination);
  writeFileSync(join(destination, "request.json"), JSON.stringify(request, null, 2) + "\n", { flag: "wx" });
  let order;
  try {
    order = await buildPricedOrder(QuoteRegister.fromCsv(registerPath), request, { registerSha256: hashes.register });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    writeFileSync(join(destination, "order.json"), JSON.stringify({ status: "validation_rejected", error: message }, null, 2) + "\n", { flag: "wx" });
    writeFileSync(join(destination, "order.md"), `# Validation rejected\n\n${message}\n`, { flag: "wx" });
  }
  if (order) {
    writeFileSync(join(destination, "order.json"), JSON.stringify(order, null, 2) + "\n", { flag: "wx" });
    writeFileSync(join(destination, "order.md"), renderOrderMarkdown(order), { flag: "wx" });
  }
  results.push(gradeTask(join(tasksDir, task.id), destination));
}
const completed = results.filter((r) => r.all_pass && r.outcome === "order" && loaded.find((t) => t.task.id === r.id)?.task.expected.state === "PRICED_REQUIRES_REVIEW").length;
const correctHolds = results.filter((r) => r.all_pass && r.outcome === "order" && loaded.find((t) => t.task.id === r.id)?.task.expected.state === "BLOCKED").length;
const correctRejections = results.filter((r) => r.all_pass && r.outcome === "validation").length;
const passed = results.filter((r) => r.all_pass).length;
const sha = (file: string) => createHash("sha256").update(readFileSync(file)).digest("hex");
const sourceFiles = ["estimator/src/order.ts", "estimator/src/estimate.ts", "estimator/src/price.ts",
  "estimator/src/retrieve.ts", "estimator/src/register.ts", "estimator/src/jev.ts", "estimator/src/types.ts",
  "estimator/package-lock.json", "evals/run-orders.ts", "evals/order-grader.ts"];
const sourceHash = createHash("sha256");
for (const file of sourceFiles) sourceHash.update(file).update("\0").update(readFileSync(new URL(`../${file}`, import.meta.url))).update("\0");
const provenance = { harvey_reference_commit: "845a08840869b21a5c11958aae58bf5f00a7b775",
  implementation_sha256: sourceHash.digest("hex"), hashed_files: sourceFiles,
  tasks: Object.fromEntries(loaded.map(({ task, hashes }) => [task.id, {
  ...hashes, artifacts: { "request.json": sha(join(out, task.id, "request.json")), "order.json": sha(join(out, task.id, "order.json")), "order.md": sha(join(out, task.id, "order.md")) },
}])) };
const summary = { tasks: results.length, passed, failed: results.length - passed, completed_orders: completed, correct_holds: correctHolds, correct_validation_rejections: correctRejections,
  all_pass_rate: passed / results.length, criterion_pass_rate: results.reduce((sum, r) => sum + r.n_passed, 0) / results.reduce((sum, r) => sum + r.n_criteria, 0) };
writeFileSync(join(out, "scores.json"), JSON.stringify({ schema_version: 1, summary, provenance, results }, null, 2) + "\n", { flag: "wx" });
writeFileSync(join(out, "report.md"), [
  "# Deterministic order artifact benchmark", "", `Harvey rubric methodology reference: ${provenance.harvey_reference_commit}. Offline, no judge calls.`,
  `Keller implementation SHA-256: ${provenance.implementation_sha256}.`,
  `All-pass: ${passed}/${results.length}; criterion pass rate: ${(summary.criterion_pass_rate * 100).toFixed(1)}%.`,
  `Completed orders requiring human review: ${completed}; correct blocked holds: ${correctHolds}; correct validation rejections: ${correctRejections}.`, "",
  "Contract coverage includes description-only/material-bearing historical retrieval and low-quantity cent rounding; this benchmark does not measure empirical price accuracy.", "",
  "| Task | Category | Outcome | All-pass | Criteria | Misses |", "| --- | --- | --- | --- | ---: | --- |",
  ...results.map((r) => `| ${r.id} | ${loaded.find((t) => t.task.id === r.id)!.task.category} | ${r.outcome} | ${r.all_pass ? "PASS" : "FAIL"} | ${r.n_passed}/${r.n_criteria} | ${r.criteria_results.filter((c) => c.verdict === "fail").map((c) => `${c.id}: ${c.reason}`).join("; ") || "—"} |`), "",
  "## Category slices", "",
  "| Category | All-pass |", "| --- | ---: |",
  ...[...new Set(loaded.map((t) => t.task.category))].sort().map((category) => {
    const slice = results.filter((r) => loaded.find((t) => t.task.id === r.id)!.task.category === category);
    return `| ${category} | ${slice.filter((r) => r.all_pass).length}/${slice.length} |`;
  }), "",
].join("\n"), { flag: "wx" });
console.log(JSON.stringify(summary));
if (passed !== results.length) process.exitCode = 1;
