#!/usr/bin/env python3
"""Read bounded, owner-bound Keller source evidence without resolving caller paths."""

import base64
import json
import os
from pathlib import Path
import re
import stat
import sys

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
        "dbf_rows": {"action", "source_set", "path", "quote_no", "record_id", "offset", "limit"},
    }
    if action not in allowed or set(request) - allowed[action]:
        raise InvalidRequest("unsupported action or fields")
    if action == "sets":
        return request
    if request.get("source_set") not in SETS:
        raise InvalidRequest("unknown source set")
    components = parts(request.get("path", ""), action != "list")
    if action in ("read", "dbf_schema", "dbf_rows"):
        if Path(components[-1]).suffix.lower() not in SETS[request["source_set"]]:
            raise InvalidRequest("source file type not approved")
    if action.startswith("dbf_") and (request["source_set"] != "fabritrak" or
                                     Path(components[-1]).suffix.lower() != ".dbf"):
        raise InvalidRequest("DBF action requires a fabritrak .dbf file")
    if action == "dbf_rows":
        if ("quote_no" in request) == ("record_id" in request):
            raise InvalidRequest("exactly one of quote_no or record_id required")
        field = "quote_no" if "quote_no" in request else "record_id"
        value = request[field]
        if not isinstance(value, str) or not value.strip() or len(value) > 32 or any(ord(c) < 32 for c in value):
            raise InvalidRequest(f"exact {field} required (maximum 32 characters)")
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


def dbf_table(fd):
    try:
        from dbfread import DBF
    except ImportError:
        raise InvalidRequest("DBF reader unavailable in configured Python") from None
    header = os.pread(fd, 32, 0)
    if len(header) != 32 or int.from_bytes(header[8:10], "little") > 65536 or int.from_bytes(header[10:12], "little") > 65536:
        raise InvalidRequest("DBF structure exceeds reader limits")
    table = DBF(f"/proc/self/fd/{fd}", ignorecase=False, raw=True, ignore_missing_memofile=True)
    if table.header.recordlen > 65536 or table.header.headerlen > 65536 or len(table.fields) > 256:
        raise InvalidRequest("DBF structure exceeds reader limits")
    return table


def dbf_schema(table, request):
    return {"action": "dbf_schema", "citation": citation(request), "record_count_header": table.header.numrecords,
            "fields": [{"name": f.name, "type": f.type, "length": f.length, "decimal_count": f.decimal_count}
                       for f in table.fields], "warning": WARNING}


def dbf_rows(fd, table, request):
    filter_key = "quote_no" if "quote_no" in request else "record_id"
    names = {"QUOTE_NO"} if filter_key == "quote_no" else {"ID", "FORM_ID", "OPER_ID"}
    matching = [f for f in table.fields if f.name.upper() in names and f.type == "C"]
    if len(matching) != 1:
        raise InvalidRequest("DBF lacks one unambiguous approved identifier field")
    filter_field = matching[0]
    filter_start = 1 + sum(f.length for f in table.fields[:table.fields.index(filter_field)])
    offset = request.get("offset", 0)
    limit = request.get("limit", 5)
    size = os.fstat(fd).st_size
    count = min(table.header.numrecords, max(0, (size - table.header.headerlen) // table.header.recordlen))
    if offset > count:
        raise InvalidRequest("offset exceeds DBF record count")
    position = offset
    rows = []
    max_scan = 20000
    os.lseek(fd, table.header.headerlen + position * table.header.recordlen, os.SEEK_SET)
    while position < count and position - offset < max_scan:
        record = os.read(fd, table.header.recordlen)
        if len(record) != table.header.recordlen:
            raise InvalidRequest("DBF changed during read")
        index = position
        position += 1
        if record[:1] != b" " or record[filter_start:filter_start + filter_field.length].strip().decode(table.encoding) != request[filter_key]:
            continue
        values = {}
        truncated = []
        start = 1
        for field in table.fields:
            raw = record[start:start + field.length].strip(b" \x00")
            start += field.length
            value = raw.decode(table.encoding, errors="replace")
            if len(value) > 512:
                value = value[:512]
                truncated.append(field.name)
            values[field.name] = value
        candidate = {"record_index": index, "values": values, "truncated_fields": truncated,
                     "memo_fields": [f.name for f in table.fields if f.type in "MGPB"]}
        if len(json.dumps(rows + [candidate])) > 48000:
            position = index
            break
        rows.append(candidate)
        if len(rows) == limit:
            break
    more = position < count
    return {"action": "dbf_rows", "citation": citation(request), filter_key: request[filter_key],
            "filter_field": filter_field.name,
            "rows": rows, "record_count_header": table.header.numrecords, "scanned_records": position - offset,
            "has_more": more, "next_offset": position if more else None,
            "memo_note": "Memo fields show DBF pointers only; inspect approved FPT bytes separately.", "warning": WARNING}


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
        return dbf_schema(table, request) if action == "dbf_schema" else dbf_rows(fd, table, request)
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
