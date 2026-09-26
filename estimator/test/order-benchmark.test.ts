import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";

const repo = join(dirname(fileURLToPath(import.meta.url)), "../..");
const tasks = join(repo, "evals/tasks");
const scratch = mkdtempSync(join(tmpdir(), "keller-order-benchmark-"));
const out = join(scratch, "baseline");
afterAll(() => rmSync(scratch, { recursive: true, force: true }));

const run = (script: string, args: string[]) => {
  const env = { ...process.env };
  delete env.AI_GATEWAY_API_KEY;
  return spawnSync(process.execPath, [join(repo, "estimator/node_modules/tsx/dist/cli.mjs"), join(repo, `evals/${script}`), ...args],
    { cwd: repo, env, encoding: "utf8" });
};
const grade = (id: string, artifactDir: string) => run("order-grader.ts", ["--task", join(tasks, id), "--artifacts", artifactDir]);

describe("order artifact benchmark", () => {
  it("runs offline and records all-pass, holds, rejections and provenance", () => {
    const result = run("run-orders.ts", ["--tasks", tasks, "--out", out]);
    expect(result.status, result.stderr).toBe(0);
    const scores = JSON.parse(readFileSync(join(out, "scores.json"), "utf8"));
    expect(scores.schema_version).toBe(1);
    expect(scores.summary).toMatchObject({ tasks: 11, passed: 11, failed: 0, completed_orders: 7, correct_holds: 2, correct_validation_rejections: 2 });
    expect(scores.provenance.harvey_reference_commit).toBe("845a08840869b21a5c11958aae58bf5f00a7b775");
    expect(scores.provenance.implementation_sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(scores.provenance.hashed_files).toContain("estimator/src/order.ts");
    expect(scores.provenance.tasks.historical.artifacts["order.json"]).toMatch(/^[a-f0-9]{64}$/);
    expect(readFileSync(join(out, "report.md"), "utf8")).toContain("description-only/material-bearing historical retrieval");
    expect(existsSync(join(out, "historical/request.json"))).toBe(true);
    const again = run("run-orders.ts", ["--tasks", tasks, "--out", out]);
    expect(again.status).not.toBe(0);
    expect(again.stderr).toContain("refusing to overwrite");
  });

  it.each([
    ["mixed-charges", "dropped line", (order: any) => { order.lines.pop(); }, "C-002"],
    ["explicit", "wrong unit price", (order: any) => { order.lines[0].unit_price = 0.01; }, "C-003"],
    ["mixed-charges", "wrong total", (order: any) => { order.total += 1; }, "C-004"],
    ["unknown-price", "false ready status", (order: any) => { order.state = "PRICED_REQUIRES_REVIEW"; }, "C-006"],
    ["unknown-charges", "invented charge", (order: any) => { order.charges.shipping = 0; }, "C-005"],
    ["historical", "future analog", (order: any) => { order.lines[0].analogs[0].quote_date = "2026-01-01"; }, "C-009"],
    ["explicit", "malformed structure", (order: any) => { order.charges = null; }, "C-004"],
  ] as const)("rejects %s artifact mutation: %s", (id, _description, mutate, missed) => {
    const artifactDir = join(scratch, `${id}-${missed}-${_description.replaceAll(" ", "-")}`);
    cpSync(join(out, id), artifactDir, { recursive: true });
    const file = join(artifactDir, "order.json");
    const order = JSON.parse(readFileSync(file, "utf8"));
    mutate(order);
    writeFileSync(file, JSON.stringify(order));
    const result = grade(id, artifactDir);
    expect(result.status, result.stderr).toBe(1);
    const scored = JSON.parse(result.stdout);
    expect(scored.all_pass).toBe(false);
    expect(scored.criteria_results.find((c: any) => c.id === missed).verdict).toBe("fail");
  });

  it("fails missing, corrupt, and altered Markdown artifacts", () => {
    const artifactDir = join(scratch, "markdown-corrupt");
    cpSync(join(out, "explicit"), artifactDir, { recursive: true });
    const file = join(artifactDir, "order.md");
    writeFileSync(file, "# Priced order O-EXPLICIT\nState: READY\n");
    expect(JSON.parse(grade("explicit", artifactDir).stdout).criteria_results.find((c: any) => c.id === "C-007").verdict).toBe("fail");
    writeFileSync(join(artifactDir, "order.json"), "{");
    const result = grade("explicit", artifactDir);
    expect(result.status).toBe(1);
    expect(JSON.parse(result.stdout).n_passed).toBe(0);
    rmSync(file);
    expect(grade("explicit", artifactDir).status).toBe(1);
  });

  it("rejects a Markdown-only unit price mutation while JSON stays correct", () => {
    const artifactDir = join(scratch, "markdown-price-mutation");
    cpSync(join(out, "mixed-charges"), artifactDir, { recursive: true });
    const file = join(artifactDir, "order.md");
    writeFileSync(file, readFileSync(file, "utf8").replace("$2.0000", "$2.0100"));
    const result = grade("mixed-charges", artifactDir);
    expect(result.status, result.stderr).toBe(1);
    const scored = JSON.parse(result.stdout);
    expect(scored.criteria_results.find((c: any) => c.id === "C-003").verdict).toBe("pass");
    expect(scored.criteria_results.find((c: any) => c.id === "C-007").verdict).toBe("fail");
  });

  it("rejects a Markdown-only additional charge mutation", () => {
    const artifactDir = join(scratch, "markdown-charge-mutation");
    cpSync(join(out, "mixed-charges"), artifactDir, { recursive: true });
    const file = join(artifactDir, "order.md");
    writeFileSync(file, readFileSync(file, "utf8").replace("Packaging: $2.00", "Packaging: $3.00"));
    const scored = JSON.parse(grade("mixed-charges", artifactDir).stdout);
    expect(scored.criteria_results.find((c: any) => c.id === "C-007").verdict).toBe("fail");
  });

  it("writes diagnostic scores and exits nonzero when a task fails", () => {
    const fixture = join(scratch, "failed-criterion-tasks");
    const taskDir = join(fixture, "explicit");
    cpSync(join(tasks, "explicit"), taskDir, { recursive: true });
    const path = join(taskDir, "task.json");
    const task = JSON.parse(readFileSync(path, "utf8"));
    task.expected.total = 999;
    writeFileSync(path, JSON.stringify(task));
    const output = join(scratch, "failed-criterion-results");
    const result = run("run-orders.ts", ["--tasks", fixture, "--out", output]);
    expect(result.status, result.stderr).toBe(1);
    const scores = JSON.parse(readFileSync(join(output, "scores.json"), "utf8"));
    expect(scores.summary.failed).toBe(1);
    expect(scores.results[0].criteria_results.find((c: any) => c.id === "C-004").verdict).toBe("fail");
  });

  it.each(["empty rubric", "duplicate IDs", "unknown grader", "escaping symlink", "unknown version", "inherited deliverable"])("rejects invalid task: %s", (defect) => {
    const fixture = join(scratch, `task-${defect.replaceAll(" ", "-")}`);
    const taskDir = join(fixture, "explicit");
    cpSync(join(tasks, "explicit"), taskDir, { recursive: true });
    const file = join(taskDir, "task.json");
    const task = JSON.parse(readFileSync(file, "utf8"));
    if (defect === "empty rubric") task.criteria = [];
    if (defect === "duplicate IDs") task.criteria.push({ ...task.criteria[0] });
    if (defect === "unknown grader") task.criteria[0].check = "llm";
    if (defect === "unknown version") task.schema_version = 99;
    if (defect === "inherited deliverable") task.criteria[0].deliverables = ["toString"];
    if (defect !== "escaping symlink") writeFileSync(file, JSON.stringify(task));
    else {
      rmSync(join(taskDir, "register.csv"));
      symlinkSync(join(tasks, "historical/register.csv"), join(taskDir, "register.csv"));
    }
    const output = join(scratch, `rejected-${defect.replaceAll(" ", "-")}`);
    const result = run("run-orders.ts", ["--tasks", fixture, "--out", output]);
    expect(result.status).not.toBe(0);
    expect(existsSync(output)).toBe(false);
  });
});
