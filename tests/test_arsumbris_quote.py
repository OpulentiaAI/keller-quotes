"""Synthetic native quote-tool integration; no real database or customer data."""
import hashlib
import csv
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
CORPUS = "a" * 64
CSV = b"quote_no,item_no,quote_date,part_no,description,customer,quantity,unit_price,status\nQ-OLD,,2024-01-01,AXLE-101,Axle,Sample Shop,10,12.5,won\nQ-FUTURE,,2025-02-01,AXLE-101,Axle,Sample Shop,10,99,won\n"


class NativeQuoteTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-quote-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.python = self.home / "fixture-export"
        self.python.write_text("""#!/usr/bin/env python3
import hashlib, json, os, pathlib, sys
assert len(sys.argv) == 4 and sys.argv[1].endswith('/arsumbris/quote/export.py')
assert sys.argv[2] == '""" + CORPUS + """'
assert 'AI_GATEWAY_API_KEY' not in os.environ
assert 'TEAMVIEWER_PASSWORD' not in os.environ
assert 'TAILSCALE_AUTH_KEY' not in os.environ
assert 'POLYGRES_DIRECT_URL' in os.environ
data = """ + repr(CSV) + """
pathlib.Path(sys.argv[3]).write_bytes(data)
pathlib.Path(sys.argv[3]).chmod(0o600)
print(json.dumps({'sha256': hashlib.sha256(data).hexdigest(), 'rows': 2}))
""")
        self.python.chmod(0o700)

    def request(self, parts, charges=None):
        return {"order_id": "SYNTHETIC-1", "quote_date": "2024-06-01", "customer": "Sample Shop",
                "parts": parts, **({"charges": charges} if charges is not None else {})}

    def invoke(self, request, corpus=CORPUS, reviewer="Synthetic Reviewer", internal=None, artifact_change=None, no_database=False):
        env = {**os.environ, "HOME": str(self.home), "KELLER_PYTHON": str(self.python),
               "POLYGRES_DIRECT_URL": "secret-never-exposed", "AI_GATEWAY_API_KEY": "sentinel-key",
               "TEAMVIEWER_PASSWORD": "sentinel-remote", "TAILSCALE_AUTH_KEY": "sentinel-tailnet"}
        if no_database:
            env.pop('POLYGRES_DIRECT_URL', None)
        script = """import fs from 'node:fs';
import {syncBuiltinESMExports} from 'node:module';
const change = JSON.parse(process.argv[2]);
if (change) {
  const original = fs.readFileSync;
  let requestReads = 0;
  fs.readFileSync = function(path, ...args) {
    const data = original.call(this, path, ...args);
    if (change === 'file_after_pricing' && String(path).endsWith('/request.json') && requestReads++ > 0) {
      const request = JSON.parse(data.toString());
      request.parts[0].quantity += 1;
      return JSON.stringify(request);
    }
    if (String(path).endsWith('/output/order.json')) {
      const order = JSON.parse(data.toString());
      if (change === 'hash') order.provenance.request_sha256 = '0'.repeat(64);
      if (change === 'request') order.request.parts[0].quantity += 1;
      return JSON.stringify(order);
    }
    return data;
  };
  syncBuiltinESMExports();
}
const {createPlugin} = await import('./arsumbris/quote/tool.ts');
const result = await createPlugin({workspace: process.cwd()}).invoke(JSON.parse(process.argv[1]));
console.log(JSON.stringify(result));"""
        payload = {"corpus": corpus, "request": json.dumps(request) if not isinstance(request, str) else request,
                   "reviewer": reviewer, **(internal or {})}
        if corpus is None:
            payload.pop('corpus')
        completed = subprocess.run(["node", "--input-type=module", "-e", script, json.dumps(payload), json.dumps(artifact_change)], cwd=ROOT,
                                   env=env, capture_output=True, text=True, timeout=45, check=True)
        self.assertNotIn("secret-never-exposed", completed.stdout + completed.stderr)
        self.assertNotIn("sentinel-key", completed.stdout + completed.stderr)
        self.assertNotIn("sentinel-remote", completed.stdout + completed.stderr)
        self.assertNotIn("sentinel-tailnet", completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def artifacts(self, result):
        content = result["content"]
        directory = self.home / ".local/share/keller-quotes/drafts" / content["draft_id"]
        self.assertEqual(content["artifacts"]["order_json"], f'quote-draft:{content["draft_id"]}/order.json')
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        files = [directory / name for name in ("request.json", "corpus.csv", "output/order.json", "output/order.md", "output/review.json")]
        for file in files:
            self.assertTrue(file.is_file())
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(hashlib.sha256(files[1].read_bytes()).hexdigest(), content["corpus_sha256"])
        review = json.loads(files[4].read_text())
        self.assertEqual(review["reviewer"], "Synthetic Reviewer")
        self.assertFalse(review["customer_release_authorized"])
        self.assertEqual(content["artifacts"]["review_json"], f'quote-draft:{content["draft_id"]}/review.json')
        order, markdown = json.loads(files[2].read_text()), files[3].read_text()
        request_sha = hashlib.sha256(files[0].read_bytes()).hexdigest()
        self.assertEqual(order['request'], json.loads(files[0].read_text()))
        self.assertEqual(order['provenance']['request_sha256'], request_sha)
        self.assertEqual(review['request_sha256'], request_sha)
        self.assertEqual(content['request_sha256'], request_sha)
        self.assertEqual(content["order"], order)
        self.assertEqual(content["markdown"], markdown)
        self.assertEqual(content["review"], review)
        return order, markdown

    def test_uploaded_engineering_should_cost_survives_native_and_local_handoffs(self):
        self.check_uploaded_engineering_should_cost()

    def test_purchase_increment_survives_retention_native_review_and_local_inbox(self):
        self.check_uploaded_engineering_should_cost(purchase_increment=2)

    def test_exact_conversion_ratio_survives_retention_native_review_and_local_inbox(self):
        self.check_uploaded_engineering_should_cost(conversion_ratio=True)

    def check_uploaded_engineering_should_cost(self, purchase_increment=None, conversion_ratio=False):
        original = json.loads((ROOT / 'estimator/examples/should-cost-intake.json').read_text())
        expected_total, expected_cost = 120, 90
        if conversion_ratio:
            part = original['parts'][0]
            part['quantity'] = part['uom']['original_quantity'] = 3
            part['pricing']['cost_basis']['routing'][0]['process_quantity'] = 3
            material = part['pricing']['cost_basis']['components'][0]
            del material['original_units_per_quantity_unit']
            material.update(conversion_ratio={'original_units': 2, 'quantity_units': 3},
                            quantity=3, minimum_quantity=0, purchase_increment=1)
            assumption = 'SYNTHETIC: two purchased blanks per three pieces; exact ratio, no separate scrap'
            material['assumptions'] = [assumption]
            next(f for f in part['geometry'] if f['id'] == 'material')['value'] = assumption
            expected_total, expected_cost = 226.67, 170
        if purchase_increment is not None:
            material = original['parts'][0]['pricing']['cost_basis']['components'][0]
            material['purchase_increment'] = purchase_increment
            assumption = 'SYNTHETIC: buy packs of two blanks; charge the unused blank to this line, no inventory credit'
            material['assumptions'] = [assumption]
            next(f for f in original['parts'][0]['geometry'] if f['id'] == 'material')['value'] = assumption
            expected_total, expected_cost = 173.33, 130
        original_path = self.home / 'original.json'
        original_path.write_text(json.dumps(original))
        uploads = []
        for name in ('drawing', 'worksheet'):
            path = self.home / (name + '.txt')
            path.write_text('SYNTHETIC evidence only: ' + name +
                            ('; two original blanks per three pieces, buy whole blanks'
                             if name == 'worksheet' and conversion_ratio else '') +
                            (f'; purchase_increment={purchase_increment} blanks, no inventory credit'
                             if name == 'worksheet' and purchase_increment is not None else ''))
            uploads.append({'id': name, 'path': str(path), 'media_type': 'text/plain'})
        manifest = self.home / 'uploads.json'
        manifest.write_text(json.dumps(uploads))
        retained = subprocess.run(['node', str(ROOT / 'estimator/node_modules/tsx/dist/cli.mjs'),
            str(ROOT / 'estimator/src/intake-cli.ts'), str(original_path),
            '--attachments', str(manifest), '--operator', 'Synthetic Operator'],
            env={**os.environ, 'HOME': str(self.home)}, capture_output=True, text=True, check=True, timeout=20)
        request_path = Path(json.loads(retained.stdout)['request_path'])
        directory = request_path.parent
        self.addCleanup(lambda: directory.chmod(0o700))
        request = json.loads(request_path.read_text())
        result = self.invoke(request, corpus=None, no_database=True)
        self.assertFalse(result.get('isError'), result)
        content = result['content']
        self.assertEqual(content['total'], expected_total)
        self.assertEqual(content['order']['request'], request)
        line = content['order']['lines'][0]
        self.assertEqual(line['analogs'], [])
        self.assertEqual(line['cost_breakdown']['estimated_line_cost']['base'], expected_cost)
        self.assertEqual(line['cost_breakdown']['estimated_line_margin_pct']['base'], 25)
        if conversion_ratio:
            self.assertEqual(line['cost_breakdown']['components'][0]['priced_quantity'], 2)
            self.assertEqual(line['cost_breakdown']['supplied_basis']['components'][0]['conversion_ratio'],
                             {'original_units': 2, 'quantity_units': 3})
        if purchase_increment is not None:
            material_cost = line['cost_breakdown']['components'][0]
            self.assertEqual(material_cost['priced_quantity'], 2)
            self.assertEqual(material_cost['total_cost']['base'], 80)
            self.assertEqual(material_cost['purchase_rounding'], {
                'original_unit': 'blank', 'quantity_before_increment': 1, 'increment': 2})
        basis = request['parts'][0]['pricing']['cost_basis']
        self.assertEqual(line['cost_breakdown']['supplied_basis'], basis)
        worksheet = next(a for a in request['intake']['attachments'] if a['id'] == 'worksheet')
        for group in ('components', 'routing', 'not_applicable'):
            for item in basis[group]:
                self.assertEqual(item['sources'][0]['sha256'], worksheet['sha256'])
                self.assertEqual(item['sources'][0]['locator'], worksheet['locator'])
        self.assertEqual(line['part']['geometry'], request['parts'][0]['geometry'])
        self.assertFalse(content['review']['customer_release_authorized'])
        self.assertEqual(content['review']['request_sha256'], content['order']['provenance']['request_sha256'])
        # Existing local inbox must route the same fully supplied order to the order builder.
        workspace = self.home / 'queue'
        (workspace / 'inbox').mkdir(parents=True)
        (workspace / 'inbox/rfq.json').write_text(json.dumps(request))
        cycle = subprocess.run(['node', str(ROOT / 'scripts/keller-local.mjs'), 'cycle', '--workspace', str(workspace)],
            env={**os.environ, 'HOME': str(self.home)}, capture_output=True, text=True, check=True, timeout=20)
        self.assertEqual(json.loads(cycle.stdout)['drafted'], ['rfq.json'])
        local = json.loads(next((workspace / 'drafts').glob('*.json')).read_text())
        self.assertEqual(local['request'], request)
        self.assertEqual(local['total'], expected_total)
        self.assertIsNone(local['provenance']['register_sha256'])
        # Corruption or a changed original quantity cannot be authorized by replaying locators.
        changed = json.loads(json.dumps(request))
        changed['parts'][0]['quantity'] = 2
        self.assertTrue(self.invoke(changed, corpus=None, no_database=True).get('isError'))
        changed = json.loads(json.dumps(request))
        changed['parts'][0]['pricing']['cost_basis']['components'][0]['purchase_increment'] = 3
        self.assertTrue(self.invoke(changed, corpus=None, no_database=True).get('isError'))
        cost_attachment = directory / 'attachment-1.bin'
        original_cost_bytes = cost_attachment.read_bytes()
        cost_attachment.chmod(0o600)
        cost_attachment.write_text('changed synthetic worksheet bytes')
        cost_attachment.chmod(0o400)
        self.assertTrue(self.invoke(request, corpus=None, no_database=True).get('isError'))
        cost_attachment.chmod(0o600)
        cost_attachment.write_bytes(original_cost_bytes)
        cost_attachment.chmod(0o400)
        attachment = directory / 'attachment-0.bin'
        attachment.chmod(0o600)
        attachment.write_text('changed synthetic bytes')
        attachment.chmod(0o400)
        self.assertTrue(self.invoke(request, corpus=None, no_database=True).get('isError'))

    def test_native_cost_sources_cannot_claim_missing_retained_or_pending_upload_evidence(self):
        request = json.loads((ROOT / 'estimator/examples/should-cost-intake.json').read_text())
        part = request['parts'][0]
        part.pop('source_evidence')
        part.pop('geometry')
        basis = part['pricing']['cost_basis']
        for group in ('components', 'routing', 'not_applicable'):
            for item in basis[group]:
                item.pop('engineering_fact_ids', None)
                for source in item['sources']:
                    source.update(sha256=hashlib.sha256(b'SYNTHETIC external estimate').hexdigest(),
                                  locator='synthetic-external:reviewed-estimate#row=1')
        positive = self.invoke(request, corpus=None, no_database=True)
        self.assertFalse(positive.get('isError'), positive)
        self.assertEqual(positive['content']['total'], 120)
        self.assertFalse(positive['content']['review']['customer_release_authorized'])
        self.assertEqual(positive['content']['order']['lines'][0]['cost_breakdown']['assertion_status'],
                         'supplied_not_authenticated')
        receipts = set(self.home.rglob('review.json'))
        self.assertTrue(receipts)
        for group in ('components', 'routing', 'not_applicable'):
            for locator in ('upload:worksheet',
                            'keller-intake:00000000-0000-0000-0000-000000000000/attachment-0.bin'):
                with self.subTest(group=group, locator=locator):
                    invalid = json.loads(json.dumps(request))
                    invalid['parts'][0]['pricing']['cost_basis'][group][0]['sources'][0]['locator'] = locator
                    result = self.invoke(invalid, corpus=None, no_database=True)
                    self.assertTrue(result.get('isError'), result)
                    self.assertEqual(set(self.home.rglob('review.json')), receipts)

    def test_unreferenced_engineering_conflict_blocks_native_order_completion(self):
        request = self.request([{'line_id': 'cost', 'part_no': 'SYNTHETIC', 'quantity': 1,
            'pricing': {'method': 'unit_price', 'unit_price': 120, 'reason': 'synthetic proposal'},
            'geometry': [{'id': 'revision', 'field': 'drawing_revision', 'value': 'Explicit revision conflict',
                          'source_ids': [], 'applicability': 'conflict'}]}], {'shipping': 0, 'tax': 0})
        result = self.invoke(request, corpus=None, no_database=True)
        self.assertFalse(result.get('isError'), result)
        content = result['content']
        self.assertEqual(content['state'], 'BLOCKED')
        self.assertIsNone(content['total'])
        self.assertEqual(content['order']['lines'][0]['unit_price'], 120)
        self.assertIn('explicit engineering conflict', ' '.join(content['order']['blockers']))
        self.assertFalse(content['review']['customer_release_authorized'])
        self.assertTrue(content['review']['requires_human_review'])

    def test_cost_estimate_review_dates_must_follow_their_source_without_requiring_current_prices(self):
        original = json.loads((ROOT / 'estimator/examples/should-cost-intake.json').read_text())
        part = original['parts'][0]
        del part['geometry'], part['source_evidence']
        basis = part['pricing']['cost_basis']
        for entry in basis['components'] + basis['routing'] + basis['not_applicable']:
            entry.pop('engineering_fact_ids', None)
            for source in entry['sources']:
                source.update(sha256='a' * 64, locator='synthetic-cost:worksheet')
        for method in ('should_cost', 'cost_plus'):
            request = json.loads(json.dumps(original))
            pricing = request['parts'][0]['pricing']; pricing['method'] = method
            if method == 'cost_plus':
                pricing.update(material_per_unit=40, labor_per_unit=20, outside_per_unit=0, setup_total=30)
            baseline = self.invoke(request, corpus=None, no_database=True)
            self.assertFalse(baseline.get('isError'), baseline)
            self.assertEqual(baseline['content']['total'], 120)
            for group in ('components', 'routing', 'not_applicable'):
                with self.subTest(method=method, group=group):
                    invalid = json.loads(json.dumps(request))
                    source = invalid['parts'][0]['pricing']['cost_basis'][group][0]['sources'][0]
                    source['source_date'] = '2024-05-31'; source['approval']['date'] = '2024-05-30'
                    receipts = set(self.home.rglob('review.json'))
                    held = self.invoke(invalid, corpus=None, no_database=True)
                    self.assertTrue(held.get('isError'), held)
                    self.assertNotIn('artifacts', held['content'])
                    self.assertNotIn('order', held['content'])
                    self.assertNotIn('review', held['content'])
                    self.assertEqual(set(self.home.rglob('review.json')), receipts)
            source = pricing['cost_basis']['components'][0]['sources'][0]
            source.update(source_class='supplier_quote', source_date='2020-01-01', effective_date='2020-01-01',
                          expires_date='2020-01-31', captured_date='2026-10-09')
            source['approval']['date'] = request['quote_date']
            source['approval']['reason'] = 'Synthetic review of a historical estimate, not current supplier validity'
            estimate = self.invoke(request, corpus=None, no_database=True)
            self.assertFalse(estimate.get('isError'), estimate)
            content = estimate['content']; cost = content['order']['lines'][0]['cost_breakdown']
            self.assertEqual(content['total'], 120)
            self.assertEqual(cost['estimated_line_margin_pct']['base'], 25)
            self.assertEqual(cost['supplied_basis']['components'][0]['sources'][0], source)
            self.assertFalse(content['review']['customer_release_authorized'])
            self.assertTrue(content['review']['requires_human_review'])
            self.assertEqual(content['review']['request_sha256'], content['order']['provenance']['request_sha256'])
            self.assertIn('not guaranteed actual costs or current buy prices', ' '.join(cost['warnings']))
            source['status'] = 'current'; del source['approval']
            receipts = set(self.home.rglob('review.json'))
            held = self.invoke(request, corpus=None, no_database=True)
            self.assertTrue(held.get('isError'), held)
            self.assertEqual(set(self.home.rglob('review.json')), receipts)

    def test_register_free_costs_need_no_database_and_still_bind_review(self):
        request = self.request([{'line_id': 'cost', 'part_no': 'SYNTHETIC', 'quantity': 1,
            'pricing': {'method': 'cost_plus', 'material_per_unit': 40, 'labor_per_unit': 20,
                        'outside_per_unit': 0, 'setup_total': 30, 'margin_pct': 25, 'reason': 'synthetic worksheet'}}],
            {'shipping': 0, 'tax': 0})
        result = self.invoke(request, corpus=None, no_database=True)
        self.assertFalse(result.get('isError'), result)
        content = result['content']
        self.assertEqual(content['total'], 120)
        self.assertIsNone(content['corpus_sha256'])
        self.assertIsNone(content['corpus_id'])
        self.assertEqual(content['source_rows'], 0)
        self.assertEqual(content['order']['request'], request)
        self.assertEqual(content['order']['lines'][0]['analogs'], [])
        self.assertFalse(content['review']['customer_release_authorized'])
        self.assertEqual(content['review']['reviewer'], 'Synthetic Reviewer')
        directory = self.home / '.local/share/keller-quotes/drafts' / content['draft_id']
        self.assertFalse((directory / 'corpus.csv').exists())
        self.assertEqual(content['request_sha256'], hashlib.sha256((directory / 'request.json').read_bytes()).hexdigest())
        for change in ('hash', 'request', 'file_after_pricing'):
            self.assertTrue(self.invoke(request, corpus=None, no_database=True, artifact_change=change).get('isError'))
        # Invalid costs, mixed requests and explicit corpus selection may not take this path.
        request['parts'].append({'line_id': 'history', 'part_no': 'OTHER', 'quantity': 1})
        self.assertTrue(self.invoke(request, corpus=None, no_database=True).get('isError'))
        request['parts'].pop()
        request['parts'][0]['pricing']['margin_pct'] = 100
        self.assertTrue(self.invoke(request, corpus=None, no_database=True).get('isError'))

    def test_changed_request_during_export_cannot_reach_review(self):
        with self.python.open('a') as script:
            script.write("""
request_path = pathlib.Path(sys.argv[3]).parent / 'request.json'
request = json.loads(request_path.read_text())
request['parts'][0]['quantity'] = 999
request_path.write_text(json.dumps(request))
""")
        request = self.request([{'line_id': 'cost', 'part_no': 'SYNTHETIC', 'quantity': 3,
            'pricing': {'method': 'cost_plus', 'material_per_unit': 1, 'labor_per_unit': .1,
                        'outside_per_unit': 0, 'setup_total': 1, 'margin_pct': 20, 'reason': 'synthetic worksheet'}}],
            {'shipping': 0, 'tax': 0})
        self.assertTrue(self.invoke(request).get('isError'))
        self.assertEqual(list((self.home / '.local/share/keller-quotes/drafts').iterdir()), [])

    def test_artifact_hash_and_embedded_request_must_match_caller(self):
        request = self.request([{'line_id': 'explicit', 'part_no': 'SYNTHETIC', 'quantity': 3,
            'pricing': {'method': 'unit_price', 'unit_price': 2, 'reason': 'synthetic proposal'}}],
            {'shipping': 0, 'tax': 0})
        for change in ('hash', 'request', 'file_after_pricing'):
            with self.subTest(change=change):
                self.assertTrue(self.invoke(request, artifact_change=change).get('isError'))
                self.assertEqual(list((self.home / '.local/share/keller-quotes/drafts').iterdir()), [])

    def test_request_binding_uses_canonical_json_not_wire_format(self):
        request = self.request([{'line_id': 'line', 'part_no': 'SYNTHETIC', 'quantity': 2,
            'pricing': {'method': 'unit_price', 'unit_price': 3, 'reason': 'synthetic proposal'}}],
            {'shipping': 0, 'tax': 0})
        request['customer_id'] = 'SYNTHETIC-λ'
        result = self.invoke(json.dumps(request, indent=2, ensure_ascii=True))
        self.assertFalse(result.get('isError'))
        order, _ = self.artifacts(result)
        self.assertEqual(order['request'], request)

    def test_explicit_operator_amount_and_costs_stay_internal(self):
        parts = [{"line_id": "explicit", "part_no": "SYNTHETIC", "quantity": 3,
                  "pricing": {"method": "unit_price", "unit_price": 0.3333, "reason": "operator proposal"}},
                 {"line_id": "cost", "part_no": "SYNTHETIC-2", "quantity": 3,
                  "pricing": {"method": "cost_plus", "material_per_unit": 1, "labor_per_unit": .1,
                              "outside_per_unit": 0, "setup_total": 1, "margin_pct": 20, "reason": "synthetic cost sheet"}}]
        result = self.invoke(self.request(parts, {"shipping": 0, "tax": 0}))
        self.assertFalse(result.get("isError"))
        content = result["content"]
        self.assertEqual(content["state"], "PRICED_REQUIRES_REVIEW")
        self.assertEqual(content["review_status"], "PENDING_NAMED_HUMAN_REVIEW")
        self.assertEqual(content["reviewer"], "Synthetic Reviewer")
        self.assertTrue(content["requires_human_review"])
        self.assertEqual(set(content["price_bases"]), {"explicit_unit_price", "cost_build_up"})
        self.assertIn("not current", content["warning"])
        order, markdown = self.artifacts(result)
        self.assertEqual(order["total"], content["total"])
        self.assertIn("human review required", markdown)
        self.assertNotIn(str(self.home), json.dumps(content))

    def test_unmatched_and_missing_charges_stay_blocked_without_total(self):
        result = self.invoke(self.request([{"line_id": "unknown", "part_no": "UNMATCHED", "quantity": 2}]))
        self.assertEqual(result["content"]["state"], "BLOCKED")
        self.assertIsNone(result["content"]["total"])
        order, markdown = self.artifacts(result)
        self.assertIsNone(order["subtotal"])
        self.assertIsNone(order["total"])
        self.assertIn("line unknown is unpriced", result["content"]["blockers"])
        self.assertIn("Total: —", markdown)

    def test_historical_draft_uses_cutoff_and_warns_of_unknown_outcome(self):
        result = self.invoke(self.request([{"line_id": "history", "part_no": "AXLE-101", "quantity": 10}],
                                                  {"shipping": 0, "tax": 0}))
        self.assertEqual(result["content"]["state"], "PRICED_REQUIRES_REVIEW")
        self.assertIn("historical_analog", result["content"]["price_bases"])
        self.assertIn("unknown outcome", result["content"]["warning"])
        order, _ = self.artifacts(result)
        self.assertEqual([item["quote_no"] for item in order["lines"][0]["analogs"]], ["Q-OLD"])

    def test_scoped_register_filters_before_pricing_and_reconciles_verified_breaks(self):
        fields = ["quote_no", "item_no", "quantity", "unit_price", "extended_price", "quote_date",
                  "letter_date", "date_stamp", "part_no", "customer_id", "source_document",
                  "source_document_sha256", "source_transcript_sha256", "source_price_field",
                  "price_basis", "status", "quote_letter", "description", "customer"]
        allowed = {"quote_no": "ALLOWED", "item_no": "", "quantity": "3.000", "unit_price": "1.23456",
                   "extended_price": "3.70", "quote_date": "2023-01-01", "letter_date": "2023-01-01",
                   "date_stamp": "", "part_no": "SYNTHETIC-P", "customer_id": "C",
                   "source_document": "synthetic/allowed.pdf", "source_document_sha256": "b" * 64,
                   "source_transcript_sha256": "c" * 64, "source_price_field": "PRICE",
                   "price_basis": "customer_quote_pdf", "status": "unknown", "quote_letter": "L-A",
                   "description": "Synthetic Part", "customer": "Synthetic Customer"}
        forbidden = {**allowed, "quote_no": "EXCLUDED", "item_no": "2", "unit_price": "9.99999",
                     "extended_price": "30.00", "quote_date": "2024-01-01", "letter_date": "2024-01-01",
                     "source_document": "synthetic/excluded.pdf", "source_document_sha256": "d" * 64,
                     "source_transcript_sha256": "e" * 64, "quote_letter": "L-E"}
        second_break = {**allowed, "quantity": "5.00", "unit_price": "1.11111", "extended_price": "5.56"}
        request = self.request([{"line_id": "line", "part_no": "SYNTHETIC-P", "quantity": 3}],
                               {"shipping": 0, "tax": 0})
        request["customer_id"] = "C"
        scope = {"schema_version": 1, "case_id": "synthetic", "corpus": CORPUS,
                 "quote_date": request["quote_date"], "excluded_quote_nos": ["EXCLUDED"],
                 "request": {**request, "reviewer": "Synthetic Reviewer"},
                 "eligible_prices": [], "allowed_files": []}
        def eligible(row):
            return {key: row[source] for key, source in {
                "source_path": "source_document", "pdf_sha256": "source_document_sha256",
                "transcript_sha256": "source_transcript_sha256"}.items()} | {
                    key: row[key] for key in ("quote_no", "item_no", "quantity", "unit_price", "extended_price",
                                         "quote_date", "letter_date", "date_stamp", "part_no", "customer_id",
                                         "source_price_field", "price_basis", "status")}
        scope["eligible_prices"] = [eligible(allowed), eligible(second_break)]
        private = self.home / "scope"
        private.mkdir(mode=0o700)
        scope_path = private / "scope.json"
        def write_scope():
            scope_path.write_text(json.dumps(scope))
            scope_path.chmod(0o600)
            return {"evaluation_scope_path": str(scope_path),
                    "evaluation_scope_sha256": hashlib.sha256(scope_path.read_bytes()).hexdigest()}
        def export(rows):
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fields)
            writer.writeheader()
            writer.writerows(rows)
            data = output.getvalue().encode()
            self.python.write_text("""#!/usr/bin/env python3
import hashlib, json, pathlib, sys
data = """ + repr(data) + """
pathlib.Path(sys.argv[3]).write_bytes(data)
pathlib.Path(sys.argv[3]).chmod(0o600)
print(json.dumps({'sha256': hashlib.sha256(data).hexdigest(), 'rows': """ + str(len(rows)) + """}))
""")
        export([forbidden, allowed, second_break])
        binding = write_scope()
        full = self.invoke(request)["content"]
        self.assertEqual(full["order"]["lines"][0]["analogs"][0]["quote_no"], "EXCLUDED")
        first = self.invoke(request, internal=binding)
        self.assertFalse(first.get("isError"), first)
        content = first["content"]
        self.assertEqual(content["state"], "PRICED_REQUIRES_REVIEW")
        self.assertEqual(content["source_rows"], 2)
        self.assertEqual(content["evaluation_scope_sha256"], binding["evaluation_scope_sha256"])
        self.assertEqual([a["quote_no"] for a in content["order"]["lines"][0]["analogs"]], ["ALLOWED"])
        folder = self.home / ".local/share/keller-quotes/drafts" / content["draft_id"]
        original = folder / "corpus.csv"
        filtered = folder / "scoped-corpus.csv"
        self.assertEqual(original.stat().st_mode & 0o777, 0o600)
        self.assertEqual(filtered.stat().st_mode & 0o777, 0o600)
        self.assertIn(b"EXCLUDED", original.read_bytes())
        self.assertNotIn(b"EXCLUDED", filtered.read_bytes())
        self.assertIn(b"1.23456", filtered.read_bytes())
        self.assertIn(b"1.11111", filtered.read_bytes())
        self.assertNotIn(b"description", filtered.read_bytes())
        self.assertNotIn(b"L-A", filtered.read_bytes())
        self.assertNotIn("evidence", content["order"]["lines"][0]["analogs"][0])
        self.assertIn("evidence", full["order"]["lines"][0]["analogs"][0])
        self.assertEqual(content["corpus_sha256"], hashlib.sha256(filtered.read_bytes()).hexdigest())
        self.assertEqual(content["order"]["provenance"]["register_sha256"], content["corpus_sha256"])
        self.assertEqual(json.loads((folder / "output/review.json").read_text())["source_rows"], 2)

        export([{**forbidden, "unit_price": "2.22222", "extended_price": "6.67"}, allowed, second_break])
        second = self.invoke(request, internal=binding)["content"]
        self.assertEqual(second["corpus_sha256"], content["corpus_sha256"])
        self.assertEqual(second["order"]["lines"][0]["unit_price"], content["order"]["lines"][0]["unit_price"])
        self.assertEqual(second["order"]["lines"][0]["analogs"], content["order"]["lines"][0]["analogs"])

        export([forbidden, {**allowed, "description": "unfrozen engineering", "customer": "unfrozen name", "quote_letter": "unfrozen letter"}, second_break])
        isolated = self.invoke(request, internal=binding)["content"]
        self.assertEqual(isolated["corpus_sha256"], content["corpus_sha256"])
        self.assertEqual(isolated["order"]["lines"], content["order"]["lines"])

        scope["eligible_prices"] = []
        empty = self.invoke(request, internal=write_scope())["content"]
        self.assertEqual(empty["state"], "BLOCKED")
        self.assertIsNone(empty["order"]["lines"][0]["unit_price"])
        self.assertEqual(empty["source_rows"], 0)
        scope["eligible_prices"] = [eligible(allowed), eligible(second_break)]
        binding = write_scope()
        for change in [{"evaluation_scope_sha256": "0" * 64},
                       {"evaluation_scope_path": str(scope_path), "evaluation_scope_sha256": "bad"}]:
            self.assertTrue(self.invoke(request, internal={**binding, **change})["isError"])
        scope["eligible_prices"][0]["unit_price"] = "7.77777"
        self.assertTrue(self.invoke(request, internal=write_scope())["isError"])
        scope["eligible_prices"] = [eligible(allowed), eligible(second_break),
                                    {**eligible(allowed), "quote_no": "MISSING"}]
        self.assertTrue(self.invoke(request, internal=write_scope())["isError"])
        scope["eligible_prices"] = [eligible(allowed), eligible(second_break)]
        self.assertTrue(self.invoke(request, reviewer="Wrong Reviewer", internal=write_scope())["isError"])

    def test_invalid_inputs_fail_without_export_or_artifacts(self):
        for request, corpus, reviewer in [
            ("{", CORPUS, "Person"),
            (self.request([{"line_id": "x", "part_no": "P", "quantity": 1,
                            "pricing": {"method": "unit_price", "unit_price": 1}}]), CORPUS, "Person"),
            (self.request([{"line_id": "x", "part_no": "P", "quantity": 1}]), "bad", "Person"),
            (self.request([{"line_id": "x", "part_no": "P", "quantity": 1}]), CORPUS, " "),
        ]:
            with self.subTest(corpus=corpus, reviewer=reviewer):
                result = self.invoke(request, corpus, reviewer)
                self.assertTrue(result["isError"])
                self.assertNotIn("artifacts", result["content"])
        storage = self.home / ".local/share/keller-quotes/drafts"
        self.assertEqual(list(storage.iterdir()) if storage.exists() else [], [])

    def test_incomplete_scope_binding_fails_before_export(self):
        marker = self.home / "export-was-called"
        self.python.write_text("#!/usr/bin/env python3\nfrom pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n")
        scope_path = self.home / "not-a-scope.json"
        request = self.request([{"line_id": "line", "part_no": "SYNTHETIC", "quantity": 3}],
                               {"shipping": 0, "tax": 0})
        for internal in [
            {"evaluation_scope_path": ""},
            {"evaluation_scope_sha256": "a" * 64},
            {"evaluation_scope_path": "", "evaluation_scope_sha256": "a" * 64},
            {"evaluation_scope_path": str(scope_path)},
            {"evaluation_scope_path": str(scope_path), "evaluation_scope_sha256": ""},
            {"evaluation_scope_path": str(scope_path), "evaluation_scope_sha256": "bad"},
            {"evaluation_scope_path": str(scope_path), "evaluation_scope_sha256": "a" * 64},
        ]:
            with self.subTest(internal=internal):
                self.assertTrue(self.invoke(request, internal=internal)["isError"])
                self.assertFalse(marker.exists())
        storage = self.home / ".local/share/keller-quotes/drafts"
        self.assertEqual(list(storage.iterdir()) if storage.exists() else [], [])

    def test_private_storage_rejects_insecure_existing_directory(self):
        storage = self.home / ".local/share/keller-quotes/drafts"
        storage.mkdir(parents=True, mode=0o700)
        storage.chmod(0o755)
        result = self.invoke(self.request([{"line_id": "x", "part_no": "P", "quantity": 1}]))
        self.assertTrue(result["isError"])
        self.assertEqual(list(storage.iterdir()), [])

    def test_node_children_receive_no_credentials(self):
        probe = self.home / 'probe.cjs'
        observed = self.home / 'child-environments.jsonl'
        probe.write_text("""const child = require('node:child_process');
const fs = require('node:fs');
const util = require('node:util');
const original = child.execFile;
function inspect(binary, args, options) {
  if (binary === process.execPath) {
    const env = options.env;
    fs.appendFileSync('""" + str(observed) + """', JSON.stringify({
      args: args.slice(0, 2), names: Object.keys(env)
    }) + '\\n');
    for (const key of ['POLYGRES_DIRECT_URL', 'AI_GATEWAY_API_KEY',
      'TEAMVIEWER_PASSWORD', 'TAILSCALE_AUTH_KEY', 'NODE_OPTIONS']) {
      if (key in env) throw new Error('child credential leaked');
    }
  }
}
child.execFile = function(binary, args, options, callback) {
  inspect(binary, args, options);
  return original.call(this, binary, args, options, callback);
};
child.execFile[util.promisify.custom] = function(binary, args, options) {
  inspect(binary, args, options);
  return original[util.promisify.custom](binary, args, options);
};
""")
        with patch.dict(os.environ, {'NODE_OPTIONS': f'--require={probe}'}):
            result = self.invoke(self.request([{"line_id": "x", "part_no": "P", "quantity": 1,
                                                "pricing": {"method": "unit_price", "unit_price": 1,
                                                            "reason": "fixture"}}], {"shipping": 0, "tax": 0}))
        self.assertFalse(result.get('isError'), (result, observed.read_text() if observed.exists() else 'probe did not run'))
        children = [json.loads(line) for line in observed.read_text().splitlines()]
        self.assertEqual(len(children), 2)
        self.assertTrue(all('POLYGRES_DIRECT_URL' not in child['names'] for child in children))

    def test_unknown_export_failure_is_redacted(self):
        self.python.write_text('#!/usr/bin/env python3\nimport sys\nprint("secret-never-exposed", file=sys.stderr)\nsys.exit(1)\n')
        result = self.invoke(self.request([{"line_id": "x", "part_no": "P", "quantity": 1}]))
        self.assertTrue(result['isError'])
        self.assertEqual(result['content'], {'error': 'Invalid request or verified offline draft unavailable; no quote was released'})
        self.assertEqual(list((self.home / '.local/share/keller-quotes/drafts').iterdir()), [])

    @unittest.skipUnless(importlib.util.find_spec('psycopg'), 'requires configured psycopg interpreter')
    def test_guarded_export_uses_existing_readonly_cli_and_redacts_credentials(self):
        spec = importlib.util.spec_from_file_location("quote_export", ROOT / "arsumbris/quote/export.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        url = "postgresql://user:secret@db.example.org/" + module.EXPECTED_DATABASE
        run = subprocess.CompletedProcess([], 0, '{"rows":2,"sha256":"digest"}\n', "")
        with patch.dict(os.environ, {"POLYGRES_DIRECT_URL": url, "AI_GATEWAY_API_KEY": "secret-gateway"}, clear=True), \
             patch.object(module.subprocess, "run", return_value=run) as invoke:
            self.assertEqual(module.export(CORPUS, "/private/output.csv"), run.stdout)
        args, kwargs = invoke.call_args
        self.assertEqual(args[0][2:7], ["export", "--expected-database", module.EXPECTED_DATABASE,
                                         "--corpus", CORPUS])
        self.assertEqual(args[0][-2:], ["--out", "/private/output.csv"])
        config = module.conninfo_to_dict(kwargs["env"]["POLYGRES_DIRECT_URL"])
        self.assertEqual(config["sslmode"], "verify-full")
        self.assertEqual(config["sslrootcert"], module.CA_CERT)
        self.assertIn("default_transaction_read_only=on", config["options"])
        self.assertNotIn("PGSERVICE", kwargs["env"])
        with patch.dict(os.environ, {"POLYGRES_DIRECT_URL": "postgresql://user:secret@db.example.org/wrong"}, clear=True), \
             self.assertRaises(ValueError):
            module.export(CORPUS, "/private/output.csv")


if __name__ == "__main__":
    unittest.main()
