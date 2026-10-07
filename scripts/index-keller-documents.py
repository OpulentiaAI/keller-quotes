#!/usr/bin/env python3
"""Build public native document metadata and look up pinned private recovery aliases offline."""

import argparse
from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys


PDF_PREFIX = "keller-pdf-corpus/source/"
TRANSCRIPTION_PREFIX = "keller-pdf-corpus/transcription/"
RECORD_PREFIX = TRANSCRIPTION_PREFIX + "records/"
TRANSCRIPT_PREFIX = TRANSCRIPTION_PREFIX + "transcripts/"
ARCHIVE = "[[Keller Git delivery and private artifact access 2026-10-07]]"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
PUBLIC_HINTS = {"QuoteLetter", "Invoice", "PO", "Optional", "Certificate", "Packing", "other"}
PUBLIC_BASES = {"filename-only"}
PUBLIC_STATUSES = {"success", "failed", "needs_ocr", "blank"}
END = object()


class IndexError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise IndexError from None


def safe_relative(value):
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part in ("", ".", "..") for part in value.split("/"))):
        raise IndexError
    return value


def safe_hex(value):
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise IndexError
    return value


def safe_count(value):
    if type(value) is not int or value < 0:
        raise IndexError
    return value


def safe_text(value):
    if not isinstance(value, str) or not value:
        raise IndexError
    return value


def original_path(value):
    value = safe_text(value)
    if not value.startswith("/"):
        raise IndexError
    safe_relative(value[1:])
    return value


def alias_id(value):
    return sha256(safe_relative(value).encode("utf-8")).hexdigest()


def no_duplicate_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise IndexError
        obj[key] = value
    return obj


def reject_constant(value):
    raise IndexError


def decode_json(data):
    return json.loads(data, object_pairs_hook=no_duplicate_keys, parse_constant=reject_constant)


