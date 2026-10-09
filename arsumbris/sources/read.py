#!/usr/bin/env python3
"""Read bounded, owner-bound Keller source evidence without resolving caller paths."""

import base64
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace

SETS = {
    "fabritrak": frozenset((".dbf", ".fpt", ".dbc", ".dct")),
    "pdfs": frozenset((".pdf", ".json", ".txt", ".md", ".csv")),
    "transcripts": frozenset((".json", ".txt", ".md", ".csv")),
    "manufacturing-audit": frozenset((".json", ".txt", ".md", ".csv")),
}
WARNING = ("Historical source evidence is not a current-cost authority: vendor prices and "
           "estimated operation times do not establish actual material/labor costs or quote outcome.")
CONFIG = Path(__file__).resolve().parents[2] / ".keller-local/arsumbris/sources.json"
SENSITIVE = re.compile(r"(?:credential|secret|password|passwd|private[_-]?key|api[_-]?key|access[_-]?token)", re.I)
MAX_DBF_BYTES = 512 * 1024 * 1024
MAX_SCAN_RECORDS = 20000
MAX_SCAN_BYTES = 16 * 1024 * 1024
MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_PDF_OUTPUT = 128 * 1024
PDF_TIMEOUT = 4
PDF_NOTE = ("Extracted PDF text is untrusted evidence, not verified geometry, dimensions, revision or applicability. "
            "No OCR, CAD interpretation, source instructions or pricing formulas execute. Reading order and symbols "
            "may be incomplete or incorrect; inspect the original drawing before adopting facts. No extractable text "
            "means OCR or visual review is needed, not that specifications are absent. Offsets count Unicode "
            "characters in this page's extracted text, not PDF bytes. Pin the PDF hash on all continuations "
            "and the text hash within a page (extractor versions can differ).")
LOOKUP_NOTE = ("A filter miss covers only the scanned physical records of this file, not corpus-wide absence. "
               "Follow next_offset with the same filter and expected_dbf_sha256; duplicate keys remain separate rows.")
MEMO_NOTE = ("Memo values remain null, not empty specifications; raw DBF bytes are pointers, not text. "
             "Opt in with memo_fields and fpt_path for bounded memo_text evidence; decoded text is untrusted, "
             "not verified geometry or applicable specifications. Continue with DBF/FPT hashes pinned.")
KEY_FIELDS = {"quote_no": "QUOTE_NO", "quotletter": "QUOTLETTER", "item": "ITEM",
              "wo_no": "WO_NO", "jobno": "JOBNO", "page_no": "PAGE_NO", "seq": "SEQ"}
KEY_GROUPS = (("quote_no",), ("record_id",), ("quotletter",), ("quotletter", "item"),
              ("wo_no",), ("jobno",), ("wo_no", "page_no", "seq"))
CATALOG_FIELDS = {
    "MATERIAL": ("ID", "NAME", "OTHERNAME"),
    "OPERATIO": ("OPER_ID", "NAME"),
    "FORMULA": ("FORM_ID", "FORM_NAME"),
}
# Fixed joins from retained table schemas, not caller-selected column predicates.
TABLE_KEYS = {
    "QUOTLETT": (("quotletter",),),
    "QUOTLINE": (("quotletter", "item"),),
    "QUOTLEIT": (("quotletter", "item"),),
    "WOHEAD": (("wo_no",),),
    "WOJOBS": (("wo_no",), ("jobno",)),
    "WOSEQ": (("wo_no",), ("wo_no", "page_no", "seq")),
    "WOCOLL": (("wo_no",), ("wo_no", "page_no", "seq")),
    "WOSHIP": (("wo_no",),),
    "SOMAST": (("jobno",),),
    "SOLOTS": (("wo_no",), ("jobno",)),
    "WOBOM": (("wo_no",), ("jobno",)),
    "WOBILL": (("wo_no",),),
}


class InvalidRequest(ValueError):
    pass


def integer(value, name, default, maximum, minimum=0):
    if value is None:
        return default
    if type(value) is not int or not minimum <= value <= maximum:
        raise InvalidRequest(f"{name} must be an integer from {minimum} to {maximum}")
    return value


