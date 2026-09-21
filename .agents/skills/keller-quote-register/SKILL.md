---
name: keller-quote-register
description: Reference for the C. Keller Mfg. FabriTRAK quote register (quotes.csv / quotes.json.gz) — schema, table provenance, field quirks, and how to query or extend it. Use when querying the data, adding fields, or debugging estimator analogs.
---

# Keller Quote Register

One row per **quote qty/price break** — 179,608 rows covering 40,111 part-quotes (quote_no+item), 1994–2026. Source: `C:\Vftw\KELLER` Visual FoxPro tables, extracted read-only via TeamViewer on 2026-09-21.

## Files

- `quotes.csv` — canonical flat table, Excel-openable.
- `quotes.json.gz` — same rows as JSON (`gunzip` it; 132 MB unpacked).
- `estimator/data/quotes.csv` — symlink to `../quotes.csv` so the estimator resolves it in place.

## Provenance (which FoxPro table feeds what)

| Register fields | Source table | Notes |
|---|---|---|
| quote_no, part_no, description, customer_id, quote_date (`ORG_DATE`), date_stamp, rev, drawing_no, rfq_no, buyer_name, salesperson, to_quote, comment | `QUOTEN.DBF` (40,111) | one row per part-quote |
| quantity, unit_price, unit_cost, extended_price, markup, del_seq | `QUOTQTYS.DBF` (177,417) | qty/price breaks; `extended_price = quantity × unit_price` |
| quote_letter, letter_date, customer name | `QUOTLINE.DBF` → `QUOTLETT.DBF` | letter→quote link; `CNAME` resolved to `customer` |
| material | `QUOTLEIT.DBF` | sparse — most material info lives in `comment` text |
| status, won_date | `QUOTHIST.DBF` | presence ⇒ `won`; `won_date` = `POST_D` |

Not yet extracted into the flat files: `VENDQUOT` (vendor quotes, 12,779), `QUOTOPER`/`QUOTTOO`/`QUOTQA` (ops/tooling/fixture detail), `QUOTEH/M/O` (markup matrices). The full DBF tree exists in the original 351 MB zip (regenerate by re-extracting if needed).

## Field quirks that matter

- **`status` is only `won` or `open`.** `QUOTEHN.DBF` (the lost-quote table) is empty — FabriTRAK never recorded explicit losses. "open" includes silently-lost and expired quotes. Never report "lost" counts from this data.
- **`quote_date` vs `date_stamp`**: `quote_date` = original quote date; `date_stamp` = last touch (revisions). Use `quote_date` for era/recency.
- **Re-quotes**: `to_quote` points to the earlier quote this one re-quotes (`0000000` = original). Useful for price-over-time curves of the same part.
- **`item_no`/`assembly_no`**: multi-part assemblies group by `assembly_no`.
- **`customer_id` ↔ `customer`**: name resolved via the most recent `QUOTLETT` for that `COMP_ID`; quotes whose customer never got a letter have `customer` empty — join on `customer_id`.
- **Prices are historical as-quoted.** No inflation index. 1994 dollars ≠ 2026 dollars.
- **`comment`** carries material/finish free text (e.g. `.048 S.S 304 BRUSHED PVC`) — grep it for material hints `material` misses.

## Common queries

```bash
# exact part history (all breaks)
csvgrep -c part_no -m '96-0085-00' quotes.csv   # or: grep ',96-0085-00,' quotes.csv

# a customer's quotes
awk -F, '$6=="000317"' quotes.csv

# python
python3 - <<'EOF'
import csv
rows=[r for r in csv.DictReader(open('quotes.csv')) if r['status']=='won']
print(len(rows))
EOF
```

For programmatic access use `estimator/src/register.ts` (`QuoteRegister.fromCsv`) — it groups breaks per quote and builds part_no/customer/token indexes.

## Extending the register

To add fields (e.g. ops detail from `QUOTOPER`): re-extract `C:\Vftw\KELLER` (see session history / TeamViewer device 1321305824), join the new table on `QUOTE_NO`, regenerate CSV+JSON, bump this README's provenance table. Never hand-edit `quotes.csv`.

## Polygres mirror

The register is also loaded into a Polygres Postgres database — normalized
tables + embedding/graph/FTS retrieval layers. Use it for semantic analog
search, re-quote lineage traversal, and fuzzy part lookup instead of scanning
the CSV. Connection, schema map, and query recipes live in the **polygres**
skill (`polygres`) and `docs/polygres.md`. The CSV remains the source of truth;
the DB is a derived copy — regenerate via `scripts/load.py`.
