"""Synthetic-only tests; private temporary files, no archive or credentials needed."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal, ROUND_DOWN, localcontext
import importlib.util
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if os.name != "posix":
    raise unittest.SkipTest("WonderSearch offline boundary requires POSIX file/lock semantics")

import wondersearch_boundary as w

PRIVATE = os.environ.get("WONDERSEARCH_SYNTHETIC_TEST_DIR")
PLAN, MANIFEST, SEQUENCE = (w.digest(s.encode()) for s in ("synthetic-plan", "synthetic-manifest", "synthetic-sequence"))
RFQ = {"part_no": "SYNTHETIC-PART", "quantity": 12}
DOC = w.Document("synthetic-document", "synthetic-external", "1", w.digest(b"synthetic original"),
                 ("SYNTHETIC-SOURCE",), ("2020-01-01", "2020-01-02"), True)
SCOPE = w.Scope(PLAN, MANIFEST, "synthetic-case", "2021-01-01", ("SYNTHETIC-EXCLUDED",),
                (w.digest(b"synthetic target"),), True, "synthetic-isolated-drive", "synthetic-folder",
                (DOC,), (DOC.document_id,))
TEXT = "prefix café suffix".encode()
EXTRACTED = {(DOC.document_id, DOC.revision): TEXT}


def response():
    return {"drive_id": SCOPE.isolated_drive, "request_id": "synthetic-request", "model": w.MODEL,
            "effort_requested": "small", "effort_served": "small",
            "usage": {"cost": {"amount": "0.001", "currency": "USD"}},
            "results": [{"document_id": DOC.document_id, "external_id": DOC.external_id,
                "document_revision": DOC.revision, "passage_id": "synthetic-passage", "text": "café",
                "start_byte": 7, "end_byte": 12}]}


def reserve_worker(path, ordinal, queue):
    try:
        w.Budget(Path(path), PLAN).reserve(w.digest(str(ordinal).encode()), "0.01")
        queue.put("ok")
    except w.BoundaryError as error:
        queue.put(error.code)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-boundary-", dir=PRIVATE)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.ledger = w.Budget.create_synthetic(self.root / "ledger.jsonl", PLAN, "5")
        self.calls = []

    def kwargs(self, **changes):
        result = dict(scope=SCOPE, rfq=RFQ, effort="small", plan_sha256=PLAN, sequence_sha256=SEQUENCE,
                      frozen_scope_sha256=w.scope_digest(SCOPE),
                      frozen_query_sha256=w.digest(w.sanitized_query(RFQ).encode()),
                      budget=self.ledger, receipt_path=self.root / "receipt.json", extracted=EXTRACTED)
        result.update(changes)
        return result

    def transport(self, **kwargs):
        self.calls.append(kwargs)
        # A reservation is visible on disk before entering the provider seam.
        rows = [w.parse_json(line) for line in self.ledger.path.read_bytes().splitlines()]
        self.assertEqual(rows[-1]["event"], "reserve")
        self.assertEqual(rows[-1]["maximum"], "0.01")
        return response()

    def adapter(self):
        return w.WonderSearchAdapter(enabled=True, synthetic_transport=self.transport)

    def test_disabled_does_not_touch_scope_query_budget_or_transport(self):
        kwargs = self.kwargs(scope=None, rfq=None)
        with patch.object(w, "validate_scope", side_effect=AssertionError), patch.object(w, "sanitized_query", side_effect=AssertionError):
            result = w.WonderSearchAdapter(synthetic_transport=self.transport).retrieve(**kwargs)
        self.assertEqual(result, {"status": "disabled"})
        self.assertFalse(self.calls)

    def test_enabled_without_synthetic_transport_is_closed(self):
        with self.assertRaisesRegex(w.BoundaryError, "LIVE_NOT_REVIEWED"):
            w.WonderSearchAdapter(enabled=True).retrieve(**self.kwargs())

    def test_scope_before_query_not_post_filter(self):
        invalid = replace(SCOPE, permits_original_text=False)
        kwargs = self.kwargs(scope=invalid, frozen_query_sha256=PLAN)
        with patch.object(w, "sanitized_query", side_effect=AssertionError):
            with self.assertRaisesRegex(w.BoundaryError, "SCOPE_REQUIRED"):
                self.adapter().retrieve(**kwargs)
        self.assertFalse(self.calls)

    def test_excluded_quote_in_any_break_target_or_late_original_rejected(self):
        documents = [replace(DOC, quote_ids=("SYNTHETIC-SOURCE", "SYNTHETIC-EXCLUDED")),
                     replace(DOC, original_sha256=SCOPE.target_hashes[0]),
                     replace(DOC, availability_dates=("2020-01-01", "2021-01-01")),
                     replace(DOC, availability_dates=("2022-01-01",)),
                     replace(DOC, availability_dates=("2020-02-30",)),
                     replace(DOC, versioned=False), replace(DOC, availability_dates=())]
        for doc in documents:
            with self.subTest(doc=doc.versioned):
                scope = replace(SCOPE, documents=(doc,))
                with self.assertRaises(w.BoundaryError):
                    self.adapter().retrieve(**self.kwargs(scope=scope, frozen_scope_sha256=w.scope_digest(scope)))
        self.assertFalse(self.calls)

    def test_exact_server_scope_no_default_or_extra_members(self):
        for scope in (replace(SCOPE, isolated_drive="default"), replace(SCOPE, isolated_drive=""),
                      replace(SCOPE, folder_id=""), replace(SCOPE, server_membership=(DOC.document_id, "extra")),
                      replace(SCOPE, server_membership=()), replace(SCOPE, documents=())):
            with self.assertRaises(w.BoundaryError):
                self.adapter().retrieve(**self.kwargs(scope=scope, frozen_scope_sha256=w.scope_digest(scope)))
        self.assertFalse(self.calls)

    def test_missing_target_exclusions_and_ambiguous_scope_ids_rejected(self):
        scopes = (replace(SCOPE, target_hashes=()), replace(SCOPE, target_hashes=("bad-hash",)),
                  replace(SCOPE, excluded_quotes=(" ",)),
                  replace(SCOPE, server_membership=(DOC.document_id, DOC.document_id)),
                  replace(SCOPE, documents=(replace(DOC, quote_ids=("",)),)),
                  replace(SCOPE, documents=(replace(DOC, revision=1),)))
        for scope in scopes:
            with self.assertRaises(w.BoundaryError):
                self.adapter().retrieve(**self.kwargs(scope=scope, frozen_scope_sha256=w.scope_digest(scope)))
        self.assertFalse(self.calls)

    def test_effort_and_plan_query_scope_pins(self):
        for change in ({"effort": "giant"}, {"plan_sha256": MANIFEST}, {"frozen_scope_sha256": MANIFEST},
                       {"frozen_query_sha256": MANIFEST}, {"sequence_sha256": "not-a-pin"}):
            with self.assertRaises(w.BoundaryError):
                self.adapter().retrieve(**self.kwargs(**change))
        self.assertFalse(self.calls)

    def test_query_rejects_oracle_and_free_text_fields(self):
        for extra in ("price", "source_quote_no", "notes", "actual_unit_price", "target_document"):
            with self.assertRaises(w.BoundaryError):
                w.sanitized_query({**RFQ, extra: "synthetic secret"})

    def test_storage_unknown_overflow_bool_and_forecast(self):
        w.storage_guard(used=10, reserved=20, incoming=30, capacity=1_000_000_000)
        for args in ((None, 0, 0, 100), (0, True, 0, 100), (1, 0, 1_000_000_000, 2_000_000_000)):
            with self.assertRaises(w.BoundaryError):
                w.storage_guard(used=args[0], reserved=args[1], incoming=args[2], capacity=args[3])
        kwargs = dict(searches_per_effort=250, import_usd="0", processing_usd="0", storage_usd="0", available_usd="5")
        self.assertEqual(w.import_forecast(**kwargs), Decimal("3.3750"))
        for change in ({"import_usd": None}, {"available_usd": None}, {"storage_usd": "2"}, {"available_usd": "3"}):
            with self.assertRaises(w.BoundaryError):
                w.import_forecast(**{**kwargs, **change})

    def test_budget_low_balance_blocks_worst_effort_before_call(self):
        budget = w.Budget.create_synthetic(self.root / "low.jsonl", PLAN, "0.009")
        with self.assertRaisesRegex(w.BoundaryError, "BUDGET_EXHAUSTED"):
            self.adapter().retrieve(**self.kwargs(budget=budget))
        self.assertFalse(self.calls)
        with self.assertRaisesRegex(w.BoundaryError, "UNKNOWN_BALANCE"):
            w.Budget.create_synthetic(self.root / "unknown.jsonl", PLAN, None)

    def test_timeout_reserved_no_retry_unknown_charge_not_refunded(self):
        calls = []
        def timeout(**kwargs):
            calls.append(kwargs)
            raise TimeoutError("synthetic credential query and document must not escape")
        budget = w.Budget.create_synthetic(self.root / "timeout.jsonl", PLAN, "0.01")
        adapter = w.WonderSearchAdapter(enabled=True, synthetic_transport=timeout)
        with self.assertRaisesRegex(w.BoundaryError, "^PROVIDER_FAILURE$"):
            adapter.retrieve(**self.kwargs(budget=budget))
        with self.assertRaisesRegex(w.BoundaryError, "ATTEMPT_ALREADY_RESERVED"):
            adapter.retrieve(**self.kwargs(budget=budget))
        with self.assertRaisesRegex(w.BoundaryError, "BUDGET_EXHAUSTED"):
            budget.reserve(w.digest(b"another"), "0.001")
        self.assertEqual(len(calls), 1)

    def test_concurrent_process_reservations_cannot_overspend(self):
        budget = w.Budget.create_synthetic(self.root / "concurrent.jsonl", PLAN, "0.03")
        ctx = multiprocessing.get_context("fork")
        queue = ctx.Queue()
        workers = [ctx.Process(target=reserve_worker, args=(str(budget.path), i, queue)) for i in range(12)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
        verdicts = [queue.get(timeout=2) for _ in workers]
        self.assertEqual(verdicts.count("ok"), 3)
        self.assertEqual(verdicts.count("BUDGET_EXHAUSTED"), 9)
        queue.close()

    def test_success_saved_receipt_resume_not_repeat_known_cost_reconciliation(self):
        result = self.adapter().retrieve(**self.kwargs())
        self.assertEqual(result["actual_cost_usd"], "0.001")
        self.assertEqual(result["manufacturing_compatibility"], "unknown")
        self.assertIsNone(result["snapshot_id"])
        self.assertGreaterEqual(result["latency_ms"], 0)
        saved = (self.root / "receipt.json").read_bytes()
        self.ledger.resume(result["operation_sha256"], saved)
        with self.assertRaises(w.BoundaryError):
            self.ledger.resume(result["operation_sha256"], b"changed")
        with self.assertRaises(w.BoundaryError):
            self.adapter().retrieve(**self.kwargs())
        # Known receipt releases only known unused reservation (0.009).
        self.ledger.reserve(w.digest(b"next"), "4.999")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["drive_id"], SCOPE.isolated_drive)
        self.assertEqual(self.calls[0]["folder_id"], SCOPE.folder_id)

    def test_lost_receipt_and_overcharge_poison_resumption(self):
        op = w.digest(b"lost")
        self.ledger.reserve(op, "0.01")
        with self.assertRaises(w.BoundaryError):
            self.ledger.resume(op, b"missing")
        path = self.root / "overcharge.json"
        w.freeze_private(path, {"operation_sha256": op, "actual_cost_usd": "0.02",
                                "effort_served": "large", "request_id": "synthetic-overcharge"})
        with self.assertRaisesRegex(w.BoundaryError, "COST_EXCEEDED"):
            self.ledger.settle(op, path)
        with self.assertRaisesRegex(w.BoundaryError, "COST_EXCEEDED"):
            self.ledger.reserve(w.digest(b"next"), "0.01")

    def test_settlement_requires_saved_operation_bound_receipt(self):
        op = w.digest(b"reserved")
        self.ledger.reserve(op, "0.01")
        with self.assertRaisesRegex(w.BoundaryError, "RECEIPT_REQUIRED"):
            self.ledger.settle(op, self.root / "missing.json")
        path = self.root / "wrong-operation.json"
        w.freeze_private(path, {"operation_sha256": w.digest(b"other"), "actual_cost_usd": "0",
                                "effort_served": "small", "request_id": "synthetic-receipt"})
        with self.assertRaisesRegex(w.BoundaryError, "RECEIPT_REQUIRED"):
            self.ledger.settle(op, path)
        with self.ledger._locked() as (_, records, _):
            self.assertEqual(self.ledger._state(records)[1], Decimal("0.01"))

    def test_save_before_settle_crash_reconciles_without_another_call(self):
        with patch.object(self.ledger, "settle", side_effect=OSError("synthetic crash")):
            with self.assertRaisesRegex(w.BoundaryError, "PROVIDER_FAILURE"):
                self.adapter().retrieve(**self.kwargs())
        path = self.root / "receipt.json"
        op = w.parse_json(path.read_bytes())["operation_sha256"]
        with self.assertRaisesRegex(w.BoundaryError, "IMMUTABLE_CONFLICT"):
            self.adapter().retrieve(**self.kwargs())
        self.ledger.settle(op, path)
        self.ledger.resume(op, path.read_bytes())
        self.assertEqual(len(self.calls), 1)
        with self.assertRaisesRegex(w.BoundaryError, "RECEIPT_REQUIRED"):
            self.ledger.settle(op, path)

    def test_invalid_citation_still_saves_known_cost_and_poisoning_overcharge(self):
        for amount in ("0.001", "0.02"):
            with self.subTest(amount=amount):
                budget = w.Budget.create_synthetic(self.root / f"cost-{amount}.jsonl", PLAN, "0.02")
                path = self.root / f"receipt-{amount}.json"
                bad = response()
                bad["usage"]["cost"]["amount"] = amount
                bad["results"][0]["text"] = "synthetic-untrusted-text"
                adapter = w.WonderSearchAdapter(enabled=True, synthetic_transport=lambda **_: bad)
                expected = "CITATION_MISMATCH" if amount == "0.001" else "COST_EXCEEDED"
                with self.assertRaisesRegex(w.BoundaryError, expected):
                    adapter.retrieve(**self.kwargs(budget=budget, receipt_path=path))
                receipt = w.parse_json(path.read_bytes())
                self.assertEqual(receipt["actual_cost_usd"], amount)
                self.assertEqual(receipt["citation_status"], "rejected")
                self.assertEqual(receipt["citations"], [])
                self.assertNotIn(b"synthetic-untrusted-text", path.read_bytes())
                with budget._locked() as (_, records, _):
                    _, used, _, poisoned = budget._state(records)
                    self.assertEqual(used, Decimal(amount))
                    self.assertEqual(poisoned, amount == "0.02")
                if poisoned:
                    with self.assertRaisesRegex(w.BoundaryError, "COST_EXCEEDED"):
                        budget.reserve(w.digest(b"next"), "0.001")

    def test_invalid_accounting_and_failed_receipt_write_keep_full_reservation(self):
        for name in ("unknown-accounting", "write-failure"):
            budget = w.Budget.create_synthetic(self.root / f"{name}.jsonl", PLAN, "0.01")
            raw = response()
            if name == "unknown-accounting":
                raw["usage"]["cost"]["currency"] = "unknown"
            adapter = w.WonderSearchAdapter(enabled=True, synthetic_transport=lambda **_: raw)
            with patch.object(w, "freeze_private", side_effect=OSError("synthetic sensitive path")):
                with self.assertRaises(w.BoundaryError):
                    adapter.retrieve(**self.kwargs(budget=budget))
            with self.assertRaisesRegex(w.BoundaryError, "BUDGET_EXHAUSTED"):
                budget.reserve(w.digest(b"next"), "0.001")
            self.assertFalse((self.root / "receipt.json").exists())

    def test_money_math_does_not_inherit_low_precision_round_down(self):
        budget = w.Budget.create_synthetic(self.root / "precision.jsonl", PLAN, "0.019")
        with localcontext() as ctx:
            ctx.prec = 1
            ctx.rounding = ROUND_DOWN
            budget.reserve(w.digest(b"first"), "0.019")
            with self.assertRaisesRegex(w.BoundaryError, "BUDGET_EXHAUSTED"):
                budget.reserve(w.digest(b"second"), "0.001")
            self.assertEqual(w.import_forecast(searches_per_effort=250, import_usd="0", processing_usd="0",
                                              storage_usd="0", available_usd="5"), Decimal("3.3750"))
            with self.assertRaisesRegex(w.BoundaryError, "BUDGET_EXHAUSTED"):
                w.import_forecast(searches_per_effort=250, import_usd="1.626", processing_usd="0",
                                  storage_usd="0", available_usd="5")

    def test_ledger_tamper_partial_write_and_plan_change_fail_closed(self):
        with self.assertRaises(w.BoundaryError):
            w.Budget(self.ledger.path, MANIFEST).reserve(w.digest(b"operation"), "0.01")
        with self.ledger.path.open("ab") as stream:
            stream.write(b'{"partial":')
        with self.assertRaises(w.BoundaryError):
            self.ledger.reserve(w.digest(b"operation"), "0.01")

    def test_response_identity_revision_text_utf8_and_offsets(self):
        valid = w.validate_response(response(), SCOPE, "small", EXTRACTED)
        self.assertEqual(valid["citations"][0]["text"], "café")
        changes = [{"document_id": "other"}, {"external_id": "other"}, {"document_revision": "2"},
                   {"text": "cafe"}, {"start_byte": 8}, {"end_byte": 11}, {"end_byte": 500},
                   {"start_byte": True}, {"passage_id": ""}]
        for change in changes:
            bad = response()
            bad["results"][0].update(change)
            with self.assertRaises(w.BoundaryError):
                w.validate_response(bad, SCOPE, "small", EXTRACTED)
        for change in ({"drive_id": "other"}, {"model": "other"}, {"effort_requested": "large"}, {"effort_served": "unknown"}):
            with self.assertRaises(w.BoundaryError):
                w.validate_response({**response(), **change}, SCOPE, "small", EXTRACTED)
        with self.assertRaises(w.BoundaryError):
            w.validate_response(response(), SCOPE, "small", {(DOC.document_id, "latest"): TEXT})

    def test_returned_usage_and_degraded_effort_authoritative(self):
        raw = response()
        raw.update(effort_requested="large", effort_served="medium")
        raw["usage"]["cost"]["amount"] = "0.0025"
        result = w.validate_response(raw, SCOPE, "large", EXTRACTED)
        self.assertEqual(result["actual_cost_usd"], "0.0025")
        self.assertEqual(result["effort_served"], "medium")

    def test_private_immutable_writes_redaction_and_safe_serialization(self):
        file = self.root / "freeze.json"
        first = w.freeze_private(file, {"synthetic": True})
        self.assertEqual(first, w.freeze_private(file, {"synthetic": True}))
        self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(w.BoundaryError):
            w.freeze_private(file, {"changed": True})
        link = self.root / "linked.json"
        link.symlink_to(file)
        with self.assertRaises(w.BoundaryError):
            w.freeze_private(link, {})
        for value in (float("inf"), float("nan"), {"x": Decimal("1")}):
            with self.assertRaises(w.BoundaryError):
                w.json_bytes(value)
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}'):
            with self.assertRaises(w.BoundaryError):
                w.parse_json(raw)
        self.assertEqual(w.safe_error(ValueError("synthetic-sensitive-payload")), "PROVIDER_FAILURE")
        self.assertEqual(w.safe_error(w.BoundaryError("synthetic-sensitive-payload")), "INVALID_INPUT")
        altered = w.BoundaryError("PROVIDER_FAILURE")
        for code in ("synthetic-sensitive-payload", ["unhashable"], None):
            altered.code = code
            self.assertEqual(w.safe_error(altered), "PROVIDER_FAILURE")

    def test_subprocess_credential_binding_does_not_mutate_parent_or_copy_secrets(self):
        parent = {"WONDERSEARCH_STEVE_RETRIEVAL_API_KEY": "synthetic-wonder-key", "POLYGRES_API_KEY": "synthetic-original-key",
                  "ANTHROPIC_API_KEY": "synthetic-other", "HTTP_PROXY": "synthetic-proxy", "OTEL_EXPORTER_OTLP_ENDPOINT": "synthetic-trace"}
        original = dict(parent)
        env = w.sdk_subprocess_environment(parent)
        self.assertEqual(parent, original)
        self.assertEqual(env["POLYGRES_API_KEY"], "synthetic-wonder-key")
        self.assertEqual(env["POLYGRES_BASE_URL"], w.BASE_URL)
        self.assertFalse(set(parent).intersection(env) - {"POLYGRES_API_KEY"})

    def test_all_case_denominator_failed_held_unattempted_and_independent_labels(self):
        ids = ("a", "b", "c", "d", "e")
        base = {k: {"status": s} for k, s in zip(ids, ("failed", "held", "not_run", "completed", "completed"))}
        candidate = deepcopy(base)
        for key, left, right in (("d", False, True), ("e", True, False)):
            for output, label in ((base, left), (candidate, right)):
                output[key].update(relevant=label, independent=True, label_evidence_sha256=MANIFEST)
        result = w.paired_gains(ids, base, candidate)
        self.assertEqual((result["all_case_denominator"], result["improvements"], result["regressions"]), (5, 1, 1))
        self.assertEqual(result["paired_independent_judgments"], 2)
        with self.assertRaises(w.BoundaryError):
            w.paired_gains(ids, base, {k: v for k, v in candidate.items() if k != "a"})
        candidate["d"]["independent"] = False
        with self.assertRaises(w.BoundaryError):
            w.paired_gains(ids, base, candidate)
        candidate["d"]["independent"] = True
        candidate["d"]["latency_ms"] = float("nan")
        with self.assertRaises(w.BoundaryError):
            w.paired_gains(ids, base, candidate)

    def test_failed_preflight_validation_cannot_be_promoted(self):
        spec = importlib.util.spec_from_file_location("eval_cli", Path(__file__).resolve().parents[1] / "wondersearch-eval.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        w.freeze_private(self.root / "preflight-validation.private.json",
                         {"status": "failed", "live_safe": False, "artifact_count": 11})
        with self.assertRaisesRegex(w.BoundaryError, "PIN_MISMATCH"):
            module.verify_preflight(self.root)

    def test_blocked_report_complete_null_not_zero_and_cli_no_argument_echo(self):
        spec = importlib.util.spec_from_file_location("eval_cli", Path(__file__).resolve().parents[1] / "wondersearch-eval.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate_run_dir(self.root)  # Arbitrary owner-private directory is portable.
        self.assertEqual(module.preflight_artifact_path(self.root, "/former/home/private/synthetic.json"),
                         self.root / "synthetic.json")
        self.assertEqual(module.preflight_artifact_path(self.root, "synthetic.json"), self.root / "synthetic.json")
        with self.assertRaises(w.BoundaryError):
            module.preflight_artifact_path(self.root, "../synthetic.json")
        with self.assertRaises(w.BoundaryError):
            module.validate_run_dir(Path(__file__).resolve().parents[2])
        result = module.blocked_report([f"synthetic-{i}" for i in range(250)], {"plan": PLAN})
        self.assertEqual(result["summary"]["all_case_denominator"], 250)
        self.assertEqual(len(result["cases"]), 250)
        self.assertIsNone(result["summary"]["improvements"])
        self.assertIsNone(result["summary"]["pricing_outcomes"])
        self.assertTrue(all(r["status"] == "not_run" and r["reason_codes"]
                            for c in result["cases"] for r in c["arms"].values()))
        for case in result["cases"]:
            self.assertEqual(case["arms"]["unchanged-estimator"]["reason_codes"], ["BASELINE_NOT_EXECUTED"])
            for arm in w.EFFORTS:
                self.assertEqual(case["arms"][arm]["reason_codes"], module.BLOCKERS)
        command = [sys.executable, "-B", str(Path(module.__file__)), "--synthetic-sensitive-input"]
        process = subprocess.run(command, capture_output=True)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stderr, b"INVALID_INPUT\n")
        self.assertEqual(process.stdout, b"")


if __name__ == "__main__":
    unittest.main()
