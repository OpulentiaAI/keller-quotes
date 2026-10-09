#!/usr/bin/env python3
"""Reproduce blocked import/evaluation evidence without any provider or estimator call.

Usage: see the native AU map 'WonderSearch isolated evaluation boundary'.
No live flag exists. This is not an uploader, search executor, or priced evaluation.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
import os
import re
import subprocess
import sys

from wondersearch_boundary import (BASE_URL, SDK_VERSION, MODEL, EFFORTS, PRICES,
    BoundaryError, digest, freeze_private, json_bytes, parse_json, pin, private_path, require, safe_error)

PINS = {
    "plan": "7199501d8dfc75ac7072a458a474f8923cbb36c398f44b6c99af6059ffec10a3",
    "cases": "12414d36a0f2d721d86d74dea61a66673c043931668f7573ece4f27553445311",
    "register": "a7d84545b00ecb3f976d100d3e214885cca009189c1f59c500687539e5728757",
}
BASELINE = "34a0880037cf1cd40ae062e68b7201ad0b8c4cd9"
BLOCKERS = [
    "WHOLE_ORIGINAL_DOCUMENT_AUTHORIZATION_MISSING",
    "PRICE_ONLY_SCOPE_CANNOT_BE_BROADENED",
    "IMMUTABLE_CASE_ELIGIBLE_SERVER_SCOPE_UNPROVEN",
    "CREDITS_USED_RESERVED_STORAGE_UNVERIFIED",
    "IMPORT_PROCESSING_STORAGE_CHARGES_UNVERIFIED",
    "NARROWER_FROZEN_ORIGINAL_MANIFEST_NOT_ESTABLISHED",
    "LIVE_TRANSPORT_AND_LEDGER_MIGRATION_NOT_REVIEWED",
]
SOURCE_FILES = ["estimator/src/estimate.ts", "estimator/src/retrieve.ts", "estimator/src/price.ts",
                "estimator/src/register.ts", "estimator/src/types.ts", "estimator/src/jev.ts",
                "estimator/package-lock.json", "evals/run-eval.ts", "evals/metrics.ts", "evals/selection.ts"]
ARMS = ("unchanged-estimator", *EFFORTS)


def file_hash(path: Path) -> str:
    # Stream large verified registers/artifacts; never display bytes or input paths.
    import hashlib
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def pinned_json(path: Path, expected: str):
    data = path.read_bytes()
    require(digest(data) == expected, "PIN_MISMATCH")
    return parse_json(data)


def source_hash(root: Path, files: list[str]) -> str:
    return digest(json_bytes({name: file_hash(root / name) for name in files}))


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False,
                            env={"PATH": os.defpath, "LANG": "C", "GIT_OPTIONAL_LOCKS": "0"})
    require(result.returncode == 0, "PIN_MISMATCH")
    return result.stdout.decode().strip()


def verify_baseline(root: Path, plan: dict) -> dict:
    require(root.is_absolute() and root == root.resolve(), "PIN_MISMATCH")
    require(plan["baseline_commit"] == BASELINE and git(root, "rev-parse", "HEAD") == BASELINE,
            "PIN_MISMATCH")
    require(not git(root, "status", "--porcelain", "--untracked-files=no"), "PIN_MISMATCH")
    return {"commit": BASELINE, "source_lock_sha256": source_hash(root, SOURCE_FILES),
            "tracked_clean": True, "executed": False}


def preflight_artifact_path(run: Path, stored: str) -> Path:
    # Retained absolute receipt paths are provenance, not a required workstation layout.
    # A restored bundle uses the same direct-child filenames and unchanged pinned bytes.
    path = Path(stored)
    require(path.is_absolute() or len(path.parts) == 1, "PRIVATE_PATH_REQUIRED")
    require(path.name not in ("", ".", ".."), "PRIVATE_PATH_REQUIRED")
    return run / path.name


def verify_preflight(run: Path) -> dict:
    validation_path = run / "preflight-validation.private.json"
    private_path(validation_path)
    validation = parse_json(validation_path.read_bytes())
    require(validation["status"] == "passed" and validation["live_safe"] is False and
            validation["artifact_count"] == 11, "PIN_MISMATCH")
    manifest = pinned_json(run / "preflight-artifact-manifest.v2.private.json", validation["manifest_sha256"])
    require(len(manifest["files"]) == 11, "PIN_MISMATCH")
    seen = set()
    for entry in manifest["files"]:
        path = preflight_artifact_path(run, entry["path"])
        require(path.name not in seen, "PIN_MISMATCH")
        seen.add(path.name)
        private_path(path)
        require(path.stat().st_size == entry["bytes"] and file_hash(path) == pin(entry["sha256"]), "PIN_MISMATCH")
    pinned_json(run / "preflight-clarifications.private.json", validation["clarifications_sha256"])
    preflight = parse_json((run / "preflight.v2.private.json").read_bytes())
    require(preflight["live_safe"] is False and preflight["frozen_case_count"] == 250, "PIN_MISMATCH")
    return {"preflight_sha256": file_hash(run / "preflight.v2.private.json"),
            "validation_sha256": file_hash(validation_path),
            "manifest_sha256": validation["manifest_sha256"],
            "clarifications_sha256": validation["clarifications_sha256"],
            "prior_budget_ledger_sha256": file_hash(run / "budget-ledger.private.jsonl")}


def blocked_report(ids: list[str], bindings: dict) -> dict:
    require(bool(ids) and len(set(ids)) == len(ids) and all(type(x) is str and x for x in ids))
    # No target, input RFQ, source locator, price, or invented relevance label is copied.
    cases = [{"case_id": case_id, "arms": {arm: {"status": "not_run", "attempted": False,
              "reason_codes": ["BASELINE_NOT_EXECUTED"] if arm == "unchanged-estimator" else list(BLOCKERS),
              "independent_relevance": None, "citation_verdict": None,
              "manufacturing_compatibility": "unknown", "latency_ms": None,
              "actual_cost_usd": None, "served_effort": None, "pricing_outcome": None}
              for arm in ARMS}} for case_id in ids]
    return {"schema_version": 1, "status": "blocked", "population": "development",
            "bindings": bindings, "blockers": BLOCKERS, "cases": cases,
            "summary": {"all_case_denominator": len(ids), "comparison_attempts": 0,
                "arms": {arm: {"not_run": len(ids), "failed": 0, "held": 0, "completed": 0,
                               "attempted": 0, "independently_labelled": 0} for arm in ARMS},
                "relevance": None, "citation_accuracy": None, "manufacturing_assessed": 0,
                "latency_ms": None, "actual_cost_usd": None,
                "improvements": None, "regressions": None, "pricing_outcomes": None},
            "historical_tolerance_diagnostic_only": True, "threshold_unchanged": True,
            "live_safe": False}


def validate_run_dir(run: Path) -> None:
    require(run.is_absolute() and run == run.resolve(), "PRIVATE_PATH_REQUIRED")
    require(not any((parent / ".git").exists() for parent in (run, *run.parents)), "PRIVATE_PATH_REQUIRED")
    private_path(run / "implementation-sentinel.private.json")


def execute(args) -> dict:
    run = args.run_dir
    validate_run_dir(run)
    preflight_dir = args.preflight_dir or run
    require(preflight_dir.is_absolute() and preflight_dir == preflight_dir.resolve(), "PRIVATE_PATH_REQUIRED")
    prefix = args.artifact_prefix
    require(re.fullmatch(r"[a-z][a-z0-9-]{0,63}", prefix) is not None)
    plan = pinned_json(args.plan, PINS["plan"])
    data = args.cases.read_bytes()
    require(digest(data) == PINS["cases"] and file_hash(args.register) == PINS["register"], "PIN_MISMATCH")
    cases = [parse_json(line) for line in data.splitlines() if line.strip()]
    ids = [case["id"] for case in cases]
    require(len(ids) == 250 and len(set(ids)) == 250, "PIN_MISMATCH")
    require(plan["attempt_denominator"] == 250 and plan["threshold_unchanged"] is True, "PIN_MISMATCH")
    baseline = verify_baseline(args.baseline_repo, plan)
    prior = verify_preflight(preflight_dir)
    repo = Path(__file__).resolve().parent.parent
    implementation = source_hash(repo, ["scripts/wondersearch_boundary.py", "scripts/wondersearch-eval.py",
                                       "scripts/wondersearch-requirements.txt", "scripts/wondersearch_sdk_contract.py",
                                       "scripts/test/test_wondersearch_boundary.py", "scripts/test/test_wondersearch_sdk_contract.py",
                                       "scripts/verify.mjs"])
    bindings = {**PINS, **prior, "baseline": baseline, "implementation_sha256": implementation,
                "adapter_sdk_version": SDK_VERSION, "base_url": BASE_URL, "model": MODEL,
                "selected_case_ids_sha256": digest(json_bytes(ids))}
    # A blocked declaration, NOT a selected/authorized upload manifest. No originals
    # are opened or altered here, and diagnostic candidate sets are not promoted.
    source_manifest = {"schema_version": 1, "status": "blocked_no_authorized_manifest",
        "bindings": bindings, "documents": [], "upload_authorized": False,
        "original_inventory_sha256": file_hash(preflight_dir / "original-document-inventory.v2.private.json"),
        "hard_storage_cap_bytes": 1_000_000_000, "blockers": BLOCKERS}
    source_sha = freeze_private(run / f"{prefix}-source-manifest.blocked.private.json", source_manifest)
    # Fix order before any future judgment, but DO NOT manufacture an authorized RFQ.
    # A real plan must freeze reviewed query bytes and scope for every entry first.
    sequence = {"schema_version": 1, "status": "blocked_not_executable", "bindings": bindings,
        "source_manifest_sha256": source_sha, "query_sequence": [
            {"ordinal": i * 3 + j, "case_id": case_id, "effort": effort,
             "query_sha256": None, "scope_sha256": None, "status": "not_run"}
            for i, case_id in enumerate(ids) for j, effort in enumerate(EFFORTS)],
        "forecast_search_only_usd": str(sum(PRICES.values(), Decimal(0)) * len(ids)),
        "other_charges_usd": None, "total_forecast_usd": None, "hard_budget_cap_usd": "5"}
    sequence_sha = freeze_private(run / f"{prefix}-query-sequence.blocked.private.json", sequence)
    bindings = {**bindings, "source_manifest_sha256": source_sha, "query_sequence_sha256": sequence_sha}
    report = blocked_report(ids, bindings)
    report_sha = freeze_private(run / f"{prefix}-paired-report.blocked.private.json", report)
    # Public projection is a fixed allowlist of aggregates/hashes, never a generic
    # serialization of preflight, provider errors, private IDs, or per-case results.
    summary = {"schema_version": 1, "live_safe": False, "status": "blocked",
        "population": "development", "cohort_cases": 250, "planned_searches": 750,
        "comparison_attempts": 0, "paid_calls_this_execution": 0, "drives_created_this_execution": 0,
        "provider_requests_this_execution": 0, "source_bytes_uploaded_this_execution": 0,
        "hard_budget_cap_usd": "5", "hard_storage_cap_bytes": 1_000_000_000,
        "observed_initial_available_usd": None, "workspace_used_bytes": None, "workspace_reserved_bytes": None,
        "arms": report["summary"]["arms"],
        "forecast_search_only_usd": sequence["forecast_search_only_usd"],
        "other_charges_usd": None, "actual_cost_usd": None, "relevance": None,
        "improvements": None, "regressions": None, "pricing_outcomes": None,
        "baseline_commit": BASELINE, "baseline_executed": False,
        "input_sha256": PINS, "source_manifest_sha256": source_sha,
        "query_sequence_sha256": sequence_sha, "private_report_sha256": report_sha,
        "implementation_sha256": implementation, "blockers": BLOCKERS}
    freeze_private(run / f"{prefix}-summary.public.json", summary)
    # Existing financial ledger MUST remain untouched; synthetic tests use separate
    # temporary ledgers, never a second live experiment ledger.
    require(file_hash(preflight_dir / "budget-ledger.private.jsonl") == prior["prior_budget_ledger_sha256"], "PIN_MISMATCH")
    return summary


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        raise BoundaryError("INVALID_INPUT")  # argparse otherwise echoes arbitrary input.


def main() -> int:
    os.umask(0o077)
    try:
        parser = SafeParser(description=__doc__, allow_abbrev=False)
        parser.add_argument("command", choices=("import-plan", "eval-blocked"))
        for name in ("run-dir", "plan", "cases", "register", "baseline-repo"):
            parser.add_argument("--" + name, required=True, type=Path)
        parser.add_argument("--preflight-dir", type=Path)
        parser.add_argument("--artifact-prefix", default="review-v4")
        summary = execute(parser.parse_args())
        sys.stdout.buffer.write(json_bytes(summary))
        return 0
    except Exception as error:
        sys.stderr.write(safe_error(error) + "\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
