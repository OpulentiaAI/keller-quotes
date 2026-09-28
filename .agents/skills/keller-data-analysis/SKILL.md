---
name: keller-data-analysis
description: Analyze Keller historical quote calculations and verified customer-PDF prices with explicit grains, provenance, and outcome limitations. Use for price trends, customer/part analysis, and quoting-data questions.
---

# Analyze Keller quoting data

Choose the evidence and grain before calculating anything. The frozen `quotes.csv`/`quotes.json.gz` has 179,608 break rows for 40,111 part-quotes, including 2,210 zero-quantity placeholders. Its price basis is `internal_quote_calculation`, not a validated issued customer price. For issued customer-price questions, prefer a **selected, explicit corpus** of `customer_quote_pdf` prices exported read-only from Polygres; keep it separate from the original register. See [the register guide](../keller-quote-register/SKILL.md) for provenance and [Polygres](../polygres/SKILL.md) for corpus selection and connection.

The Ars Umbris profile exposes bounded `keller_polygres` price/page reads and `keller_sources` read-only private source inspection, not general SQL, large exports, or a shell. Use them for evidence lookup and small cited checks; use the standalone approved private workflow below for aggregate SQL or full-register analysis. Neither the source reader nor `keller_quote` is an evaluation or automatic customer-release tool.

## Query and interpret

1. Define population, date field, unit of analysis, and price basis. A break count is not a quote count; use `count(distinct quote_no)` for unique quote numbers, or `(quote_no,item_no)` for part-quotes. Exclude `is_placeholder` from price arithmetic. A verified PDF price's `quote_date` is recorded inquiry/header metadata, not a recovered original `QUOTEN` date or independently proved version availability; `date_stamp` may be a later revision. Reconcile printed footer dates before making a historical-eligibility claim. Ingestion time is not quote time.
2. Name outcome limitations up front. Frozen `won` means a posted-history mapping, not verified acceptance; `open` does not mean lost. Document prices have `unknown` outcome. Never call `won / (won + open)` a win rate, or infer revenue, payment, or accepted orders from a quote, invoice, or posting.
3. Use parameterized read-only SQL for grouped historical analysis, filtering price basis and corpus where applicable. Document text search finds **candidate pages**, not numeric prices: verify an issued letter's quantity, full source unit price, extension, PDF hash and transcript hash against `verified_document_prices` and the original private PDF. Do not use arbitrary supplier PO or invoice figures as customer quote prices.
4. For trends, compare like part revision, drawing, customer, UOM, quantity band and price basis. Historical nominal dollars have no automatic inflation or current-cost adjustment. Report missing fields and small cohorts rather than smoothing them away. Keep private exports/reports outside the checkout.

For example, this query describes the *posted-history label share*, **not a win rate**:

```sql
select q.customer_id, count(*) as part_quotes,
       count(*) filter (where q.status = 'won') as posted_history_labels,
       round(100.0 * count(*) filter (where q.status = 'won') / nullif(count(*), 0), 1)
         as posted_history_label_pct
from quotes q
group by q.customer_id
order by part_quotes desc;
```

For a nominal legacy unit-price trend, join `quote_qty_breaks b` to `quotes q` on `quote_no`, filter `not b.is_placeholder` and a specified part/revision/quantity scope, and label the chart **internal calculations**. Never join `estimates`/`estimate_lines` as though they were source history. See [pricing evals and orders](../../../docs/pricing-evals-and-orders.md) when interpreting estimator accuracy; an eval's priced-only error, all-case coverage, and workflow completeness answer different questions.

Use Python's `csv.DictReader` with `newline=''` for local CSV analysis; quoted comments can contain commas and embedded newlines, so line-oriented `awk`/`grep` is unsafe. State both numerator and denominator, attach SQL or reproducible code, identify whether figures are historical calculations or verified customer quotations, and make no customer-facing price recommendation from a population statistic alone.
