---
name: polygres
description: Connect to and query the Keller quote register's Polygres database (Postgres + pgContext vectors + graph + full-text). Use when working with the quoting dataset in Polygres — schema, embeddings, graph traversal, or connecting a new agent/tool.
---

# Polygres — Keller quote register

The FabriTRAK quote register (source: `quotes.csv`) also lives in a Polygres
Postgres database with three retrieval layers on top: pgContext embedding
collections, the `graph` extension, and Postgres FTS/trigram.

## Connection

Secrets live in Devin org secrets — never print, log, or commit them:

| Env var | Endpoint | Use for |
|---|---|---|
| `POLYGRES_DATABASE_URL` | pooled (`shared-lower-012.pool.db.polygres.com`, pgbouncer) | app queries, reads |
| `POLYGRES_DIRECT_URL` | direct (`shared-lower-012.direct.db.polygres.com`) | DDL, migrations, COPY, bulk writes |
| `POLYGRES_PROJECT_ID` | `peb68ccd10bc4e4ea3b43852` | CLI / MCP wiring |
| `POLYGRES_DB_PASSWORD` | native role password | only when a tool needs it separately |

- Database `app_peb68ccd10bc4e4ea3b43852`, role
  `project_owner_peb68ccd10bc4e4ea3b43852`, port 5432, TLS `verify-full` supported.
- Python: `psycopg.connect(os.environ["POLYGRES_DIRECT_URL"])` (psycopg 3).
- psql: `psql "$POLYGRES_DIRECT_URL"`.
- The `polygres` CLI (pip, `~/.pyenv/shims/polygres`) exists but control-plane
  commands return `AUTH_REQUIRED` until `polygres login` (browser OAuth) — do
  database-level work over SQL instead. `polygres --project $POLYGRES_PROJECT_ID
  env` prints passwordless connection metadata once logged in.
- MCP wiring for a future agent:
  `https://mcp.polygres.com/mcp?project_id=peb68ccd10bc4e4ea3b43852&features=database,graph,context`
  (features ∈ projects, database, imports, sync, context, graph, debugging, docs).

## Schema (migrations in `db/migrations/`, applied in order)

| Table | Grain | Notes |
|---|---|---|
| `customers` | one per `customer_id` | `customer_name` only for ids that reached a quote letter; `quote_count`, `first_quote`, `last_quote` |
| `parts` | deduped `(part_no, drawing_no, description)` | `part_id` pk; `id` = stored generated text alias (pgContext source key); `embedding` pgcontext.vector(512); `fts` generated |
| `quotes` | one per `quote_no` | `quote_date` (ORG_DATE) vs `date_stamp` (last touch) kept separate; `status` only `'won'`/`'open'` — no lost state (QUOTEHN empty); `to_quote` self-FK re-quote lineage; `comment` verbatim CRLF; `comment_embedding`; `id` source-key alias |
| `quote_qty_breaks` | one per source CSV row | `is_placeholder` rows preserve the 179,608-row grain for breakless quotes |
| `quote_letters` + `quote_letter_lines` | QUOTLETT headers + per-quote lines | `material` lives here only; letters are NOT graph nodes (Nano unit budget) |
| `estimates` / `estimate_lines` | estimator output, request-id keyed | generated estimates — never mix with real history |

Row counts after the baseline load: customers 258, parts 38,091, quotes 40,111,
quote_qty_breaks 179,608 (2,210 placeholders), quote_letters 23,822,
quote_letter_lines 23,903, requote edges 9,815 (1 dangling target kept null).

## Layer usage

### Embeddings (pgContext)

Collections `parts_desc` (parts.embedding) and `quote_comments`
(quotes.comment_embedding), both 512-dim cosine, populated by
`scripts/embed.py` via the Vercel AI Gateway (`openai/text-embedding-3-small`,
`dimensions=512` — requires `AI_GATEWAY_API_KEY`).

- Source tables MUST have an `id` column — `search` resolves `source_key` to it.
  That's why `parts.id`/`quotes.id` generated aliases exist.
- Register rows: `select pgcontext.upsert_points('<collection>', array[<id>...])`.
  Only upsert rows whose vector column is populated; `backfill_points` registers
  every row.
- Query:
  ```sql
  select p.part_no, p.description, s.score
  from pgcontext.search('parts_desc', 'desc_emb', $1::pgcontext.vector, 20) s
  join parts p on p.id = s.source_key;
  -- score is cosine DISTANCE: 0.0 = identical, ~1.0 = orthogonal
  ```
- Embeddings embed text verbatim — pass the same surface at query time.

### Graph (`graph` extension, Postgres-native Cypher)

Registered nodes: `customers`, `parts`, `quotes`. Edges:
`quotes.customer_id → customers (QUOTED)`, `quotes.part_id → parts (FOR_PART)`,
`quotes.to_quote → quotes (REQUOTE_OF)`. Built via `graph.build()`; sync mode
`trigger` keeps it live on writes.

```sql
-- re-quote lineage chain
select * from graph.cypher(
  'MATCH (q:quotes)-[:REQUOTE_OF]->(p:quotes) RETURN q.quote_no, p.quote_no LIMIT 20',
  null, false);
-- all quotes for a part
select * from graph.cypher(
  'MATCH (q:quotes)-[:FOR_PART]->(p:parts) WHERE p.part_no = ''101104'' RETURN q.quote_no, q.status LIMIT 20',
  null, false);
```

- Result rows are capped (~10k) — always `LIMIT` and filter on the label side.
- Grant note: `graph.build()`/`auto_discover` execute as `graph_sync_owner`;
  that role holds `GRANT ALL` on the three node tables. New node tables need
  the same grant before build.

### Full-text + fuzzy

- `quotes.fts` (comment+rfq_no+buyer_name) and `parts.fts`
  (description+part_no+drawing_no) are generated tsvector columns with GIN
  indexes: `where fts @@ plainto_tsquery('english', $1)`.
- Trigram indexes for fuzzy match: `parts.part_no`, `parts.drawing_no`,
  `parts.description`, `customers.customer_name`, `quotes.comment`
  (`similarity(a,b)`, `a % b`, `ilike`).

## Budgets (Nano tier)

- Storage cap 500 MiB — check `select pg_size_pretty(pg_database_size(current_database()))`.
- 100k embedding points: `select count(*) from pgcontext._collection_points`.
- 100k graph units (node=1, 10 edges=1): current ≈ 87.5k — letters deliberately
  excluded; adding them (+23.8k nodes) would overflow.
- `pgcontext.collection_limits('<name>')` shows per-collection caps (all unset).

## Verification checklist

1. `select count(*) from quotes` → 40,111; `quote_qty_breaks` → 179,608.
2. `select * from graph.cypher('MATCH (q:quotes)-[:REQUOTE_OF]->(p:quotes) RETURN count(*) LIMIT 1', null, false)` → 9,815.
3. `pgcontext.search('parts_desc','desc_emb',<vec>,5)` returns rows after embed.
4. `select count(*) from quotes where fts @@ plainto_tsquery('english','anodize')` > 0.

## Anti-patterns

- Don't `create extension vector` — superuser-gated; use `pgcontext.vector`.
- Don't upsert collection points for rows with null vectors.
- Don't add `quote_letters` as graph nodes — Nano unit cap.
- Don't write to `estimates`/`estimate_lines` from data repair — they're for
  generated estimator output only.
- Don't print secret values; use the env vars.
