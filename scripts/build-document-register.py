#!/usr/bin/env python3
"""Build a separate, document-verified quote register from offline PDF transcripts."""

import argparse
from collections import Counter, defaultdict
import csv
import ctypes
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from hashlib import sha256
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
import shutil


EXTRA_COLUMNS = ("price_basis", "source_document", "source_document_sha256",
                 "source_transcript_sha256", "source_price_field")
CENT = Decimal("0.01")
HASH = re.compile(r"[a-f0-9]{64}\Z")
PDF_NAME = re.compile(r"QuoteLetter([0-9]{8})\.pdf\Z")
INTEGER = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"
PRICE_ROW = re.compile(r"(?<![\w.$+\-−,])([+\-−]?\s*" + INTEGER + r")(?:\s|\|)+"
                       r"\$(" + INTEGER + r"\.[0-9]{2})(?:\s|\|)+"
                       r"\$(" + INTEGER + r"\.[0-9]{2})(?![\d.,])")
QUOTE_ID = re.compile(r"\bQuote\s*#\s*:\s*([0-9]{7})(?!\d)", re.I)
LETTER_ID = re.compile(r"\bLetter\s*:\s*([0-9]{8})(?!\d)", re.I)
PART_ID = re.compile(r"\bP/N\s*:\s*(.*?)(?=\b(?:Comment|Rev)\s*:|\n|$)", re.I | re.S)
DATE_ID = re.compile(r"\bInquiry\s+Date\s*:\s*([0-9]{2}/[0-9]{2}/[0-9]{2})\b", re.I)
PRICE_HEADER = re.compile(r"\bDescription\s+Quantity\s+Price\s+Each\s+Extended\s+Price\b", re.I)


class Hold(ValueError):
    pass


def digest(path):
    hash_value = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hash_value.update(chunk)
    return hash_value.hexdigest()


def private_write(path, data):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".document-register-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish_new_directory(staging, output):
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                       ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(staging), -100, os.fsencode(output), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def safe_relative(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("unsafe relative path")
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if (path.is_absolute() or re.match(r"^[A-Za-z]:", value)
            or any(part in (".", "..", "") for part in value.split("/"))):
        raise ValueError("unsafe relative path")
    return path


def confined_file(root, relative):
    if root.is_symlink():
        raise ValueError("symlinked input root")
    path = root / safe_relative(relative)
    for component in (root, *[root.joinpath(*path.relative_to(root).parts[:n])
                              for n in range(1, len(path.relative_to(root).parts) + 1)]):
        if component.is_symlink():
            raise ValueError("symlinked input component")
    if not path.is_file() or root.resolve(strict=True) not in path.resolve(strict=True).parents:
        raise ValueError("input proof file escapes its root")
    return path


def decimal(value):
    try:
        number = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, TypeError, ValueError):
        raise Hold("invalid_numeric_value") from None
    if not number.is_finite() or number <= 0:
        raise Hold("nonpositive_or_nonfinite_value")
    return number


def candidate_price(value):
    try:
        return decimal(value)
    except Hold:
        return None


def text(value):
    return str(value or "").strip()


def normal_part(value):
    return re.sub(r"\s+", "", text(value)).casefold()


def iso_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(text(value))


