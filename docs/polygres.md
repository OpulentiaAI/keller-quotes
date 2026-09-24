# Polygres connection & setup

The quoting dataset lives in a Polygres Postgres project (org **Numeric Wombat**,
`org-26b7c272c5754443ae818faafae8f8bd`). This file is the connection reference —
see `.agents/skills/polygres/SKILL.md` for the query cookbook.

## Secrets (Devin org secrets — never commit values)

| Variable | Purpose |
|---|---|
| `POLYGRES_DATABASE_URL` | Pooled app endpoint — runtime traffic, normal queries |
| `POLYGRES_DIRECT_URL` | Direct endpoint — DDL, migrations, COPY/bulk ingest |
| `POLYGRES_PROJECT_ID` | Project id for CLI/MCP wiring |
| `POLYGRES_DB_PASSWORD` | Native role password, only if a tool needs it standalone |

## Non-secret metadata

| Field | Value |
|---|---|
| Pooled host | `shared-lower-012.pool.db.polygres.com` (pgbouncer, `sslmode=require`) |
| Direct host | `shared-lower-012.direct.db.polygres.com` |
| Port | `5432` |
| Database | `app_peb68ccd10bc4e4ea3b43852` |
| Role | `project_owner_peb68ccd10bc4e4ea3b43852` |
| Project | `peb68ccd10bc4e4ea3b43852` |
| TLS | `sslmode=verify-full` supported |

## MCP server URL form

```
https://mcp.polygres.com/mcp?project_id=peb68ccd10bc4e4ea3b43852&features=database,graph,context
```

Feature set: `projects`, `database`, `imports`, `sync`, `context`, `graph`,
`debugging`, `docs`.

## CLI

`pip install polygres` → `~/.pyenv/shims/polygres`. Control-plane commands
require `polygres login` (browser OAuth, one-time per machine). Database-level
work (schema, COPY, `graph.*`, `pgcontext.*`) works over plain SQL through the
direct URL without login. `polygres --project $POLYGRES_PROJECT_ID env` prints
connection metadata once authenticated.

## Reproduce from scratch

```bash
psql "$POLYGRES_DIRECT_URL" -f db/migrations/0001_schema.sql
psql "$POLYGRES_DIRECT_URL" -f db/migrations/0002_fts.sql
psql "$POLYGRES_DIRECT_URL" -f db/migrations/0005_letter_line_date.sql
python3 scripts/load.py quotes.csv          # staging COPY → normalized tables
# graph: register tables/edges, GRANT ALL on node tables to graph_sync_owner,
# then select * from graph.build()   (see db/migrations/0003_graph.sql)
psql "$POLYGRES_DIRECT_URL" -f db/migrations/0004_embeddings.sql
AI_GATEWAY_API_KEY=... python3 scripts/embed.py   # embeds + registers points
```

For Python scripts, install `python3 -m pip install -r requirements-db.txt`.
`load.py` accepts a full register or a CSV containing only the quotes to
refresh. It locks concurrent loader/embedder writes and commits the whole CSV
atomically; failures leave the previous state intact. Only input quote numbers
have their quote rows, price breaks, and letter links replaced. It preserves
part and quote identities, untouched history, and generated estimates. Customer
counts/dates and affected letter headers are recomputed from remaining rows;
source-order first rows determine quote heads. The source CSV must be complete
for each quote number included in a partial refresh, including all duplicate
break rows. Customer names outside the input have only their previously resolved
name available (the normalized schema does not store their source names), so a
partial refresh cannot reconstruct a missing historical name from unrelated
quotes. A full import resolves names deterministically from the latest dated
source letter, then quote number and source row.
Apply `db/migrations/0005_letter_line_date.sql` to an **existing** database
before using the refresh loader. Per-link `letter_date` preserves distinct
letter dates for a quote appearing in multiple letters; letter-header dates are
recomputed from those links rather than the quote's cross-letter maximum. Old
links added before this migration lack date provenance. When a partial refresh
shares a letter with any such undated retained link, the loader preserves its
previous header date rather than inventing a replacement. A complete source
reload rebuilds all links from available CSV dates and restores exact
letter-date aggregates where the source carries dates.

Changed comments retain embedded CRLF and clear their source vector; the point
mapping remains keyed to the same quote and the next embedding run repopulates
it. Run `embed.py` after loading: it idempotently replays **all** nonnull source
vectors through the public `pgcontext.upsert_points(text,text[])` API in bounded
batches, repairing persisted vectors whose registration was missed without
depending on pgContext private catalog columns. Each newly generated vector
batch and its point registration commit together, and the returned source keys
must match every updated key before the transaction commits. A retry resumes
without paying for completed batches.
The script rejects malformed gateway counts, indexes, dimensions, and nonfinite
values before writing. Local PostgreSQL tests use relational equivalents and
explicit pgContext stubs; actual pgContext search, graph sync, and extension
transaction semantics still need verification on Polygres.
The public pgContext 0.3.0 [API reference](https://pgxn.org/dist/pgcontext/0.3.0/docs/user_guide/api_reference.html#stable-user-apis)
declares `upsert_points(collection_name text, source_keys text[])` returning
`(point_id, source_key, inserted)` rows; [point lifecycle](https://pgxn.org/dist/pgcontext/0.3.0/docs/user_guide/collections.html#map-points)
documents idempotent reactivation. Local stubs verify relational transaction
boundaries only, not the deployed extension version, grants, HNSW index, or
graph sync; check those on an authorized Polygres connection before promotion.
For a disposable local PostgreSQL instance, run the DB regressions with
`KELLER_TEST_DATABASE_URL=postgresql://.../postgres python3 -m unittest discover -s tests -v`.
The tests refuse non-loopback hosts and never require a gateway key.

Note: `graph.build()` executes as internal role `graph_sync_owner` — grant it
access to every node table before building (`grant all on customers, parts,
quotes to graph_sync_owner` was needed here).

## Capacity (Nano tier)

| Resource | Cap | Used |
|---|---|---|
| Storage | 500 MiB | see `pg_database_size` — ~290 MB after embeddings |
| Embedding points | 100,000 | ~77.1k (parts descriptions + quote comments) |
| Graph units | 100,000 | ~87.5k (78,460 nodes + 9,003 edge-units) |
