"""Disposable PostgreSQL tests; no production URL or gateway is ever used.

Run with KELLER_TEST_DATABASE_URL=postgresql://.../postgres python -m unittest discover -s tests
Only an explicitly provided local test URL is accepted. pgContext is stubbed;
this suite cannot prove actual extension index/graph sync behavior.
"""
import csv
from datetime import date
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import uuid
from unittest.mock import patch

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo, conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]
COLS = "quote_no item_no assembly_no quote_date date_stamp customer_id customer part_no description rev drawing_no rfq_no buyer_name salesperson quote_letter letter_date quantity unit_price unit_cost extended_price markup del_seq material status won_date to_quote user_quote newsellpri comment".split()
STUB = """
create schema pgcontext;
create domain pgcontext.vector as text;
create table pgcontext._collections (collection_id int generated always as identity primary key, name text unique);
create table pgcontext._collection_points (point_id bigint generated always as identity, collection_id int references pgcontext._collections, source_key text, deleted_at timestamptz, primary key(collection_id, source_key));
insert into pgcontext._collections (name) values ('parts_desc'), ('quote_comments');
create function pgcontext.upsert_points(collection text, keys text[])
returns table(point_id bigint, source_key text, inserted boolean) language plpgsql as $$
declare k text; cid int;
begin
  select collection_id into cid from pgcontext._collections where name = collection;
  foreach k in array keys loop
    insert into pgcontext._collection_points(collection_id, source_key)
    values (cid, k) on conflict on constraint _collection_points_pkey do update set deleted_at = null;
    return query select p.point_id, p.source_key, true
      from pgcontext._collection_points p where p.collection_id = cid and p.source_key = k;
  end loop;
end $$;
"""


def row(**kwargs):
    defaults = dict(quote_no="Q1", quote_date="2024-01-01", date_stamp="2024-01-01",
                    customer_id="C1", customer="ACME", part_no="P1", description="Plate",
                    drawing_no="D1", quote_letter="L1", letter_date="2024-01-02",
                    quantity="10", unit_price="5", material="Steel", status="open",
                    to_quote="0000000", comment="line one\r\nline two")
    defaults.update(kwargs)
    return defaults


def csv_file(rows, folder):
    path = Path(folder) / (uuid.uuid4().hex + ".csv")
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLS, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)
    return path


class DatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ.get("KELLER_TEST_DATABASE_URL")
        if not url:
            raise unittest.SkipTest("set KELLER_TEST_DATABASE_URL to a disposable local PostgreSQL URL")
        params = conninfo_to_dict(url)
        if params.get("host") not in ("localhost", "127.0.0.1", "::1"):
            raise ValueError("tests require a local PostgreSQL host")
        cls.admin_url = url

    def setUp(self):
        self.dbname = "keller_test_" + uuid.uuid4().hex
        with psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("create database {}").format(sql.Identifier(self.dbname)))
        self.url = make_conninfo(self.admin_url, dbname=self.dbname)
        with psycopg.connect(self.url) as conn:
            conn.execute(STUB)
            conn.execute((ROOT / "tests/fixtures/relational.sql").read_text())
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()
        with psycopg.connect(self.admin_url, autocommit=True) as conn:
            conn.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(self.dbname)))

    def load(self, rows, success=True):
        path = csv_file(rows, self.temp.name)
        process = subprocess.run(
            [os.sys.executable, str(ROOT / "scripts/load.py"), str(path)],
            env={"PATH": os.environ["PATH"], "POLYGRES_DIRECT_URL": self.url},
            capture_output=True, text=True,
        )
        if success:
            self.assertEqual(process.returncode, 0, process.stderr)
        else:
            self.assertNotEqual(process.returncode, 0)
        return process

    def query(self, statement, params=()):
        with psycopg.connect(self.url) as conn:
            return conn.execute(statement, params).fetchall()

    def test_identical_import_preserves_ids_vectors_and_duplicate_breaks(self):
        rows = [row(), row(), row(quote_no="Q2", part_no="P2", description="Bracket",
                                      quote_letter="L2", material="Aluminum", to_quote="Q1")]
        self.load(rows)
        with psycopg.connect(self.url) as conn:
            conn.execute("update quotes set comment_embedding = '[1]' where quote_no = 'Q1'")
            conn.execute("update parts set embedding = '[2]' where part_no = 'P1'")
            conn.execute("insert into estimates (customer_id, request_id) values ('C1', 'request')")
            conn.execute("insert into estimate_lines (estimate_id, quote_no) select estimate_id, 'Q1' from estimates")
        before = self.query("select quote_no, part_id, comment, comment_embedding from quotes order by quote_no")
        ids = self.query("select part_id, embedding from parts order by part_id")
        self.load(rows)
        self.assertEqual(before, self.query("select quote_no, part_id, comment, comment_embedding from quotes order by quote_no"))
        self.assertEqual(ids, self.query("select part_id, embedding from parts order by part_id"))
        self.assertEqual(self.query("select quote_no, count(*) from quote_qty_breaks group by quote_no order by quote_no"), [("Q1", 2), ("Q2", 1)])
        self.assertEqual(self.query("select count(*) from estimate_lines"), [(1,)])
        self.assertEqual(self.query("select comment from quotes where quote_no='Q1'"), [("line one\r\nline two",)])

    def test_partial_updates_aggregates_and_clears_obsolete_lineage(self):
        self.load([row(), row(quote_no="Q2", customer_id="C2", customer="BETA", part_no="P2",
                              description="Other", quote_letter="L1", material="Aluminum",
                              to_quote="Q1", quote_date="2024-02-01")])
        with psycopg.connect(self.url) as conn:
            conn.execute("update quotes set comment_embedding='[1]' where quote_no='Q1'")
            conn.execute("select count(*) from pgcontext.upsert_points('quote_comments', array['Q1'])")
            conn.execute("insert into estimates (customer_id, request_id) values ('C1', 'persistent')")
            conn.execute("insert into estimate_lines (estimate_id, quote_no) select estimate_id, 'Q1' from estimates")
        self.load([row(customer_id="C2", customer="BETA", quote_letter="L2", material="Copper",
                       comment="changed", quantity="", to_quote="0000000")])
        self.assertEqual(self.query("select quote_no, customer_id, to_quote, comment_embedding, has_breaks from quotes order by quote_no"),
                         [("Q1", "C2", None, None, False), ("Q2", "C2", "Q1", None, True)])
        self.assertEqual(self.query("select deleted_at is null from pgcontext._collection_points where source_key='Q1'"), [(True,)])
        self.assertEqual(self.query("select customer_id, quote_count from customers order by customer_id"), [("C1", 0), ("C2", 2)])
        self.assertEqual(self.query("select count(*) from estimate_lines"), [(1,)])
        self.assertEqual(self.query("select quote_letter, quote_count, material from quote_letters order by quote_letter"),
                         [("L1", 1, "Aluminum"), ("L2", 1, "Copper")])
        self.assertEqual(self.query("select count(*) from quote_qty_breaks where quote_no='Q1' and is_placeholder"), [(1,)])
        self.assertEqual(self.query("select quote_no, comment from quotes where quote_no='Q2'"), [("Q2", "line one\r\nline two")])

    def test_bad_break_rolls_back_all_changes(self):
        self.load([row()])
        snapshot = self.query("select quote_no, comment from quotes")
        result = self.load([row(comment="edited"), row(quantity="not-a-number")], success=False)
        self.assertIn("invalid input syntax for type numeric", result.stderr)
        self.assertEqual(self.query("select quote_no, comment from quotes"), snapshot)
        self.assertEqual(self.query("select count(*) from quote_qty_breaks"), [(1,)])

    def test_noncanonical_headers_fail_before_changes(self):
        self.load([row()])
        before = self.query("select quote_no, customer_id, comment from quotes")
        for fields in ([COLS[1], COLS[0], *COLS[2:]],
                       COLS[:-1],
                       [*COLS[:-1], COLS[0]]):
            path = Path(self.temp.name) / (uuid.uuid4().hex + ".csv")
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(fields)
                writer.writerow(["tampered" if col == "quote_no" else "" for col in fields])
            process = subprocess.run(
                [os.sys.executable, str(ROOT / "scripts/load.py"), str(path)],
                env={"PATH": os.environ["PATH"], "POLYGRES_DIRECT_URL": self.url},
                capture_output=True, text=True,
            )
            self.assertNotEqual(process.returncode, 0)
            self.assertIn("CSV header must exactly match", process.stderr)
            self.assertEqual(self.query("select quote_no, customer_id, comment from quotes"), before)

    def test_partial_old_letter_does_not_replace_newer_customer_name(self):
        self.load([row(customer="RECENT", letter_date="2025-01-01")])
        self.load([row(quote_no="Q2", quote_date="2023-01-01", letter_date="2023-01-02",
                       quote_letter="L2", customer="OLD")])
        self.assertEqual(self.query("select customer_name, quote_count from customers"), [("RECENT", 2)])

    def test_multiple_letters_for_one_quote_keep_per_letter_dates(self):
        self.load([row(quote_letter="L-old", letter_date="2020-01-02"),
                   row(quote_letter="L-new", letter_date="2025-01-02")])
        self.assertEqual(self.query("select letter_date from quotes where quote_no='Q1'"),
                         [(date(2025, 1, 2),)])
        self.assertEqual(self.query("select quote_letter, letter_date from quote_letters order by quote_letter"),
                         [("L-new", date(2025, 1, 2)),
                          ("L-old", date(2020, 1, 2))])
        self.load([row(quote_no="Q2", quote_letter="L-old", letter_date="2022-01-02")])
        self.load([row(quote_letter="L-old", letter_date="2019-01-02"),
                   row(quote_letter="L-new", letter_date="2026-01-02")])
        self.assertEqual(self.query("select quote_letter, quote_count, letter_date from quote_letters order by quote_letter"),
                         [("L-new", 1, date(2026, 1, 2)),
                          ("L-old", 2, date(2022, 1, 2))])

    def test_partial_refresh_preserves_legacy_undated_shared_letter_header(self):
        self.load([row(quote_letter="L1", letter_date="2020-01-02"),
                   row(quote_no="Q2", quote_letter="L1", letter_date="2025-01-02")])
        with psycopg.connect(self.url) as conn:
            conn.execute("update quote_letter_lines set letter_date = null where quote_no = 'Q2'")
        self.load([row(quote_letter="L1", letter_date="2021-01-02")])
        self.assertEqual(self.query("select letter_date, quote_count from quote_letters where quote_letter='L1'"),
                         [(date(2025, 1, 2), 2)])

    def test_existing_schema_adds_per_link_date_before_refresh(self):
        with psycopg.connect(self.url) as conn:
            conn.execute("alter table quote_letter_lines drop column letter_date")
            migration = (ROOT / "db/migrations/0005_letter_line_date.sql").read_text()
            conn.execute(migration)
            conn.execute(migration)
        self.load([row(quote_letter="L1", letter_date="2020-01-02")])
        self.assertEqual(self.query("select letter_date from quote_letter_lines"),
                         [(date(2020, 1, 2),)])

    def test_customerless_quote_replays_and_assigns_a_customer(self):
        blank = row(customer_id="", customer="", quote_letter="")
        self.load([blank])
        self.load([blank])
        self.assertEqual(self.query("select customer_id from quotes where quote_no='Q1'"), [(None,)])
        self.assertEqual(self.query("select count(*) from customers"), [(0,)])
        assigned = row(customer_id="C2", customer="BETA", quote_letter="L2")
        self.load([assigned])
        self.load([assigned])
        self.assertEqual(self.query("select customer_id from quotes where quote_no='Q1'"), [("C2",)])
        self.assertEqual(self.query("select customer_id, quote_count from customers"), [("C2", 1)])
        self.load([blank])
        self.load([blank])
        self.assertEqual(self.query("select customer_id from quotes where quote_no='Q1'"), [(None,)])
        self.assertEqual(self.query("select count(*) from customers"), [(0,)])

    def test_replay_and_batch_commit_without_paid_gateway(self):
        self.load([row(), row(quote_no="Q2", part_no="P2", description="Bracket", comment="second")])
        with psycopg.connect(self.url) as conn:
            conn.execute("update quotes set comment_embedding='[1]' where quote_no='Q1'")
        spec = importlib.util.spec_from_file_location("keller_embed", ROOT / "scripts/embed.py")
        embed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(embed)
        calls = []

        def fake(texts):
            calls.append(texts)
            return [[0.1] * embed.DIMS for _ in texts]

        with patch.object(embed, "embed_batch", side_effect=fake):
            with psycopg.connect(self.url) as conn:
                embed.run_table(conn, "quotes", "quote_no", "comment", "comment_embedding", "quote_comments")
            self.assertEqual(self.query("select source_key from pgcontext._collection_points order by source_key"), [("Q1",), ("Q2",)])
            with psycopg.connect(self.url) as conn:
                embed.run_table(conn, "quotes", "quote_no", "comment", "comment_embedding", "quote_comments")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.query("select count(*) from quotes where comment_embedding is null"), [(0,)])

    def test_embedding_failed_registration_rolls_back_batch_and_retries(self):
        self.load([row()])
        spec = importlib.util.spec_from_file_location("keller_embed", ROOT / "scripts/embed.py")
        embed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(embed)
        with psycopg.connect(self.url) as conn:
            conn.execute("drop function pgcontext.upsert_points(text, text[])")
        with patch.object(embed, "embed_batch", return_value=[[0.1] * embed.DIMS]):
            with self.assertRaises(psycopg.errors.UndefinedFunction):
                with psycopg.connect(self.url) as conn:
                    embed.run_table(conn, "quotes", "quote_no", "comment", "comment_embedding", "quote_comments")
        self.assertEqual(self.query("select comment_embedding from quotes"), [(None,)])
        with psycopg.connect(self.url) as conn:
            conn.execute("""create function pgcontext.upsert_points(collection text, keys text[])
                returns table(point_id bigint, source_key text, inserted boolean) language sql as $$
                insert into pgcontext._collection_points(collection_id, source_key)
                select c.collection_id, key from pgcontext._collections c,
                    unnest(keys) key where c.name = collection
                on conflict (collection_id, source_key) do update set deleted_at = null
                returning pgcontext._collection_points.point_id,
                          pgcontext._collection_points.source_key, true $$""")
        with patch.object(embed, "embed_batch", return_value=[[0.1] * embed.DIMS]) as gateway:
            with psycopg.connect(self.url) as conn:
                embed.run_table(conn, "quotes", "quote_no", "comment", "comment_embedding", "quote_comments")
        gateway.assert_called_once()
        self.assertEqual(self.query("select source_key from pgcontext._collection_points"), [("Q1",)])

    def test_embedding_noop_registration_cannot_commit_vector(self):
        self.load([row()])
        spec = importlib.util.spec_from_file_location("keller_embed", ROOT / "scripts/embed.py")
        embed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(embed)
        with psycopg.connect(self.url) as conn:
            conn.execute("drop function pgcontext.upsert_points(text, text[])")
            conn.execute("""create function pgcontext.upsert_points(collection text, keys text[])
                returns table(point_id bigint, source_key text, inserted boolean)
                language sql as $$ select null::bigint, null::text, false where false $$""")
        with patch.object(embed, "embed_batch", return_value=[[0.1] * embed.DIMS]):
            with self.assertRaisesRegex(ValueError, "did not register all"):
                with psycopg.connect(self.url) as conn:
                    embed.run_table(conn, "quotes", "quote_no", "comment", "comment_embedding", "quote_comments")
        self.assertEqual(self.query("select comment_embedding from quotes"), [(None,)])

    def test_gateway_rejects_bad_vectors_without_database_or_network(self):
        spec = importlib.util.spec_from_file_location("keller_embed", ROOT / "scripts/embed.py")
        embed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(embed)

        class Response:
            def __init__(self, data):
                self.data = data

            def __enter__(self):
                return io.BytesIO(json.dumps(self.data).encode())

            def __exit__(self, *args):
                pass

        for items in ([{"index": 0, "embedding": [0.1] * embed.DIMS}],
                      [{"index": 0, "embedding": [float("nan")] * embed.DIMS},
                       {"index": 1, "embedding": [0.1] * embed.DIMS}],
                      [{"index": 0, "embedding": [0.1] * embed.DIMS},
                       {"index": 0, "embedding": [0.1] * embed.DIMS}],
                      [{"index": 0, "embedding": [1.0]},
                       {"index": 1, "embedding": [0.1] * embed.DIMS}]):
            with patch.dict(os.environ, {"AI_GATEWAY_API_KEY": "fake"}), \
                 patch.object(embed.urllib.request, "urlopen", return_value=Response({"data": items})):
                with self.assertRaises(ValueError):
                    embed.embed_batch(["a", "b"])
