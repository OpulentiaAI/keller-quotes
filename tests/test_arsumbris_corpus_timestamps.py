import importlib.util
import io
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("corpus_timestamp_reader", ROOT / "arsumbris/polygres/read.py")
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


class Connection:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def transaction(self):
        return self

    def execute(self, query):
        self.queries.append(query)
        return self

    def fetchall(self):
        return self.rows


class CorpusTimestampsTest(unittest.TestCase):
    def test_real_driver_datetime_is_json_serializable_with_offset_and_precision(self):
        timestamp = datetime(2026, 10, 4, 5, 0, 1, 123456, tzinfo=timezone(timedelta(hours=-4)))
        conn = Connection([("a" * 64, 3, 4, 5, timestamp)])
        result = reader.read(conn, {"action": "corpora"})
        decoded = json.loads(json.dumps(result))
        self.assertEqual(decoded["corpora"][0]["ingested_at"], "2026-10-04T05:00:01.123456-04:00")
        self.assertEqual(conn.queries[0], "set transaction read only")
        self.assertFalse(decoded["has_more"])

    def test_main_serializes_native_timestamps_and_retains_pagination(self):
        conn = Connection([("a" * 64, 3, 4, 5, datetime(2026, 10, 4, tzinfo=timezone.utc))] * 51)
        output = io.StringIO()
        with patch.object(reader, "connect", return_value=conn), patch.object(reader.sys, "stdin", io.StringIO('{"action":"corpora"}')), patch.object(reader.sys, "stdout", output):
            reader.main()
        result = json.loads(output.getvalue())
        self.assertEqual(len(result["corpora"]), 50)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["corpora"][0]["ingested_at"], "2026-10-04T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
