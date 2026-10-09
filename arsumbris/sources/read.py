#!/usr/bin/env python3
"""Read bounded, owner-bound Keller source evidence without resolving caller paths."""

import base64
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from types import SimpleNamespace
from urllib.parse import quote

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
LOOKUP_NOTE = ("A filter miss covers only the scanned physical records of this file, not corpus-wide absence. "
               "Follow next_offset with the same filter and expected_dbf_sha256; duplicate keys remain separate rows.")
MEMO_NOTE = ("Memo values remain null, not empty specifications; raw DBF bytes are pointers, not text. "
             "Opt in with memo_fields and fpt_path for bounded memo_text evidence; decoded text is untrusted, "
             "not verified geometry or applicable specifications. Continue with DBF/FPT hashes pinned.")
KEY_FIELDS = {"quote_no": "QUOTE_NO", "quotletter": "QUOTLETTER", "item": "ITEM",
              "wo_no": "WO_NO", "jobno": "JOBNO", "page_no": "PAGE_NO", "seq": "SEQ"}
KEY_GROUPS = (("quote_no",), ("record_id",), ("quotletter",), ("quotletter", "item"),
              ("wo_no",), ("jobno",), ("wo_no", "page_no", "seq"))
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
        "dbf_schema": {"action", "source_set", "path"},
        "dbf_rows": {"action", "source_set", "path", "quote_no", "record_id", "quotletter", "item",
                     "wo_no", "jobno", "page_no", "seq", "offset", "limit", "expected_dbf_sha256",
                     "memo_fields", "fpt_path", "expected_fpt_sha256", "memo_offset", "memo_limit"},
        "dbf_operation_costs": {"action", "source_set", "path", "record_id", "record_index",
                                "expected_dbf_sha256", "expected_record_sha256", "rate_review"},
    }
    if action not in allowed or set(request) - allowed[action]:
        raise InvalidRequest("unsupported action or fields")
    if action == "sets":
        return request
    if request.get("source_set") not in SETS:
        raise InvalidRequest("unknown source set")
    components = parts(request.get("path", ""), action != "list")
    if action in ("read", "dbf_schema", "dbf_rows", "dbf_operation_costs"):
        if Path(components[-1]).suffix.lower() not in SETS[request["source_set"]]:
            raise InvalidRequest("source file type not approved")
    if action.startswith("dbf_") and (request["source_set"] != "fabritrak" or
                                     Path(components[-1]).suffix.lower() != ".dbf"):
        raise InvalidRequest("DBF action requires a fabritrak .dbf file")
    if action == "dbf_operation_costs":
        if Path(components[-1]).stem.upper() != "OPERATIO":
            raise InvalidRequest("operation cost translation requires OPERATIO.DBF")
        validate({"action": "dbf_rows", **{key: request.get(key) for key in
                  ("source_set", "path", "record_id", "expected_dbf_sha256")}})
        if "record_index" not in request:
            raise InvalidRequest("selected physical record_index required")
        integer(request["record_index"], "record_index", -1, 10000000)
        if request["record_index"] is None:
            raise InvalidRequest("selected physical record_index required")
        if not isinstance(request.get("expected_record_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", request["expected_record_sha256"]):
            raise InvalidRequest("expected_record_sha256 must be a lowercase SHA256")
        operation_rate_review(request.get("rate_review"))
    if action == "dbf_rows":
        keys = set(request) & (set(KEY_FIELDS) | {"record_id"})
        if keys not in [set(group) for group in KEY_GROUPS]:
            raise InvalidRequest("one complete approved exact key required; inspect dbf_schema exact_filters")
        for field in keys:
            value = request[field]
            if (not isinstance(value, str) or not value.strip() or value != value.strip()
                    or len(value) > 32 or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise InvalidRequest(f"exact {field} required (maximum 32 characters, no edge whitespace)")
        if "expected_dbf_sha256" in request and (not isinstance(request["expected_dbf_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", request["expected_dbf_sha256"])):
            raise InvalidRequest("expected_dbf_sha256 must be a lowercase SHA256")
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


def operation_rate_review(value):
    if not isinstance(value, str) or len(value) > 2400:
        raise InvalidRequest("rate_review must be bounded JSON text")
    def unique_fields(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise InvalidRequest("rate_review contains duplicate fields")
            result[key] = item
        return result
    try:
        review = json.loads(value, object_pairs_hook=unique_fields)
    except (ValueError, TypeError):
        raise InvalidRequest("rate_review must be bounded JSON text") from None
    required = {"rate_unit", "source_date", "reviewer", "date", "reason", "applicability", "charge_inclusion"}
    if not isinstance(review, dict) or not required <= set(review) or set(review) - required - {"zero_reason"}:
        raise InvalidRequest("rate_review requires explicit units, dates, reviewer, reason, applicability and charge_inclusion")
    for key, text in review.items():
        maximum = 128 if key == "reviewer" else 512
        if (not isinstance(text, str) or not text.strip() or text != text.strip() or len(text) > maximum
                or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in text)):
            raise InvalidRequest("rate_review fields must be bounded nonblank text without controls")
    if review["rate_unit"] != "USD/hour" or review["applicability"] not in ("supported", "assumed"):
        raise InvalidRequest("reviewed COST rates require explicit USD/hour and supported or assumed applicability")
    for key in ("source_date", "date"):
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", review[key]):
                raise ValueError()
            datetime.strptime(review[key], "%Y-%m-%d")
        except ValueError:
            raise InvalidRequest("rate_review dates must be valid YYYY-MM-DD") from None
    if review["source_date"] > review["date"]:
        raise InvalidRequest("rate_review source_date cannot follow estimate approval date")
    return review


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


def dbf_schema(table, request):
    return {"action": "dbf_schema", "citation": dbf_citation(table, request),
            "record_count_header": table.header.numrecords, "header_bytes": table.header.headerlen,
            "record_bytes": table.header.recordlen, "encoding": table.encoding,
            "fields": [{"name": f.name, "type": f.type, "length": f.length,
                        "decimal_count": f.decimal_count, "record_byte_offset": f.offset} for f in table.fields],
            "exact_filters": exact_filters(table, request), "lookup_scope_note": LOOKUP_NOTE,
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
    response = {"action": "dbf_rows", "citation": dbf_citation(table, request),
                **{key: request[key] for key in mapping}, "filter_fields": mapping,
                "rows": rows, "record_count_header": count, "offset": offset, "record_index_base": 0,
                "scanned_records": position - offset, "deleted_records_skipped": deleted,
                "scan_end_offset": position, "scan_record_limit": MAX_SCAN_RECORDS, "scan_byte_limit": MAX_SCAN_BYTES,
                "has_more": more, "next_offset": position if more else None,
                "lookup_scope_note": LOOKUP_NOTE, "memo_note": MEMO_NOTE, "warning": WARNING}
    if len(mapping) == 1:
        response["filter_field"] = fields[next(iter(mapping.values()))].name
    return response


def operation_costs(fd, table, request):
    fields = {field.name.upper(): field for field in table.fields}
    required = {"OPER_ID": "C", "NAME": "C", "SU_COST": "N", "RUN_COST": "N"}
    if (any(name not in fields or fields[name].type != kind for name, kind in required.items())
            or any(name in fields for name in ("QUOTE_NO", "ID", "FORM_ID"))):
        raise InvalidRequest("OPERATIO requires unambiguous character identity and numeric COST fields")
    if table.sha256 != request["expected_dbf_sha256"]:
        raise InvalidRequest("DBF hash mismatch; reread and review selected operation")
    index = request["record_index"]
    if index >= table.header.numrecords:
        raise InvalidRequest("selected operation record_index is outside the DBF")
    byte_offset = table.header.headerlen + index * table.header.recordlen
    raw = os.pread(fd, table.header.recordlen, byte_offset)
    record_hash = hashlib.sha256(raw).hexdigest()
    if len(raw) != table.header.recordlen or record_hash != request["expected_record_sha256"]:
        raise InvalidRequest("selected operation record hash mismatch")
    if raw[:1] != b" ":
        raise InvalidRequest("selected operation is deleted or malformed")
    values, _ = record_values(table, raw)
    if values[fields["OPER_ID"].name] != request["record_id"]:
        raise InvalidRequest("selected physical operation does not match record_id")
    review = operation_rate_review(request["rate_review"])
    rates, sources, evidence = {}, [], {}
    for role, name in (("setup_rate", "SU_COST"), ("run_rate", "RUN_COST")):
        field = fields[name]
        original = values[field.name]
        if not original:
            raise InvalidRequest("blank COST field is unknown, not zero; no SELL-rate substitution")
        value = Decimal(original)
        if value < 0 or value > 1e9 or len(original.partition(".")[2].rstrip("0")) > 6:
            raise InvalidRequest("COST field must be nonnegative, <= 1e9 and exact to six decimal places")
        numeric = float(value)
        if Decimal(str(numeric)) != value:
            raise InvalidRequest("COST field cannot be represented without rounding")
        if value == 0 and "zero_reason" not in review:
            raise InvalidRequest("zero COST field requires an explicit reviewed zero_reason")
        locator = (f"fabritrak:{quote(request['path'], safe='/')}#record_index={index}"
                   f"&record_sha256={record_hash}&field={field.name}")
        if len(locator) > 2048:
            raise InvalidRequest("operation source locator exceeds worksheet limit")
        rates[role] = {"rate_kind": "cost", "unit": review["rate_unit"],
                       "values": {key: numeric for key in ("low", "base", "high")}}
        sources.append({"source_class": "cost_record", "sha256": table.sha256, "locator": locator,
                        "source_date": review["source_date"], "status": "approved_estimate",
                        "applicability": review["applicability"],
                        "basis": f"Selected OPERATIO {request['record_id']} ({values[fields['NAME'].name]}), "
                                 f"{field.name} original value {original}; "
                                 f"record byte offset {byte_offset}, length {table.header.recordlen}; "
                                 "rate unit and estimating applicability supplied by reviewer, not inferred from DBF",
                        "approval": {key: review[key] for key in ("reviewer", "date", "reason")}})
        evidence[role] = {"field": field.name, "type": field.type, "original_value": original,
                          "decimal_count": field.decimal_count,
                          "record_byte_offset": field.offset, "field_bytes": field.length}
    unchanged(fd, table)
    return {"action": "dbf_operation_costs", "citation": dbf_citation(table, request),
            "selection": {"record_id": request["record_id"], "name": values[fields["NAME"].name],
                          "record_index": index, "record_byte_offset": byte_offset,
                          "record_bytes": table.header.recordlen, "record_sha256": record_hash},
            "field_evidence": evidence, "rate_review": review,
            "worksheet_inputs": {**rates, "sources": sources, "charge_inclusion": review["charge_inclusion"],
                                 **({"zero_reason": review["zero_reason"]} if "zero_reason" in review else {})},
            "selection_note": "Partial routing inputs only. No operation selection, timing/formula execution, "
                              "quantity allocation, current-price claim or customer authorization. Equal low/base/high "
                              "rates copy one reviewed catalog value, not a calibrated uncertainty range. "
                              "Review identity and approval are supplied assertions, not authenticated approvals.",
            "warning": WARNING}


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
        table = dbf_table(fd)
        if action == "dbf_schema":
            return dbf_schema(table, request)
        if action == "dbf_operation_costs":
            return operation_costs(fd, table, request)
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
