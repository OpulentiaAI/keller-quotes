---
name: keller-data-analysis
description: Analyze the Keller quoting dataset — answer data questions, write SQL against the Polygres register or queries over quotes.csv, and produce charts/reports. Use for win rates, price trends, customer/part analysis, or any quoting-data question.
---

# Data analysis on the Keller quote register

Adapted from Devin's builtin data-analysis skill for this repo's two query
surfaces. Prefer Polygres for anything beyond a trivial grep — the normalized
schema makes joins and aggregation correct by construction.

## Before you start

1. **Pick the surface:**
   - **Polygres** (default): normalized tables + `graph` + pgContext embeddings
     + FTS/trigram. See the `polygres` skill for connection and recipes.
     `POLYGRES_DIRECT_URL` for writes, `POLYGRES_DATABASE_URL` for reads.
   - **`quotes.csv`** (179,608 rows): fine for quick pandas/awk work; remember it
     is break-grain — one row per qty/price break, not per quote.
2. **Read `keller-quote-register` first** for field quirks (status won|open only
   — no lost; `quote_date` vs `date_stamp`; `to_quote='0000000'` = original;
   `material` sparse; `comment` holds finish/material verbatim).
3. **If asked about estimator output**: `estimates`/`estimate_lines` are
   generated quotes — exclude them from historical analysis.

## Analysis flow

1. **Frame the grain.** Decide whether the question is per-quote (`quotes`),
   per-break (`quote_qty_breaks`), per-part (`parts`), per-customer
   (`customers`), or per-letter (`quote_letters`). Most "how many quotes"
   questions want `count(distinct quote_no)` semantics, not row counts.
2. **Validate assumptions before querying**: are won/open pools wanted together
   or separately? Which era (`quote_date` ranges)? Re-quotes inflate counts —
   `to_quote is null` isolates originals.
3. **Query incrementally** — `LIMIT` while exploring; run independent
   aggregations in one batch; handle nulls explicitly (`customer_name`,
   `material`, `won_date` are legitimately null).
4. **Sanity-check**: negative prices, qty=0 placeholder rows
   (`is_placeholder`), pre-2000 vs 2020s price eras — flag anomalies rather than
   averaging them away.
5. **Persist results**: save query outputs to CSV under `out/` (gitignored)
   before charting.

## Useful patterns (Polygres SQL)

```sql
-- win rate by customer (real denominators: won is all we can measure)
select c.customer_name, count(*) quotes,
       count(*) filter (where q.status='won') won,
       round(100.0*count(*) filter (where q.status='won')/count(*),1) pct
from quotes q join customers c using (customer_id)
group by 1 order by quotes desc;

-- unit-price trend for a part (log-log friendly)
select q.quote_date, b.quantity, b.unit_price
from quote_qty_breaks b join quotes q using (quote_no)
join parts p on p.part_id = q.part_id
where p.part_no = '101104' and not b.is_placeholder
order by q.quote_date, b.quantity;

-- re-quote chains (graph)
select * from graph.cypher(
  'MATCH (q:quotes)-[:REQUOTE_OF]->(p:quotes) RETURN p.quote_no, q.quote_no LIMIT 50',
  null, false);

-- semantic analog: nearest part descriptions
select p.part_no, p.description, s.score
from pgcontext.search('parts_desc','desc_emb', $1::pgcontext.vector, 20) s
join parts p on p.id = s.source_key;   -- score = cosine distance, 0 = identical
```

## Charts

- seaborn/matplotlib; colorblind-friendly palette; labeled axes with units;
  titles state the finding, not the metric name.
- Price-over-time: scatter of `unit_price` vs `quote_date` colored by qty band;
  note in the caption that prices are as-quoted nominal dollars (no inflation
  index) — 1990s analogs read low.

## Communication

- Answer in 1–3 sentences with the chart/table attached; include the SQL used.
- Flag data issues proactively (empty result → check join keys, grain,
  placeholders).
- If a finding is reusable (schema gotcha, useful query), update the
  `keller-quote-register` or `polygres` skill — don't open a PR for one-off
  results.
