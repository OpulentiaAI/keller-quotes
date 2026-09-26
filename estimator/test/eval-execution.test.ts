import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, describe, expect, it } from "vitest";

const repo = join(dirname(fileURLToPath(import.meta.url)), "../..");
const scratch = mkdtempSync(join(tmpdir(), "keller-eval-execution-"));
afterAll(() => rmSync(scratch, { recursive: true, force: true }));
const csv = join(scratch, "register.csv");
const evalset = join(scratch, "evalset.jsonl");
const report = join(scratch, "report.md");

const run = (extra: string[] = []) => {
  const env = { ...process.env };
  delete env.AI_GATEWAY_API_KEY;
  return spawnSync(process.execPath,
    [join(repo, "estimator/node_modules/tsx/dist/cli.mjs"), join(repo, "evals/run-eval.ts"),
      evalset, "--register", csv, "--report", report, ...extra],
    { cwd: repo, env, encoding: "utf8" });
};

describe("eval execution", () => {
  it("reports even, odd, and empty median APE accurately", () => {
    writeFileSync(csv, "quote_no,item_no,quote_date,part_no,status,quantity,unit_price\n" +
      ["A", "B", "C"].flatMap((part, i) => [
        `${part}-old,,2023-01-01,${part}${part}${part}${part},open,10,10`,
        `${part}-target,,2024-01-01,${part}${part}${part}${part},open,10,${i === 0 ? 20 : 10}`,
      ]).join("\n") + "\n");
    const cases = ["A", "B", "C"].map((part, i) => JSON.stringify({
      id: part, source_quote_no: `${part}-target`, quote_date: "2024-01-01", status: "open",
      input: { part_no: part.repeat(4), quantity: 10 }, actual_unit_price: i === 0 ? 20 : 10,
    }));
    writeFileSync(evalset, cases.join("\n") + "\n");

    for (const [limit, priced, median] of [[2, 2, 0.25], [3, 3, 0], [0, 0, null]] as const) {
      const result = run(["--limit", String(limit)]);
      expect(result.status, result.stderr).toBe(0);
      const { summary } = JSON.parse(readFileSync(report.replace(/\.md$/, ".json"), "utf8"));
      expect(summary).toMatchObject({ priced, median_ape: median, jev_configured: false });
    }
  });

  it("fails --jev without a key before creating either report", () => {
    rmSync(report, { force: true });
    rmSync(report.replace(/\.md$/, ".json"), { force: true });
    const result = run(["--jev"]);
    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain("--jev requires AI_GATEWAY_API_KEY");
    expect(existsSync(report)).toBe(false);
    expect(existsSync(report.replace(/\.md$/, ".json"))).toBe(false);
  });
});