def encode_json(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def absolute_path(value):
    raw = os.fspath(value)
    if not raw.startswith("/"):
        raise IndexError
    safe_relative(raw[1:])
    path = Path(raw)
    for ancestor in (path, *path.parents):
        if os.path.lexists(ancestor) and ancestor.is_symlink():
            raise IndexError
    return path


def open_regular(path):
    path = absolute_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise IndexError
    return os.fdopen(fd, "rb")


def read_verified(path, expected_sha=None, expected_bytes=None, capture=False):
    h = sha256()
    size = 0
    data = []
    with open_regular(path) as stream:
        before = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
            size += len(chunk)
            if capture:
                data.append(chunk)
        after = os.fstat(stream.fileno())
    stamp = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
    if (stamp(before) != stamp(after) or size != after.st_size
            or (expected_sha is not None and h.hexdigest() != expected_sha)
            or (expected_bytes is not None and size != expected_bytes)):
        raise IndexError
    return h.hexdigest(), size, b"".join(data) if capture else None


def descriptor(entry):
    return {"alias": entry["path"], "original_path": entry["original_path"],
            "sha256": entry["sha256"], "bytes": entry["bytes"]}


def load_catalog(path, pin):
    _, _, raw = read_verified(path, safe_hex(pin), capture=True)
    catalog = decode_json(raw)
    if (not isinstance(catalog, dict) or type(catalog.get("schema_version")) is not int
            or catalog["schema_version"] != 1 or catalog.get("scope") != "OPERATOR_ONLY"
            or catalog.get("kind") != "KELLER_OPERATOR_EVIDENCE_ARCHIVE"
            or not isinstance(catalog.get("files"), list)):
        raise IndexError
    entries = {}
    sizes = {}
    trie = {}
    for item in catalog["files"]:
        if not isinstance(item, dict):
            raise IndexError
        alias = safe_relative(item.get("path"))
        original_path(item.get("original_path"))
        pin = safe_hex(item.get("sha256"))
        size = safe_count(item.get("bytes"))
        node = trie
        for part in alias.split("/"):
            if END in node:
                raise IndexError
            node = node.setdefault(part, {})
        if node or (pin in sizes and sizes[pin] != size):
            raise IndexError
        node[END] = True
        entries[alias] = item
        sizes[pin] = size
    return entries


def public_annotation(value, allowed):
    return value if value in allowed else "private-source-annotation"


def public_fields(row):
    record = row["record"]
    status = "missing-record" if record is None else public_annotation(row["record_status"], PUBLIC_STATUSES)
    if row["pdf"]["bytes"] == 0:
        status += ":zero-byte-pdf"
    if row["transcript"] is not None and row["transcript"]["bytes"] == 0:
        status += ":empty-transcript"
    fields = {
        "document_id": row["document_id"], "pdf_sha256": row["pdf"]["sha256"],
        "classification_hint": "unavailable" if record is None else public_annotation(row["filename_classification"], PUBLIC_HINTS),
        "classification_basis": "no-record" if record is None else public_annotation(row["classification_basis"], PUBLIC_BASES),
        "extraction_status": status,
    }
    if record is not None:
        fields["record_sha256"] = record["sha256"]
    if row["transcript"] is not None:
        fields["transcript_sha256"] = row["transcript"]["sha256"]
    return fields


def render_native(row):
    fields = {"type": "keller.document",
              "tldr": "Retained Keller document metadata; source annotations and extraction state do not establish business outcomes.",
              **public_fields(row), "archive": ARCHIVE}
    text = "---\n" + "".join(f"{key}: {json.dumps(value, ensure_ascii=True)}\n" for key, value in fields.items()) + "---\n"
    return text.encode("utf-8")


def collect_documents(entries, root):
    pdfs = {}
    metadata = {}
    transcripts = {}
    dispositions = []
    for alias, entry in sorted(entries.items()):
        if not (alias.startswith(PDF_PREFIX) or alias.startswith(TRANSCRIPTION_PREFIX)):
            continue
        is_json = alias.startswith(TRANSCRIPTION_PREFIX) and PurePosixPath(alias).suffix.lower() == ".json"
        _, _, raw = read_verified(root / alias, entry["sha256"], entry["bytes"], capture=is_json)
        if alias.startswith(PDF_PREFIX) and PurePosixPath(alias).suffix.lower() == ".pdf":
            pdfs[alias[len(PDF_PREFIX):]] = entry
        elif alias.startswith(TRANSCRIPT_PREFIX) and PurePosixPath(alias).suffix.lower() == ".md":
            transcripts[alias] = entry
        elif is_json:
            metadata[alias] = decode_json(raw)
        else:
            dispositions.append({"alias_id": alias_id(alias), "sha256": entry["sha256"], "disposition": "auxiliary-file"})
    records = {}
    transcript_claims = {}
    for alias, record in metadata.items():
        if not alias.startswith(RECORD_PREFIX):
            if isinstance(record, dict) and "relative_source_path" in record:
                raise IndexError
            dispositions.append({"alias_id": alias_id(alias), "sha256": entries[alias]["sha256"], "disposition": "auxiliary-metadata"})
            continue
        if not isinstance(record, dict):
            raise IndexError
        source = safe_relative(record.get("relative_source_path"))
        if PurePosixPath(source).suffix.lower() != ".pdf" or source in records:
            raise IndexError
        source_sha = safe_hex(record.get("source_sha256"))
        source_bytes = safe_count(record.get("source_bytes"))
        status = safe_text(record.get("status"))
        safe_text(record.get("filename_classification"))
        safe_text(record.get("classification_basis"))
        pdf = pdfs.get(source)
        if pdf is not None and (source_sha != pdf["sha256"] or source_bytes != pdf["bytes"]):
            raise IndexError
        transcript_alias = None
        declared = record.get("transcript_path")
        if declared is not None:
            declared = TRANSCRIPTION_PREFIX + safe_relative(declared)
            if (not declared.startswith(TRANSCRIPT_PREFIX) or PurePosixPath(declared).suffix.lower() != ".md"
                    or declared in transcript_claims):
                raise IndexError
            transcript_claims[declared] = source
        has_sha = record.get("transcript_sha256") is not None
        has_size = record.get("transcript_bytes") is not None
        if has_sha != has_size or (status == "success" and not has_sha):
            raise IndexError
        if has_sha:
            transcript_sha = safe_hex(record["transcript_sha256"])
            transcript_bytes = safe_count(record["transcript_bytes"])
            transcript = transcripts.get(declared)
            if transcript is None or transcript["sha256"] != transcript_sha or transcript["bytes"] != transcript_bytes:
                raise IndexError
            transcript_alias = declared
        elif declared in transcripts:
            raise IndexError
        records[source] = (alias, record, declared, transcript_alias)
        if pdf is None:
            dispositions.append({"alias_id": alias_id(alias), "sha256": entries[alias]["sha256"], "disposition": "orphan-record"})
    rows = []
    used_transcripts = set()
    for source, pdf in pdfs.items():
        association = records.get(source)
        record_alias, record, declared, transcript_alias = association if association else (None, None, None, None)
        row = {
            "document_id": alias_id(pdf["path"]), "relative_source_path": source,
            "pdf": descriptor(pdf),
            "record": descriptor(entries[record_alias]) if record_alias is not None else None,
            "transcript": descriptor(transcripts[transcript_alias]) if transcript_alias is not None else None,
            "declared_transcript_alias": declared,
            "filename_classification": record["filename_classification"] if record is not None else None,
            "classification_basis": record["classification_basis"] if record is not None else None,
            "record_status": record["status"] if record is not None else None,
        }
        rows.append(row)
        if transcript_alias is not None:
            used_transcripts.add(transcript_alias)
    for alias in transcripts.keys() - used_transcripts:
        dispositions.append({"alias_id": alias_id(alias), "sha256": transcripts[alias]["sha256"], "disposition": "orphan-transcript"})
    rows.sort(key=lambda row: row["document_id"])
    counts = {
        "pdf_documents": len(rows), "unique_pdf_hashes": len({row["pdf"]["sha256"] for row in rows}),
        "zero_byte_pdfs": sum(row["pdf"]["bytes"] == 0 for row in rows),
        "associated_records": sum(row["record"] is not None for row in rows),
        "missing_records": sum(row["record"] is None for row in rows),
        "transcription_json_files": len(metadata), "transcript_files": len(transcripts),
        "associated_transcripts": len(used_transcripts),
        "extraction_status": dict(sorted(Counter(public_fields(row)["extraction_status"] for row in rows).items())),
        "dispositions": dict(sorted(Counter(item["disposition"] for item in dispositions).items())),
    }
    return rows, sorted(dispositions, key=lambda item: item["alias_id"]), counts


def validate_output(out, root, catalog):
    out = absolute_path(out)
    if os.path.lexists(out) or not out.parent.is_dir():
        raise IndexError
    parent = out.parent.stat()
    if parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) & 0o022:
        raise IndexError
    if out == root or root in out.parents or out in root.parents or catalog in (out, *out.parents):
        raise IndexError
    if any(os.path.lexists(ancestor / ".git") for ancestor in (out.parent, *out.parent.parents)):
        raise IndexError
    return out


