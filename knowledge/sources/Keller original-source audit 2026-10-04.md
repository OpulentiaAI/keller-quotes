---
type: source::au-base-types
tldr: Dated aggregate source observations and pinned private receipts for Keller's historical case audit.
origin: Operator-held original-byte receipts, source-positive-v4 assessment and full-data-v1 bundle dated 2026-10-04.
---

This source note captures public-safe aggregate observations from the retained private originals and sealed audit.
It does not reproduce case identities, customer/part details, targets, prices or ledger entries, and it does not authenticate business semantics or independent human review.
The private build and original receipts were rechecked against their retained hashes before this documentation was written on 2026-10-07; their business observation date remains 2026-10-04.

## Register and case populations

The frozen internal-calculation register contains 179,608 quantity-break rows, 40,111 distinct quote/part records and 258 customer IDs.
Recorded quote dates run from 1994-07-25 through 2026-08-12.
The assessed diagnostic has 250 unique case IDs, 250 distinct quote numbers, 250 customer/part pairs and 63 customers.
Case coverage is not an estimate of source prevalence across the full register or live Keller RFQs.

| Source condition | Cases / 250 | Share |
|---|---:|---:|
| Verified internal calculation | 250 | 100.0% |
| Verified recorded customer amount | 107 | 42.8% |
| Target-comparable recorded customer amount | 105 | 42.0% |
| Original work-order candidate | 102 | 40.8% |
| Exact quote-level ERP pointer chain | 99 | 39.6% |
| Every mandatory historical evidence condition established | 0 | 0.0% |

Coverage rows overlap, and target-comparable amounts are a subset of recorded customer amounts.

| Mutually exclusive recorded-amount / ERP-pointer group | Cases / 250 | Share |
|---|---:|---:|
| Both recorded amount and ERP pointer | 40 | 16.0% |
| Recorded amount without ERP pointer | 67 | 26.8% |
| ERP pointer without recorded amount | 59 | 23.6% |
| Neither recorded amount nor ERP pointer | 84 | 33.6% |

Of the 40 cases with both sources, 39 have target-comparable amounts.
All 99 pointer cases also have work-order candidates, leaving three candidate-only cases.
The 107 document-supported cases have 102 consistent recorded chronologies and five inquiry/footer-date conflicts; consistency is not proof of original sending or historical version availability.
The 143 cases without selected document-price support consist of 139 without a selected document group at the target quantity and four with a document group but no target-quantity amount.

## Native order and cost observations

The original-byte audit found 724 quote/customer/part-matching SOMAST records across 101 cases, 954 four-table ERP pointer chains across 99 cases, and 853 distinct WOHEAD candidate records across 102 cases.
It found 1,981 linked WOBILL rows and 13 linked WOBOM rows, without a supplied complete closure enumeration or material/labor/outside/setup reconciliation.
Known nonplaceholder revision matches occur in 84 candidate cases; two candidate cases additionally match fabrication quantity.
Only 31 native-chain cases combine blank quote item, known nonplaceholder matching order/work-order revision and order quantity equal to the original target.
Earlier counts of 96 or 89 revision-matching candidate cases included blank or hyphen placeholders; the superseding audit preserves the corrected count of 84.
The earlier stronger native count of 34 included three hyphen-placeholder revision matches; its corrected count is 31.
These corrections do not change the 99-case pointer observation and do not establish complete manufacturing equivalence.

ORDERS and PURCHASE dictionary inspection retained 337 and 395 dictionary rows respectively.
Dictionary names and stored field values are metadata observations, not independently approved labor/setup semantics, accepted-order events or certified cross-table transaction snapshots.
The VENDQUOT original has 12,779 readable nonvoided rows; the latest recorded GOOD_UNTIL is 2026-07-03, and none has GOOD_UNTIL on or after 2026-10-04.
This does not prove that Keller has no newer quotes elsewhere.

## Retained provenance

| Private artifact | Whole-file SHA-256 |
|---|---|
| Full-data-v1 seal | `5c032ce97b4c84e1bea6f9fb1ecc79e7a78da08b6518a73a72713ea436e12f96` |
| Superseding native-order-pointer-audit-v2 | `dee2357a89bb80ab6a60e378f473072345b58460e41dbddd55a33f4e4b1157e7` |
| Original quote/job/vendor byte receipt | `ff717a353c3cad0bd545d24271e6e79f424703e6b498d94347e36382e8b5c312` |
| Original order/ledger byte receipt | `2a539d7d123d3916d41808e5cc9858d01dae2085d91b9367dffb7280c6bc036b` |
| Private full-evidence ZIP | `6c57956b129d33f38eca268a114ed874d3976665209e1ccb77b108197f77ab1f` |

The sealed bundle pins 441 inputs: 139 PDFs, 137 Markdown transcript artifacts, 149 JSON records/configurations, ten DBFs, four FPT memo files, one CSV and one JSONL.
Input-file counts include derivative proofs and configuration, not 441 independent business events; the separate original WOBILL/WOBOM audit is not converted into eligible ledger evidence by this inventory.
All eight original files in each byte receipt matched their recorded sizes and whole-file hashes during the documentation check.
Source kinds and local hashes establish retained bytes, not original authorship, trusted completeness, immutable storage or authenticated human identity.
