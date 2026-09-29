#!/usr/bin/env python3
"""Bounded read-only Polygres queries for the native Ars Umbris tool."""

import importlib.util
import json
import os
from pathlib import Path
import re
import sys

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_DATABASE = "app_peb68ccd10bc4e4ea3b43852"
CA_CERT = "/etc/ssl/certs/ca-certificates.crt"
CORPUS_ID = re.compile(r"[0-9a-f]{64}\Z")
KINDS = frozenset(("quote", "invoice", "packing_slip", "supplier_po", "certificate", "other", "unknown"))
PRICE_FIELDS = ("quote_no", "item_no", "quantity", "unit_price", "extended_price", "quote_date", "letter_date",
                "part_no", "customer_id", "source_price_field", "price_basis", "status")


class InvalidRequest(ValueError):
    pass


def nonempty(value, label, max_length=256):
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise InvalidRequest(f"{label} must be nonempty and at most {max_length} characters")
    return value


def integer(value, label, default, ceiling, minimum=0):
    if value is None:
        return default
    if type(value) is not int or not minimum <= value <= ceiling:
        raise InvalidRequest(f"{label} must be an integer from {minimum} to {ceiling}")
    return value


def validate(request):
    if not isinstance(request, dict):
        raise InvalidRequest("input must be an object")
    action = request.get("action")
    if action not in ("corpora", "search", "prices", "page"):
        raise InvalidRequest("action must be corpora, search, prices, or page")
    allowed = {
        "corpora": {"action"},
        "search": {"action", "corpus", "query", "quote_no", "kind", "limit", "offset"},
        "prices": {"action", "corpus", "part_no", "quote_no", "limit", "offset"},
        "page": {"action", "corpus", "source_path", "page_number", "limit", "offset"},
    }
    if set(request) - allowed[action]:
        raise InvalidRequest("unsupported fields for action")
    if action == "corpora":
        return request
    if not isinstance(request.get("corpus"), str) or not CORPUS_ID.fullmatch(request["corpus"]):
        raise InvalidRequest("explicit public corpus ID required")
    if action == "search":
        nonempty(request.get("query"), "query", 200)
        if request.get("kind") is not None and request["kind"] not in KINDS:
            raise InvalidRequest("unknown document kind")
    if action == "prices" and not (request.get("part_no") or request.get("quote_no")):
        raise InvalidRequest("prices requires an exact part_no or quote_no")
    if action in ("prices", "search"):
        for field in ("part_no", "quote_no"):
            if field in request:
                nonempty(request[field], field)
        integer(request.get("limit"), "limit", 20, 50, 1)
        integer(request.get("offset"), "offset", 0, 100000)
    if action == "page":
        nonempty(request.get("source_path"), "source_path", 1024)
        integer(request.get("page_number"), "page_number", None, 100000, 1)
        if request.get("page_number") is None:
            raise InvalidRequest("page_number required")
        integer(request.get("limit"), "limit", 4000, 4000, 1)
        integer(request.get("offset"), "offset", 0, 1000000)
    return request