def remember_created(path, created):
    info = path.lstat()
    created.append((path, info.st_dev, info.st_ino))


def write_private(path, chunks, created):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    h = sha256()
    size = 0
    with os.fdopen(fd, "wb") as stream:
        remember_created(path, created)
        os.fchmod(stream.fileno(), 0o400)
        for chunk in chunks:
            stream.write(chunk)
            h.update(chunk)
            size += len(chunk)
        stream.flush()
        os.fsync(stream.fileno())
    return {"sha256": h.hexdigest(), "bytes": size}


def cleanup_created(created):
    if not created:
        return
    root, root_dev, root_ino = created[0]
    for path, dev, ino in reversed(created):
        try:
            absolute_path(path)
            root_info = root.lstat()
            if (root_info.st_dev, root_info.st_ino) != (root_dev, root_ino):
                return
            current = path.lstat()
            if (current.st_dev, current.st_ino) != (dev, ino):
                continue
            if stat.S_ISDIR(current.st_mode):
                path.rmdir()
            else:
                path.unlink()
        except (IndexError, OSError):
            pass


def build(catalog, catalog_sha256, restored_root, out):
    catalog = absolute_path(catalog)
    root = absolute_path(restored_root)
    if not root.is_dir():
        raise IndexError
    out = validate_output(out, root, catalog)
    entries = load_catalog(catalog, catalog_sha256)
    rows, dispositions, counts = collect_documents(entries, root)
    script_sha, _, _ = read_verified(Path(__file__).absolute())
    created = []
    try:
        out.mkdir(mode=0o700)
        remember_created(out, created)
        out.chmod(0o700)
        native = out / "native-documents"
        native.mkdir(mode=0o700)
        remember_created(native, created)
        native.chmod(0o700)
        index = write_private(out / "document-index.private.jsonl", (encode_json(row) for row in rows), created)
        native_hash = sha256()
        native_bytes = 0
        for row in rows:
            name = "Keller retained document " + row["document_id"] + ".md"
            receipt = write_private(native / name, [render_native(row)], created)
            native_hash.update(f"{name}\t{receipt['sha256']}\n".encode("utf-8"))
            native_bytes += receipt["bytes"]
        manifest = {
            "schema_version": 1, "kind": "KELLER_DOCUMENT_INDEX",
            "inputs": {"catalog_sha256": catalog_sha256, "builder_sha256": script_sha},
            "outputs": {
                "document_index": dict(index, files=1, records=len(rows)),
                "native_documents": {"files": len(rows), "bytes": native_bytes, "sha256": native_hash.hexdigest(),
                                     "hash_basis": "SHA256 of document-id-sorted UTF-8 lines: filename TAB whole-file-sha256 LF"},
            },
            "counts": counts, "dispositions": dispositions,
            "limitations": "Filename classifications are source annotations only. Retention and extraction do not establish issuance, acceptance, payment, actual job costs or direct quote-line manufacturing identity.",
        }
        receipt = write_private(out / "manifest.json", [encode_json(manifest)], created)
        return {"documents": len(rows), "index_sha256": index["sha256"], "manifest_sha256": receipt["sha256"]}
    except BaseException:
        cleanup_created(created)
        raise


