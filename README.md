# C. Keller Mfg. — FabriTRAK quoting data extract

Quoting history extracted from the client's live **Metalsoft FabriTRAK** (Visual FoxPro) database.

## Source

- Machine: Windows 11 workstation `2026PC` (Dell OptiPlex 3060), accessed read-only via TeamViewer.
- Dataset: `C:\Vftw\KELLER\` — the live FabriTRAK data directory (files last modified 2026-08-12/13; `C:\Vftw2` and `C:\Vftw\data` are 2000–2001 blank templates and were NOT used).
- Method: the whole `C:\Vftw\KELLER` tree was zipped on the box (`Compress-Archive`, 351 MB) and copied off; DBF files were then parsed with `dbfread` (FoxPro `.DBF` + `.FPT` memos + `.CDX` indexes present alongside).

## Files

- `quotes.csv` — one row per **quote qty/price break** (179,608 rows). Openable in Excel.
- `quotes.json.gz` — same rows as JSON (`gunzip quotes.json.gz` → `quotes.json`, 132 MB).

## Data model (how tables were joined)

- `QUOTEN.DBF` (40,111 rows) — internal quote record, one row per part quoted. Key `QUOTE_NO`; carries `PART_NO`, `DESCR`, `COMP_ID` (customer id), `ORG_DATE`/`DATE_STAMP`, `REV_NO`, `DRAWING_NO`, `RFQ_NO`, `BUYER_NAME`, `SALES_PERS`, `TO_QUOTE` (re-quote lineage), `COMMENT` (finish/material notes).
- `QUOTQTYS.DBF` (177,417 rows) — quantity/price breaks per `QUOTE_NO`: `QTY`, `UNIT_SELL` (quoted unit price), `UNIT_COST`, `MARKUP`, `DEL` (break seq). `extended_price = QTY × UNIT_SELL`. Quotes with no price breaks emit a single row with empty qty/price fields.
- `QUOTLINE.DBF` (45,165) — links `QUOTE_NO` → printed quote letter (`QUOTLETTER` + `ITEM`).
- `QUOTLETT.DBF` (44,962) — quote letter headers: `CNAME` (customer name), `COMP_ID`, `DATE_STAMP` (letter date), `APPROVE_DA`. Used to resolve `customer` names from `COMP_ID` (most recent letter wins) and `letter_date`.
- `QUOTLEIT.DBF` (215,760) — letter line items; `MATERIAL` pulled into `material` when populated.
- `QUOTHIST.DBF` (19,546) — posted quote history (`POST_D`). Presence of `QUOTE_NO` here → `status = "won"` (3,997 quotes).

## Fields

`quote_no, item_no, assembly_no, quote_date, date_stamp, customer_id, customer, part_no, description, rev, drawing_no, rfq_no, buyer_name, salesperson, quote_letter, letter_date, quantity, unit_price, unit_cost, extended_price, markup, del_seq, material, status, won_date, to_quote, user_quote, newsellpri, comment`

## Caveats / unpopulated fields

- `status` is only `won` or `open` — the lost-quote outcome table `QUOTEHN.DBF` exists but is empty (0 rows); FabriTRAK never recorded explicit "lost" flags. "open" therefore includes quotes that silently lost or expired. `won_date` = `QUOTHIST.POST_D` where known.
- `material` is sparse — populated only where a quote-letter line carries it (`QUOTLEIT.MATERIAL`); most quotes keep material/finish info in the free-text `comment` (e.g. ".048 S.S 304 BRUSHED PVC").
- `item_no`/`assembly_no`/`to_quote` relate multi-part assemblies and re-quotes (`TO_QUOTE='0000000'` = original, otherwise the earlier quote it re-quotes).
- `date_stamp` is the record's last-touch date; `quote_date` (`ORG_DATE`) is the original quote date — they differ where quotes were revised.
- `customer` is resolved via `QUOTLETT.CNAME` for the 365 customer ids that ever got a letter; the remainder keep `customer_id` only.
- Memo (`COMMENT`) fields are included verbatim with original CRLFs.
- Vendor-side quote requests (`VENDQUOT.DBF`, 12,779 rows) and quote ops/tooling detail (`QUOTOPER`, `QUOTTOO`, `QUOTQA`, `QUOTEH/M/O` markup matrices, `QUOTCAD`) were extracted in the zip but are not part of this flat export — ask if you want those too.

## Estimator

`estimator/` is a TypeScript pipeline that turns a pricing request (parts + materials + drawing refs) into a priced quote draft by retrieving historical analogs from this register, ranking/screening them with TypeSafe Jev (`typesafe-ai/jev` via Vercel AI Gateway, deterministic fallback without a key), and interpolating qty/price breaks.

For a cross-platform offline onboarding check and safe request inbox → draft/receipt cycle, see [the 15-minute operator guide](docs/local-automation.md). This does not automatically send customer quotes or connect a request producer.

Skills in `.agents/skills/` document the workflows:

- **keller-quote-estimator** — request → quote procedure
- **keller-quote-register** — this dataset's schema, provenance, and quirks
- **keller-estimator-evals** — leave-one-out eval harness (`evals/`) + hill-climbing guide; current baseline: 98.8% coverage, median APE 46.3%, 24.3% within ±20% (`evals/report-baseline.md`)
- **polygres** — connect to and query the register in Polygres (Postgres + embeddings + graph + FTS)
- **keller-data-analysis** — data-analysis workflow adapted to this dataset (SQL recipes, charting, grain rules)

## Polygres database

The register is also normalized into a Polygres Postgres project (Nano tier).
Connection metadata, secrets, and MCP wiring: `docs/polygres.md`. Reproducible
schema in `db/migrations/` + `scripts/load.py` / `scripts/embed.py`.

Table map (CSV → normalized):

| Table | Rows | Maps from |
|---|---|---|
| `customers` | 258 | `customer_id` + `customer` (letter-resolved names) |
| `parts` | 38,091 | deduped `part_no`+`drawing_no`+`description` |
| `quotes` | 40,111 | QUOTEN heads; `to_quote` self-FK re-quote lineage |
| `quote_qty_breaks` | 179,608 | every source row incl. `is_placeholder` breakless quotes |
| `quote_letters` / `quote_letter_lines` | 23,822 / 23,903 | QUOTLETT headers + per-letter quote links, `material` |
| `estimates` / `estimate_lines` | — | estimator output only, never history |

Retrieval layers: pgContext embedding collections `parts_desc` +
`quote_comments` (512-dim, ~77k points), `graph` extension with
customers/parts/quotes nodes and QUOTED/FOR_PART/REQUOTE_OF edges (~87.5k of
100k Nano units), Postgres `tsvector` FTS + `pg_trgm` fuzzy indexes.

## Ars Umbris brand overlay

`brand/ckeller/` carries the Opulent × C. Keller branding for the Ars Umbris
build (`au-host`): a CKeller theme instance (navy surfaces, `#0568dd` accent),
Inter + JetBrains Mono faces, the "Opulent × C. Keller" start-here lockup with
the CK mark and product shots — all pulled from ckellermfg.com via Context.dev.
Apply instructions in `brand/ckeller/README.md`.
