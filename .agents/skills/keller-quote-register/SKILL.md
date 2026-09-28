---
name: keller-quote-register
description: Reference for frozen FabriTRAK calculation quotes and separately verified customer-PDF quote registers; use for schema, provenance, date, precision, and source selection.
---

# Keller quote registers: keep price bases separate

The immutable `quotes.csv` and `quotes.json.gz` represent 179,608 quantity-break rows for 40,111 part-quotes (`quote_no` plus `item_no`), dated 1994–2026. `estimator/data/quotes.csv` symlinks to this **internal-calculation** source. There are 2,210 placeholder breaks with no usable unit price. These are frozen local exports of the read-only September 2026 `C:\Vftw\KELLER` FabriTRAK snapshot, not a live cost feed or verified accepted-order history.

| Fields | Original source | Interpretation |
|---|---|---|
| `quote_no`, `item_no`, `part_no`, `description`, `customer_id`, `quote_date`, `date_stamp`, `rev`, `drawing_no`, `rfq_no`, `to_quote`, `comment` | `QUOTEN.DBF` | Original quote date and last touch differ; `to_quote=0000000` means original. `comment` can hold material/finish text and embedded newlines. |
| `quantity`, `unit_price`, `unit_cost`, `extended_price`, `markup`, `del_seq` | `QUOTQTYS.DBF` | Internal calculation breaks, which can differ from printed letters; `DEL` counts deliveries. |
| `quote_letter`, `letter_date`, customer name, sparse `material` | `QUOTLINE`/`QUOTLETT`/`QUOTLEIT` | Names may be blank without a letter; join by `customer_id`. |
| `status`, `won_date` | `QUOTHIST.DBF` | `won` is an **unverified posted-history label**, not a confirmed sale; `open` is not a loss. `QUOTEHN` is empty. |

The separately derived `customer_quote_pdf` register contains only conservatively verified issued-quote letter lines. It is not an override of the frozen CSV. Its `status` is `unknown`; it retains the source document and AnyDoc transcript hashes, letter number/date, source price field, quantity, full source unit price, and printed extension. Source `quote_date` in this derivative is **set to the verified `letter_date`**, not the original `QUOTEN` date; `date_stamp` is the maximum known source revision/letter date. Do not claim the derivative corrected an original date. The builder permits up to five decimal places in source prices; preserve all reported precision even when the printed two-decimal unit looks truncated. Confirm `quantity × full source unit price` reconciles to the printed extension and keep all breaks of a price curve from one compatible verified letter/provenance. Never fill gaps from internal calculations without clearly changing the basis and obtaining review. See [document evidence](../../../docs/document-evidence.md).

For local frozen-register queries, use a CSV parser rather than physical-line `grep` or comma-splitting `awk`:

```sh
python3 - <<'PY'
import csv
with open('quotes.csv', newline='', encoding='utf-8') as source:
    rows = (r for r in csv.DictReader(source) if r['part_no'] == 'SYNTHETIC-PART')
    for r in rows:
        print(r['quote_no'], r['item_no'], r['quantity'], r['unit_price'])
PY
```

That synthetic part will usually return no rows; replace the filter only for authorized private analysis. The normalized Polygres legacy tables are a **mirror** of these calculations; the four separate document-evidence tables and explicit-corpus read-only export provide the verified price source. [Polygres](../polygres/SKILL.md) describes safe retrieval. Do not run `scripts/load.py` to load document prices, hand-edit frozen inputs, or revisit source PDFs/DBFs just to quote against the already verified corpus. New source extraction, importer writes, and capacity decisions require separate authorization and post-import hash/row proofs. [The estimator guide](../keller-quote-estimator/SKILL.md) explains the review gate for an actual request.
