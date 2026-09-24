import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "csv-parse/sync";
import { afterAll, describe, expect, it } from "vitest";

const estimatorRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = join(estimatorRoot, "..");
const tmp = mkdtempSync(join(tmpdir(), "keller-cli-test-"));
const cli = join(estimatorRoot, "node_modules/.bin/tsx");
const source = join(estimatorRoot, "src/cli.ts");
const fixture = join(tmp, "fixture.csv");
writeFileSync(fixture, "quote_no,item_no,quote_date,part_no,description,customer_id,customer,status,quantity,unit_price\n000001,,2024-01-01,ABC-123,RETAINER PLATE,C1,ACME,won,10,10\n");
afterAll(() => rmSync(tmp, { recursive: true, force: true }));

function run(request: string, cwd: string, args: string[] = [], register?: string) {
  const env = { ...process.env };
  delete env.AI_GATEWAY_API_KEY;
  delete env.KELLER_REGISTER;
  if (register) env.KELLER_REGISTER = register;
  return spawnSync(cli, [source, request, "--offline", ...args], {
    cwd, env, encoding: "utf8",
  });
}

describe("CLI", () => {
  it("uses the implicit register from both documented working directories", () => {
    for (const cwd of [repoRoot, estimatorRoot]) {
      const request = cwd === repoRoot ? "estimator/examples/request.json" : "examples/request.json";
      const res = run(request, cwd);
      expect(res.status, res.stderr).toBe(0);
      const estimate = JSON.parse(res.stdout);
      expect(estimate.register_rows).toBeGreaterThan(1);
      expect(estimate.lines).toHaveLength(3);
    }
  }, 30_000);

  it("keeps explicit and environment register paths relative to the caller", () => {
    const request = join(estimatorRoot, "examples/request.json");
    for (const res of [
      run(request, tmp, ["--register", "fixture.csv"]),
      run(request, tmp, [], "fixture.csv"),
    ]) {
      expect(res.status, res.stderr).toBe(0);
      expect(JSON.parse(res.stdout).register_rows).toBe(1);
    }
  });

  it("reports malformed request shapes and invalid quantities with a nonzero exit", () => {
    for (const [name, body] of [
      ["null", "null"],
      ["part", '{"parts":[null]}'],
      ["string", '{"parts":[{"quantity":"10"}]}'],
      ["infinity", '{"parts":[{"quantity":1e999}]}'],
      ["json", "{"],
    ] as const) {
      const request = join(tmp, `${name}.json`);
      writeFileSync(request, body);
      const res = run(request, tmp, ["--register", "fixture.csv"]);
      expect(res.status).toBe(2);
      expect(res.stderr).toContain("invalid request:");
      expect(res.stdout).toBe("");
    }
  });

  it("neutralizes formula-leading text and quotes carriage returns in CSV", () => {
    const request = join(tmp, "formula.json");
    const output = join(tmp, "quote.csv");
    const descriptions = ["=1+1", "+1+1", "-1+1", "@SUM(1,1)", "\r=1+1", "normal\rtext"];
    writeFileSync(request, JSON.stringify({
      parts: [
        ...descriptions.map((description) => ({ part_no: "ABC-123", description, quantity: 10 })),
        { part_no: "=1+1", quantity: 10 },
      ],
    }));
    const res = run(request, tmp, ["--register", "fixture.csv", "--csv", output]);
    expect(res.status, res.stderr).toBe(0);

    const csv = readFileSync(output, "utf8");
    const rows = parse(csv, { columns: true }) as { part_no: string; description: string; unit_price: string }[];
    expect(rows.slice(0, 6).map((row) => row.description)).toEqual(descriptions.map((value, i) => i < 5 ? `'${value}` : value));
    expect(rows.slice(0, 6).every((row) => row.unit_price === "10")).toBe(true);
    expect(rows[6]?.part_no).toBe("'=1+1");
    expect(csv).toContain('"\'\r=1+1"');
    expect(csv).toContain('"normal\rtext"');
  });
});
