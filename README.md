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
