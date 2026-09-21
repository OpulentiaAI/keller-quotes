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
python3 scripts/load.py quotes.csv          # staging COPY → normalized tables
# graph: register tables/edges, GRANT ALL on node tables to graph_sync_owner,
# then select * from graph.build()   (see db/migrations/0003_graph.sql)
psql "$POLYGRES_DIRECT_URL" -f db/migrations/0004_embeddings.sql
AI_GATEWAY_API_KEY=... python3 scripts/embed.py   # embeds + registers points
```

Note: `graph.build()` executes as internal role `graph_sync_owner` — grant it
access to every node table before building (`grant all on customers, parts,
quotes to graph_sync_owner` was needed here).

## Capacity (Nano tier)

| Resource | Cap | Used |
|---|---|---|
| Storage | 500 MiB | see `pg_database_size` — ~290 MB after embeddings |
| Embedding points | 100,000 | ~77.1k (parts descriptions + quote comments) |
| Graph units | 100,000 | ~87.5k (78,460 nodes + 9,003 edge-units) |