def parse_document(markdown, letter, reference_date):
    clean = markdown.replace("**", "").replace("__", "")
    if re.search(r"(?im)^\s*#*\s*(?:invoice|purchase\s+order|p\.?o\.?)\b", clean):
        raise Hold("non_quotation_content")
    if not re.search(r"(?im)^\s*#*\s*QUOTE(?:\s|$)", clean):
        raise Hold("missing_quotation_title")
    letters = LETTER_ID.findall(clean)
    quotes = QUOTE_ID.findall(clean)
    parts = [normal_part(match) for match in PART_ID.findall(clean)]
    dates = DATE_ID.findall(clean)
    if not letters or set(letters) != {letter}:
        raise Hold("letter_identity_mismatch")
    if not quotes or len(set(quotes)) != 1 or not parts or len(set(parts)) != 1 or not parts[0]:
        raise Hold("ambiguous_quote_or_part_identity")
    if not dates or len(set(dates)) != 1:
        raise Hold("missing_or_ambiguous_inquiry_date")
    try:
        month, day, short_year = (int(piece) for piece in dates[0].split("/"))
        inquiry = date(reference_date.year // 100 * 100 + short_year, month, day)
    except ValueError:
        raise Hold("invalid_inquiry_date") from None
    headers = list(PRICE_HEADER.finditer(clean))
    if not headers:
        raise Hold("missing_price_table_header")
    rows = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(clean)
        body = clean[header.end():end]
        body = re.split(r"(?im)^\s*#*\s*(?:By\s*:|Inquiry\s+Date\s*:|Page\b)", body, maxsplit=1)[0]
        matches = list(PRICE_ROW.finditer(body))
        if body.count("$") != 2 * len(matches):
            raise Hold("unparsed_or_extra_price_row")
        rows.extend(tuple(decimal(token) for token in match.groups()) for match in matches)
    if not rows or any(qty != qty.to_integral_value() for qty, _, _ in rows):
        raise Hold("missing_or_invalid_price_rows")
    if len({qty for qty, _, _ in rows}) != len(rows):
        raise Hold("duplicate_printed_quantity")
    return quotes[0], parts[0], inquiry, rows


def index_sources(tables, originals):
    register = defaultdict(list)
    quotes = defaultdict(set)
    for row in originals:
        key = row["quote_no"], row["item_no"]
        register[key].append(row)
        quotes[row["quote_no"]].add(key)
    lines = defaultdict(list)
    for row in tables["QUOTLINE"]:
        lines[text(row["QUOTLETTER"])].append(row)
    breaks = defaultdict(list)
    for row in tables["QUOTLEIT"]:
        breaks[(text(row["QUOTLETTER"]), text(row["ITEM"]))].append(row)
    letters = defaultdict(list)
    for row in tables["QUOTLETT"]:
        letters[text(row["QUOTLETTER"])].append(row)
    return register, quotes, lines, breaks, letters


def verify_document(markdown, letter_id, original_columns, sources):
    register, quotes, lines, breaks, letters = sources
    header_rows = letters[letter_id]
    if len(header_rows) != 1:
        raise Hold("ambiguous_or_missing_letter_header")
    header = header_rows[0]
    try:
        letter_date = iso_date(header["DATE_STAMP"])
        revision = iso_date(header["REVISION_D"]) if header.get("REVISION_D") else None
    except (ValueError, TypeError):
        raise Hold("invalid_letter_date") from None
    quote_id, part_id, inquiry, printed = parse_document(markdown, letter_id, letter_date)
    matches = lines[letter_id]
    if len(matches) != 1 or text(matches[0]["QUOTE_NO"]) != quote_id:
        raise Hold("ambiguous_or_missing_letter_line")
    line = matches[0]
    if normal_part(line["PART_NO"]) != part_id:
        raise Hold("part_identity_mismatch")
    if inquiry != letter_date or (revision and inquiry != revision):
        raise Hold("document_date_mismatch")
    if len(quotes[quote_id]) != 1:
        raise Hold("ambiguous_or_missing_original_quote")
    key = next(iter(quotes[quote_id]))
    original_rows = register[key]
    original = original_rows[0]
    if (any(normal_part(row["part_no"]) != part_id or
            text(row["customer_id"]) != text(header["COMP_ID"]) for row in original_rows)
            or not text(header["COMP_ID"])):
        raise Hold("original_identity_mismatch")
    source_rows = breaks[(letter_id, text(line["ITEM"]))]
    if not source_rows or len(source_rows) != len(printed):
        raise Hold("source_break_count_mismatch")
    by_qty = {}
    for row in source_rows:
        quantity = decimal(row["QTY"])
        if quantity != quantity.to_integral_value() or quantity in by_qty:
            raise Hold("ambiguous_source_quantity")
        by_qty[quantity] = row
    selected = []
    agreements = Counter()
    for qty, display, extension in printed:
        source = by_qty.get(qty)
        if source is None:
            raise Hold("source_quantity_mismatch")
        prices = {field: candidate_price(source.get(field)) for field in ("PRICE", "QUOTEPRICE")}
        valid = [field for field, value in prices.items()
                 if value is not None and value.quantize(CENT, rounding=ROUND_DOWN) == display
                 and (qty * value).quantize(CENT, rounding=ROUND_HALF_UP) == extension]
        if not valid:
            raise Hold("printed_price_mismatch")
        if len(valid) == 2:
            if prices["PRICE"] != prices["QUOTEPRICE"]:
                raise Hold("indistinguishable_price_fields")
            field = None
            agreements["fields_agree"] += 1
        else:
            field = valid[0]
            agreements[field + "_only"] += 1
        selected.append((qty, prices[field or "PRICE"], extension, field))
    decisive_fields = {field for _, _, _, field in selected if field}
    if len(decisive_fields) > 1:
        raise Hold("inconsistent_price_field")
    chosen_field = next(iter(decisive_fields)) if decisive_fields else "PRICE"
    try:
        stamp = max(iso_date(original["date_stamp"]), letter_date, *([revision] if revision else []))
    except (ValueError, TypeError):
        raise Hold("invalid_original_date") from None
    rows = []
    internal = {decimal(row["quantity"]): row for row in original_rows if row["quantity"]}
    legacy_mismatches = 0
    for quantity, price, extension, field in selected:
        result = dict.fromkeys(original_columns, "")
        result.update(original)
        result.update(quote_no=quote_id, item_no=key[1], quote_date=letter_date.isoformat(),
                      date_stamp=stamp.isoformat(), customer_id=text(header["COMP_ID"]),
                      customer=text(header.get("CNAME")), part_no=text(line["PART_NO"]),
                      description=text(line.get("DESCR")), rev=text(line.get("REV_NO")),
                      drawing_no=text(line.get("DRAWING_NO")), rfq_no=text(line.get("RFQ_NO")),
                      buyer_name=text(header.get("BUYER_NAME")),
                      salesperson=text(header.get("SALES_PERS")), quote_letter=letter_id,
                      letter_date=letter_date.isoformat(), quantity=str(quantity),
                      unit_price=str(price), unit_cost="", extended_price=f"{extension:.2f}",
                      markup="", del_seq="", status="unknown", won_date="", newsellpri="")
        legacy = internal.get(quantity)
        if legacy is None or candidate_price(legacy.get("unit_price")) != price:
            legacy_mismatches += 1
        rows.append(result)
    return key, letter_date, rows, chosen_field, agreements, legacy_mismatches


def load_tables(folder):
    from dbfread import DBF

    names = ("QUOTLINE", "QUOTLEIT", "QUOTLETT")
    files = {p.name: digest(confined_file(folder, p.name)) for p in sorted(folder.iterdir())
             if p.is_file() and p.suffix.upper() in (".DBF", ".FPT")}
    tables = {name: list(DBF(folder / (name + ".DBF"), encoding="cp1252")) for name in names}
    if files != {name: digest(confined_file(folder, name)) for name in files}:
        raise ValueError("DBF inputs changed while loading")
    return tables, files


def load_records(transcripts, source_dir, source_manifest):
    summary_path = transcripts / "summary.json"
    summary = json.loads(confined_file(transcripts, "summary.json").read_text(encoding="utf-8-sig"))
    if summary.get("schema_version") != 1 or digest(source_manifest) != summary.get("source_manifest_sha256"):
        raise ValueError("transcription source manifest digest mismatch")
    inventory = json.loads(source_manifest.read_text(encoding="utf-8-sig"))
    toolchain = summary.get("toolchain")
    if (not isinstance(toolchain, dict) or not isinstance(summary.get("toolchain_sha256"), str)
            or summary["toolchain_sha256"] != sha256(json.dumps(
                toolchain, sort_keys=True).encode("utf-8")).hexdigest()
            or toolchain.get("script_sha256") != digest(Path(__file__).with_name("transcribe-pdfs.py"))
            or not isinstance(summary.get("local_ocr"), bool)):
        raise ValueError("transcription toolchain fingerprint mismatch")
    expected = {safe_relative(item["path"]).as_posix(): item for item in inventory["files"]}
    if (len(expected) != len(inventory["files"]) or len(expected) != inventory["file_count"]
            or len({name.casefold() for name in expected}) != len(expected)):
        raise ValueError("invalid PDF source inventory")
    records = summary["records"]
    if set(records) != set(expected) or len(records) != summary["document_count"]:
        raise ValueError("transcription inventory mismatch")
    output = []
    record_hashes = {}
    transcript_hashes = {}
    for name in sorted(records):
        source_path = confined_file(source_dir, name)
        expected_record = "records/" + sha256(name.encode("utf-8")).hexdigest() + ".json"
        if records[name] != expected_record:
            raise ValueError("transcription record path mismatch")
        record_path = confined_file(transcripts, records[name])
        record = json.loads(record_path.read_text(encoding="utf-8-sig"))
        record_hashes[name] = digest(record_path)
        expected_sha = expected[name]["sha256"].lower()
        if (not HASH.fullmatch(expected_sha) or digest(source_path) != expected_sha
                or source_path.stat().st_size != expected[name]["bytes"]
                or record.get("relative_source_path") != name
                or record.get("source_sha256", "").lower() != expected_sha
                or record.get("source_bytes") != expected[name]["bytes"]
                or record.get("toolchain_sha256") != summary["toolchain_sha256"]
                or record.get("local_ocr") != summary["local_ocr"]
                or record.get("tool") != "firecrawl-anydoc"
                or record.get("tool_version") != summary.get("tool_version")):
            raise ValueError("PDF source provenance mismatch")
        markdown = None
        if record.get("status") == "success":
            expected_path = "transcripts/" + sha256(name.encode("utf-8")).hexdigest() + ".md"
            if record.get("transcript_path") != expected_path:
                raise ValueError("transcript path mismatch")
            transcript_path = confined_file(transcripts, record["transcript_path"])
            expected_transcript = record.get("transcript_sha256")
            pages = record.get("pages")
            methods = record.get("page_methods")
            ocr_pages = record.get("ocr_pages")
            if (not isinstance(expected_transcript, str) or not HASH.fullmatch(expected_transcript)
                    or digest(transcript_path) != expected_transcript
                    or transcript_path.stat().st_size != record.get("transcript_bytes")
                    or transcript_path.stat().st_size <= 0
                    or not isinstance(pages, int) or pages < 1
                    or record.get("covered_pages") != list(range(1, pages + 1))
                    or not isinstance(methods, list) or len(methods) != pages
                    or not set(methods) <= {"anydoc", "local-ocr", "pdftotext-layout"}
                    or not isinstance(ocr_pages, list)
                    or ocr_pages != [i for i, method in enumerate(methods, 1) if method == "local-ocr"]
                    or (ocr_pages and record.get("local_ocr") is not True)
                    ):
                raise ValueError("transcript provenance mismatch")
            transcript_hashes[name] = expected_transcript
            if PDF_NAME.fullmatch(PurePosixPath(name).name):
                markdown = transcript_path.read_text(encoding="utf-8-sig")
                if not markdown.strip():
                    raise ValueError("empty candidate transcript")
        elif record.get("status") not in ("failed", "needs_ocr"):
            raise ValueError("invalid transcription status")
        output.append((name, record, markdown, source_path))
    return output, {"transcription_summary": digest(summary_path),
                    "pdf_source_manifest": digest(source_manifest),
                    "transcription_tool_version": summary["tool_version"],
                    "transcription_records": record_hashes,
                    "transcripts": transcript_hashes}


def layout_text(path):
    result = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True,
                            timeout=30, check=True)
    return result.stdout.decode("utf-8", errors="strict")


