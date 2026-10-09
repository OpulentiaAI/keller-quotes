"""Offline-only WonderSearch evaluation boundary; not imported by the estimator.

No SDK/network implementation is enabled. Injected transports are for synthetic tests
only. A scope declaration is NOT evidence of server-enforced immutable membership.
Live use requires a separately reviewed implementation, not an environment toggle.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Context, Decimal, InvalidOperation, localcontext
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Callable, Mapping

SDK_VERSION = "0.2.0"
BASE_URL = "https://api.wondersearch.ai"
MODEL = "wondersearch-1.1"
PRICES = {"small": Decimal("0.001"), "medium": Decimal("0.0025"), "large": Decimal("0.01")}
EFFORTS = tuple(PRICES)
CAP = Decimal("5")
STORAGE_CAP = 1_000_000_000  # Conservative decimal GB, not GiB.
CODES = frozenset({"DISABLED", "LIVE_NOT_REVIEWED", "INVALID_INPUT", "PIN_MISMATCH",
    "PRIVATE_PATH_REQUIRED", "IMMUTABLE_CONFLICT", "LEDGER_INVALID", "BUDGET_EXHAUSTED",
    "UNKNOWN_BALANCE", "ATTEMPT_ALREADY_RESERVED", "RECEIPT_REQUIRED", "COST_EXCEEDED",
    "SCOPE_REQUIRED", "EXCLUDED_SOURCE", "LATE_OR_UNVERSIONED", "UNSUPPORTED_EFFORT",
    "STORAGE_UNKNOWN", "STORAGE_OVERFLOW", "CITATION_MISMATCH", "RESPONSE_MISMATCH",
    "PROVIDER_FAILURE", "CREDENTIAL_REQUIRED"})


class BoundaryError(Exception):
    def __init__(self, code: str):
        self.code = code if code in CODES else "INVALID_INPUT"
        super().__init__(self.code)


def require(ok: bool, code: str = "INVALID_INPUT") -> None:
    if not ok:
        raise BoundaryError(code)


def safe_error(error: BaseException) -> str:
    """Never stringify HTTP/SDK exceptions, request IDs, bodies, paths or URLs."""
    code = getattr(error, "code", None) if type(error) is BoundaryError else None
    return code if type(code) is str and code in CODES else "PROVIDER_FAILURE"


def json_bytes(value: object) -> bytes:
    try:
        return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise BoundaryError("INVALID_INPUT") from None


def parse_json(data: bytes) -> object:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result)
            result[key] = value
        return result
    try:
        return json.loads(data, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(BoundaryError("INVALID_INPUT")))
    except (ValueError, UnicodeError):
        raise BoundaryError("INVALID_INPUT") from None


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pin(value: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None)
    return value


def money(value: str) -> Decimal:
    require(isinstance(value, str) and len(value) <= 32)
    require(re.fullmatch(r"\d+(?:\.\d{1,9})?", value) is not None)
    try:
        result = Decimal(value)
        require(result.is_finite() and result >= 0)
        return result
    except InvalidOperation:
        raise BoundaryError("INVALID_INPUT") from None


def private_path(path: Path) -> None:
    """Reject symlinks (including ancestors), shared parents and hard-linked files."""
    require(path.is_absolute() and path == path.resolve(), "PRIVATE_PATH_REQUIRED")
    for parent in path.parents:
        st = parent.lstat()
        require(stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode), "PRIVATE_PATH_REQUIRED")
        require(st.st_uid in (0, os.getuid()), "PRIVATE_PATH_REQUIRED")
        require(not st.st_mode & 0o022 or (st.st_uid == 0 and st.st_mode & stat.S_ISVTX),
                "PRIVATE_PATH_REQUIRED")
    parent = path.parent.stat()
    require(parent.st_uid == os.getuid() and not parent.st_mode & 0o077, "PRIVATE_PATH_REQUIRED")
    if path.exists():
        st = path.lstat()
        require(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_uid == os.getuid()
                and not st.st_mode & 0o177, "PRIVATE_PATH_REQUIRED")


def freeze_private(path: Path, value: object) -> str:
    """Exclusive, fsynced, immutable write; identical resumes do not overwrite.

    A partial/crashed write blocks resume rather than silently repairing evidence.
    """
    private_path(path)
    data = json_bytes(value)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        require(path.read_bytes() == data, "IMMUTABLE_CONFLICT")
        return digest(data)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return digest(data)


def storage_guard(*, used: int | None, reserved: int | None, incoming: int,
                  capacity: int | None) -> None:
    require(all(type(x) is int and x >= 0 for x in (used, reserved, capacity)), "STORAGE_UNKNOWN")
    require(type(incoming) is int and incoming >= 0)
    require(used + reserved + incoming <= min(capacity, STORAGE_CAP), "STORAGE_OVERFLOW")


class Budget:
    """Single append-only, flock/fsync/hash-chained reservation ledger.

    Reconciles only known, saved receipts to actual cost. Unknown charges keep the
    full worst-effort reservation. Lost receipts/timeouts cannot be replayed. This format
    deliberately rejects the earlier GET-only ledger: no automatic migration/reset.
    Caller-supplied balance is not authoritative billing proof; live remains blocked.
    """
    def __init__(self, path: Path, plan_sha256: str):
        self.path, self.plan = path, pin(plan_sha256)

    @classmethod
    def create_synthetic(cls, path: Path, plan_sha256: str, available: str | None,
                         cap: str = "5") -> Budget:
        require(available is not None, "UNKNOWN_BALANCE")
        ceiling = min(money(available), money(cap), CAP)
        body = {"schema": 1, "event": "synthetic_budget", "plan": pin(plan_sha256),
                "ceiling": str(ceiling), "prev": "0" * 64}
        body["sha256"] = digest(json_bytes(body))
        freeze_private(path, body)
        return cls(path, plan_sha256)

    @contextmanager
    def _locked(self):
        private_path(self.path)
        fd = os.open(self.path, os.O_RDWR | os.O_NOFOLLOW)
        with os.fdopen(fd, "r+b") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                data = stream.read()
                require(data.endswith(b"\n"), "LEDGER_INVALID")
                records, previous = [], "0" * 64
                for line in data.splitlines():
                    record = parse_json(line)
                    require(isinstance(record, dict), "LEDGER_INVALID")
                    checksum = record.get("sha256")
                    body = {k: v for k, v in record.items() if k != "sha256"}
                    require(body.get("prev") == previous and digest(json_bytes(body)) == checksum,
                            "LEDGER_INVALID")
                    records.append(body)
                    previous = checksum
                require(bool(records) and records[0].get("schema") == 1 and
                        records[0].get("event") == "synthetic_budget" and
                        records[0].get("plan") == self.plan, "LEDGER_INVALID")
                yield stream, records, previous
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    @staticmethod
    def _state(records):
        ceiling = money(records[0]["ceiling"])
        require(ceiling <= CAP, "LEDGER_INVALID")
        attempts = {}
        for row in records[1:]:
            key = pin(row["operation"])
            if row["event"] == "reserve":
                require(key not in attempts and money(row["maximum"]) > 0, "LEDGER_INVALID")
                attempts[key] = dict(row)
            else:
                require(row["event"] == "receipt" and key in attempts and
                        "receipt" not in attempts[key], "LEDGER_INVALID")
                pin(row["receipt"])
                money(row["actual"])
                require(row["served"] in EFFORTS, "LEDGER_INVALID")
                attempts[key].update({k: row[k] for k in ("receipt", "actual", "served")})
        # Do not inherit an application's low-precision/round-down decimal context.
        with localcontext(Context(prec=64)):
            used = sum((money(r["actual"]) if "receipt" in r else money(r["maximum"])
                        for r in attempts.values()), Decimal(0))
        poisoned = any(money(r.get("actual", "0")) > money(r["maximum"]) for r in attempts.values())
        return ceiling, used, attempts, poisoned

    @staticmethod
    def _append(stream, previous, row):
        row = {**row, "prev": previous}
        row["sha256"] = digest(json_bytes(row))
        stream.seek(0, os.SEEK_END)
        stream.write(json_bytes(row))
        stream.flush()
        os.fsync(stream.fileno())

    def reserve(self, operation: str, maximum: str) -> None:
        pin(operation)
        amount = money(maximum)
        require(amount > 0)
        with self._locked() as (stream, records, previous), localcontext(Context(prec=64)):
            ceiling, used, attempts, poisoned = self._state(records)
            require(not poisoned, "COST_EXCEEDED")
            require(operation not in attempts, "ATTEMPT_ALREADY_RESERVED")
            require(used + amount <= ceiling, "BUDGET_EXHAUSTED")
            self._append(stream, previous, {"event": "reserve", "operation": operation, "maximum": maximum})

    def settle(self, operation: str, receipt_path: Path) -> None:
        """Reconcile saved bytes, never a caller's unsupported cost/hash assertion.

        Receipt parsing and operation binding also permit offline reconciliation of
        the save-before-settle crash window, without another transport invocation.
        Local receipts remain synthetic evidence, not authenticated provider billing.
        """
        pin(operation)
        private_path(receipt_path)
        require(receipt_path.is_file(), "RECEIPT_REQUIRED")
        saved = receipt_path.read_bytes()
        receipt = parse_json(saved)
        require(type(receipt) is dict and receipt.get("operation_sha256") == operation and
                type(receipt.get("request_id")) is str and bool(receipt["request_id"]), "RECEIPT_REQUIRED")
        actual, served = receipt.get("actual_cost_usd"), receipt.get("effort_served")
        amount = money(actual)
        require(served in EFFORTS, "UNSUPPORTED_EFFORT")
        with self._locked() as (stream, records, previous):
            _, _, attempts, _ = self._state(records)
            require(operation in attempts and "receipt" not in attempts[operation], "RECEIPT_REQUIRED")
            self._append(stream, previous, {"event": "receipt", "operation": operation,
                         "actual": actual, "served": served, "receipt": digest(saved)})
            require(amount <= money(attempts[operation]["maximum"]), "COST_EXCEEDED")

    def resume(self, operation: str, saved_receipt: bytes) -> None:
        with self._locked() as (_, records, _):
            _, _, attempts, poisoned = self._state(records)
            require(not poisoned, "COST_EXCEEDED")
            require(attempts.get(operation, {}).get("receipt") == digest(saved_receipt), "RECEIPT_REQUIRED")


@dataclass(frozen=True)
class Document:
    document_id: str
    external_id: str
    revision: str
    original_sha256: str
    quote_ids: tuple[str, ...]  # Every quote/break contained in the whole original.
    availability_dates: tuple[str, ...]  # Includes version/letter/revision chronology.
    versioned: bool


@dataclass(frozen=True)
class Scope:
    plan_sha256: str
    manifest_sha256: str
    case_id: str
    cutoff: str
    excluded_quotes: tuple[str, ...]
    target_hashes: tuple[str, ...]
    permits_original_text: bool
    isolated_drive: str
    folder_id: str | None
    documents: tuple[Document, ...]
    server_membership: tuple[str, ...]  # Synthetic assertion, NOT live provider proof.


def scope_digest(scope: Scope) -> str:
    return digest(json_bytes(asdict(scope)))


def validate_scope(scope: Scope) -> None:
    pin(scope.plan_sha256)
    pin(scope.manifest_sha256)
    require(scope.permits_original_text is True and bool(scope.case_id) and
            bool(scope.isolated_drive) and scope.isolated_drive != "default" and
            bool(scope.documents) and bool(scope.excluded_quotes), "SCOPE_REQUIRED")
    require(scope.folder_id is None or (type(scope.folder_id) is str and bool(scope.folder_id.strip())),
            "SCOPE_REQUIRED")
    for values in (scope.excluded_quotes, scope.target_hashes, scope.server_membership):
        require(type(values) is tuple and bool(values) and
                all(type(value) is str and bool(value.strip()) for value in values) and
                len(set(values)) == len(values), "SCOPE_REQUIRED")
    for target in scope.target_hashes:
        pin(target)
    try:
        require(date.fromisoformat(scope.cutoff).isoformat() == scope.cutoff, "SCOPE_REQUIRED")
        ids = [d.document_id for d in scope.documents]
        require(len(set(ids)) == len(ids) and len(set(scope.server_membership)) == len(ids)
                and set(ids) == set(scope.server_membership), "SCOPE_REQUIRED")
        for doc in scope.documents:
            pin(doc.original_sha256)
            require(all(type(value) is str and bool(value.strip()) for value in
                        (doc.document_id, doc.external_id, doc.revision)), "SCOPE_REQUIRED")
            require(type(doc.quote_ids) is tuple and bool(doc.quote_ids) and
                    all(type(value) is str and bool(value.strip()) for value in doc.quote_ids), "SCOPE_REQUIRED")
            require(doc.original_sha256 not in scope.target_hashes and bool(doc.quote_ids) and
                    not set(doc.quote_ids).intersection(scope.excluded_quotes), "EXCLUDED_SOURCE")
            require(doc.versioned is True and bool(doc.availability_dates), "LATE_OR_UNVERSIONED")
            require(all(date.fromisoformat(d).isoformat() == d and d < scope.cutoff
                        for d in doc.availability_dates), "LATE_OR_UNVERSIONED")
    except ValueError:
        raise BoundaryError("LATE_OR_UNVERSIONED") from None


def sanitized_query(rfq: Mapping[str, object]) -> str:
    """Deliberately narrow structured RFQ: never notes, quote IDs, prices or oracle fields.

    A reviewed frozen RFQ is still required; field names cannot prove blinded content.
    Material/description are omitted to avoid broadening historical price-only scope.
    """
    require(set(rfq) == {"part_no", "quantity"})
    require(isinstance(rfq["part_no"], str) and 0 < len(rfq["part_no"]) <= 120)
    require(not any(ord(c) < 32 for c in rfq["part_no"]))
    require(type(rfq["quantity"]) is int and rfq["quantity"] > 0)
    return json_bytes(dict(rfq)).decode().strip()


def operation_key(plan: str, sequence: str, scope: Scope, rfq: Mapping[str, object], effort: str) -> str:
    return digest(json_bytes([pin(plan), pin(sequence), scope_digest(scope), sanitized_query(rfq), effort]))


def validate_usage(response: dict, scope: Scope, effort: str) -> dict:
    """Separate returned accounting from citation acceptance; bad evidence still costs."""
    try:
        require(response["drive_id"] == scope.isolated_drive and response["model"] == MODEL and
                response["effort_requested"] == effort and response["effort_served"] in EFFORTS,
                "RESPONSE_MISMATCH")
        require(type(response["request_id"]) is str and bool(response["request_id"].strip()), "RESPONSE_MISMATCH")
        cost = response["usage"]["cost"]
        money(cost["amount"])
        require(cost["currency"] == "USD", "RESPONSE_MISMATCH")
        return {"drive_id": scope.isolated_drive, "request_id": response["request_id"],
                "effort_requested": effort, "effort_served": response["effort_served"],
                "actual_cost_usd": cost["amount"]}
    except (KeyError, TypeError, UnicodeError, AttributeError):
        raise BoundaryError("RESPONSE_MISMATCH") from None


def validate_response(response: dict, scope: Scope, effort: str,
                      extracted: Mapping[tuple[str, str], bytes]) -> dict:
    """Saved search text plus exact revision is authority. No latest-snapshot reads."""
    usage = validate_usage(response, scope, effort)
    try:
        require(type(response["results"]) is list and len(response["results"]) <= 10, "RESPONSE_MISMATCH")
        docs = {d.document_id: d for d in scope.documents}
        citations, seen = [], set()
        for passage in response["results"]:
            doc = docs.get(passage["document_id"])
            require(doc is not None and passage["external_id"] == doc.external_id and
                    passage["document_revision"] == doc.revision, "CITATION_MISMATCH")
            start, end, text = passage["start_byte"], passage["end_byte"], passage["text"]
            source = extracted.get((doc.document_id, doc.revision))
            require(type(source) is bytes and type(start) is int and type(end) is int and
                    0 <= start < end <= len(source) and type(text) is str, "CITATION_MISMATCH")
            require(source[start:end].decode("utf-8") == text, "CITATION_MISMATCH")
            require(bool(passage["passage_id"]) and passage["passage_id"] not in seen, "CITATION_MISMATCH")
            seen.add(passage["passage_id"])
            citations.append({k: passage[k] for k in ("document_id", "external_id", "document_revision",
                              "passage_id", "start_byte", "end_byte", "text")})
        return {**usage, "citations": citations, "citation_status": "validated",
                "snapshot_id": None, "manufacturing_compatibility": "unknown"}
    except (KeyError, TypeError, UnicodeError, AttributeError):
        raise BoundaryError("RESPONSE_MISMATCH") from None


def sdk_subprocess_environment(parent: Mapping[str, str]) -> dict[str, str]:
    """Build, do not install/mutate, an environment for a future reviewed subprocess.

    Never inherit source key, other providers, proxies, tracing or Polygres defaults.
    No subprocess is launched by this offline implementation.
    """
    key = parent.get("WONDERSEARCH_STEVE_RETRIEVAL_API_KEY")
    require(bool(key), "CREDENTIAL_REQUIRED")
    return {"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "POLYGRES_API_KEY": key,
            "POLYGRES_BASE_URL": BASE_URL}


def import_forecast(*, searches_per_effort: int, import_usd: str | None,
                    processing_usd: str | None, storage_usd: str | None,
                    available_usd: str | None) -> Decimal:
    require(type(searches_per_effort) is int and 0 <= searches_per_effort <= 250)
    require(all(x is not None for x in (import_usd, processing_usd, storage_usd, available_usd)),
            "UNKNOWN_BALANCE")
    with localcontext(Context(prec=64)):
        total = sum(PRICES.values(), Decimal(0)) * searches_per_effort
        total += money(import_usd) + money(processing_usd) + money(storage_usd)
    require(total <= min(CAP, money(available_usd)), "BUDGET_EXHAUSTED")
    return total


def paired_gains(case_ids: tuple[str, ...], baseline: Mapping, candidate: Mapping) -> dict:
    """Aggregate independent retrieval judgments only, never infer from target price.

    All cases must be present, including held/failed/not_run. Judgment provenance is
    an operator assertion requiring independent review, not an automatic relevance
    labeler. Not wired to current blocked reports (there are no such judgments).
    """
    require(bool(case_ids) and len(set(case_ids)) == len(case_ids) and
            set(baseline) == set(candidate) == set(case_ids))
    pairs, gains, losses = 0, 0, 0
    counts = {arm: {s: 0 for s in ("not_run", "held", "failed", "completed")}
              for arm in ("baseline", "candidate")}
    for case_id in case_ids:
        rows = (baseline[case_id], candidate[case_id])
        for arm, row in zip(counts, rows):
            require(row["status"] in counts[arm])
            counts[arm][row["status"]] += 1
            json_bytes(row)  # Refuse NaN/Infinity rather than emit invalid metrics.
            require(row.get("manufacturing", "unknown") in ("match", "conflict", "unknown"))
            if row.get("relevant") is not None:
                require(row["status"] == "completed" and type(row["relevant"]) is bool and
                        row.get("independent") is True)
                pin(row["label_evidence_sha256"])
        if all(r.get("relevant") is not None for r in rows):
            require(rows[0]["label_evidence_sha256"] == rows[1]["label_evidence_sha256"], "PIN_MISMATCH")
            pairs += 1
            gains += not rows[0]["relevant"] and rows[1]["relevant"]
            losses += rows[0]["relevant"] and not rows[1]["relevant"]
    return {"all_case_denominator": len(case_ids), "status_counts": counts,
            "paired_independent_judgments": pairs, "improvements": gains if pairs else None,
            "regressions": losses if pairs else None}


class WonderSearchAdapter:
    """Default off with no built-in live transport; injected code must be synthetic.

    This callable seam is trusted test code, not a sandbox against arbitrary Python.
    It cannot certify server membership or enforce a frozen plan supplied by a caller.
    """
    def __init__(self, *, enabled: bool = False, synthetic_transport: Callable | None = None):
        self.enabled, self.transport = enabled, synthetic_transport

    def retrieve(self, *, scope: Scope, rfq: Mapping[str, object], effort: str,
                 plan_sha256: str, sequence_sha256: str, frozen_scope_sha256: str,
                 frozen_query_sha256: str, budget: Budget, receipt_path: Path,
                 extracted: Mapping[tuple[str, str], bytes]) -> dict:
        if not self.enabled:
            return {"status": "disabled"}
        require(self.transport is not None, "LIVE_NOT_REVIEWED")
        require(effort in EFFORTS, "UNSUPPORTED_EFFORT")
        validate_scope(scope)  # MUST precede constructing query or invoking transport.
        require(scope.plan_sha256 == pin(plan_sha256) and budget.plan == plan_sha256 and
                scope_digest(scope) == pin(frozen_scope_sha256), "PIN_MISMATCH")
        query = sanitized_query(rfq)
        require(digest(query.encode()) == pin(frozen_query_sha256), "PIN_MISMATCH")
        operation = operation_key(plan_sha256, sequence_sha256, scope, rfq, effort)
        private_path(receipt_path)
        require(not receipt_path.exists(), "IMMUTABLE_CONFLICT")
        # Worst supported effort, not requested effort: fail BEFORE a possibly
        # higher charge. Reclaim unused reserve only from a saved known receipt.
        budget.reserve(operation, str(max(PRICES.values())))
        started = time.monotonic_ns()
        try:
            response = self.transport(query=query, effort=effort, drive_id=scope.isolated_drive,
                                      folder_id=scope.folder_id, idempotency_key=operation)
            accounting = validate_usage(response, scope, effort)
            citation_error = None
            try:
                receipt = validate_response(response, scope, effort, extracted)
            except BoundaryError as error:
                citation_error = error
                # Never preserve rejected/out-of-scope passage content. Keep known
                # charges even when citations fail, including poisoning overcharges.
                receipt = {**accounting, "citation_status": "rejected", "citations": [],
                           "error_code": safe_error(error), "snapshot_id": None,
                           "manufacturing_compatibility": "unknown"}
            receipt["latency_ms"] = (time.monotonic_ns() - started) / 1_000_000
            receipt["operation_sha256"] = operation
            freeze_private(receipt_path, receipt)  # Save before ledger reconciliation.
            budget.settle(operation, receipt_path)
            if citation_error is not None:
                raise citation_error
            return receipt
        except Exception as error:
            # Unknown charges remain fully reserved. No retry, fallback, or exception dump.
            raise BoundaryError(safe_error(error)) from None
