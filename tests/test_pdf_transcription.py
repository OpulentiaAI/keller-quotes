import importlib.util
from hashlib import sha256
import json
import io
import os
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch
from datetime import datetime, timezone


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "transcribe-pdfs.py"
spec = importlib.util.spec_from_file_location("pdf_transcription", SCRIPT)
transcriber = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transcriber)


class NeedsOcrError(Exception):
    def __init__(self, pages, page_count):
        super().__init__("pages need OCR")
        self.pages = pages
        self.page_count = page_count
        self.code = "needsOcr"


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        (self.source / "OUTPUT").mkdir(parents=True)
        self.pdf = self.source / "OUTPUT" / "QuoteLetter0001.pdf"
        self.pdf.write_bytes(b"%PDF-1.4\nfixture")
        self.out = self.root / "private"
        self.manifest = self.root / "manifest.json"
        self.item = {"path": "OUTPUT\\QuoteLetter0001.pdf", "bytes": self.pdf.stat().st_size,
                     "sha256": transcriber.digest(self.pdf),
                     "modified_utc": datetime.fromtimestamp(self.pdf.stat().st_mtime, timezone.utc).isoformat()}
        self.data = {"schema_version": 1, "file_count": 1, "total_bytes": self.item["bytes"],
                     "all_source_hashes_and_mtimes_unchanged": True,
                     "archive_sha256": "a" * 64, "archive_bytes": 100, "files": [self.item]}
        self.save()

    def save(self):
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")

    def validate(self):
        return transcriber.validate_sources(self.source, self.manifest, self.out)

    def test_windows_path_and_filename_only_classification(self):
        self.assertEqual(self.validate()[0][0], "OUTPUT/QuoteLetter0001.pdf")
        self.assertEqual(transcriber.category("dir/PO124.pdf"), "PO")
        self.assertEqual(transcriber.category("dir/unknown.pdf"), "other")

    def test_powershell_uppercase_hashes_and_utf8_bom(self):
        self.item["sha256"] = self.item["sha256"].upper()
        self.data["archive_sha256"] = "ABCDEF01" * 8
        self.manifest.write_text("\ufeff" + json.dumps(self.data), encoding="utf-8")
        records = self.validate()
        self.assertEqual(records[0][2]["sha256"], transcriber.digest(self.pdf))

    def test_path_traversal_and_absolute_paths(self):
        for name in ("../secret.pdf", "OUTPUT/../secret.pdf", "/secret.pdf", "C:\\secret.pdf",
                     "OUTPUT//secret.pdf", "OUTPUT/./secret.pdf"):
            with self.subTest(name=name):
                self.item["path"] = name
                self.save()
                with self.assertRaises(ValueError):
                    self.validate()

    def test_duplicate_paths_case_insensitive(self):
        self.data["files"].append(dict(self.item, path="output/quoteletter0001.pdf"))
        self.data["file_count"] = 2
        self.data["total_bytes"] *= 2
        self.save()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.validate()

    def test_inventory_hash_size_mtime_and_outside_source(self):
        self.assertEqual(len(self.validate()), 1)
        second = self.source / "OUTPUT" / "Other.pdf"
        second.write_bytes(b"another")
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.validate()
        second.unlink()
        self.pdf.write_bytes(b"%PDF-1.4\ntampered")
        with self.assertRaisesRegex(ValueError, "hash"):
            self.validate()
        self.pdf.write_bytes(b"%PDF-1.4\nfixture")
        os.utime(self.pdf, (self.pdf.stat().st_atime, self.pdf.stat().st_mtime + 10))
        with self.assertRaisesRegex(ValueError, "mtime"):
            self.validate()
        with self.assertRaisesRegex(ValueError, "separate"):
            transcriber.validate_sources(self.source, self.manifest, self.source / "private")

    def test_symlink_is_rejected(self):
        (self.source / "shortcut.pdf").symlink_to(self.pdf)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.validate()

    def test_manifest_total_and_provenance_flag(self):
        self.data["total_bytes"] += 1
        self.save()
        with self.assertRaisesRegex(ValueError, "total bytes"):
            self.validate()
        self.data["total_bytes"] -= 1
        self.data["all_source_hashes_and_mtimes_unchanged"] = False
        self.save()
        with self.assertRaisesRegex(ValueError, "metadata"):
            self.validate()


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.pdf"
        self.path.write_bytes(b"%PDF-1.4\nfixture")
        self.output = Path(self.temp.name) / "test.md"
        self.anydoc = types.SimpleNamespace(to_markdown=lambda *args, **kwargs: "AnyDoc text\n",
                                            NeedsOcrError=NeedsOcrError)

    def test_anydoc_first_and_complete_text_page_coverage(self):
        calls = []
        def anydoc(path, *, ocr):
            calls.append(ocr)
            return "AnyDoc text\n"
        self.anydoc.to_markdown = anydoc
        with patch.dict("sys.modules", anydoc=self.anydoc), patch.object(transcriber, "page_count", return_value=2) as count, patch.object(transcriber, "page_text", side_effect=["one", "two"]):
            result = transcriber.convert(self.path, self.output, False, 3)
        self.assertEqual(calls, ["reject"])
        count.assert_called_once()
        self.assertEqual(result["covered_pages"], [1, 2])
        self.assertEqual(result["page_methods"], ["anydoc", "anydoc"])
        self.assertEqual(self.output.read_text(), "AnyDoc text\n")

    def test_mixed_scans_preserve_text_and_attribute_ocr(self):
        def needs_ocr(*args, **kwargs):
            raise NeedsOcrError([2], 3)
        self.anydoc.to_markdown = needs_ocr
        with patch.dict("sys.modules", anydoc=self.anydoc), patch.object(transcriber, "page_count", return_value=3), patch.object(transcriber, "page_text", side_effect=["price 10", "", "total 20"]), patch.object(transcriber, "ocr_page", return_value="scanned page") as ocr:
            result = transcriber.convert(self.path, self.output, True, 3)
        ocr.assert_called_once_with(self.path, 2, 3)
        self.assertEqual(result["ocr_pages"], [2])
        self.assertEqual(result["page_methods"], ["pdftotext-layout", "local-ocr", "pdftotext-layout"])
        self.assertIn("price 10", self.output.read_text())
        self.assertIn("scanned page", self.output.read_text())

    def test_scanned_without_opt_in_fails_and_ocr_blank_fails(self):
        def needs_ocr(*args, **kwargs):
            raise NeedsOcrError([1], 1)
        self.anydoc.to_markdown = needs_ocr
        with patch.dict("sys.modules", anydoc=self.anydoc):
            with self.assertRaises(NeedsOcrError):
                transcriber.convert(self.path, self.output, False, 3)
            with patch.object(transcriber, "page_count", return_value=1), patch.object(transcriber, "page_text", return_value=""), patch.object(transcriber, "ocr_page", return_value=""):
                with self.assertRaisesRegex(transcriber.IncompletePagesError, "blank") as caught:
                    transcriber.convert(self.path, self.output, True, 3)
                self.assertEqual(caught.exception.ocr_pages, [1])
                self.assertEqual(caught.exception.covered_pages, [])
        self.assertFalse(self.output.exists())

    def test_blank_page_fails_without_ocr_even_when_anydoc_succeeds(self):
        with patch.dict("sys.modules", anydoc=self.anydoc), patch.object(transcriber, "page_count", return_value=2), patch.object(transcriber, "page_text", side_effect=["text", ""]):
            with self.assertRaisesRegex(ValueError, "page 2"):
                transcriber.convert(self.path, self.output, False, 3)

    def test_malformed_or_encrypted_anydoc_failure_is_not_silenced(self):
        for message in ("encrypted", "malformed"):
            with self.subTest(message=message):
                self.anydoc.to_markdown = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError(message))
                with patch.dict("sys.modules", anydoc=self.anydoc):
                    with self.assertRaisesRegex(ValueError, message):
                        transcriber.convert(self.path, self.output, True, 3)

    def test_child_argument_contract_and_needs_ocr_status(self):
        args = types.SimpleNamespace(_input=str(self.path), _output=str(self.output),
                                     local_ocr=False, timeout=3)
        output = io.StringIO()
        with patch.dict("sys.modules", anydoc=self.anydoc), patch.object(transcriber, "convert", side_effect=NeedsOcrError([1], 1)), patch("sys.stdout", output):
            self.assertEqual(transcriber.child(args), 0)
        record = json.loads(output.getvalue())
        self.assertEqual(record["status"], "needs_ocr")
        self.assertEqual(record["ocr_pages"], [1])


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf = self.root / "Invoice.pdf"
        self.pdf.write_bytes(b"source")
        self.out = self.root / "output"
        (self.out / "records").mkdir(parents=True)
        (self.out / "transcripts").mkdir()
        self.item = {"sha256": transcriber.digest(self.pdf), "bytes": self.pdf.stat().st_size}

    def test_resume_requires_integrity_and_version(self):
        key = transcriber.record_key("Invoice.pdf")
        markdown = self.out / "transcripts" / (key + ".md")
        markdown.write_text("complete", encoding="utf-8")
        record = {"status": "success", "relative_source_path": "Invoice.pdf", "source_sha256": self.item["sha256"],
                  "source_bytes": self.item["bytes"], "tool": "firecrawl-anydoc", "tool_version": transcriber.TOOL_VERSION,
                  "options_version": 1, "toolchain_sha256": "toolchain", "local_ocr": False,
                  "filename_classification": "Invoice",
                  "classification_basis": "filename-only", "transcript_path": "transcripts/" + key + ".md",
                  "transcript_sha256": transcriber.digest(markdown), "transcript_bytes": 8,
                  "pages": 1, "covered_pages": [1], "page_methods": ["anydoc"],
                  "ocr_pages": [], "elapsed_ms": 1}
        (self.out / "records" / (key + ".json")).write_text(json.dumps(record))
        with patch.object(transcriber.subprocess, "Popen", side_effect=AssertionError("should resume")):
            self.assertTrue(transcriber.transcribe("Invoice.pdf", self.pdf, self.item, self.out, False, 3, "toolchain")["resumed"])
        with patch.object(transcriber.subprocess, "Popen", side_effect=RuntimeError("toolchain changed")):
            changed = transcriber.transcribe("Invoice.pdf", self.pdf, self.item, self.out, False, 3, "different-toolchain")
        self.assertEqual(changed["status"], "failed")
        markdown.write_text("complete", encoding="utf-8")
        (self.out / "records" / (key + ".json")).write_text(json.dumps(record))
        markdown.write_text("tampered")
        with patch.object(transcriber.subprocess, "Popen", side_effect=RuntimeError("called")):
            failure = transcriber.transcribe("Invoice.pdf", self.pdf, self.item, self.out, False, 3, "toolchain")
        self.assertEqual(failure["status"], "failed")
        self.assertFalse(markdown.exists())
        with patch.object(transcriber, "TOOL_VERSION", "0.2.5"), patch.object(transcriber.subprocess, "Popen", side_effect=RuntimeError("version invalidated cache")):
            failure = transcriber.transcribe("Invoice.pdf", self.pdf, self.item, self.out, False, 3, "toolchain")
        self.assertEqual(failure["tool_version"], "0.2.5")

    def test_timeout_is_isolated_and_recorded(self):
        class HangingProcess:
            pid = 999
            returncode = None
            def communicate(self, timeout=None):
                if timeout is not None:
                    raise transcriber.subprocess.TimeoutExpired("child", timeout)
                return b"", b""
        with patch.object(transcriber.subprocess, "Popen", return_value=HangingProcess()), patch.object(transcriber.os, "killpg") as kill:
            record = transcriber.transcribe("Invoice.pdf", self.pdf, self.item, self.out, False, 0.1, "toolchain")
        kill.assert_called_once()
        self.assertEqual(record["error_type"], "TimeoutError")
        self.assertEqual(record["status"], "failed")

    def test_successful_child_writes_verified_record(self):
        key = transcriber.record_key("Invoice.pdf")
        transcript = self.out / "transcripts" / (key + ".md")
        class CompletedProcess:
            returncode = 0
            def communicate(self, timeout=None):
                transcript.write_text("complete", encoding="utf-8")
                result = {"status": "success", "pages": 1, "covered_pages": [1],
                          "ocr_pages": [], "page_methods": ["anydoc"],
                          "transcript_sha256": sha256(b"complete").hexdigest(),
                          "transcript_bytes": 8, "elapsed_ms": 1}
                return json.dumps(result).encode(), b""
        with patch.object(transcriber.subprocess, "Popen", return_value=CompletedProcess()):
            record = transcriber.transcribe("Invoice.pdf", self.pdf, self.item, self.out, False, 3, "toolchain")
        self.assertEqual(record["status"], "success")
        self.assertEqual(record["transcript_sha256"], transcriber.digest(transcript))
        self.assertEqual(json.loads((self.out / "records" / (key + ".json")).read_text())["status"], "success")


if __name__ == "__main__":
    unittest.main()