def render(register_path, tables, records, input_hashes):
    with register_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = reader.fieldnames
        if not columns or len(columns) != len(set(columns)) or set(EXTRA_COLUMNS) & set(columns):
            raise ValueError("invalid original register header")
        originals = list(reader)
    sources = index_sources(tables, originals)
    audit = []
    verified = defaultdict(list)
    counts = Counter()
    agreements = Counter()
    for name, record, markdown, source_path in records:
        filename = PDF_NAME.fullmatch(PurePosixPath(name).name)
        reason = None
        engine = None
        verification_sha = None
        if not filename:
            reason = "non_quotation_filename"
            state = "excluded"
        elif markdown is None:
            reason = "transcription_failed"
            state = "held"
        else:
            state = "held"
            counts["candidate_documents"] += 1
            try:
                layout = layout_text(source_path)
                if layout.strip():
                    layout_pages = layout.split("\f")
                    if not layout_pages[-1].strip():
                        layout_pages.pop()
                    if (len(layout_pages) != record["pages"]
                            or any(not page.strip() for page in layout_pages)):
                        raise Hold("incomplete_layout_page_coverage")
                    verification = layout
                    engine = "pdftotext-layout"
                elif (record.get("local_ocr") is True and record.get("ocr_pages")
                      and record["ocr_pages"] == list(range(1, record["pages"] + 1))
                      and record.get("page_methods") == ["local-ocr"] * record["pages"]):
                    verification = markdown
                    engine = "local-ocr"
                else:
                    raise Hold("no_independent_text_or_complete_local_ocr")
                verification_sha = sha256(verification.encode("utf-8")).hexdigest()
                key, stamp, rows, field, agreement, mismatch = verify_document(
                    verification, filename[1], columns, sources)
                for row in rows:
                    row.update(price_basis="customer_quote_pdf", source_document=name,
                               source_document_sha256=record["source_sha256"].lower(),
                               source_transcript_sha256=record["transcript_sha256"],
                               source_price_field=field)
                verified[key].append((stamp, name, rows, agreement, mismatch))
                state = "verified"
            except (Hold, subprocess.CalledProcessError, subprocess.TimeoutExpired,
                    UnicodeDecodeError, FileNotFoundError) as error:
                reason = str(error) if isinstance(error, Hold) else "layout_extraction_failed"
        counts[state + "_documents"] += 1
        if reason:
            counts["reason:" + reason] += 1
        audit.append({"document": name, "status": state, "reason": reason,
                      "source_sha256": record["source_sha256"],
                      "transcript_sha256": record.get("transcript_sha256"),
                      "verification_engine": engine, "verification_text_sha256": verification_sha})
    selected = []
    audited = {entry["document"]: entry for entry in audit}
    for key, documents in sorted(verified.items()):
        latest = max(stamp for stamp, _, _, _, _ in documents)
        best = [(name, rows, agreement, mismatch) for stamp, name, rows, agreement, mismatch
                in documents if stamp == latest]
        if len(best) != 1:
            counts["ambiguous_latest_groups"] += 1
            for name, _, _, _ in best:
                audited[name]["status"] = "held"
                audited[name]["reason"] = "ambiguous_latest_letter"
                counts["verified_documents"] -= 1
                counts["held_documents"] += 1
                counts["reason:ambiguous_latest_letter"] += 1
            continue
        selected.extend(best[0][1])
        agreements.update(best[0][2])
        counts["legacy_price_mismatched_rows"] += best[0][3]
    selected.sort(key=lambda row: (row["quote_no"], row["item_no"], Decimal(row["quantity"])))
    result = io.StringIO(newline="")
    writer = csv.DictWriter(result, fieldnames=columns + list(EXTRA_COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(selected)
    counts["selected_rows"] = len(selected)
    counts["selected_groups"] = len({(r["quote_no"], r["item_no"]) for r in selected})
    manifest = {"schema_version": 1, "input_sha256": input_hashes,
                "counts": dict(sorted(counts.items())),
                "price_field_agreements": dict(sorted(agreements.items())),
                "verification_engines": dict(sorted(Counter(
                    entry["verification_engine"] for entry in audit if entry["verification_engine"]).items())),
                "verification_text_sha256": {entry["document"]: entry["verification_text_sha256"]
                    for entry in audit if entry["verification_text_sha256"]},
                "document_quotes_sha256": sha256(result.getvalue().encode("utf-8")).hexdigest()}
    return result.getvalue(), manifest, audit


def verify_unchanged(args, input_hashes, records):
    if (digest(args.register) != input_hashes["original_register"]
            or digest(args.source_manifest) != input_hashes["pdf_source_manifest"]
            or digest(confined_file(args.transcripts, "summary.json")) != input_hashes["transcription_summary"]
            or digest(Path(__file__)) != input_hashes["builder_script"]
            or digest(Path(__file__).with_name("transcribe-pdfs.py")) != input_hashes["transcription_script"]):
        raise ValueError("input proof changed during build")
    for name, expected in input_hashes["dbf_files"].items():
        if digest(confined_file(args.dbf_dir, name)) != expected:
            raise ValueError("DBF input changed during build")
    for name, record, _, _ in records:
        if (digest(confined_file(args.source_dir, name)) != record["source_sha256"].lower()
                or digest(confined_file(args.transcripts, "records/" +
                    sha256(name.encode("utf-8")).hexdigest() + ".json"))
                != input_hashes["transcription_records"][name]):
            raise ValueError("PDF or transcription proof changed during build")
        if name in input_hashes["transcripts"]:
            transcript = "transcripts/" + sha256(name.encode("utf-8")).hexdigest() + ".md"
            if digest(confined_file(args.transcripts, transcript)) != input_hashes["transcripts"][name]:
                raise ValueError("transcript changed during build")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("register", "dbf-dir", "transcripts", "source-dir", "source-manifest", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    roots = [args.register.resolve(), args.dbf_dir.resolve(), args.transcripts.resolve(),
             args.source_dir.resolve(), args.source_manifest.resolve()]
    out = args.out.resolve()
    repository = Path(__file__).resolve().parents[1]
    if (any(out == path or out in path.parents or (path.is_dir() and path in out.parents)
            for path in roots) or out == repository or repository in out.parents
            or args.out.is_symlink()):
        parser.error("output must be separate from source inputs and repository")
    try:
        if os.path.lexists(out):
            raise ValueError("output directory already exists")
        if args.register.is_symlink() or args.source_manifest.is_symlink():
            raise ValueError("symlinked register or source manifest")
        original_hash = digest(args.register)
        source_hash = digest(args.source_manifest)
        tables, dbf_hashes = load_tables(args.dbf_dir)
        records, hashes = load_records(args.transcripts, args.source_dir, args.source_manifest)
        if hashes["pdf_source_manifest"] != source_hash:
            raise ValueError("source manifest changed during build")
        hashes.update(original_register=original_hash, dbf_files=dbf_hashes,
                      builder_script=digest(Path(__file__)),
                      transcription_script=digest(Path(__file__).with_name("transcribe-pdfs.py")))
        csv_data, manifest, audit = render(args.register, tables, records, hashes)
        out.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=out.parent, prefix=".document-register-"))
        try:
            for name, data in (("document-quotes.csv", csv_data),
                               ("evidence-manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n"),
                               ("private-document-audit.json", json.dumps(audit, indent=2, sort_keys=True) + "\n")):
                private_write(staging / name, data)
            verify_unchanged(args, hashes, records)
            if os.path.lexists(out):
                raise ValueError("output directory already exists")
            publish_new_directory(staging, out)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        print(json.dumps({"output": str(out), "counts": manifest["counts"]}, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, ImportError) as error:
        print(f"Document register build failed: {type(error).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