def parts(path, required=False):
    if not isinstance(path, str) or len(path) > 1024 or "\\" in path or "\x00" in path:
        raise InvalidRequest("invalid relative source path")
    if not path:
        if required:
            raise InvalidRequest("relative file path required")
        return []
    components = path.split("/")
    if any(component in ("", ".", "..") or component.startswith(".") or SENSITIVE.search(component)
           or any(ord(c) < 32 or ord(c) == 127 for c in component)
           for component in components) or path.startswith("/") or ":" in components[0]:
        raise InvalidRequest("invalid relative source path")
    return components


def validate(request):
    if not isinstance(request, dict):
        raise InvalidRequest("input must be an object")
    action = request.get("action")
    allowed = {
        "sets": {"action"},
        "list": {"action", "source_set", "path", "offset", "limit"},
        "read": {"action", "source_set", "path", "offset", "limit", "encoding"},
        "pdf_text": {"action", "source_set", "path", "page", "offset", "limit", "expected_pdf_sha256", "expected_text_sha256"},
        "dbf_schema": {"action", "source_set", "path"},
        "dbf_catalog": {"action", "source_set", "path", "query", "offset", "limit", "expected_dbf_sha256"},
        "dbf_rows": {"action", "source_set", "path", "quote_no", "record_id", "quotletter", "item",
                     "wo_no", "jobno", "page_no", "seq", "offset", "limit", "expected_dbf_sha256",
                     "memo_fields", "fpt_path", "expected_fpt_sha256", "memo_offset", "memo_limit"},
    }
    if action not in allowed or set(request) - allowed[action]:
        raise InvalidRequest("unsupported action or fields")
    if action == "sets":
        return request
    if request.get("source_set") not in SETS:
        raise InvalidRequest("unknown source set")
    components = parts(request.get("path", ""), action != "list")
    if action in ("read", "dbf_schema", "dbf_rows", "dbf_catalog"):
        if Path(components[-1]).suffix.lower() not in SETS[request["source_set"]]:
            raise InvalidRequest("source file type not approved")
    if action.startswith("dbf_") and (request["source_set"] != "fabritrak" or
                                     Path(components[-1]).suffix.lower() != ".dbf"):
        raise InvalidRequest("DBF action requires a fabritrak .dbf file")
    if action == "pdf_text":
        if request["source_set"] != "pdfs" or Path(components[-1]).suffix.lower() != ".pdf":
            raise InvalidRequest("pdf_text requires an owner-bound pdfs .pdf file")
        if request.get("page") is None:
            raise InvalidRequest("explicit one-based page required")
        page = integer(request["page"], "page", 1, 10000, 1)
        offset = integer(request.get("offset"), "offset", 0, MAX_PDF_OUTPUT)
        integer(request.get("limit"), "limit", 4096, 4096, 1)
        for key in ("expected_pdf_sha256", "expected_text_sha256"):
            if key in request and (not isinstance(request[key], str) or not re.fullmatch(r"[0-9a-f]{64}", request[key])):
                raise InvalidRequest(f"{key} must be a lowercase SHA256")
        if (page > 1 or offset > 0) and "expected_pdf_sha256" not in request:
            raise InvalidRequest("PDF page/text continuation requires expected_pdf_sha256")
        if offset > 0 and "expected_text_sha256" not in request:
            raise InvalidRequest("PDF text continuation requires expected_text_sha256")
    if action == "dbf_rows":
        keys = set(request) & (set(KEY_FIELDS) | {"record_id"})
        if keys not in [set(group) for group in KEY_GROUPS]:
            raise InvalidRequest("one complete approved exact key required; inspect dbf_schema exact_filters")
        for field in keys:
            value = request[field]
            if (not isinstance(value, str) or not value.strip() or value != value.strip()
                    or len(value) > 32 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise InvalidRequest(f"exact {field} required (maximum 32 characters, no edge whitespace)")
        memo_keys = {"fpt_path", "expected_fpt_sha256", "memo_offset", "memo_limit"}
        if "memo_fields" in request:
            selected = request["memo_fields"]
            if (not isinstance(selected, list) or not 1 <= len(selected) <= 4 or
                    any(not isinstance(f, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,10}", f) for f in selected) or
                    len(set(selected)) != len(selected)):
                raise InvalidRequest("memo_fields requires 1..4 unique schema field names")
            memo = parts(request.get("fpt_path", ""), True)
            if (memo[:-1] != components[:-1] or Path(memo[-1]).suffix.lower() != ".fpt" or
                    Path(memo[-1]).stem != Path(components[-1]).stem):
                raise InvalidRequest("fpt_path must be the same-stem sibling FPT within the owner root")
            if "expected_fpt_sha256" in request and (not isinstance(request["expected_fpt_sha256"], str) or
                    not re.fullmatch(r"[0-9a-f]{64}", request["expected_fpt_sha256"])):
                raise InvalidRequest("expected_fpt_sha256 must be a lowercase SHA256")
            integer(request.get("memo_offset"), "memo_offset", 0, MAX_DBF_BYTES)
            integer(request.get("memo_limit"), "memo_limit", 2048, 4096, 1)
        elif memo_keys & set(request):
            raise InvalidRequest("memo options require explicit memo_fields")
    if action == "dbf_catalog":
        if Path(components[-1]).stem.upper() not in CATALOG_FIELDS:
            raise InvalidRequest("catalog discovery is limited to MATERIAL, OPERATIO and FORMULA")
        if "query" in request:
            query = request["query"]
            if (not isinstance(query, str) or not query.strip() or query != query.strip() or len(query) > 80
                    or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in query)):
                raise InvalidRequest("query must be 1..80 literal characters without edge whitespace or controls")
        if integer(request.get("offset"), "offset", 0, 10000000) and "expected_dbf_sha256" not in request:
            raise InvalidRequest("catalog continuation requires expected_dbf_sha256")
    if action in ("dbf_rows", "dbf_catalog"):
        if "expected_dbf_sha256" in request and (not isinstance(request["expected_dbf_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", request["expected_dbf_sha256"])):
            raise InvalidRequest("expected_dbf_sha256 must be a lowercase SHA256")
        integer(request.get("offset"), "offset", 0, 10000000)
        integer(request.get("limit"), "limit", 5, 5, 1)
    if action == "list":
        integer(request.get("offset"), "offset", 0, 1000000)
        integer(request.get("limit"), "limit", 50, 50, 1)
    if action == "read":
        integer(request.get("offset"), "offset", 0, 10000000000)
        integer(request.get("limit"), "limit", 4096, 4096, 1)
        if request.get("encoding", "utf-8") not in ("utf-8", "latin-1", "base64"):
            raise InvalidRequest("encoding must be utf-8, latin-1 or base64")
    return request


def configuration():
    path = Path(os.environ.get("KELLER_SOURCE_CONFIG") or CONFIG)
    if not path.is_absolute() or path.is_symlink():
        raise InvalidRequest("owner source configuration unavailable")
    try:
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid() or metadata.st_mode & 0o022 or metadata.st_size > 4096:
            raise InvalidRequest("owner source configuration unavailable")
        with path.open("r", encoding="utf-8") as file:
            bindings = json.load(file)
    except (OSError, UnicodeError, ValueError):
        raise InvalidRequest("owner source configuration unavailable") from None
    if not isinstance(bindings, dict) or set(bindings) - set(SETS):
        raise InvalidRequest("invalid owner source configuration")
    for name, location in bindings.items():
        if not isinstance(location, str) or not location.startswith("/") or len(location) > 1024:
            raise InvalidRequest("invalid owner source configuration")
        root = Path(location)
        if root.is_symlink() or not root.is_dir() or root.resolve() != root:
            raise InvalidRequest("owner source root unavailable")
    return bindings


def open_source(root, components, directory=False):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
    fd = os.open(root, flags)
    try:
        for component in components[:-1] if not directory else components:
            following = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = following
        if not directory:
            following = os.open(components[-1], os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            os.close(fd)
            fd = following
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise InvalidRequest("source is not a regular file")
        return fd
    except BaseException:
        os.close(fd)
        raise


def citation(request):
    return {"source_set": request["source_set"], "path": request.get("path", ""),
            "verification": "owner-bound local source; content hash not checked"}


def file_state(fd):
    info = os.fstat(fd)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def unchanged(fd, table):
    if file_state(fd) != table.state:
        raise InvalidRequest("DBF changed during read; restart with a stable source")


def dbf_table(fd):
    """Parse only bounded fixed-width DBFs; never open an inferred memo/index path."""
    state = file_state(fd)
    size = state[2]
    if not 65 <= size <= MAX_DBF_BYTES:
        raise InvalidRequest("DBF file size exceeds reader limits or is truncated")
    header = os.pread(fd, 32, 0)
    if len(header) != 32 or header[0] not in (0x03, 0x83, 0x30, 0x31, 0x32, 0xF5):
        raise InvalidRequest("unsupported or malformed DBF header")
    count = int.from_bytes(header[4:8], "little")
    headerlen = int.from_bytes(header[8:10], "little")
    recordlen = int.from_bytes(header[10:12], "little")
    if not 65 <= headerlen <= 65535 or not 2 <= recordlen <= 65535 or count > 10000000:
        raise InvalidRequest("DBF structure exceeds reader limits")
    if header[14] or header[15]:
        raise InvalidRequest("incomplete or encrypted DBF is unsupported")
    end = headerlen + count * recordlen
    if size not in (end, end + 1) or (size == end + 1 and os.pread(fd, 1, end) != b"\x1a"):
        raise InvalidRequest("DBF size does not match declared physical records")
    data = os.pread(fd, headerlen, 0)
    if len(data) != headerlen:
        raise InvalidRequest("truncated DBF header")
    fields, names, cursor, start = [], set(), 32, 1
    while cursor < headerlen and data[cursor] != 0x0D:
        if cursor + 32 > headerlen or len(fields) >= 256:
            raise InvalidRequest("malformed or oversized DBF field descriptors")
        descriptor = data[cursor:cursor + 32]
        name_bytes = descriptor[:11].split(b"\x00", 1)[0]
        if not re.fullmatch(rb"[A-Za-z_][A-Za-z_0-9]{0,10}", name_bytes):
            raise InvalidRequest("invalid DBF field name")
        name = name_bytes.decode("ascii")
        kind, length, decimals = chr(descriptor[11]), descriptor[16], descriptor[17]
        if name.upper() in names or kind not in "CNFDLMGPIBYT" or not length:
            raise InvalidRequest("duplicate or unsupported DBF field")
        # Nullable, variable-width and binary character fields need separate semantics.
        if descriptor[18] & 0x06 or (kind not in "NF" and decimals):
            raise InvalidRequest("unsupported DBF field flags or precision")
        fixed_lengths = {"D": (8,), "L": (1,), "I": (4,), "Y": (8,), "T": (8,),
                         "B": (8,), "M": (4, 10), "G": (4, 10), "P": (4, 10)}
        if (kind in fixed_lengths and length not in fixed_lengths[kind]) or (kind in "NF" and decimals >= length):
            raise InvalidRequest("invalid DBF field width or precision")
        names.add(name.upper())
        fields.append(SimpleNamespace(name=name, type=kind, length=length, decimal_count=decimals, offset=start))
        start += length
        cursor += 32
    if cursor >= headerlen or not fields or start != recordlen:
        raise InvalidRequest("missing DBF terminator or record width mismatch")
    # Visual FoxPro may retain a 263-byte database backlink after the terminator.
    remainder = headerlen - cursor - 1
    if remainder and not (header[0] in (0x30, 0x31, 0x32) and remainder == 263):
        raise InvalidRequest("unsupported DBF header extension")
    encoding = {0: "ascii", 0x01: "cp437", 0x02: "cp850", 0x03: "cp1252", 0x57: "cp1252"}.get(header[29])
    if encoding is None:
        raise InvalidRequest("unsupported DBF code page")
    digest = hashlib.sha256()
    for position in range(0, size, 1024 * 1024):
        chunk = os.pread(fd, min(1024 * 1024, size - position), position)
        if len(chunk) != min(1024 * 1024, size - position):
            raise InvalidRequest("DBF changed during hashing")
        digest.update(chunk)
    table = SimpleNamespace(fields=fields, encoding=encoding, state=state, sha256=digest.hexdigest(), version=header[0],
                            header=SimpleNamespace(numrecords=count, headerlen=headerlen, recordlen=recordlen))
    unchanged(fd, table)
    return table


def exact_filters(table, request):
    fields = {field.name.upper(): field for field in table.fields}
    filters = []
    # Preserve the original schema-gated quote/catalog forms on previously supported DBFs.
    if "QUOTE_NO" in fields and fields["QUOTE_NO"].type == "C":
        filters.append({"quote_no": "QUOTE_NO"})
    ids = [name for name in ("ID", "FORM_ID", "OPER_ID") if name in fields and fields[name].type == "C"]
    if len(ids) == 1:
        filters.append({"record_id": ids[0]})
    for group in TABLE_KEYS.get(Path(request["path"]).stem.upper(), ()):
        mapping = {key: KEY_FIELDS[key] for key in group}
        if all(name in fields and fields[name].type == ("N" if key == "page_no" else "C")
               and fields[name].decimal_count == 0 for key, name in mapping.items()):
            filters.append(mapping)
    return filters


def dbf_citation(table, request):
    return {**citation(request), "dbf_sha256": table.sha256, "size_bytes": table.state[2],
            "verification": "SHA256 measured from opened DBF; not authenticated against an external catalog"}


def catalog_fields(table, request):
    selected = CATALOG_FIELDS.get(Path(request["path"]).stem.upper(), ())
    fields = {field.name.upper(): field for field in table.fields}
    if (not selected or not all(name in fields and fields[name].type == "C" for name in selected)
            or "QUOTE_NO" in fields
            or [name for name in ("ID", "OPER_ID", "FORM_ID") if name in fields] != [selected[0]]):
        return ()
    return tuple(fields[name].name for name in selected)


def dbf_schema(table, request):
    return {"action": "dbf_schema", "citation": dbf_citation(table, request),
            "record_count_header": table.header.numrecords, "header_bytes": table.header.headerlen,
            "record_bytes": table.header.recordlen, "encoding": table.encoding,
            "fields": [{"name": f.name, "type": f.type, "length": f.length,
                        "decimal_count": f.decimal_count, "record_byte_offset": f.offset} for f in table.fields],
            "exact_filters": exact_filters(table, request), "lookup_scope_note": LOOKUP_NOTE,
            **({"catalog_lookup": {"action": "dbf_catalog", "text_fields": catalog_fields(table, request),
                                    "match": "case-insensitive literal substring; candidates only"}}
               if catalog_fields(table, request) else {}),
            "scan_record_limit": MAX_SCAN_RECORDS, "scan_byte_limit": MAX_SCAN_BYTES,
            "memo_note": MEMO_NOTE, "warning": WARNING}


def record_values(table, record):
    values, binary = {}, {}
    for field in table.fields:
        raw = record[field.offset:field.offset + field.length]
        if field.type in "MGPBIYT":
            values[field.name] = None
            binary[field.name] = {"status": "memo_decode_deferred" if field.type in "MGP" else "binary_decode_deferred",
                                  "encoding": "base64", "raw_bytes": base64.b64encode(raw).decode("ascii"),
                                  "record_byte_offset": field.offset, "length": field.length}
            continue
        try:
            value = raw.strip(b" \x00").decode(table.encoding if field.type == "C" else "ascii")
        except UnicodeDecodeError:
            raise InvalidRequest("undecodable DBF field; no replacement text returned") from None
        if field.type in "NF" and value and not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", value):
            raise InvalidRequest("malformed DBF numeric field")
        if field.type == "L" and value not in ("", "?", "T", "F", "Y", "N", "t", "f", "y", "n"):
            raise InvalidRequest("malformed DBF logical field")
        if field.type == "D" and value not in ("", "00000000"):
            try:
                if len(value) != 8 or not value.isascii() or not value.isdigit():
                    raise ValueError()
                datetime.strptime(value, "%Y%m%d")
            except ValueError:
                raise InvalidRequest("malformed DBF date field") from None
        values[field.name] = value
    return values, binary


def fpt_table(fd, request):
    state = file_state(fd)
    if not 512 <= state[2] <= MAX_DBF_BYTES:
        raise InvalidRequest("FPT is truncated or exceeds reader limits")
    header = os.pread(fd, 512, 0)
    block_size = int.from_bytes(header[6:8], "big")
    if not 1 <= block_size <= 65535:
        raise InvalidRequest("invalid FPT block size")
    digest = hashlib.sha256()
    for position in range(0, state[2], 1024 * 1024):
        chunk = os.pread(fd, min(1024 * 1024, state[2] - position), position)
        if len(chunk) != min(1024 * 1024, state[2] - position):
            raise InvalidRequest("FPT changed during hashing")
        digest.update(chunk)
    memo = SimpleNamespace(state=state, sha256=digest.hexdigest(), block_size=block_size, fd=fd)
    unchanged(fd, memo)
    if request.get("expected_fpt_sha256", memo.sha256) != memo.sha256:
        raise InvalidRequest("FPT hash mismatch; do not continue across source versions")
    return memo


def memo_text(table, record, field, memo, request):
    evidence = {"status": "decode_error", "field_record_byte_offset": field.offset,
                "pointer_length": field.length, "fpt_path": request["fpt_path"]}
    if memo is not None:
        evidence["fpt_sha256"] = memo.sha256
    if table.version not in (0x30, 0x31, 0x32, 0xF5):
        return {**evidence, "status": "unsupported_dbf_memo_format"}
    raw = record[field.offset:field.offset + field.length]
    if field.length == 4:
        block = int.from_bytes(raw, "little")
    else:
        pointer = raw.strip(b" \x00")
        if pointer and not pointer.isdigit():
            return evidence
        block = int(pointer or b"0")
    if block == 0:
        return {**evidence, "status": "empty_pointer"}
    if memo is None:
        return {**evidence, "status": "memo_file_missing"}
    start = block * memo.block_size
    evidence["fpt_block_offset"] = start
    if start < 512 or start + 8 > memo.state[2]:
        return evidence
    header = os.pread(memo.fd, 8, start)
    kind, length = int.from_bytes(header[:4], "big"), int.from_bytes(header[4:], "big")
    if start + 8 + length > memo.state[2]:
        return evidence
    if kind != 1:
        return {**evidence, "status": "unsupported_memo_type", "memo_type": kind}
    offset, limit = request.get("memo_offset", 0), request.get("memo_limit", 2048)
    if offset > length:
        return {**evidence, "status": "offset_exceeds_memo", "size_bytes": length}
    chunk = os.pread(memo.fd, min(limit, length - offset), start + 8 + offset)
    if len(chunk) != min(limit, length - offset):
        raise InvalidRequest("FPT changed during read")
    try:
        content = chunk.decode(table.encoding)
    except UnicodeDecodeError:
        return {**evidence, "encoding": table.encoding}
    following = offset + len(chunk)
    return {**evidence, "status": "decoded_text", "encoding": table.encoding, "content": content,
            "fpt_text_byte_offset": start + 8, "offset": offset, "bytes_read": len(chunk),
            "size_bytes": length, "chunk_sha256": hashlib.sha256(chunk).hexdigest(),
            "has_more": following < length, "next_offset": following if following < length else None}


def dbf_rows(fd, table, request, memo=None):
    catalog = request["action"] == "dbf_catalog"
    if catalog:
        text_fields = catalog_fields(table, request)
        if not text_fields:
            raise InvalidRequest("DBF lacks the approved catalog schema; inspect dbf_schema")
        mapping = {}
    else:
        keys = set(request) & (set(KEY_FIELDS) | {"record_id"})
        filters = [mapping for mapping in exact_filters(table, request) if set(mapping) == keys]
        if len(filters) != 1:
            raise InvalidRequest("DBF lacks the requested approved exact key; inspect dbf_schema exact_filters")
        mapping = filters[0]
    selected_memos = request.get("memo_fields", [])
    memo_fields = {f.name: f for f in table.fields if f.type == "M"}
    if any(name not in memo_fields for name in selected_memos):
        raise InvalidRequest("memo_fields must select exact text M fields from dbf_schema")
    fields = {field.name.upper(): field for field in table.fields}
    if request.get("expected_dbf_sha256", table.sha256) != table.sha256:
        raise InvalidRequest("DBF hash mismatch; do not continue across source versions")
    offset = integer(request.get("offset"), "offset", 0, 10000000)
    limit = integer(request.get("limit"), "limit", 5, 5, 1)
    count = table.header.numrecords
    if offset > count:
        raise InvalidRequest("offset exceeds DBF record count")
    position, deleted, rows = offset, 0, []
    max_scan = min(MAX_SCAN_RECORDS, MAX_SCAN_BYTES // table.header.recordlen)
    while position < count and position - offset < max_scan:
        index = position
        byte_offset = table.header.headerlen + index * table.header.recordlen
        record = os.pread(fd, table.header.recordlen, byte_offset)
        if len(record) != table.header.recordlen:
            raise InvalidRequest("DBF changed during read")
        position += 1
        if record[:1] == b"*":
            deleted += 1
            continue
        if record[:1] != b" ":
            raise InvalidRequest("malformed DBF deletion marker")
        values, binary = record_values(table, record)
        if any(values[fields[name].name] != request[key] for key, name in mapping.items()):
            continue
        if catalog and "query" in request and not any(request["query"].casefold() in values[name].casefold()
                                                       for name in text_fields):
            continue
        candidate = {"record_index": index, "record_byte_offset": byte_offset,
                     "record_bytes": table.header.recordlen, "record_sha256": hashlib.sha256(record).hexdigest(),
                     "values": values, "truncated_fields": [], "binary_fields": binary,
                     "memo_fields": [f.name for f in table.fields if f.type in "MGP"]}
        if selected_memos:
            candidate["memo_text"] = {name: memo_text(table, record, memo_fields[name], memo, request)
                                      for name in selected_memos}
        if len(json.dumps(rows + [candidate])) > 48000:
            if not rows:
                raise InvalidRequest("DBF record projection exceeds response limit")
            position = index
            break
        rows.append(candidate)
        if len(rows) == limit:
            break
    unchanged(fd, table)
    if memo is not None:
        unchanged(memo.fd, memo)
    more = position < count
    response = {"action": request["action"], "citation": dbf_citation(table, request),
                **{key: request[key] for key in mapping}, "filter_fields": mapping,
                "rows": rows, "record_count_header": count, "offset": offset, "record_index_base": 0,
                "scanned_records": position - offset, "deleted_records_skipped": deleted,
                "scan_end_offset": position, "scan_record_limit": MAX_SCAN_RECORDS, "scan_byte_limit": MAX_SCAN_BYTES,
                "has_more": more, "next_offset": position if more else None,
                "lookup_scope_note": LOOKUP_NOTE, "memo_note": MEMO_NOTE, "warning": WARNING}
    if catalog:
        response.update({"catalog_text_fields": text_fields, "query": request.get("query"),
                         "selection_note": "Discovery candidates only; no applicability, unit, COST/SELL or freshness decision made"})
    if len(mapping) == 1:
        response["filter_field"] = fields[next(iter(mapping.values()))].name
    return response


def pdf_limits():
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_PDF_OUTPUT,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def pdf_command(fd, command):
    # Files plus RLIMIT_FSIZE bound child output without unbounded parent pipe buffers.
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        try:
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output, stderr=errors,
                                    pass_fds=(fd,), timeout=PDF_TIMEOUT, preexec_fn=pdf_limits,
                                    env={"PATH": os.environ.get("PATH", os.defpath), "LC_ALL": "C.UTF-8"})
        except FileNotFoundError:
            raise InvalidRequest("PDF text tools unavailable; install poppler-utils on the source host") from None
        except subprocess.TimeoutExpired:
            raise InvalidRequest("PDF text extraction timed out; no page text accepted") from None
        output.seek(0)
        errors.seek(0)
        content, diagnostics = output.read(MAX_PDF_OUTPUT + 1), errors.read(MAX_PDF_OUTPUT + 1)
        if result.returncode or diagnostics.strip() or len(content) >= MAX_PDF_OUTPUT:
            raise InvalidRequest("PDF extraction failed, warned or exceeded resource/output limits; no text accepted")
        try:
            return content.decode("utf-8")
        except UnicodeDecodeError:
            raise InvalidRequest("PDF extractor returned invalid UTF-8; no text accepted") from None


def pdf_text(fd, request):
    state = file_state(fd)
    if not 8 <= state[2] <= MAX_PDF_BYTES or os.pread(fd, 5, 0) != b"%PDF-":
        raise InvalidRequest("PDF must have a PDF header and be at most 32 MiB")
    digest = hashlib.sha256()
    for start in range(0, state[2], 1024 * 1024):
        digest.update(os.pread(fd, min(1024 * 1024, state[2] - start), start))
    sha = digest.hexdigest()
    if "expected_pdf_sha256" in request and request["expected_pdf_sha256"] != sha:
        raise InvalidRequest("PDF hash mismatch; restart with reviewed source bytes")
    source = f"/proc/self/fd/{fd}"
    info = pdf_command(fd, ["pdfinfo", "-enc", "UTF-8", source])
    pages = re.findall(r"^Pages:\s+(\d+)\s*$", info, re.M)
    encrypted = re.findall(r"^Encrypted:\s+(yes|no)(?:\s+[^\r\n]*)?$", info, re.M)
    if len(pages) != 1 or len(encrypted) != 1 or encrypted[0] != "no":
        raise InvalidRequest("PDF page count/encryption metadata unavailable or encrypted PDF unsupported")
    page_count, page = int(pages[0]), request["page"]
    if not 1 <= page_count <= 10000 or page > page_count:
        raise InvalidRequest("PDF page exceeds page count or supported document limit")
    content = pdf_command(fd, ["pdftotext", "-f", str(page), "-l", str(page), "-layout",
                               "-nopgbrk", "-enc", "UTF-8", source, "-"])
    if file_state(fd) != state:
        raise InvalidRequest("PDF changed during extraction; restart with a stable source")
    text_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
    if "expected_text_sha256" in request and request["expected_text_sha256"] != text_sha:
        raise InvalidRequest("extracted text hash mismatch; restart this page with a stable extractor")
    offset, limit = request.get("offset", 0), request.get("limit", 4096)
    if offset > len(content):
        raise InvalidRequest("offset exceeds extracted page text")
    following = min(offset + limit, len(content))
    return {"action": "pdf_text", "citation": {**citation(request), "pdf_sha256": sha,
            "verification": "measured local PDF SHA256; not authenticated against an external catalog"},
            "page": page, "page_count": page_count, "size_bytes": state[2],
            "extractor": "poppler_pdftotext_layout_utf8", "text_sha256": text_sha,
            "status": "text_extracted" if content.strip() else "no_extractable_text",
            "offset": offset, "offset_unit": "unicode_characters", "total_characters": len(content),
            "content": content[offset:following], "has_more": following < len(content),
            "next_offset": following if following < len(content) else None,
            "extraction_note": PDF_NOTE, "warning": WARNING}


def read(bindings, request):
    if request["action"] == "sets":
        return {"action": "sets", "source_sets": [{"id": name, "configured": name in bindings,
                 "extensions": sorted(extensions)} for name, extensions in SETS.items()], "warning": WARNING}
    source_set = request["source_set"]
    if source_set not in bindings:
        raise InvalidRequest("source set is not configured")
    components = parts(request.get("path", ""))
    action = request["action"]
    fd = open_source(bindings[source_set], components, directory=action == "list")
    try:
        if action == "list":
            entries = []
            with os.scandir(fd) as listing:
                for item in listing:
                    if item.name.startswith(".") or SENSITIVE.search(item.name) or item.is_symlink():
                        continue
                    if item.is_dir(follow_symlinks=False):
                        entries.append({"name": item.name, "kind": "directory"})
                    elif item.is_file(follow_symlinks=False) and Path(item.name).suffix.lower() in SETS[source_set]:
                        entries.append({"name": item.name, "kind": "file", "size_bytes": item.stat(follow_symlinks=False).st_size})
                    if len(entries) > 100000:
                        raise InvalidRequest("directory exceeds inventory limit")
            entries.sort(key=lambda item: item["name"])
            offset, limit = request.get("offset", 0), request.get("limit", 50)
            return {"action": action, "citation": citation(request), "entries": entries[offset:offset + limit],
                    "has_more": offset + limit < len(entries), "next_offset": offset + limit if offset + limit < len(entries) else None,
                    "warning": WARNING}
        if action == "read":
            size = os.fstat(fd).st_size
            offset, limit = request.get("offset", 0), request.get("limit", 4096)
            if offset > size:
                raise InvalidRequest("offset exceeds file size")
            os.lseek(fd, offset, os.SEEK_SET)
            chunk = os.read(fd, limit)
            encoding = request.get("encoding", "utf-8")
            if encoding == "base64":
                content = base64.b64encode(chunk).decode("ascii")
            else:
                try:
                    content = chunk.decode(encoding)
                except UnicodeDecodeError:
                    raise InvalidRequest("bytes cannot be decoded at this offset/limit; use base64 or latin-1") from None
            following = offset + len(chunk)
            return {"action": action, "citation": citation(request), "size_bytes": size, "offset": offset,
                    "bytes_read": len(chunk), "encoding": encoding, "content": content,
                    "has_more": following < size, "next_offset": following if following < size else None,
                    "warning": WARNING}
        if action == "pdf_text":
            return pdf_text(fd, request)
        table = dbf_table(fd)
        if action == "dbf_schema":
            return dbf_schema(table, request)
        if "memo_fields" not in request:
            return dbf_rows(fd, table, request)
        try:
            memo_fd = open_source(bindings[source_set], parts(request["fpt_path"], True))
        except FileNotFoundError:
            if "expected_fpt_sha256" in request:
                raise InvalidRequest("pinned FPT unavailable") from None
            return dbf_rows(fd, table, request)
        try:
            return dbf_rows(fd, table, request, fpt_table(memo_fd, request))
        finally:
            os.close(memo_fd)
    finally:
        os.close(fd)


def main():
    try:
        payload = sys.stdin.read(4097)
        if len(payload) > 4096:
            raise InvalidRequest("input exceeds request limit")
        request = validate(json.loads(payload))
        result = read(configuration(), request)
    except InvalidRequest as exc:
        result = {"error": str(exc)}
    except Exception:
        result = {"error": "Keller source unavailable or source validation failed"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
