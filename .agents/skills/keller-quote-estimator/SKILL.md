---
name: keller-quote-estimator
description: Turn a C. Keller Mfg. pricing request (parts, quantities, materials, drawing references) into a priced quote using the FabriTRAK quote register and TypeSafe Jev analog ranking. Use when asked to quote, estimate, or price parts against Keller quote history.
---

# Keller Quote Estimator

Estimator pipeline: pricing request → historical analog retrieval → Jev rank/screen/strategy → qty-break interpolation → priced quote draft. It lives in `estimator/` and resolves the default quote register (`quotes.csv` at repo root) relative to its module, independently of the working directory.

## What's needed from the user

- The **pricing request**: parts list with whatever the customer supplied — part numbers, descriptions, quantities, material/finish, drawing numbers, RFQ number, customer name. Accept it in any form (text, image, spreadsheet); normalize into `request.json`.
- Optionally: whether an authorized Jev ranking call should run. It needs `AI_GATEWAY_API_KEY` in the environment (org secret). Without it the estimator still works — deterministic fallback, `status_basis` reads `fallback:*`. The committed offline evaluation does not establish a Jev accuracy improvement; compare matched runs before claiming one. The scheduled draft worker always runs offline.

## Procedure

1. **Normalize the request** into the input schema. Write a `request.json`:

   ```json
   {
     "customer": "IPEG, INC.",
     "customer_id": "000317",
     "rfq_no": "RFQ-123",
     "parts": [
       {
         "part_no": "96-0085-00",
         "description": "RETAINER PLATE",
         "quantity": 250,
         "material": "PAINTLOK",
         "drawing_ref": "RAL-0214",
         "notes": "anything the customer said that isn't a column"
       }
     ]
   }
   ```

   - `quantity` is required per part. Everything else is optional but each field improves retrieval: `part_no` (exact match is strongest), `drawing_ref` (matches `DRAWING_NO` in the register — this is how customer drawings/visualizations connect), `material`/`finish` (matched against `MATERIAL` and `COMMENT` text), `description` (token overlap).
   - If the request arrives as an image or PDF drawing, extract part numbers, descriptions, materials, and quantities first (read it directly, or OCR via the vision tooling available to you), then fill the JSON. The estimator does not do vision.

2. **Run the estimator** from the repo root:

   ```bash
   cd estimator && npm ci   # first time only
   cd ..
   ./estimator/node_modules/.bin/tsx estimator/src/cli.ts request.json --csv quote.csv
   ```

   Add `--offline` to force the deterministic path even when `AI_GATEWAY_API_KEY` is set. Output: full `QuoteEstimate` JSON to stdout (lines with `unit_price`, `extended_price`, `price_low`/`price_high` (weighted p25/p75), `confidence`, `method`, `analogs` with Jev probabilities, `warnings`), plus a flat CSV if `--csv` is given.

3. **Require human review before external delivery**. The estimator drafts; an agent may assist, but a named human must approve pricing and scope:
   - `warnings` flag "no historical analogs", "no won-quote analogs", or rejected analogs — price those lines manually.
   - `confidence` < ~0.3 means thin or old evidence — flag for estimator review, don't send as-is.
   - Prices are **as-quoted historically** — there is no inflation normalization. A line priced off 1990s analogs will show a wide `price_low`–`price_high` band and low confidence; sanity-check against current material/labor rates.
   - `analogs[]` shows exactly which historical quotes drove each price — cite them to the customer if asked "how did you get this number".

4. **Hand off** the draft (JSON/CSV), preserving `analogs` and `warnings` for the human reviewer. Only the existing human-approved delivery channel may send a customer quote; the estimator and scheduled worker do not authorize delivery.

## Anti-patterns

- Do not edit `quotes.csv` or treat it as mutable — it is the frozen extract. Corrections go through re-extraction from FabriTRAK.
- Do not bypass the analog layer and hand Jev (or any model) the whole register to "pick a price" — Jev only ranks/screens prevalidated candidates; it never generates prices.
- Do not evaluate a historical quote with the source quote visible to retrieval — pass `EstimateOptions.exclude` through the library or use the eval harness, which also supplies the quote-time cutoff. The live CLI does not expose these options; see the evals skill.
- Do not treat `status: "open"` as lost — QUOTEHN is empty; open includes silently-lost history.

## Verification

```bash
# from the repository root, after cd estimator && npm ci && cd ..
node scripts/verify.mjs
```