def validate_lookup_row(row):
    keys = {"document_id", "relative_source_path", "pdf", "record", "transcript", "declared_transcript_alias",
            "filename_classification", "classification_basis", "record_status"}
    if not isinstance(row, dict) or set(row) != keys:
        raise IndexError
    safe_hex(row["document_id"])
    source = safe_relative(row["relative_source_path"])
    if PurePosixPath(source).suffix.lower() != ".pdf":
        raise IndexError
    for role, prefix, suffix in (("pdf", PDF_PREFIX, ".pdf"), ("record", RECORD_PREFIX, ".json"),
                                 ("transcript", TRANSCRIPT_PREFIX, ".md")):
        item = row[role]
        if item is None and role != "pdf":
            continue
        if not isinstance(item, dict) or set(item) != {"alias", "original_path", "sha256", "bytes"}:
            raise IndexError
        alias = safe_relative(item["alias"])
        if not alias.startswith(prefix) or PurePosixPath(alias).suffix.lower() != suffix:
            raise IndexError
        original_path(item["original_path"])
        safe_hex(item["sha256"])
        safe_count(item["bytes"])
    if row["pdf"]["alias"] != PDF_PREFIX + source or alias_id(row["pdf"]["alias"]) != row["document_id"]:
        raise IndexError
    declared = row["declared_transcript_alias"]
    if declared is not None:
        safe_relative(declared)
        if not declared.startswith(TRANSCRIPT_PREFIX) or PurePosixPath(declared).suffix.lower() != ".md":
            raise IndexError
    if row["record"] is None:
        if any(row[key] is not None for key in ("transcript", "declared_transcript_alias", "filename_classification", "classification_basis", "record_status")):
            raise IndexError
    else:
        for key in ("filename_classification", "classification_basis", "record_status"):
            safe_text(row[key])
        if row["record_status"] == "success" and row["transcript"] is None:
            raise IndexError
    if row["transcript"] is not None and row["transcript"]["alias"] != declared:
        raise IndexError


def lookup(index, index_sha256, document_id):
    pin = safe_hex(index_sha256)
    document_id = safe_hex(document_id)
    previous = ""
    selected = None
    h = sha256()
    with open_regular(index) as stream:
        info = os.fstat(stream.fileno())
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise IndexError
        for line in stream:
            h.update(line)
            row = decode_json(line)
            validate_lookup_row(row)
            if row["document_id"] <= previous:
                raise IndexError
            previous = row["document_id"]
            if row["document_id"] == document_id:
                selected = row
    if h.hexdigest() != pin or selected is None:
        raise IndexError
    return selected


def main(argv=None):
    parser = Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    build_parser = commands.add_parser("build", help="Create a new owner-private directory outside Git.")
    build_parser.add_argument("--catalog", required=True)
    build_parser.add_argument("--catalog-sha256", required=True)
    build_parser.add_argument("--restored-root", required=True)
    build_parser.add_argument("--out", required=True)
    lookup_parser = commands.add_parser("lookup", help="Return private operator metadata; never a quote-worker transport.")
    lookup_parser.add_argument("--index", required=True)
    lookup_parser.add_argument("--index-sha256", required=True)
    lookup_parser.add_argument("--document-id", required=True)
    try:
        args = parser.parse_args(argv)
        if args.command == "build":
            result = build(args.catalog, args.catalog_sha256, args.restored_root, args.out)
        else:
            result = lookup(args.index, args.index_sha256, args.document_id)
        sys.stdout.buffer.write(encode_json(result))
        return 0
    except (IndexError, OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        print("document index operation failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
