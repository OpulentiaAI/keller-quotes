#!/usr/bin/env python3
"""Prepare private PDF evidence and load/query its additive PostgreSQL mirror."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import math
import platform

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db/migrations/0006_document_evidence.sql"
HASH = re.compile(r"[0-9a-f]{64}\Z")
FIELDS = ("quote_no", "item_no", "quantity", "unit_price", "extended_price", "quote_date",
          "letter_date", "part_no", "customer_id", "source_document", "source_document_sha256",
          "source_transcript_sha256", "source_price_field", "price_basis", "status", "won_date")
PRICE_SELECT = ("select v.csv_row_number,v.raw_csv,v.quote_no,v.item_no,v.quantity,v.unit_price,"
                "v.extended_price,v.quote_date,v.letter_date,v.part_no,v.customer_id,v.source_price_field,"
                "d.source_path,d.pdf_sha256,d.anydoc_transcript_sha256 "
                "from verified_document_prices v join evidence_documents d "
                "on d.corpus_key=v.corpus_key and d.document_id=v.document_id")


def helpers():
    spec = importlib.util.spec_from_file_location("document_register_helpers", ROOT / "scripts/build-document-register.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def digest(path):
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_tool(command):
    result = subprocess.run(command, capture_output=True, check=True, timeout=60)
    return (result.stdout or result.stderr).decode("utf-8", errors="strict")


def kind(text):
    header = [line.upper() for line in text.splitlines() if line.strip()][:8]
    matches = [name for pattern, name in ((r"^\s*(?:QUOTATION|QUOTE)(?:\s*#\s*:\s*\S+|\s{2,}|\s*$)", "quote"),
                 (r"(?:^|\s{2,})INVOICE(?:\s{2,}|\s*$)", "invoice"),
                 (r"^\s*PACKING\s+SLIP(?:\s{2,}|\s*$)", "packing_slip"),
                 (r"^\s*PURCHASE\s+ORDER(?:\s{2,}|\s*$)", "supplier_po"),
                 (r"^\s*CERTIFICATE\s+OF\s+COMPLIANCE(?:\s{2,}|\s*$)", "certificate"))
               if any(re.search(pattern, line) for line in header)]
    if matches:
        return matches[0] if len(matches) == 1 else "unknown"
    signatures = (r"^\s*NO\s*:\s*\d+\s*$", r"^\s*INVOICE\s+DATE\s*:\s*\d{2}/\d{2}/\d{2}(?:\d{2})?\s*$",
                  r'^\s*(?:"\s*)*SHIPPED\s+DATE\s*:\s*\d{2}/\d{2}/\d{2}(?:\d{2})?\s*$')
    return "invoice" if all(any(re.search(pattern, line) for line in header) for pattern in signatures) else "unknown"


def extract(entry):
    name, path, source, record, record_sha, hint = entry
    pages = []
    status = "failed"
    layout_sha = None
    extraction_error = None
    try:
        info = run_tool(["pdfinfo", str(path)])
        match = re.search(r"^Pages:\s*(\d+)\s*$", info, re.M)
        if not match or int(match.group(1)) < 1:
            raise ValueError("invalid page count")
        count = int(match.group(1))
        text = run_tool(["pdftotext", "-layout", str(path), "-"])
        layout_sha = sha256(text.encode()).hexdigest()
        segments = text.split("\f")
        if segments[-1] == "":
            segments.pop()
        if len(segments) != count:
            raise ValueError("page boundary mismatch")
        pages = [{"source_path": name, "page_number": i, "layout_text": value,
                  "text_sha256": sha256(value.encode()).hexdigest()}
                 for i, value in enumerate(segments, 1)]
        status = "text" if any(value.strip() for value in segments) else "blank"
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, OSError, ValueError, UnicodeError) as exc:
        count = 0
        if isinstance(exc, subprocess.CalledProcessError):
            extraction_error = f"tool exit {exc.returncode}"
        elif isinstance(exc, subprocess.TimeoutExpired):
            extraction_error = "tool timeout after 60 seconds"
        elif isinstance(exc, UnicodeError):
            extraction_error = "invalid UTF-8 layout text"
        elif isinstance(exc, OSError):
            extraction_error = "PDF tool unavailable"
        else:
            extraction_error = str(exc)
    metadata = {"anydoc_pages": record.get("pages"), "anydoc_page_methods": record.get("page_methods"),
                "anydoc_error_type": record.get("error_type"), "anydoc_error_message": record.get("error_message"),
                "extraction_error_type": extraction_error, "extraction_engine": "pdftotext-layout",
                "layout_sha256": layout_sha, "source_modified_utc": source["modified_utc"]}
    document = {"source_path": name, "pdf_sha256": source["sha256"].lower(),
                "pdf_bytes": source["bytes"], "modified_utc": source["modified_utc"],
                "page_count": count, "filename_hint": hint,
                "content_kind": kind("\n".join(p["layout_text"] for p in pages[:2])) if pages else "unknown",
                "extraction_status": status, "anydoc_status": record["status"],
                "anydoc_record_sha256": record_sha,
                "anydoc_transcript_sha256": record.get("transcript_sha256"), "metadata": metadata}
    return document, pages


def numeric(value):
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError):
        raise ValueError("invalid verified price") from None
    if not number.is_finite() or number <= 0:
        raise ValueError("invalid verified price")
    return number


def price_rows(path, header):
    with path.open("rb") as stream:
        first = stream.readline()
        names = next(csv.reader([first.decode("utf-8")]))
        if len(names) != len(set(names)) or not set(FIELDS) <= set(names):
            raise ValueError("invalid verified CSV columns")
        if first != header.encode("utf-8"):
            raise ValueError("CSV header boundary mismatch")
        index = 0
        while line := stream.readline():
            record = bytearray(line)
            while True:
                try:
                    rows = list(csv.reader(io.StringIO(record.decode("utf-8"), newline=""), strict=True))
                except csv.Error as exc:
                    if "unexpected end of data" not in str(exc):
                        raise ValueError("invalid verified CSV record") from None
                    continuation = stream.readline()
                    if not continuation:
                        raise ValueError("unterminated verified CSV record") from None
                    record.extend(continuation)
                    continue
                if len(rows) != 1:
                    raise ValueError("invalid verified CSV record boundary")
                values = rows[0]
                break
            index += 1
            if len(values) != len(names):
                raise ValueError("invalid verified CSV row width")
            yield index, dict(zip(names, values)), bytes(record).decode("utf-8")


def validate_price(row, docs):
    for key in ("quantity", "unit_price", "extended_price"):
        numeric(row[key])
    quantity, price, extended = (Decimal(row[key]) for key in ("quantity", "unit_price", "extended_price"))
    if (quantity != quantity.to_integral_value() or price != price.quantize(Decimal(".00001"))
            or extended != extended.quantize(Decimal(".01"))
            or extended != (quantity * price).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)):
        raise ValueError("verified price arithmetic mismatch")
    if row["price_basis"] != "customer_quote_pdf" or row["status"] != "unknown" or row["won_date"]:
        raise ValueError("unverified price basis or outcome")
    if row["source_price_field"] not in ("PRICE", "QUOTEPRICE"):
        raise ValueError("invalid source price field")
    doc = docs.get(row["source_document"])
    if not doc or doc["pdf_sha256"] != row["source_document_sha256"] or not doc["anydoc_transcript_sha256"] or doc["anydoc_transcript_sha256"] != row["source_transcript_sha256"]:
        raise ValueError("verified price provenance mismatch")
    if not row["quote_no"]:
        raise ValueError("blank quote number")
    for field in ("quote_date", "letter_date"):
        if not row[field] or datetime.strptime(row[field], "%Y-%m-%d").strftime("%Y-%m-%d") != row[field]:
            raise ValueError("verified date missing or invalid")


def checked_price(result, columns):
    (number, raw, quote_no, item_no, quantity, price, extended, quote_date, letter_date,
     part_no, customer_id, field, path, pdf_sha, transcript_sha) = result
    parsed = list(csv.reader(io.StringIO(raw, newline=""), strict=True))
    if len(parsed) != 1 or len(parsed[0]) != len(columns):
        raise ValueError("stored price CSV boundary mismatch")
    row = dict(zip(columns, parsed[0]))
    validate_price(row, {path: {"pdf_sha256": pdf_sha, "anydoc_transcript_sha256": transcript_sha}})
    if (row["quote_no"] != quote_no or row["item_no"] != item_no
            or Decimal(row["quantity"]) != quantity or Decimal(row["unit_price"]) != price
            or Decimal(row["extended_price"]) != extended
            or datetime.strptime(row["quote_date"], "%Y-%m-%d").date() != quote_date
            or datetime.strptime(row["letter_date"], "%Y-%m-%d").date() != letter_date
            or row["part_no"] != part_no or row["customer_id"] != customer_id
            or row["source_price_field"] != field or number < 1):
        raise ValueError("stored typed price proof mismatch")
    return row


def prepare(args):
    h = helpers()
    script_sha = digest(Path(__file__))
    roots = [args.source_dir, args.source_manifest, args.transcripts, args.price_bundle]
    out = args.out.absolute()
    resolved = out.resolve(strict=False)
    if (out.exists() or out.is_symlink() or ROOT == resolved or ROOT in resolved.parents
            or any(resolved == p.resolve(strict=False) or resolved in p.resolve(strict=False).parents
                   or p.resolve(strict=False) in resolved.parents for p in roots)):
        raise ValueError("output must be a new directory outside every input")
    for root in roots:
        if root.is_symlink():
            raise ValueError("symlinked input")
    inventory = json.loads(args.source_manifest.read_text(encoding="utf-8-sig"))
    if inventory.get("schema_version") != 1 or inventory.get("all_source_hashes_and_mtimes_unchanged") is not True:
        raise ValueError("invalid source inventory")
    sources = {}
    folded = set()
    for item in inventory["files"]:
        name = h.safe_relative(item["path"]).as_posix()
        if name.casefold() in folded:
            raise ValueError("duplicate source path")
        folded.add(name.casefold())
        sources[name] = item
    if len(sources) != inventory["file_count"] or sum(i["bytes"] for i in sources.values()) != inventory["total_bytes"]:
        raise ValueError("source inventory totals mismatch")
    actual = {p.relative_to(args.source_dir).as_posix() for p in args.source_dir.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"}
    if actual != set(sources) or any(p.is_symlink() for p in args.source_dir.rglob("*")):
        raise ValueError("source inventory or symlink mismatch")
    summary_path = h.confined_file(args.transcripts, "summary.json")
    summary = json.loads(summary_path.read_text())
    if (summary.get("schema_version") != 1 or summary.get("source_manifest_sha256") != digest(args.source_manifest)
            or set(summary["records"]) != set(sources) or summary.get("document_count") != len(sources)
            or summary.get("toolchain_sha256") != sha256(json.dumps(summary.get("toolchain"), sort_keys=True).encode()).hexdigest()):
        raise ValueError("transcription inventory mismatch")
    evidence_path = h.confined_file(args.price_bundle, "evidence-manifest.json")
    evidence = json.loads(evidence_path.read_text())
    csv_path = h.confined_file(args.price_bundle, "document-quotes.csv")
    audit_path = h.confined_file(args.price_bundle, "private-document-audit.json")
    if evidence.get("schema_version") != 1 or evidence.get("document_quotes_sha256") != digest(csv_path) or evidence.get("input_sha256", {}).get("pdf_source_manifest") != digest(args.source_manifest) or evidence["input_sha256"].get("transcription_summary") != digest(summary_path):
        raise ValueError("price-bundle proof mismatch")
    entries = []
    proofs = {"source_manifest": digest(args.source_manifest), "transcription_summary": digest(summary_path),
              "evidence_manifest": digest(evidence_path), "price_csv": digest(csv_path), "audit": digest(audit_path)}
    for name, item in sorted(sources.items()):
        path = h.confined_file(args.source_dir, name)
        modified = datetime.fromisoformat(item["modified_utc"].replace("Z", "+00:00"))
        if modified.tzinfo is None or path.stat().st_size != item["bytes"] or abs(path.stat().st_mtime - modified.timestamp()) >= 1 or digest(path) != item["sha256"].lower():
            raise ValueError("PDF inventory proof mismatch")
        record_path = h.confined_file(args.transcripts, summary["records"][name])
        expected = "records/" + sha256(name.encode()).hexdigest() + ".json"
        if summary["records"][name] != expected:
            raise ValueError("record path mismatch")
        record = json.loads(record_path.read_text())
        record_sha = digest(record_path)
        if (record.get("relative_source_path") != name or record.get("source_sha256", "").lower() != item["sha256"].lower()
                or record.get("source_bytes") != item["bytes"] or record.get("toolchain_sha256") != summary["toolchain_sha256"]
                or record.get("tool") != "firecrawl-anydoc" or record.get("tool_version") != summary["tool_version"]
                or record.get("status") not in ("success", "failed", "needs_ocr")):
            raise ValueError("AnyDoc record proof mismatch")
        if record["status"] == "success":
            transcript = "transcripts/" + sha256(name.encode()).hexdigest() + ".md"
            transcript_path = h.confined_file(args.transcripts, transcript)
            if (record.get("transcript_path") != transcript or digest(transcript_path) != record["transcript_sha256"]
                    or transcript_path.stat().st_size != record.get("transcript_bytes")
                    or record.get("covered_pages") != list(range(1, record.get("pages", 0) + 1))
                    or len(record.get("page_methods", [])) != record["pages"]):
                raise ValueError("AnyDoc transcript proof mismatch")
        if evidence["input_sha256"]["transcription_records"][name] != record_sha or evidence["input_sha256"]["transcripts"].get(name) != record.get("transcript_sha256"):
            raise ValueError("price-bundle transcript proof mismatch")
        entries.append((name, path, item, record, record_sha, record.get("filename_classification", "other")))
    audit = json.loads(audit_path.read_text())
    if (len(audit) != len(entries) or {item["document"] for item in audit} != set(sources)
            or any(item["source_sha256"] != sources[item["document"]]["sha256"].lower()
                   or item.get("transcript_sha256") != evidence["input_sha256"]["transcripts"].get(item["document"])
                   for item in audit)):
        raise ValueError("audit inventory mismatch")
    audit_hashes = {item["document"]: item["verification_text_sha256"] for item in audit if item.get("verification_text_sha256")}
    if audit_hashes != evidence.get("verification_text_sha256"):
        raise ValueError("audit verification hash mismatch")
    if evidence["input_sha256"].get("transcription_tool_version") != summary["tool_version"]:
        raise ValueError("transcription version mismatch")
    versions = {tool: run_tool([tool, "-v"] if tool == "pdftotext" else [tool, "-v"]).splitlines()[0] for tool in ("pdfinfo", "pdftotext")}
    parent = out.parent
    parent.mkdir(parents=True, exist_ok=True)
    if any(component.is_symlink() for component in (parent, *parent.parents)):
        raise ValueError("symlinked output parent")
    stage = Path(tempfile.mkdtemp(prefix=".evidence-", dir=parent))
    try:
        counts = {"documents": 0, "pages": 0, "prices": 0, "extraction_failed": 0, "blank": 0}
        docs = {}
        with (stage / "documents.jsonl").open("w", encoding="utf-8") as df, (stage / "pages.jsonl").open("w", encoding="utf-8") as pf:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                for doc, pages in pool.map(extract, entries):
                    if doc["source_path"] in audit_hashes and doc["metadata"]["layout_sha256"] != audit_hashes[doc["source_path"]]:
                        raise ValueError("independent verification layout changed")
                    docs[doc["source_path"]] = doc
                    df.write(encoded(doc).decode() + "\n")
                    for page in pages:
                        pf.write(encoded(page).decode() + "\n")
                    counts["documents"] += 1
                    counts["pages"] += len(pages)
                    counts["extraction_failed"] += doc["extraction_status"] == "failed"
                    counts["blank"] += doc["extraction_status"] == "blank"
        with csv_path.open("rb") as stream:
            header = stream.readline().decode("utf-8")
        seen = set()
        with (stage / "prices.jsonl").open("w", encoding="utf-8") as target:
            for index, row, record in price_rows(csv_path, header):
                validate_price(row, docs)
                key = (row["quote_no"], row["item_no"], Decimal(row["quantity"]))
                if key in seen:
                    raise ValueError("duplicate verified price key")
                seen.add(key)
                target.write(encoded({"csv_row_number": index, "row": row, "raw_csv": record}).decode() + "\n")
                counts["prices"] += 1
        if counts["prices"] != evidence["counts"]["selected_rows"]:
            raise ValueError("price count mismatch")
        for name, path, item, record, record_sha, _ in entries:
            stamp = datetime.fromisoformat(item["modified_utc"].replace("Z", "+00:00"))
            if (path.stat().st_size != item["bytes"] or abs(path.stat().st_mtime - stamp.timestamp()) >= 1
                    or digest(path) != item["sha256"].lower()
                    or digest(h.confined_file(args.transcripts, summary["records"][name])) != record_sha):
                raise ValueError("input changed during preparation")
            if record["status"] == "success" and digest(h.confined_file(args.transcripts, record["transcript_path"])) != record["transcript_sha256"]:
                raise ValueError("transcript changed during preparation")
        for key, path in (("source_manifest", args.source_manifest), ("transcription_summary", summary_path),
                          ("evidence_manifest", evidence_path), ("price_csv", csv_path), ("audit", audit_path)):
            if digest(path) != proofs[key]:
                raise ValueError("input manifest changed during preparation")
        if digest(Path(__file__)) != script_sha:
            raise ValueError("preparation implementation changed")
        payloads = {name: digest(stage / name) for name in ("documents.jsonl", "pages.jsonl", "prices.jsonl")}
        metadata = {"schema_version": 1, "inputs": proofs, "payload_sha256": payloads, "counts": counts,
                    "csv_header": header, "csv_columns": next(csv.reader([header])), "tool_versions": versions,
                    "python_version": platform.python_version(), "prepare_script_sha256": script_sha,
                    "anydoc_version": summary["tool_version"], "anydoc_toolchain_sha256": summary["toolchain_sha256"],
                    "source_file_count": inventory["file_count"], "source_total_bytes": inventory["total_bytes"]}
        metadata["corpus_id"] = sha256(encoded(metadata)).hexdigest()
        (stage / "manifest.json").write_bytes(encoded(metadata) + b"\n")
        h.publish_new_directory(stage, out)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    print(json.dumps({"corpus_id": metadata["corpus_id"], "counts": counts}))


def bundle(path):
    h = helpers()
    manifest_path = h.confined_file(path, "manifest.json")
    manifest = json.loads(manifest_path.read_text())
    corpus_id = manifest.pop("corpus_id")
    if manifest.get("schema_version") != 1 or sha256(encoded(manifest)).hexdigest() != corpus_id:
        raise ValueError("invalid prepared manifest digest")
    manifest["corpus_id"] = corpus_id
    data = {}
    for name, expected in manifest["payload_sha256"].items():
        file = h.confined_file(path, name)
        if not HASH.fullmatch(expected) or digest(file) != expected:
            raise ValueError("prepared payload digest mismatch")
        data[name] = [json.loads(line) for line in file.read_text().splitlines()]
    docs = {d["source_path"]: d for d in data["documents.jsonl"]}
    if len(docs) != len(data["documents.jsonl"]):
        raise ValueError("duplicate document")
    page_keys = set()
    for p in data["pages.jsonl"]:
        key = p["source_path"], p["page_number"]
        if key in page_keys or p["source_path"] not in docs or sha256(p["layout_text"].encode()).hexdigest() != p["text_sha256"]:
            raise ValueError("invalid prepared page")
        page_keys.add(key)
    page_numbers = {}
    for name, number in page_keys:
        page_numbers.setdefault(name, set()).add(number)
    for doc in docs.values():
        if page_numbers.get(doc["source_path"], set()) != set(range(1, doc["page_count"] + 1)):
            raise ValueError("missing prepared pages")
    seen = set()
    csv_hash = sha256(manifest["csv_header"].encode())
    for index, item in enumerate(data["prices.jsonl"], 1):
        row = item["row"]
        validate_price(row, docs)
        if item["csv_row_number"] != index or next(csv.reader(io.StringIO(item["raw_csv"]))) != [row[k] for k in manifest["csv_columns"]]:
            raise ValueError("invalid prepared CSV row")
        key = row["quote_no"], row["item_no"], Decimal(row["quantity"])
        if key in seen:
            raise ValueError("duplicate prepared price")
        seen.add(key)
        csv_hash.update(item["raw_csv"].encode())
    if csv_hash.hexdigest() != manifest["inputs"]["price_csv"]:
        raise ValueError("prepared CSV reconstruction mismatch")
    for key, name in (("documents", "documents.jsonl"), ("pages", "pages.jsonl"), ("prices", "prices.jsonl")):
        if manifest["counts"][key] != len(data[name]):
            raise ValueError("prepared count mismatch")
    return manifest, data


def connection(expected):
    if not expected or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", expected):
        raise ValueError("explicit expected database required")
    url = os.environ.get("POLYGRES_DIRECT_URL")
    if not url:
        raise ValueError("POLYGRES_DIRECT_URL is required")
    config = conninfo_to_dict(url)
    if config.get("service") or os.environ.get("PGSERVICE"):
        raise ValueError("service aliases are not supported")
    loopback = ("localhost", "127.0.0.1", "::1")
    hostaddr = config.get("hostaddr") or os.environ.get("PGHOSTADDR")
    remote = config.get("host") not in loopback or (hostaddr is not None and hostaddr not in loopback)
    if remote and (config.get("sslmode") != "verify-full" or config.get("sslrootcert") != "/etc/ssl/certs/ca-certificates.crt"):
        raise ValueError("nonloopback connections require verify-full and the system CA certificate")
    conn = psycopg.connect(url, autocommit=True, connect_timeout=10)
    if conn.execute("select current_database()").fetchone()[0] != expected:
        conn.close()
        raise ValueError("wrong database")
    return conn


def load(args):
    manifest, data = bundle(args.bundle)
    for value in (args.expected_growth_mib, args.storage_budget_mib):
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError("growth and storage budgets must be finite and positive")
    with connection(args.expected_database) as conn:
        current = conn.execute("select pg_database_size(current_database())").fetchone()[0]
        if not args.apply:
            with conn.transaction():
                conn.execute("set transaction read only")
                print(json.dumps({"dry_run": True, "corpus_id": manifest["corpus_id"], "counts": manifest["counts"], "database_bytes": current,
                                  "expected_growth_mib": args.expected_growth_mib, "storage_budget_mib": args.storage_budget_mib}))
            return
        with conn.transaction():
            conn.execute("select pg_advisory_xact_lock(57841433)")
            schema = conn.execute("select to_regclass('document_corpora'),to_regclass('evidence_documents'),to_regclass('evidence_page_sets'),to_regclass('evidence_pages'),to_regclass('verified_document_prices'),to_regclass('evidence_page_sets_fts'),to_regprocedure('evidence_pages_valid(jsonb)')").fetchone()
            if all(value is None for value in schema):
                conn.execute(MIGRATION.read_text())
            elif (any(value is None for value in schema)
                    or conn.execute("select relkind from pg_class where oid=to_regclass('evidence_pages')").fetchone()[0] != 'v'
                    or not conn.execute("select exists (select 1 from information_schema.columns where table_name='document_corpora' and column_name='corpus_key') and exists (select 1 from information_schema.columns where table_name='verified_document_prices' and column_name='document_id')").fetchone()[0]):
                raise ValueError("partial or incompatible document evidence schema")
            existing = conn.execute("select corpus_key,manifest_sha256,document_count,page_count,price_count,csv_sha256,csv_header,prepared_manifest from document_corpora where corpus_id=%s", (manifest["corpus_id"],)).fetchone()
            if existing:
                corpus_key = existing[0]
                actual = [conn.execute("select count(*) from evidence_documents where corpus_key=%s", (corpus_key,)).fetchone()[0],
                          conn.execute("select count(*) from evidence_pages p join evidence_documents d using (document_id) where d.corpus_key=%s", (corpus_key,)).fetchone()[0],
                          conn.execute("select count(*) from verified_document_prices where corpus_key=%s", (corpus_key,)).fetchone()[0]]
                sets = conn.execute("select count(*) from evidence_page_sets s join evidence_documents d using (document_id) where d.corpus_key=%s", (corpus_key,)).fetchone()[0]
                expected_counts = [manifest["counts"][key] for key in ("documents", "pages", "prices")]
                if (existing[1:5] != (digest(args.bundle / "manifest.json"), *actual)
                        or actual != expected_counts or sets != actual[0]
                        or existing[5:] != (manifest["inputs"]["price_csv"], manifest["csv_header"], manifest)):
                    raise ValueError("existing corpus proof/count mismatch")
                fields = ("source_path", "pdf_sha256", "pdf_bytes", "page_count", "filename_hint", "content_kind", "extraction_status", "anydoc_status", "anydoc_record_sha256", "anydoc_transcript_sha256", "metadata")
                docs = conn.execute(f"select {','.join(fields)},modified_utc from evidence_documents where corpus_key=%s", (corpus_key,)).fetchall()
                actual_docs = {r[0]: r for r in docs}
                expected_docs = {d["source_path"]: tuple(d[k] for k in fields) + (datetime.fromisoformat(d["modified_utc"].replace("Z", "+00:00")),) for d in data["documents.jsonl"]}
                if actual_docs != expected_docs:
                    raise ValueError("existing corpus document proof mismatch")
                pages = conn.execute("select d.source_path,p.page_number,p.layout_text,p.text_sha256 from evidence_pages p join evidence_documents d using (document_id) where d.corpus_key=%s", (corpus_key,)).fetchall()
                actual_pages = {(r[0], r[1]): r for r in pages}
                expected_pages = {(p["source_path"], p["page_number"]): tuple(p[k] for k in ("source_path", "page_number", "layout_text", "text_sha256")) for p in data["pages.jsonl"]}
                if actual_pages != expected_pages:
                    raise ValueError("existing corpus page proof mismatch")
                rows = conn.execute(PRICE_SELECT + " where v.corpus_key=%s order by v.csv_row_number", (corpus_key,)).fetchall()
                if len(rows) != len(data["prices.jsonl"]):
                    raise ValueError("existing corpus price count mismatch")
                for result, item in zip(rows, data["prices.jsonl"]):
                    if (result[0] != item["csv_row_number"] or result[1] != item["raw_csv"]
                            or checked_price(result, manifest["csv_columns"]) != item["row"]):
                        raise ValueError("existing corpus price proof mismatch")
                if {r[0] for r in rows} != set(range(1, len(rows) + 1)):
                    raise ValueError("existing corpus price proof mismatch")
                print(json.dumps({"corpus_id": manifest["corpus_id"], "skipped": True}))
                return
            if args.expected_growth_mib is None or args.storage_budget_mib is None:
                raise ValueError("new import requires positive expected growth and storage budget")
            current = conn.execute("select pg_database_size(current_database())").fetchone()[0]
            if current + int(args.expected_growth_mib * 1048576) > int(args.storage_budget_mib * 1048576):
                raise ValueError("storage budget exceeded before import")
            missing = conn.execute("select x.quote_no from unnest(%s::text[]) x(quote_no) except select quote_no from quotes limit 1",
                                   (list({p["row"]["quote_no"] for p in data["prices.jsonl"]}),)).fetchone()
            if missing:
                raise ValueError("verified quote absent from legacy quotes")
            c = manifest["counts"]
            corpus_key = conn.execute("insert into document_corpora (corpus_id,prepared_manifest,manifest_sha256,csv_sha256,csv_header,document_count,page_count,price_count) values (%s,%s,%s,%s,%s,%s,%s,%s) returning corpus_key",
                                      (manifest["corpus_id"], Jsonb(manifest), digest(args.bundle / "manifest.json"), manifest["inputs"]["price_csv"], manifest["csv_header"], c["documents"], c["pages"], c["prices"])).fetchone()[0]
            conn.cursor().executemany("insert into evidence_documents (corpus_key,source_path,pdf_sha256,pdf_bytes,modified_utc,page_count,filename_hint,content_kind,extraction_status,anydoc_status,anydoc_record_sha256,anydoc_transcript_sha256,metadata) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                             [(corpus_key, d["source_path"], d["pdf_sha256"], d["pdf_bytes"],
                               datetime.fromisoformat(d["modified_utc"].replace("Z", "+00:00")),
                               *[d[k] for k in ("page_count", "filename_hint", "content_kind", "extraction_status", "anydoc_status", "anydoc_record_sha256", "anydoc_transcript_sha256")], Jsonb(d["metadata"])) for d in data["documents.jsonl"]])
            ids = dict(conn.execute("select source_path,document_id from evidence_documents where corpus_key=%s", (corpus_key,)).fetchall())
            page_sets = {name: [] for name in ids}
            for page in data["pages.jsonl"]:
                page_sets[page["source_path"]].append(page)
            conn.cursor().executemany("insert into evidence_page_sets (document_id,pages) values (%s,%s)",
                             [(ids[name], Jsonb([{"text": p["layout_text"], "sha256": p["text_sha256"]}
                                                 for p in sorted(pages, key=lambda item: item["page_number"])]))
                              for name, pages in page_sets.items()])
            conn.cursor().executemany("insert into verified_document_prices (corpus_key,document_id,quote_no,item_no,quantity,csv_row_number,raw_csv,unit_price,extended_price,quote_date,letter_date,part_no,customer_id,source_price_field) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                             [(corpus_key, ids[p["row"]["source_document"]], *[p["row"][k] for k in ("quote_no", "item_no", "quantity")], p["csv_row_number"], p["raw_csv"], *[p["row"][k] for k in ("unit_price", "extended_price", "quote_date", "letter_date", "part_no", "customer_id", "source_price_field")]) for p in data["prices.jsonl"]])
            actual = conn.execute("select pg_database_size(current_database())").fetchone()[0]
            if actual > int(args.storage_budget_mib * 1048576):
                raise ValueError("storage budget exceeded during import")
        print(json.dumps({"corpus_id": manifest["corpus_id"], "loaded": c}))


def query(args):
    with connection(args.expected_database) as conn:
        with conn.transaction():
            conn.execute("set transaction read only")
            corpus = conn.execute("select corpus_key,csv_header,csv_sha256,price_count,prepared_manifest from document_corpora where corpus_id=%s", (args.corpus,)).fetchone()
            if not corpus:
                raise ValueError("unknown corpus")
            corpus_key, header, csv_sha, price_count, prepared = corpus
            columns = prepared["csv_columns"]
            if args.command == "search":
                if not args.text.strip() or not 1 <= args.limit <= 100:
                    raise ValueError("search requires text and limit 1..100")
                rows = conn.execute("select d.source_path,p.page_number,p.text_sha256,d.pdf_sha256,d.content_kind,left(p.layout_text,500) from evidence_page_sets s join evidence_documents d using (document_id) join evidence_pages p using (document_id) where d.corpus_key=%s and to_tsvector('english',jsonb_path_query_array(s.pages,'$[*].text')) @@ plainto_tsquery('english',%s) and to_tsvector('english',p.layout_text) @@ plainto_tsquery('english',%s) and (%s::text is null or d.content_kind=%s) and (%s::text is null or exists (select 1 from verified_document_prices v where v.corpus_key=d.corpus_key and v.document_id=d.document_id and v.quote_no=%s)) order by d.source_path,p.page_number limit %s",
                                    (corpus_key, args.text, args.text, args.kind, args.kind, args.quote, args.quote, args.limit)).fetchall()
                for r in rows:
                    print(json.dumps(dict(zip(("path", "page", "page_sha256", "pdf_sha256", "kind", "excerpt"), r))))
            elif args.command == "prices":
                if not args.part and not args.quote:
                    raise ValueError("exact part or quote required")
                rows = conn.execute(PRICE_SELECT + " where v.corpus_key=%s and (%s::text is null or v.part_no=%s) and (%s::text is null or v.quote_no=%s) order by v.quote_no,v.quantity limit 100",
                                    (corpus_key, args.part, args.part, args.quote, args.quote)).fetchall()
                for result in rows:
                    row = checked_price(result, columns)
                    print(json.dumps({"row": row, "source_path": result[12], "pdf_sha256": result[13], "transcript_sha256": result[14]}))
            else:
                output = args.out.absolute()
                if (output.exists() or output.is_symlink() or ROOT == output.resolve(strict=False)
                        or ROOT in output.resolve(strict=False).parents
                        or any(p.is_symlink() for p in (output.parent, *output.parent.parents))):
                    raise ValueError("export requires a new regular path")
                fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(header.encode())
                        count = 0
                        with conn.cursor(name="evidence_export") as cursor:
                            cursor.execute(PRICE_SELECT + " where v.corpus_key=%s order by v.csv_row_number", (corpus_key,))
                            for result in cursor:
                                count += 1
                                if result[0] != count:
                                    raise ValueError("export row order mismatch")
                                checked_price(result, columns)
                                stream.write(result[1].encode())
                    if count != price_count or digest(output) != csv_sha:
                        raise ValueError("export digest/count mismatch")
                except Exception:
                    output.unlink(missing_ok=True)
                    raise
                print(json.dumps({"rows": count, "sha256": csv_sha}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    for name in ("source-dir", "source-manifest", "transcripts", "price-bundle", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    p = sub.add_parser("load")
    p.add_argument("bundle", type=Path)
    p.add_argument("--expected-database", required=True)
    p.add_argument("--expected-growth-mib", type=float)
    p.add_argument("--storage-budget-mib", type=float)
    p.add_argument("--apply", action="store_true")
    for action in ("search", "prices", "export"):
        p = sub.add_parser(action)
        p.add_argument("--expected-database", required=True)
        p.add_argument("--corpus", required=True)
        if action == "search":
            p.add_argument("text")
            p.add_argument("--kind", choices=("quote", "invoice", "packing_slip", "supplier_po", "certificate", "other", "unknown"))
            p.add_argument("--quote")
            p.add_argument("--limit", type=int, default=20)
        elif action == "prices":
            p.add_argument("--part")
            p.add_argument("--quote")
        else:
            p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args)
        elif args.command == "load":
            load(args)
        else:
            query(args)
    except Exception as exc:
        if isinstance(exc, psycopg.Error):
            print("database operation failed; no connection details emitted", file=sys.stderr)
        elif isinstance(exc, subprocess.SubprocessError):
            print("PDF tool failed", file=sys.stderr)
        else:
            print(f"evidence operation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
