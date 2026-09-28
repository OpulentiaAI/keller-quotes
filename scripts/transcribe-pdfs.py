"""Offline, resumable transcription of a verified PDF source inventory."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import tempfile
import time


TOOL_VERSION = "0.2.4"
OPTIONS_VERSION = 1


class IncompletePagesError(ValueError):
    def __init__(self, message, page_count, ocr_pages, covered_pages, page_methods):
        super().__init__(message)
        self.page_count = page_count
        self.ocr_pages = ocr_pages
        self.covered_pages = covered_pages
        self.page_methods = page_methods


def digest(path):
    result = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def atomic_write(path, data):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".writing-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path, value):
    atomic_write(path, (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8"))


def relative_path(raw):
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("invalid source path")
    normalized = raw.replace("\\", "/")
    parts = normalized.split("/")
    if (normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized)
            or any(part in ("", ".", "..") for part in parts)):
        raise ValueError(f"unsafe source path: {raw!r}")
    if PurePosixPath(normalized).suffix.lower() != ".pdf":
        raise ValueError(f"non-PDF source path: {raw!r}")
    return normalized


def validate_sources(source, manifest_path, out):
    source = source.resolve(strict=True)
    out = out.resolve()
    if out == source or source in out.parents or out in source.parents:
        raise ValueError("output and source directories must be separate")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if (manifest.get("schema_version") != 1
            or manifest.get("all_source_hashes_and_mtimes_unchanged") is not True
            or not isinstance(manifest.get("archive_sha256"), str)
            or not re.fullmatch(r"[0-9a-fA-F]{64}", manifest["archive_sha256"])
            or not isinstance(manifest.get("archive_bytes"), int)
            or manifest["archive_bytes"] <= 0
            or not isinstance(manifest.get("files"), list)):
        raise ValueError("invalid source manifest metadata")
    files = manifest["files"]
    if not files or manifest.get("file_count") != len(files):
        raise ValueError("source manifest file count mismatch")
    expected = {}
    total = 0
    for item in files:
        name = relative_path(item["path"])
        if name.casefold() in expected:
            raise ValueError(f"duplicate source path: {name}")
        size = item["bytes"]
        expected_hash = item["sha256"]
        if (not isinstance(size, int) or size < 0
                or not isinstance(expected_hash, str)
                or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash)):
            raise ValueError(f"invalid size or hash: {name}")
        item = dict(item, sha256=expected_hash.lower())
        expected[name.casefold()] = (name, item)
        total += size
    if total != manifest.get("total_bytes"):
        raise ValueError("source manifest total bytes mismatch")
    actual = {}
    for path in source.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"symlink in source inventory: {path.relative_to(source)}")
        if path.is_file() and path.suffix.lower() == ".pdf":
            name = path.relative_to(source).as_posix()
            if name.casefold() in actual:
                raise ValueError(f"duplicate source file: {name}")
            actual[name.casefold()] = path
    if set(actual) != set(expected):
        raise ValueError(f"PDF inventory mismatch: {len(expected)} listed, {len(actual)} present")
    verified = []
    for key, (name, item) in expected.items():
        path = actual[key]
        if path.relative_to(source).as_posix() != name:
            raise ValueError(f"source path case mismatch: {name}")
        stamp = datetime.fromisoformat(item["modified_utc"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError(f"source mtime lacks timezone: {name}")
        stat = path.stat()
        if (stat.st_size != item["bytes"] or digest(path) != item["sha256"]
                or abs(stat.st_mtime - stamp.timestamp()) >= 1):
            raise ValueError(f"source size, hash, or mtime mismatch: {name}")
        verified.append((name, path, item))
    return sorted(verified)


def category(name):
    filename = PurePosixPath(name).name.lower()
    for prefix, label in (("quoteletter", "QuoteLetter"), ("invoice", "Invoice"),
                          ("optional", "Optional"), ("certificate", "Certificate"),
                          ("packing", "Packing"), ("po", "PO")):
        if filename.startswith(prefix):
            return label
    return "other"


def run_tool(args, timeout):
    result = subprocess.run(args, capture_output=True, check=True, timeout=timeout)
    return result.stdout.decode("utf-8", errors="replace")


def page_count(path, timeout):
    info = run_tool(["pdfinfo", str(path)], timeout)
    match = re.search(r"^Pages:\s+(\d+)\s*$", info, re.MULTILINE)
    if not match or int(match.group(1)) < 1:
        raise ValueError("PDF has no pages")
    return int(match.group(1))


def page_text(path, page, timeout):
    return run_tool(["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(path), "-"], timeout).strip()


def ocr_page(path, page, timeout):
    with tempfile.TemporaryDirectory() as directory:
        prefix = Path(directory) / "page"
        run_tool(["pdftoppm", "-f", str(page), "-l", str(page), "-singlefile",
                  "-r", "200", "-png", str(path), str(prefix)], timeout)
        return run_tool(["tesseract", str(prefix) + ".png", "stdout", "-l", "eng"], timeout).strip()


def convert(path, output, local_ocr, timeout):
    import anydoc

    ocr_pages = []
    needs_ocr = None
    try:
        markdown = anydoc.to_markdown(path, ocr="reject")
    except anydoc.NeedsOcrError as error:
        needs_ocr = error
        ocr_pages = sorted(set(error.pages))
        if not local_ocr:
            raise
        markdown = None
    count = page_count(path, timeout)
    if needs_ocr and (needs_ocr.page_count != count or not ocr_pages
                      or any(page < 1 or page > count for page in ocr_pages)):
        raise ValueError("AnyDoc OCR page accounting disagrees with PDF") from needs_ocr
    pages = []
    for number in range(1, count + 1):
        text = page_text(path, number, timeout)
        if not text.strip() and number not in ocr_pages:
            if not local_ocr:
                raise IncompletePagesError(f"page {number} has no extractable text", count,
                                           ocr_pages, [n for n, page in enumerate(pages, 1) if page],
                                           ["anydoc" if page else "uncovered" for page in pages] +
                                           ["uncovered"] * (count - len(pages)))
            ocr_pages.append(number)
        pages.append(text)
    ocr_pages = sorted(set(ocr_pages))
    methods = ["local-ocr" if n in ocr_pages else
               ("pdftotext-layout" if ocr_pages else "anydoc") for n in range(1, count + 1)]
    if ocr_pages and local_ocr:
        for number in ocr_pages:
            try:
                pages[number - 1] = ocr_page(path, number, timeout)
            except Exception as error:
                raise IncompletePagesError(f"local OCR failed on page {number}: {error}", count,
                                           ocr_pages, [n for n, page in enumerate(pages, 1)
                                                       if page.strip() and n not in ocr_pages],
                                           [method if page.strip() and n not in ocr_pages else "uncovered"
                                            for n, (method, page) in enumerate(zip(methods, pages), 1)]) from error
        if any(not page.strip() for page in pages):
            raise IncompletePagesError("one or more pages are blank after local OCR", count,
                                       ocr_pages, [n for n, page in enumerate(pages, 1) if page.strip()],
                                       [method if page.strip() else "uncovered" for method, page in zip(methods, pages)])
        markdown = "\n\n".join(f"## Page {number}\n\n{text}" for number, text in enumerate(pages, 1)) + "\n"
    elif any(not page.strip() for page in pages):
        raise IncompletePagesError("one or more pages have no extractable text", count,
                                   ocr_pages, [n for n, page in enumerate(pages, 1) if page.strip()],
                                   [method if page.strip() else "uncovered" for method, page in zip(methods, pages)])
    if not markdown or not markdown.strip():
        raise ValueError("transcript is empty")
    data = markdown.encode("utf-8")
    atomic_write(output, data)
    return {"status": "success", "pages": count, "covered_pages": list(range(1, count + 1)),
            "ocr_pages": ocr_pages, "page_methods": methods,
            "transcript_sha256": sha256(data).hexdigest(), "transcript_bytes": len(data)}


def child(args):
    import anydoc

    started = time.monotonic()
    result = {"status": "failed", "pages": None, "covered_pages": [], "ocr_pages": []}
    try:
        result = convert(Path(args._input), Path(args._output), args.local_ocr, args.timeout)
    except Exception as error:
        is_ocr = isinstance(error, anydoc.NeedsOcrError)
        result.update(status="needs_ocr" if is_ocr else "failed",
                      error_type=type(error).__name__, error_message=str(error)[:1000],
                      error_code="needsOcr" if is_ocr else getattr(error, "code", None))
        if hasattr(error, "pages"):
            result["ocr_pages"] = list(error.pages)
            result["pages"] = getattr(error, "page_count", None)
        if isinstance(error, IncompletePagesError):
            result.update(pages=error.page_count, ocr_pages=error.ocr_pages,
                          covered_pages=error.covered_pages, page_methods=error.page_methods)
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    print(json.dumps(result))
    return 0


def transcribe(name, path, item, out, local_ocr, timeout, toolchain_sha):
    key = record_key(name)
    record_path = out / "records" / (key + ".json")
    transcript = out / "transcripts" / (key + ".md")
    common = {"relative_source_path": name, "source_sha256": item["sha256"],
              "source_bytes": item["bytes"], "tool": "firecrawl-anydoc",
              "tool_version": TOOL_VERSION, "options_version": OPTIONS_VERSION,
              "toolchain_sha256": toolchain_sha,
              "local_ocr": local_ocr, "filename_classification": category(name),
              "classification_basis": "filename-only", "transcript_path": "transcripts/" + key + ".md"}
    if record_path.exists():
        try:
            old = json.loads(record_path.read_text(encoding="utf-8"))
            if (old.get("status") == "success" and all(old.get(k) == v for k, v in common.items())
                    and transcript.is_file() and digest(transcript) == old.get("transcript_sha256")
                    and transcript.stat().st_size == old.get("transcript_bytes")
                    and isinstance(old.get("pages"), int) and old["pages"] > 0
                    and old.get("covered_pages") == list(range(1, old["pages"] + 1))
                    and isinstance(old.get("page_methods"), list)
                    and len(old["page_methods"]) == old["pages"]
                    and transcript.stat().st_size > 0
                    and transcript.read_text(encoding="utf-8").strip()):
                return dict(old, resumed=True)
        except (OSError, ValueError, TypeError):
            pass
    transcript.unlink(missing_ok=True)
    started = time.monotonic()
    command = [sys.executable, str(Path(__file__).resolve()), "--_input", str(path),
               "--_output", str(transcript), "--timeout", str(timeout)]
    if local_ocr:
        command.append("--local-ocr")
    process = None
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True, env=dict(os.environ, OMP_THREAD_LIMIT="1"))
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            raise TimeoutError(f"document exceeded {timeout:g}s subprocess timeout")
        if process.returncode:
            raise RuntimeError(f"conversion subprocess exited {process.returncode}: {stderr.decode(errors='replace')[:500]}")
        result = json.loads(stdout)
        if result.get("status") == "success" and (not transcript.exists()
                or digest(transcript) != result.get("transcript_sha256")):
            raise ValueError("conversion transcript digest mismatch")
    except Exception as error:
        result = {"status": "failed", "pages": None, "covered_pages": [], "ocr_pages": [],
                  "error_type": type(error).__name__, "error_message": str(error)[:1000]}
    try:
        unchanged = path.stat().st_size == item["bytes"] and digest(path) == item["sha256"]
    except OSError:
        unchanged = False
    if not unchanged:
        result = {"status": "failed", "pages": None, "covered_pages": [], "ocr_pages": [],
                  "error_type": "SourceChanged", "error_message": "source changed during conversion"}
    if result["status"] != "success":
        transcript.unlink(missing_ok=True)
    record = dict(common, **result)
    record["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    atomic_json(record_path, record)
    return record


def record_key(name):
    return sha256(name.encode("utf-8")).hexdigest()


def toolchain_metadata():
    result = {"script_sha256": digest(Path(__file__).resolve())}
    for tool in ("pdfinfo", "pdftotext", "pdftoppm", "tesseract"):
        completed = subprocess.run([tool, "--version" if tool == "tesseract" else "-v"],
                                   capture_output=True, text=True, check=True, timeout=10)
        result[tool + "_version"] = (completed.stdout or completed.stderr).splitlines()[0]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=120, help="seconds per document")
    parser.add_argument("--local-ocr", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.workers < 1 or args.workers > 4 or args.timeout <= 0:
            raise ValueError("workers must be 1..4 and timeout must be positive")
        if version("firecrawl-anydoc") != TOOL_VERSION:
            raise ValueError(f"firecrawl-anydoc=={TOOL_VERSION} is required")
        files = validate_sources(args.source_dir, args.source_manifest, args.out)
        toolchain = toolchain_metadata()
        toolchain_sha = sha256(json.dumps(toolchain, sort_keys=True).encode("utf-8")).hexdigest()
        args.out.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(args.out, 0o700)
        for subdir in ("records", "transcripts"):
            directory = args.out / subdir
            if directory.is_symlink():
                raise ValueError(f"output directory is a symlink: {directory}")
            directory.mkdir(mode=0o700, exist_ok=True)
            os.chmod(directory, 0o700)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(transcribe, *entry, args.out, args.local_ocr, args.timeout,
                                   toolchain_sha): entry[0]
                       for entry in files}
            records = {}
            for future in as_completed(futures):
                records[futures[future]] = future.result()
        summary = {"schema_version": 1, "source_manifest_sha256": digest(args.source_manifest),
                   "tool_version": TOOL_VERSION, "local_ocr": args.local_ocr,
                   "toolchain": toolchain, "toolchain_sha256": toolchain_sha,
                   "document_count": len(files),
                   "success_count": sum(r["status"] == "success" for r in records.values()),
                   "failure_count": sum(r["status"] != "success" for r in records.values()),
                   "needs_ocr_count": sum(r["status"] == "needs_ocr" for r in records.values()),
                   "resumed_count": sum(r.get("resumed", False) for r in records.values()),
                   "ocr_document_count": sum(bool(r.get("ocr_pages")) for r in records.values()),
                   "total_pages": sum(r.get("pages") or 0 for r in records.values()),
                   "records": {name: "records/" + record_key(name) + ".json"
                               for name in sorted(records)}}
        atomic_json(args.out / "summary.json", summary)
        print(json.dumps({key: value for key, value in summary.items() if key != "records"}, sort_keys=True))
        return 1 if summary["failure_count"] else 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"Input/configuration error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    if "--_input" in sys.argv:
        child_parser = argparse.ArgumentParser()
        child_parser.add_argument("--_input", required=True)
        child_parser.add_argument("--_output", required=True)
        child_parser.add_argument("--timeout", type=float, required=True)
        child_parser.add_argument("--local-ocr", action="store_true")
        sys.exit(child(child_parser.parse_args()))
    sys.exit(main())
