#!/usr/bin/env python3
"""Embed parts.description and quotes.comment into pgContext collections.

Prereq: migrations 0001-0004 applied, data loaded via scripts/load.py.
Env:    POLYGRES_DIRECT_URL (bulk writes), AI_GATEWAY_API_KEY (embeddings).

Model: openai/text-embedding-3-small @ 512 dims via the Vercel AI Gateway
(embeddings endpoint supports the OpenAI `dimensions` truncation param).
pgcontext.search scores are cosine DISTANCE — 0.0 = identical.

Idempotent: only embeds rows whose vector column is still null, so reruns
continue where a previous run stopped. Points are upserted per batch so a
crash never loses more than one batch of registration.
"""
import json
import os
import sys
import urllib.request

import psycopg

BATCH = 1024           # inputs per embeddings request (gateway accepts it)
UPSERT_CHUNK = 5000    # source_keys per upsert_points call
MODEL = "openai/text-embedding-3-small"
DIMS = 512
MAX_CHARS = 8000
GATEWAY = "https://ai-gateway.vercel.sh/v1/embeddings"

DB = os.environ["POLYGRES_DIRECT_URL"]
KEY = os.environ["AI_GATEWAY_API_KEY"]


def embed_batch(texts: list[str]) -> list[list[float]]:
    req = urllib.request.Request(
        GATEWAY,
        data=json.dumps(
            {"model": MODEL, "input": texts, "dimensions": DIMS}
        ).encode(),
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    return [d["embedding"] for d in data["data"]]


def lit(vec: list[float]) -> str:
    return "[" + ",".join(f"{v:.6g}" for v in vec) + "]"


def upsert_points(cur, collection: str, keys: list[str]) -> int:
    n = 0
    for i in range(0, len(keys), UPSERT_CHUNK):
        chunk = keys[i : i + UPSERT_CHUNK]
        cur.execute(
            "select count(*) from pgcontext.upsert_points(%s, %s)",
            (collection, chunk),
        )
        n += cur.fetchone()[0]
    return n


def run_table(
    cur,
    table: str,
    key_col: str,
    text_col: str,
    vec_col: str,
    collection: str,
    vector_name: str,
) -> None:
    cur.execute(
        f"select {key_col}, left({text_col}, %s) from {table} "
        f"where {vec_col} is null and {text_col} is not null and btrim({text_col}) <> ''",
        (MAX_CHARS,),
    )
    rows = cur.fetchall()
    print(f"{table}.{text_col}: {len(rows)} to embed")
    keys_done: list[str] = []
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        vecs = embed_batch([r[1] for r in batch])
        keys = [str(k) for k, _ in batch]
        vals = [lit(v) for v in vecs]
        cur.execute(
            f"update {table} t set {vec_col} = v.emb::pgcontext.vector "
            f"from (select unnest(%s::text[]) as k, unnest(%s::text[]) as emb) v "
            f"where t.{key_col}::text = v.k",
            (keys, vals),
        )
        keys_done.extend(keys)
        if i % (BATCH * 10) == 0 or i + BATCH >= len(rows):
            print(f"  {table}: {min(i + BATCH, len(rows))}/{len(rows)}")
    n = upsert_points(cur, collection, keys_done)
    print(f"{collection}: {n} points registered")


def main() -> None:
    with psycopg.connect(DB, autocommit=True) as conn, conn.cursor() as cur:
        run_table(cur, "parts", "part_id", "description", "embedding", "parts_desc", "desc_emb")
        run_table(cur, "quotes", "quote_no", "comment", "comment_embedding", "quote_comments", "comment_emb")
        for c in ("parts_desc", "quote_comments"):
            cur.execute("select count(*) from pgcontext._collection_points p join pgcontext._collections c on c.collection_id = p.collection_id where c.name = %s and p.deleted_at is null", (c,))
            print(f"points[{c}] =", cur.fetchone()[0])


if __name__ == "__main__":
    main()
