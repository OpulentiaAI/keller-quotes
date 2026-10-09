"""Synthetic operator specification projection; no DB connections or credentials."""

import hashlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("steve_polygres_reader", ROOT / "arsumbris/polygres/read.py")
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)
CORPUS = "a" * 64


class FakeConnection:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.queries = []

    def transaction(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql, params=()):
        self.queries.append((sql, params))
        self.result = next(self.replies)
        return self

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


class FakeEvidence:
    PRICE_SELECT = "select verified columns from verified_document_prices v join evidence_documents d on d.document_id=v.document_id"

    def __init__(self, fields):
        self.fields = fields
        self.calls = []

    def checked_price(self, record, columns):
        self.calls.append((record, columns))
        return dict(self.fields)


class SteveSpecificationProjectionTest(unittest.TestCase):
    def setUp(self):
        self.row = {"quote_no": "Q1", "item_no": "001", "quantity": "10", "unit_price": "1.2345",
                    "extended_price": "12.35", "quote_date": "2020-01-02", "letter_date": "2020-01-03",
                    "part_no": "P1", "customer_id": "C1", "source_price_field": "PRICE",
                    "price_basis": "customer_quote_pdf", "status": "unknown", "rev": "A",
                    "drawing_no": "DRAW-1", "rfq_no": "RFQ-1", "comment": "Historical scope, no finish."}
        self.record = (1, "synthetic raw CSV\r\n", "Q1", "001", 10, "1.2345", "12.35", None, None,
                       "P1", "C1", "PRICE", "synthetic/quote.pdf", "b" * 64, "c" * 64)
        self.evidence = FakeEvidence(self.row)
        self.request = {"action": "prices", "corpus": CORPUS, "part_no": "P1"}

    def call_prices(self, records=None, **options):
        conn = FakeConnection([None, (3, {"csv_columns": list(self.row)}),
                               [self.record] if records is None else records])
        request = reader.validate({**self.request, **options})
        with patch.object(reader, "evidence_module", return_value=self.evidence):
            response = reader.read(conn, request)
        return response, conn

    def test_default_and_explicit_false_preserve_exact_price_contract(self):
        expected = {"action": "prices", "corpus": CORPUS, "basis": "verified issued customer quotation PDF",
                    "outcome": "unknown", "prices": [{"row": {key: self.row[key] for key in reader.PRICE_FIELDS},
                    "source_path": "synthetic/quote.pdf", "pdf_sha256": "b" * 64, "transcript_sha256": "c" * 64}],
                    "has_more": False, "next_offset": None}
        default, conn = self.call_prices()
        disabled, disabled_conn = self.call_prices(include_specification=False)
        self.assertEqual(default, expected)
        self.assertEqual(disabled, expected)
        self.assertEqual(conn.queries, disabled_conn.queries)
        self.assertEqual(conn.queries[-1][1][-2:], (21, 0))
        self.assertEqual(len(self.evidence.calls), 2)
        self.assertNotIn("specification", default["prices"][0])
        self.assertEqual(tuple(default["prices"][0]["row"]), reader.PRICE_FIELDS)

    def test_opt_in_metadata_has_precise_origin_and_no_numeric_replacement(self):
        response, conn = self.call_prices(include_specification=True)
        entry = response["prices"][0]
        self.assertEqual(entry["row"], {key: self.row[key] for key in reader.PRICE_FIELDS})
        self.assertEqual(entry["row"]["unit_price"], "1.2345")
        self.assertEqual(response["outcome"], "unknown")
        projection = entry["specification"]
        self.assertEqual(projection["origin"], "inherited_register_metadata_not_pdf_verified")
        self.assertEqual(set(projection["fields"]), {"rev", "drawing_no", "rfq_no", "comment"})
        for name, value in projection["fields"].items():
            self.assertEqual(value["text"], self.row[name])
            self.assertEqual(value["status"], "present")
            self.assertFalse(value["has_more"])
        self.assertEqual(projection["csv_row_number"], 1)
        self.assertEqual(projection["raw_csv_sha256"], hashlib.sha256(self.record[1].encode()).hexdigest())
        self.assertEqual(projection["related_document"]["relationship"], "associated_price_document_not_specification_proof")
        self.assertIn("No PDF page is asserted", projection["note"])
        self.assertEqual(conn.queries[-1][1][-2:], (6, 0))
        self.assertEqual(self.evidence.calls, [(self.record, list(self.row))])
        self.assertEqual(conn.queries[0][0], "set transaction read only")
        self.assertTrue(all(not any(word in sql.lower() for word in ("insert ", "update ", "delete "))
                            for sql, _ in conn.queries))

    def test_field_character_continuations_preserve_empty_unknown_and_unicode(self):
        self.row.update(comment="é漢 finish", rev="", drawing_no="D")
        del self.row["rfq_no"]
        first, _ = self.call_prices(include_specification=True, specification_limit=2)
        fields = first["prices"][0]["specification"]["fields"]
        self.assertEqual(fields["comment"]["text"], "é漢")
        self.assertEqual(fields["comment"]["next_offset"], 2)
        self.assertEqual(fields["comment"]["character_count"], len(self.row["comment"]))
        self.assertEqual((fields["rev"]["text"], fields["rev"]["status"]), ("", "empty"))
        self.assertEqual((fields["rfq_no"]["text"], fields["rfq_no"]["status"]), (None, "unavailable"))
        second, _ = self.call_prices(include_specification=True, specification_limit=1000,
                                     specification_offset=fields["comment"]["next_offset"])
        continued = second["prices"][0]["specification"]
        self.assertEqual(continued["fields"]["comment"]["text"], " finish")
        self.assertFalse(continued["fields"]["comment"]["has_more"])
        self.assertIsNone(continued["fields"]["comment"]["next_offset"])
        # Shorter fields are exhausted, not reclassified as originally empty.
        self.assertEqual(continued["fields"]["drawing_no"]["text"], "")
        self.assertEqual(continued["fields"]["drawing_no"]["status"], "present")
        self.assertEqual(continued["raw_csv_sha256"], first["prices"][0]["specification"]["raw_csv_sha256"])

    def test_row_pagination_is_separate_from_field_pagination(self):
        response, conn = self.call_prices(records=[self.record] * 6, include_specification=True, offset=7)
        self.assertEqual(len(response["prices"]), 5)
        self.assertEqual(response["next_offset"], 12)
        self.assertEqual(conn.queries[-1][1][-2:], (6, 7))
        self.assertTrue(all(entry["specification"]["fields"]["rev"]["offset"] == 0 for entry in response["prices"]))

    def test_invalid_or_oversized_metadata_fails_only_when_requested(self):
        for value in (123, "x" * 1000001):
            with self.subTest(kind=type(value).__name__):
                self.row["comment"] = value
                default, _ = self.call_prices()
                self.assertNotIn("specification", default["prices"][0])
                with self.assertRaises(reader.InvalidRequest):
                    self.call_prices(include_specification=True)

    def test_existing_price_verification_failure_is_not_bypassed(self):
        with patch.object(self.evidence, "checked_price", side_effect=ValueError("synthetic price proof mismatch")):
            with self.assertRaisesRegex(ValueError, "proof mismatch"):
                self.call_prices(include_specification=True)

    def test_projection_rejects_invalid_fields_bounds_and_non_boolean_opt_in(self):
        for fields in ({"include_specification": "true"}, {"include_specification": 1},
                       {"include_specification": None}, {"specification_offset": 0},
                       {"include_specification": False, "specification_limit": 1},
                       {"include_specification": True, "limit": 6},
                       {"include_specification": True, "specification_limit": 1001},
                       {"include_specification": True, "specification_limit": 0},
                       {"include_specification": True, "specification_offset": -1},
                       {"include_specification": True, "specification_offset": True},
                       {"include_specification": True, "specification_offset": 1000001},
                       {"include_specification": True, "columns": ["won_date"]},
                       {"include_specification": True, "sql": "select *"}):
            with self.subTest(fields=fields), self.assertRaises(reader.InvalidRequest):
                reader.validate({**self.request, **fields})
        with self.assertRaises(reader.InvalidRequest):
            reader.validate({"action": "search", "corpus": CORPUS, "query": "finish", "include_specification": True})

    def test_associated_document_lookup_can_read_continuation_page_without_claiming_metadata_origin(self):
        response, _ = self.call_prices(include_specification=True)
        lookup = response["prices"][0]["specification"]["related_document"]["page_lookup"]
        first_conn = FakeConnection([None, (3, {}), ("b" * 64, "quote", 2, "d" * 64, "start", 10)])
        first = reader.read(first_conn, reader.validate({**lookup, "limit": 5}))
        self.assertEqual((first["page_number"], first["page_count"], first["next_offset"]), (1, 2, 5))
        next_conn = FakeConnection([None, (3, {}), ("b" * 64, "quote", 2, "e" * 64, "finish excluded", 15)])
        second = reader.read(next_conn, reader.validate({**lookup, "page_number": 2}))
        self.assertEqual(second["text"], "finish excluded")
        self.assertEqual(second["page_sha256"], "e" * 64)
        self.assertEqual(second["basis"], "PDF page text; not verified numeric price")
        self.assertEqual(next_conn.queries[-1][1][-2:], ("synthetic/quote.pdf", 2))

    def test_quote_filter_miss_does_not_restrict_unfiltered_kind_discovery(self):
        filtered_conn = FakeConnection([None, (3, {}), []])
        filtered = reader.read(filtered_conn, reader.validate({"action": "search", "corpus": CORPUS,
                                                               "query": "finish", "quote_no": "Q1"}))
        self.assertEqual(filtered["hits"], [])
        hit = ("synthetic/supplier.pdf", 2, "d" * 64, "e" * 64, "supplier_po", "finish instruction")
        unrestricted_conn = FakeConnection([None, (3, {}), [hit]])
        unrestricted = reader.read(unrestricted_conn, reader.validate({"action": "search", "corpus": CORPUS,
                                                                       "query": "finish"}))
        self.assertEqual(unrestricted["hits"][0]["kind"], "supplier_po")
        self.assertEqual(unrestricted_conn.queries[-1][1][3:7], (None, None, None, None))
        self.assertEqual(filtered_conn.queries[-1][1][5:7], ("Q1", "Q1"))
        self.assertNotIn("prices", unrestricted)


if __name__ == "__main__":
    unittest.main()
