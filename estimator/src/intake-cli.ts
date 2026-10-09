#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { retainIntake, verifyRetainedIntake } from "./intake.js";
import { assertOrderRequest } from "./order.js";

try {
  const [request, flag, manifest, reviewerFlag, operator, ...extra] = process.argv.slice(2);
  if (!request || flag !== "--attachments" || !manifest || reviewerFlag !== "--operator" || !operator || extra.length) {
    throw new Error("usage: intake-cli request.json --attachments uploads.json --operator NAME");
  }
  const result = retainIntake(request, JSON.parse(readFileSync(manifest, "utf8")), operator, assertOrderRequest);
  assertOrderRequest(result.request);
  verifyRetainedIntake(result.request);
  console.log(JSON.stringify({ status: "RETAINED_UNTRUSTED_INTAKE", request_path: join(result.directory, "request.json"),
    requires_human_review: true, customer_release_authorized: false }));
} catch {
  // Never echo customer input, filesystem paths or attachment content on failure.
  console.error("Intake retention failed: check input contract, upload bindings and private storage; no quote released");
  process.exitCode = 2;
}
