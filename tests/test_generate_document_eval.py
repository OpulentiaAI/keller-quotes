"""Synthetic manifest provenance test for document evaluation generation."""

import csv
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/generate-document-eval.py"
SPEC = importlib.util.spec_from_file_location("generate_document_eval", SCRIPT)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class DocumentEvalManifestTest(unittest.TestCase):
    def test_cutoff_describes_recorded_date_without_claiming_pdf_availability(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            register = root / "register.csv"
            row = {
                "quote_no": "0004567", "quote_date": "2026-07-06", "letter_date": "2026-07-06",
                "quote_letter": "00000123", "part_no": "SYN-001", "description": "SYNTHETIC PART",
                "customer_id": "SYNTHETIC", "quantity": "10", "unit_price": "1.2345",
                "extended_price": "12.35", "price_basis": "customer_quote_pdf", "status": "unknown",
                "source_document": "QuoteLetter00000123.pdf", "source_document_sha256": sha256(b"pdf").hexdigest(),
                "source_transcript_sha256": sha256(b"transcript").hexdigest(),
                "source_price_field": "PRICE",
            }
            with register.open("w", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=row)
                writer.writeheader()
                writer.writerow(row)
            output = root / "cases.jsonl"
            manifest = generator.generate(register, output, 1)
            self.assertEqual(manifest["cases"], 1)
            self.assertEqual(json.loads(output.read_text())["quote_date"], row["letter_date"])
            self.assertIn("recorded quote-letter/inquiry date", manifest["cutoff"])
            self.assertIn("not independent proof of when the price-bearing PDF was issued or available",
                          manifest["cutoff"])
            self.assertEqual(json.loads(output.with_suffix(".manifest.json").read_text()), manifest)


if __name__ == "__main__":
    unittest.main()
