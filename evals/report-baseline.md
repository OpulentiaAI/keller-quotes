# Estimator eval — 2026-09-21T14:35:49.966Z

register: `quotes.csv` (179608 rows) · evalset: `evals/evalset.jsonl` · jev: off

| metric | value |
|---|---|
| cases | 250 |
| coverage (priced) | 98.8% |
| median APE | 46.3% |
| mean APE | 122.1% |
| within ±10% | 15.8% |
| within ±20% | 24.3% |
| within ±50% | 52.6% |
| mean confidence | 0.50 |

## Worst misses

| case | actual | predicted | APE | method | analogs |
|---|---|---|---|---|---|
| 0033540|@75 | $0.7623 | $36.6412 | 4707% | median_won | 5 |
| 0054710|@1000 | $0.6500 | $19.5477 | 2907% | median_won | 5 |
| 0028712|@15 | $10.2958 | $167.7808 | 1530% | median_won | 5 |
| 0056325|@250 | $3.7605 | $37.0496 | 885% | median_won | 5 |
| 0015819|@100 | $1.4900 | $14.0074 | 840% | median_won | 5 |
| 0058300|@500 | $0.8645 | $7.1709 | 729% | median_won | 5 |
| 0053429|2@50 | $2.1038 | $16.9638 | 706% | median_won | 5 |
| 0017895|@250 | $3.1200 | $22.2983 | 615% | median_won | 5 |
| 0054128|@100000 | $0.3282 | $2.3151 | 605% | median_won | 5 |
| 0056226|@500 | $2.3080 | $14.7639 | 540% | median_won | 5 |