def evidence_module():
    spec = importlib.util.spec_from_file_location("document_evidence_db", ROOT / "scripts/document-evidence-db.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def connect():
    url = os.environ.get("POLYGRES_DIRECT_URL")
    if not url:
        raise InvalidRequest("Polygres access is not configured")
    config = conninfo_to_dict(url)
    if config.get("service") or os.environ.get("PGSERVICE") or config.get("hostaddr") or os.environ.get("PGHOSTADDR"):
        raise InvalidRequest("Polygres connection configuration is unsupported")
    if not config.get("host") or config.get("dbname") != EXPECTED_DATABASE:
        raise InvalidRequest("Polygres database identity is not configured")
    conninfo = make_conninfo(url, sslmode="verify-full", sslrootcert=CA_CERT, connect_timeout=5,
                            options="-c default_transaction_read_only=on -c statement_timeout=5000 -c lock_timeout=1000")
    conn = psycopg.connect(conninfo, autocommit=True)
    if conn.execute("select current_database()").fetchone()[0] != EXPECTED_DATABASE:
        conn.close()
        raise InvalidRequest("Polygres database identity mismatch")
    return conn


def read(conn, request):
    action = request["action"]
    with conn.transaction():
        conn.execute("set transaction read only")
        if action == "corpora":
            rows = conn.execute("select corpus_id,document_count,page_count,price_count,ingested_at from document_corpora order by ingested_at desc,corpus_id limit 51").fetchall()
            return {"action": action, "corpora": [dict(zip(("corpus", "documents", "pages", "verified_prices", "ingested_at"), r)) for r in rows[:50]],
                    "has_more": len(rows) > 50}

        corpus_id = request["corpus"]
        record = conn.execute("select corpus_key,prepared_manifest from document_corpora where corpus_id=%s", (corpus_id,)).fetchone()
        if record is None:
            raise InvalidRequest("unknown corpus")
        corpus_key, prepared = record
        if action == "search":
            limit, offset = request.get("limit", 20), request.get("offset", 0)
            rows = conn.execute(
                "select d.source_path,p.page_number,p.text_sha256,d.pdf_sha256,d.content_kind,left(p.layout_text,500) "
                "from evidence_page_sets s join evidence_documents d using (document_id) "
                "join evidence_pages p using (document_id) "
                "where d.corpus_key=%s "
                "and to_tsvector('english',jsonb_path_query_array(s.pages,'$[*].text')) @@ plainto_tsquery('english',%s) "
                "and to_tsvector('english',p.layout_text) @@ plainto_tsquery('english',%s) "
                "and (%s::text is null or d.content_kind=%s) "
                "and (%s::text is null or exists (select 1 from verified_document_prices v "
                "where v.corpus_key=d.corpus_key and v.document_id=d.document_id and v.quote_no=%s)) "
                "order by d.source_path,p.page_number limit %s offset %s",
                (corpus_key, request["query"], request["query"], request.get("kind"), request.get("kind"),
                 request.get("quote_no"), request.get("quote_no"), limit + 1, offset)).fetchall()
            columns = ("source_path", "page_number", "page_sha256", "pdf_sha256", "kind", "excerpt")
            return {"action": action, "corpus": corpus_id, "basis": "PDF page text; not verified numeric price",
                    "hits": [dict(zip(columns, row)) for row in rows[:limit]], "has_more": len(rows) > limit,
                    "next_offset": offset + limit if len(rows) > limit else None}
        if action == "prices":
            evidence = evidence_module()
            limit, offset = request.get("limit", 20), request.get("offset", 0)
            rows = conn.execute(evidence.PRICE_SELECT + " where v.corpus_key=%s "
                "and (%s::text is null or v.part_no=%s) and (%s::text is null or v.quote_no=%s) "
                "order by v.quote_no,v.quantity,v.item_no limit %s offset %s",
                (corpus_key, request.get("part_no"), request.get("part_no"), request.get("quote_no"),
                 request.get("quote_no"), limit + 1, offset)).fetchall()
            results = []
            for result in rows[:limit]:
                row = evidence.checked_price(result, prepared["csv_columns"])
                results.append({"row": {field: row[field] for field in PRICE_FIELDS}, "source_path": result[12],
                                "pdf_sha256": result[13], "transcript_sha256": result[14]})
            return {"action": action, "corpus": corpus_id, "basis": "verified issued customer quotation PDF",
                    "outcome": "unknown", "prices": results, "has_more": len(rows) > limit,
                    "next_offset": offset + limit if len(rows) > limit else None}

        row = conn.execute(
            "select d.pdf_sha256,d.content_kind,d.page_count,p.text_sha256,"
            "substring(p.layout_text from %s for %s),char_length(p.layout_text) "
            "from evidence_documents d join evidence_pages p using (document_id) "
            "where d.corpus_key=%s and d.source_path=%s and p.page_number=%s",
            (request.get("offset", 0) + 1, request.get("limit", 4000), corpus_key,
             request["source_path"], request["page_number"])).fetchone()
        if row is None:
            raise InvalidRequest("source page not found in selected corpus")
        pdf_sha, kind, page_count, page_sha, text, length = row
        offset = request.get("offset", 0)
        return {"action": action, "corpus": corpus_id, "source_path": request["source_path"],
                "page_number": request["page_number"], "page_count": page_count, "pdf_sha256": pdf_sha,
                "page_sha256": page_sha, "kind": kind, "basis": "PDF page text; not verified numeric price",
                "text": text, "has_more": offset + len(text) < length,
                "next_offset": offset + len(text) if offset + len(text) < length else None}


def main():
    try:
        request = validate(json.load(sys.stdin))
        with connect() as conn:
            result = read(conn, request)
    except (InvalidRequest, json.JSONDecodeError) as exc:
        result = {"error": str(exc)}
    except (psycopg.Error, OSError, ValueError, KeyError, TypeError):
        result = {"error": "Polygres read unavailable or source validation failed"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
