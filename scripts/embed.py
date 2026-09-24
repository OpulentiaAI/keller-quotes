#!/usr/bin/env python3
"""Recover and populate pgContext vectors in independently committed batches.

Env: POLYGRES_DIRECT_URL and (only when new embeddings are needed)
AI_GATEWAY_API_KEY. Run after schema, load, and collection migrations.
"""
import json
import math
import os
import urllib.request

import psycopg

BATCH = 1024
MODEL = "openai/text-embedding-3-small"
DIMS = 512
MAX_CHARS = 8000
GATEWAY = "https://ai-gateway.vercel.sh/v1/embeddings"
LOCK_ID = 57841433


def embed_batch(texts: list[str]) -> list[list[float]]:
    req = urllib.request.Request(
        GATEWAY,
        data=json.dumps({"model": MODEL, "input": texts, "dimensions": DIMS}).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['AI_GATEWAY_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    items = data["data"]
    if len(items) != len(texts):
        raise ValueError(f"gateway returned {len(items)} vectors for {len(texts)} inputs")
    vectors: list[list[float] | None] = [None] * len(texts)
    for item in items:
        index = item["index"]
        vector = item["embedding"]
        if type(index) is not int or not 0 <= index < len(texts) or vectors[index] is not None:
            raise ValueError(f"invalid or duplicate gateway index: {index!r}")
        if len(vector) != DIMS or any(type(v) not in (int, float) or not math.isfinite(v) for v in vector):
            raise ValueError(f"invalid gateway vector at index {index!r}: expected {DIMS} finite numbers")
        vectors[index] = vector
    if any(v is None for v in vectors):
        raise ValueError("gateway response is missing input indexes")
    return vectors


def upsert_points(cur, collection: str, keys: list[str]) -> int:
    cur.execute("select source_key from pgcontext.upsert_points(%s, %s)", (collection, keys))
    registered = [row[0] for row in cur.fetchall()]
    if sorted(registered) != sorted(keys):
        raise ValueError(f"pgContext did not register all {len(keys)} source keys in {collection}")
    return len(registered)


def run_table(conn, table: str, key_col: str, text_col: str, vec_col: str, collection: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"select {key_col}::text from {table} where {vec_col} is not null order by {key_col}"
        )
        existing = [row[0] for row in cur.fetchall()]
    conn.commit()
    for i in range(0, len(existing), BATCH):
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("select pg_advisory_xact_lock(%s)", (LOCK_ID,))
            chunk = existing[i : i + BATCH]
            cur.execute(
                f"select {key_col}::text from {table} where {key_col}::text = any(%s) "
                f"and {vec_col} is not null",
                (chunk,),
            )
            keys = [row[0] for row in cur.fetchall()]
            if keys:
                upsert_points(cur, collection, keys)
    print(f"{collection}: reconciled {len(existing)} existing vectors")

    with conn.cursor() as cur:
        cur.execute(
            f"select {key_col}::text, {text_col} from {table} "
            f"where {vec_col} is null and {text_col} is not null "
            f"and btrim({text_col}) <> '' order by {key_col}",
        )
        rows = cur.fetchall()
    conn.commit()
    print(f"{table}.{text_col}: {len(rows)} to embed")
    for i in range(0, len(rows), BATCH):
        batch = rows[i : i + BATCH]
        vectors = embed_batch([text[:MAX_CHARS] for _, text in batch])
        keys = [key for key, _ in batch]
        literals = ["[" + ",".join(repr(v) for v in vector) + "]" for vector in vectors]
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("select pg_advisory_xact_lock(%s)", (LOCK_ID,))
            cur.execute(
                f"update {table} t set {vec_col} = v.emb::pgcontext.vector "
                "from (select unnest(%s::text[]) as k, unnest(%s::text[]) as txt, "
                "unnest(%s::text[]) as emb) v "
                f"where t.{key_col}::text = v.k and t.{text_col} = v.txt "
                f"and t.{vec_col} is null returning t.{key_col}::text",
                (keys, [text for _, text in batch], literals),
            )
            updated = [row[0] for row in cur.fetchall()]
            if updated:
                upsert_points(cur, collection, updated)
        print(f"  {table}: {min(i + BATCH, len(rows))}/{len(rows)} ({len(updated)} registered)")


def main() -> None:
    with psycopg.connect(os.environ["POLYGRES_DIRECT_URL"]) as conn:
        run_table(conn, "parts", "part_id", "description", "embedding", "parts_desc")
        run_table(conn, "quotes", "quote_no", "comment", "comment_embedding", "quote_comments")


if __name__ == "__main__":
    main()
