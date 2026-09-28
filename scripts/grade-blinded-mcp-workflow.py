#!/usr/bin/env python3
"""Grade a separately blinded historical quote proposal and its scoped MCP trace."""

import argparse
from decimal import Decimal, DecimalException, ROUND_HALF_UP
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
from statistics import median


spec = importlib.util.spec_from_file_location('reissue_workflow_helpers', Path(__file__).with_name('grade-mcp-workflow.py'))
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)
dec, day, require = helpers.dec, helpers.day, helpers.require
VALIDATION = tuple(f'V{i}' for i in range(1, 6))
JUDGE = tuple(f'J{i}' for i in range(1, 6))
HEX = re.compile(r'[0-9a-f]{64}\Z')
CENT = Decimal('0.01')
PRICE_FIELDS = ('quote_no', 'item_no', 'quantity', 'unit_price', 'extended_price', 'quote_date',
                'letter_date', 'part_no', 'customer_id', 'source_price_field', 'price_basis', 'status')


def object_value(value, label):
    require(isinstance(value, dict), f'{label} must be an object')
    return value


def digest(value):
    return isinstance(value, str) and bool(HEX.fullmatch(value))


def private_scope(path, expected):
    require(isinstance(path, str) and Path(path).is_absolute() and '..' not in Path(path).parts,
            'unsafe scope path')
    target = Path(path)
    current = Path(target.anchor)
    for part in target.parts[1:]:
        current /= part
        info = current.lstat()
        require(not stat.S_ISLNK(info.st_mode) and info.st_uid in (os.getuid(), 0), 'unsafe scope path ownership/link')
        if current != target:
            require(stat.S_ISDIR(info.st_mode) and
                    (info.st_mode & 0o022 == 0 or info.st_uid == 0 and info.st_mode & stat.S_ISVTX),
                    'unsafe scope directory')
    parent = target.parent.stat()
    require(parent.st_uid == os.getuid() and parent.st_mode & 0o077 == 0, 'scope parent must be owner-private')
    info = target.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1 and
            info.st_mode & 0o177 == 0 and info.st_size <= 128 * 1024 * 1024, 'scope file must be owner-private')
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        require((opened.st_dev, opened.st_ino, opened.st_size) == (info.st_dev, info.st_ino, info.st_size),
                'scope changed while opening')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read()
        require(len(raw) == info.st_size and sha256(raw).hexdigest() == expected, 'scope SHA256 mismatch')
        return object_value(json.loads(raw), 'scope')
    finally:
        os.close(fd)


def amount_equal(a, b):
    try:
        return dec(a, 'amount') == dec(b, 'amount')
    except ValueError:
        return False


def row_matches(price, row):
    if not isinstance(price, dict) or not isinstance(price.get('row'), dict):
        return False
    if any(price.get(k) != row.get(k) for k in ('source_path', 'pdf_sha256', 'transcript_sha256')):
        return False
    return all(amount_equal(price['row'].get(k), row.get(k)) if k in ('quantity', 'unit_price', 'extended_price')
               else price['row'].get(k) == row.get(k) for k in PRICE_FIELDS)


def same_lines(items, expected):
    return isinstance(items, list) and len(items) == len(expected) and all(isinstance(x, dict) for x in items) and \
        sorted(x.get('line_id') for x in items if isinstance(x.get('line_id'), str)) == sorted(expected)


def validate_oracle(oracle):
    require(oracle.get('schema_version') == 1 and oracle.get('population') == 'blinded-historical-quote-workflow',
            'invalid blinded population/schema')
    request = object_value(oracle.get('request'), 'request')
    case_id = oracle.get('case_id')
    require(isinstance(case_id, str) and case_id.strip() and request.get('case_id') == case_id, 'case identity mismatch')
    for key in ('order_id', 'customer', 'customer_id', 'reviewer'):
        require(isinstance(request.get(key), str) and request[key].strip(), f'invalid request {key}')
    require(digest(request.get('corpus')), 'invalid corpus')
    cutoff = day(request.get('quote_date'), 'request date')
    charges = object_value(request.get('charges'), 'charges')
    require(set(charges) == {'shipping', 'tax'}, 'explicit shipping and tax required')
    for value in charges.values():
        dec(value, 'charge')
    lines = request.get('requested_lines')
    targets = oracle.get('targets')
    require(isinstance(lines, list) and bool(lines) and isinstance(targets, list) and len(targets) == len(lines),
            'invalid target mapping')
    ids = set()
    for line in lines:
        object_value(line, 'requested line')
        require(set(line) == {'line_id', 'part_no', 'description', 'quantity', 'uom', 'revision', 'notes'} and
                isinstance(line['line_id'], str) and line['line_id'].strip() and line['line_id'] not in ids and
                isinstance(line['part_no'], str) and line['part_no'].strip() and
                isinstance(line['description'], str) and isinstance(line['revision'], str) and
                isinstance(line['notes'], str) and type(line['quantity']) is int and line['quantity'] > 0 and
                line['uom'] == 'pieces', 'invalid requested line')
        ids.add(line['line_id'])
    require(same_lines(targets, ids), 'target line mapping mismatch')
    for target in targets:
        require(all(isinstance(target.get(k), str) and target[k].strip() for k in
                    ('quote_no', 'source_document')) and isinstance(target.get('item_no'), str) and
                digest(target.get('source_document_sha256')),
                'invalid target source identity')
        require(amount_equal(target.get('quantity'), next(x['quantity'] for x in lines if x['line_id'] == target['line_id'])),
                'target quantity mismatch')
        unit = dec(target.get('unit_price'), 'target unit', True)
        extension = dec(target.get('extended_price'), 'target extension', True)
        require(extension == (unit * dec(target['quantity'], 'target quantity', True)).quantize(CENT, rounding=ROUND_HALF_UP),
                'target printed extension inconsistent')
    scope_ref = object_value(oracle.get('scope'), 'scope reference')
    require(digest(scope_ref.get('sha256')), 'invalid scope SHA256')
    return request, targets, cutoff


def validate_scope(scope, oracle, request, targets, cutoff):
    require(scope.get('schema_version') == 1 and scope.get('case_id') == oracle['case_id'] and
            scope.get('corpus') == request['corpus'] and scope.get('quote_date') == request['quote_date'],
            'scope identity mismatch')
    excluded = scope.get('excluded_quote_nos')
    require(isinstance(excluded, list) and len(excluded) == len(set(excluded)) and
            all(isinstance(x, str) and x.strip() for x in excluded) and
            {x['quote_no'] for x in targets} <= set(excluded), 'scope does not exclude all target quotes')
    sr = object_value(scope.get('request'), 'scope request')
    for key in ('order_id', 'quote_date', 'customer', 'customer_id', 'reviewer'):
        require(sr.get(key) == request[key], f'scope request {key} mismatch')
    require(isinstance(sr.get('charges'), dict) and set(sr['charges']) == {'shipping', 'tax'} and
            all(amount_equal(sr['charges'][k], request['charges'][k]) for k in ('shipping', 'tax')),
            'scope charges mismatch')
    parts = sr.get('parts')
    expected = {x['line_id']: x for x in request['requested_lines']}
    require(same_lines(parts, expected) and all(x.get('part_no') == expected[x['line_id']]['part_no'] and
            x.get('quantity') == expected[x['line_id']]['quantity'] for x in parts), 'scope parts mismatch')
    rows = scope.get('eligible_prices')
    require(isinstance(rows, list) and isinstance(scope.get('allowed_files'), list), 'invalid scope evidence/files')
    target_documents = {target['source_document'] for target in targets}
    identities = set()
    documents = {}
    for row in rows:
        object_value(row, 'eligible row')
        require(all(isinstance(row.get(k), str) and row[k].strip() for k in
                    ('quote_no', 'part_no', 'customer_id', 'source_path')) and
                isinstance(row.get('item_no'), str) and
                row['source_path'] not in target_documents and
                row['quote_no'] not in excluded and row.get('source_price_field') in ('PRICE', 'QUOTEPRICE') and
                row.get('price_basis') == 'customer_quote_pdf' and row.get('status') == 'unknown' and
                digest(row.get('pdf_sha256')) and digest(row.get('transcript_sha256')),
                'invalid eligible source')
        require(all(day(row.get(k), k) < cutoff for k in ('quote_date', 'letter_date')) and
                (row.get('date_stamp') == '' or day(row.get('date_stamp'), 'date_stamp') < cutoff),
                'future/invalid eligible date')
        quantity = dec(row.get('quantity'), 'eligible quantity', True)
        unit = dec(row.get('unit_price'), 'eligible unit', True)
        extension = dec(row.get('extended_price'), 'eligible extension', True)
        require(extension == (unit * quantity).quantize(CENT, rounding=ROUND_HALF_UP), 'eligible extension inconsistent')
        identity = (row['quote_no'], row['item_no'], row['source_path'], quantity)
        require(identity not in identities and
                documents.get(row['source_path'], row['pdf_sha256']) == row['pdf_sha256'],
                'duplicate or conflicting eligible identity')
        identities.add(identity)
        documents[row['source_path']] = row['pdf_sha256']
    root = Path(__file__).resolve().parents[1]
    public_contracts = {'docs/pricing-evals-and-orders.md', 'estimator/src/order.ts', 'estimator/src/types.ts'}
    skills = {f'.agents/skills/{name}/SKILL.md' for name in (
        'keller-data-analysis', 'polygres', 'keller-estimator-evals',
        'keller-quote-estimator', 'keller-quote-register')}
    require(all(isinstance(p, str) and Path(p).is_absolute() and '..' not in Path(p).parts and
                Path(p).is_file() and Path(p).resolve() == Path(p) and Path(p).is_relative_to(root) and
                str(Path(p).relative_to(root)) in public_contracts | skills
                for p in scope['allowed_files']), 'invalid allowed public file')
    return rows


def price_diagnostics(request, targets, answer, events, grading_result):
    turns = []
    samples = []
    wanted = {line['line_id']: line for line in request['requested_lines']} if request is not None else {}
    target_by_id = {target['line_id']: target for target in targets} if targets is not None else {}
    for ordinal, event in enumerate(events if isinstance(events, list) else [], 1):
        if not isinstance(event, dict) or event.get('tool') != 'keller_quote':
            continue
        turn = {'audit_ordinal': ordinal, 'state': 'malformed', 'draft_id': None,
                'input_provenance': [], 'lines': []}
        turns.append(turn)
        inputs = event.get('inputs')
        try:
            submitted = json.loads(inputs.get('request')) if isinstance(inputs, dict) else None
        except (ValueError, TypeError):
            submitted = None
        parts = submitted.get('parts') if isinstance(submitted, dict) else None
        input_lines_match = same_lines(parts, wanted)
        for lid in wanted:
            matching = [part for part in parts if isinstance(part, dict) and part.get('line_id') == lid] if isinstance(parts, list) else []
            pricing = matching[0].get('pricing') if len(matching) == 1 else None
            input_identity_valid = input_lines_match and len(matching) == 1 and \
                matching[0].get('part_no') == wanted[lid]['part_no'] and \
                type(matching[0].get('quantity')) is int and matching[0]['quantity'] == wanted[lid]['quantity']
            if len(matching) != 1 or not isinstance(pricing, dict) and pricing is not None:
                provenance = {'line_id': lid, 'mode': 'unknown', 'pricing_inputs': None,
                              'input_identity_valid': input_identity_valid}
            elif pricing is None:
                provenance = {'line_id': lid, 'mode': 'automatic', 'pricing_inputs': None,
                              'input_identity_valid': input_identity_valid}
            else:
                method = pricing.get('method')
                provenance = {'line_id': lid, 'mode': {'unit_price': 'explicit_unit_price',
                              'cost_plus': 'cost_plus'}.get(method, 'unknown') if isinstance(method, str) else 'unknown',
                              'pricing_inputs': pricing, 'input_identity_valid': input_identity_valid}
            turn['input_provenance'].append(provenance)
        result = event.get('result')
        if result is None:
            turn['state'] = 'error' if event.get('error') else 'held'
            continue
        if not isinstance(result, dict):
            continue
        if result.get('isError'):
            turn['state'] = 'error'
            continue
        try:
            payload = helpers.parsed_tool(event)
            require(isinstance(payload, dict), 'quote payload is not an object')
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            continue
        turn['draft_id'] = payload.get('draft_id') if isinstance(payload.get('draft_id'), str) else None
        order = payload.get('order')
        lines = order.get('lines') if isinstance(order, dict) else None
        if not isinstance(lines, list):
            continue
        turn['state'] = ('success' if payload.get('state') == 'PRICED_REQUIRES_REVIEW' else
                         'unpriced' if any(isinstance(line, dict) and line.get('unit_price') is None for line in lines)
                         else 'held')
        for lid, requested in wanted.items():
            target = target_by_id[lid]
            item = {'line_id': lid, 'quantity': requested['quantity'], 'state': 'invalid',
                    'reason': None, 'target_unit_price': target['unit_price'],
                    'proposed_unit_price': None, 'unit_delta_usd': None,
                    'signed_percentage_error_pp': None, 'ape_pp': None,
                    'squared_unit_error_usd2': None, 'squared_percentage_error_pp2': None,
                    'expected_extension_usd': None, 'recorded_extension_usd': None,
                    'target_extension_usd': target['extended_price'],
                    'expected_minus_recorded_extension_usd': None,
                    'recorded_minus_target_extension_usd': None}
            turn['lines'].append(item)
            if not next(p['input_identity_valid'] for p in turn['input_provenance'] if p['line_id'] == lid):
                item['reason'] = 'missing, duplicate, or wrong input line identity'
                continue
            matches = [line for line in lines if isinstance(line, dict) and line.get('line_id') == lid]
            if len(matches) != 1 or len(lines) != len(wanted) or any(
                    not isinstance(line, dict) or not isinstance(line.get('line_id'), str) or
                    line['line_id'] not in wanted for line in lines):
                item['reason'] = 'missing, duplicate, or unexpected line identity'
                continue
            line = matches[0]
            part = line.get('part')
            if not isinstance(part, dict) or part.get('part_no') != requested['part_no'] or \
                    type(part.get('quantity')) is not int or part['quantity'] != requested['quantity']:
                item['reason'] = 'wrong part or quantity identity'
                continue
            if line.get('unit_price') is None or line.get('extended_price') is None:
                item['state'] = 'unpriced'
                item['reason'] = 'unit or recorded extension missing'
                continue
            try:
                proposed = dec(line['unit_price'], 'proposed unit', True)
                recorded = dec(line['extended_price'], 'recorded extension', True)
                target_unit = dec(target['unit_price'], 'target unit', True)
                target_extension = dec(target['extended_price'], 'target extension', True)
                delta = proposed - target_unit
                percentage = delta / target_unit * 100
                expected = (proposed * requested['quantity']).quantize(CENT, rounding=ROUND_HALF_UP)
                item.update(state='priced', reason=None, proposed_unit_price=str(proposed),
                            unit_delta_usd=str(delta), signed_percentage_error_pp=str(percentage),
                            ape_pp=str(abs(percentage)), squared_unit_error_usd2=str(delta ** 2),
                            squared_percentage_error_pp2=str(percentage ** 2),
                            expected_extension_usd=str(expected), recorded_extension_usd=str(recorded),
                            expected_minus_recorded_extension_usd=str(expected - recorded),
                            recorded_minus_target_extension_usd=str(recorded - target_extension))
                samples.append((delta, percentage))
            except (ValueError, TypeError, DecimalException, OverflowError) as exc:
                item['reason'] = str(exc)

    def stats(values, unit):
        if not values:
            return {'mean_signed_error': None, 'mean_absolute_error': None, 'median_absolute_error': None,
                    'mse': None, 'rmse': None, 'population_variance': None, 'population_sd': None,
                    'unit': unit}
        n = Decimal(len(values))
        mean = sum(values) / n
        mse = sum(value ** 2 for value in values) / n
        variance = sum((value - mean) ** 2 for value in values) / n
        return {'mean_signed_error': str(mean), 'mean_absolute_error': str(sum(map(abs, values)) / n),
                'median_absolute_error': str(median(map(abs, values))), 'mse': str(mse),
                'rmse': str(mse.sqrt()), 'population_variance': str(variance),
                'population_sd': str(variance.sqrt()), 'unit': unit}

    final_draft = answer.get('draft') if isinstance(answer, dict) else None
    final_state = _diagnostic_draft_state(final_draft, wanted)
    matches = [turn for turn in turns if isinstance(final_draft, dict) and turn['draft_id'] is not None and
               turn['draft_id'] == final_draft.get('draft_id') and
               isinstance(events[turn['audit_ordinal'] - 1].get('result'), dict) and
               not events[turn['audit_ordinal'] - 1]['result'].get('isError') and
               _diagnostic_payload(events[turn['audit_ordinal'] - 1]) == final_draft]
    decisions = answer.get('pricing_decisions') if isinstance(answer, dict) else None
    final_order = final_draft.get('order') if isinstance(final_draft, dict) else None
    adopted = final_state == 'priced_draft' and isinstance(final_order, dict) and \
        isinstance(final_order.get('lines'), list) and \
        isinstance(decisions, list) and same_lines(decisions, wanted) and all(
        isinstance(decision, dict) and amount_equal(decision.get('proposed_unit_price'),
        next((line.get('unit_price') for line in final_order['lines']
              if isinstance(line, dict) and line.get('line_id') == decision['line_id']), None))
        for decision in decisions)
    percentage_stats = stats([sample[1] for sample in samples], 'percentage points; squared metrics pp²')
    percentage_stats['mape_pp'] = percentage_stats['mean_absolute_error']
    percentage_stats['median_ape_pp'] = percentage_stats['median_absolute_error']
    return {'non_acceptance_diagnostic': True,
            'warning': 'Repeated calls and multiple lines within one attempt are descriptive, not independent cases or cohort accuracy.',
            'oracle_valid': request is not None,
            'grading_result': {'all_pass': grading_result['all_pass'],
                               'validation_passed': grading_result['validation_passed'],
                               'judge_passed': grading_result['judge_passed'],
                               'v_context': {key: grading_result['criteria'][key] for key in VALIDATION}},
            'final': {'state': final_state,
                      'draft_id': final_draft.get('draft_id') if isinstance(final_draft, dict) else None,
                      'linked_audit_ordinal': matches[0]['audit_ordinal'] if len(matches) == 1 else None,
                      'pricing_decisions_match_draft': adopted,
                      'pricing_decision_state': 'priced_proposal' if adopted else 'held_or_null',
                      'pricing_decisions': decisions},
            'turns': turns, 'finite_priced_line_count': len(samples),
            'unit_error_usd': stats([sample[0] for sample in samples], 'USD; squared metrics USD²'),
            'percentage_error_pp': percentage_stats}


def _diagnostic_payload(event):
    try:
        return helpers.parsed_tool(event)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None


def _diagnostic_draft_state(draft, wanted):
    if not isinstance(draft, dict):
        return 'held_or_null'
    order = draft.get('order')
    lines = order.get('lines') if isinstance(order, dict) else None
    if not same_lines(lines, wanted) or not isinstance(order.get('state'), str) or \
            draft.get('state') != order['state'] or draft['state'] not in ('PRICED_REQUIRES_REVIEW', 'BLOCKED'):
        return 'malformed_draft'
    for line in lines:
        part = line.get('part')
        wanted_part = wanted[line['line_id']]
        if not isinstance(part, dict) or part.get('part_no') != wanted_part['part_no'] or \
                type(part.get('quantity')) is not int or part['quantity'] != wanted_part['quantity']:
            return 'malformed_draft'
        if line.get('unit_price') is None or line.get('extended_price') is None:
            return 'unpriced_draft'
        try:
            dec(line['unit_price'], 'final unit', True)
            dec(line['extended_price'], 'final extension', True)
        except (ValueError, TypeError):
            return 'malformed_draft'
    return 'priced_draft' if draft['state'] == 'PRICED_REQUIRES_REVIEW' else 'held_draft'


def grade(oracle, answer, events, judge=None, artifact_snapshot=None, expected_hashes=None):
    reasons = {key: [] for key in VALIDATION + JUDGE}
    case_id = oracle.get('case_id') if isinstance(oracle, dict) else None
    request = targets = scope = rows = None
    try:
        request, targets, cutoff = validate_oracle(object_value(oracle, 'oracle'))
    except (ValueError, TypeError, KeyError, StopIteration) as exc:
        for key in VALIDATION:
            reasons[key].append(f'invalid oracle: {exc}')
    if request is not None:
        try:
            ref = oracle['scope']
            scope = private_scope(ref['path'], ref['sha256'])
            rows = validate_scope(scope, oracle, request, targets, cutoff)
        except (ValueError, OSError, TypeError, KeyError) as exc:
            reasons['V5'].append(f'invalid scope: {exc}')
            scope = None
    try:
        answer = object_value(answer, 'answer')
        require(answer.get('case_id') == case_id and isinstance(answer.get('evidence'), list) and
                isinstance(answer.get('pricing_decisions'), list) and
                all(isinstance(answer.get(k), str) for k in ('reviewer_handoff', 'customer_message')) and
                isinstance(answer.get('unresolved'), list) and
                all(isinstance(x, str) for x in answer['unresolved']), 'malformed answer')
        draft = object_value(answer.get('draft'), 'draft')
        require(isinstance(events, list) and events, 'missing audit')
        for event in events:
            require(isinstance(event, dict) and isinstance(event.get('tool'), str) and
                    isinstance(event.get('inputs'), dict) and 'result' in event, 'malformed audit')
    except (ValueError, TypeError) as exc:
        draft = None
        for key in VALIDATION:
            reasons[key].append(str(exc))
    if draft is not None and request is not None:
        if scope is not None:
            for i, event in enumerate(events, 1):
                if event.get('evaluation_scope_sha256') != oracle['scope']['sha256']:
                    reasons['V5'].append(f'audit row {i}: scope binding missing/mismatched')
        skills = [e for e in events if e['tool'] == 'read_file_pinned' and
                  isinstance(e['result'], dict) and not e['result'].get('isError') and
                  isinstance(e['result'].get('content'), list) and
                  any(isinstance(c, dict) and c.get('type') == 'text' and isinstance(c.get('text'), str) and
                      'keller-quote-estimator' in c['text'] for c in e['result']['content']) and
                  helpers.pinned_path(e['inputs'].get('file_path')) and
                  scope is not None and e['inputs'].get('file_path') in scope['allowed_files']]
        if not skills:
            reasons['V1'].append('canonical quote skill not actually read')
        quotes, observed = [], []
        for i, event in enumerate(events, 1):
            result = event['result']
            if result is None:
                continue
            if not isinstance(result, dict):
                reasons['V5'].append(f'audit row {i}: malformed result')
                continue
            if result.get('isError'):
                continue
            scoped_tools = {'read_file_pinned', 'au_diagnostics', 'au_type', 'keller_quote', 'keller_polygres'}
            if event['tool'] == 'tools/list':
                if set(result) != {'tools'} or not isinstance(result['tools'], list) or any(
                        not isinstance(tool, dict) or tool.get('name') not in scoped_tools
                        for tool in result['tools']):
                    reasons['V5'].append(f'audit row {i}: unscoped tools list')
                continue
            if event['tool'] not in scoped_tools or set(result) - {'content', 'isError'} or \
                    not isinstance(result.get('content'), list) or len(result['content']) != 1 or \
                    not isinstance(result['content'][0], dict) or set(result['content'][0]) != {'type', 'text'} or \
                    result['content'][0].get('type') != 'text' or \
                    not isinstance(result['content'][0].get('text'), str):
                reasons['V5'].append(f'audit row {i}: unscoped tool or alternate result channel')
                continue
            if event['tool'] == 'read_file_pinned' and (scope is None or
                    event['inputs'].get('file_path') not in scope['allowed_files']):
                reasons['V5'].append(f'audit row {i}: out-of-scope pinned file')
                continue
            if event['tool'] not in ('keller_quote', 'keller_polygres'):
                continue
            try:
                payload = helpers.parsed_tool(event)
                require(isinstance(payload, dict), 'tool payload not an object')
                if event['tool'] == 'keller_quote':
                    quotes.append((event, payload))
                    require(event['inputs'].get('corpus') == request['corpus'] and
                            (payload.get('corpus_id') is None or payload['corpus_id'] == request['corpus']) and
                            (not isinstance(payload.get('review'), dict) or
                             payload['review'].get('corpus_id') in (None, request['corpus'])),
                            'wrong quote corpus exposed')
                    for line in payload.get('order', {}).get('lines', []):
                        require(isinstance(line, dict), 'invalid quote line')
                        for analog in line.get('analogs', []):
                            pe = analog.get('price_evidence') if isinstance(analog, dict) else None
                            require(rows is not None and isinstance(pe, dict) and any(
                                analog.get('quote_no') == r['quote_no'] and analog.get('quote_date') == r['quote_date'] and
                                analog.get('letter_date') == r['letter_date'] and analog.get('date_stamp', '') == r['date_stamp'] and
                                analog.get('part_no') == r['part_no'] and analog.get('status') == r['status'] and
                                pe.get('price_basis') == 'customer_quote_pdf' and
                                pe.get('source_document') == r['source_path'] and
                                pe.get('source_document_sha256') == r['pdf_sha256'] and
                                pe.get('source_transcript_sha256') == r['transcript_sha256'] and
                                pe.get('source_price_field') == r['source_price_field'] for r in rows),
                                'heldout/future quote analog exposed')
                else:
                    action = event['inputs'].get('action')
                    require(payload.get('action') == action and
                            (action == 'corpora' or payload.get('corpus') == request['corpus']), 'wrong evidence corpus/action')
                    if action == 'prices':
                        require(payload.get('basis') == 'verified issued customer quotation PDF' and
                                payload.get('outcome') == 'unknown' and isinstance(payload.get('prices'), list),
                                'invalid verified prices response')
                        for price in payload['prices']:
                            require(isinstance(price, dict) and set(price) ==
                                    {'row', 'source_path', 'pdf_sha256', 'transcript_sha256'} and
                                    isinstance(price.get('row'), dict) and set(price['row']) == set(PRICE_FIELDS) and
                                    price['source_path'] not in {x['source_document'] for x in targets} and
                                    rows is not None and any(row_matches(price, r) for r in rows),
                                    'heldout/future price exposed')
                            observed.append(price)
                    elif action == 'search':
                        require(isinstance(payload.get('hits'), list), 'invalid search hits')
                        for hit in payload['hits']:
                            require(isinstance(hit, dict) and rows is not None and hit.get('kind') == 'quote' and
                                    set(hit) == {'source_path', 'page_number', 'page_sha256', 'pdf_sha256', 'kind', 'excerpt'} and
                                    digest(hit.get('page_sha256')) and
                                    any(hit.get('source_path') == r['source_path'] and
                                        hit.get('pdf_sha256') == r['pdf_sha256'] for r in rows),
                                    'heldout/future search hit exposed')
                    elif action == 'page':
                        require(rows is not None and payload.get('kind') == 'quote' and
                                payload.get('source_path') == event['inputs'].get('source_path') and
                                digest(payload.get('page_sha256')) and
                                any(payload.get('source_path') == r['source_path'] and
                                    payload.get('pdf_sha256') == r['pdf_sha256'] for r in rows),
                                'heldout/future page exposed')
                    elif action == 'corpora':
                        require(isinstance(payload.get('corpora'), list) and all(
                            isinstance(x, dict) and x.get('corpus') == request['corpus'] for x in payload['corpora']),
                            'wrong corpus exposed')
                    else:
                        raise ValueError('unexpected evidence action')
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                reasons['V5'].append(f'audit row {i}: {exc}')
        if not observed:
            reasons['V1'].append('no observed verified eligible price evidence')
        if not quotes:
            reasons['V1'].append('no successful quote response')
        else:
            event, final = quotes[-1]
            if final != draft or sum(payload == draft for _, payload in quotes) != 1:
                reasons['V1'].append('draft not unique last successful quote response')
            try:
                submitted = json.loads(event['inputs']['request'])
            except (KeyError, ValueError, TypeError):
                submitted = None
            if submitted != draft.get('order', {}).get('request') or event['inputs'].get('corpus') != request['corpus'] or \
                    event['inputs'].get('reviewer') != request['reviewer']:
                reasons['V1'].append('final quote input differs from draft/reviewer/corpus')
            if isinstance(artifact_snapshot, str):
                reasons['V1'].append(artifact_snapshot)
            elif artifact_snapshot != (final.get('order'), final.get('markdown'), final.get('review')):
                reasons['V1'].append('persisted UUID-bound artifacts differ from final response')
        order, review = draft.get('order'), draft.get('review')
        if not isinstance(order, dict) or not isinstance(review, dict):
            for key in ('V2', 'V3', 'V4'):
                reasons[key].append('missing native order/review')
        else:
            source = order.get('request') if isinstance(order.get('request'), dict) else {}
            for key in ('order_id', 'quote_date', 'customer', 'customer_id'):
                if source.get(key) != request[key] or (key != 'customer_id' and order.get(key) != request[key]):
                    reasons['V2'].append(f'{key} differs from frozen request')
            expected = {x['line_id']: x for x in request['requested_lines']}
            parts, lines = source.get('parts'), order.get('lines')
            for label, items in (('request parts', parts), ('priced lines', lines)):
                if not same_lines(items, expected):
                    reasons['V2'].append(f'{label}: omitted, added or duplicate line')
            parts = {x['line_id']: x for x in parts if isinstance(x, dict) and isinstance(x.get('line_id'), str)} if isinstance(parts, list) else {}
            lines = {x['line_id']: x for x in lines if isinstance(x, dict) and isinstance(x.get('line_id'), str)} if isinstance(lines, list) else {}
            subtotal = Decimal(0)
            target_by_id = {x['line_id']: x for x in targets}
            for lid, wanted in expected.items():
                part, line = parts.get(lid, {}), lines.get(lid, {})
                lp = line.get('part') if isinstance(line.get('part'), dict) else {}
                if part.get('part_no') != wanted['part_no'] or part.get('quantity') != wanted['quantity'] or \
                        lp.get('part_no') != wanted['part_no'] or lp.get('quantity') != wanted['quantity'] or \
                        line.get('line_id') != lid:
                    reasons['V2'].append(f'{lid}: part/quantity mismatch')
                try:
                    unit = dec(line.get('unit_price'), f'{lid} unit', True)
                    extension = dec(line.get('extended_price'), f'{lid} extension', True)
                    target_unit = dec(target_by_id[lid]['unit_price'], f'{lid} target', True)
                    if not target_unit * Decimal('0.8') <= unit <= target_unit * Decimal('1.2'):
                        reasons['V3'].append(f'{lid}: outside ±20% frozen target unit')
                    if extension != (unit * wanted['quantity']).quantize(CENT, rounding=ROUND_HALF_UP) or \
                            unit.as_tuple().exponent < -4 or extension.as_tuple().exponent < -2:
                        reasons['V3'].append(f'{lid}: unit/extension precision or rounding mismatch')
                    subtotal += extension
                except (ValueError, TypeError) as exc:
                    reasons['V3'].append(str(exc))
            for charge in ('shipping', 'tax'):
                try:
                    if not amount_equal(source['charges'][charge], request['charges'][charge]) or \
                            not amount_equal(order['charges'][charge], request['charges'][charge]):
                        reasons['V2'].append(f'{charge}: differs from explicit request')
                except (KeyError, TypeError):
                    reasons['V2'].append(f'{charge}: missing')
            if order.get('additional_charges') != [] or source.get('additional_charges', []) != [] or \
                    any(not isinstance(x.get('charges'), dict) or set(x['charges']) != {'shipping', 'tax'}
                        for x in (source, order)):
                reasons['V2'].append('unexpected fee/charge')
            try:
                total = dec(order.get('total'), 'total', True)
                if dec(order.get('subtotal'), 'subtotal') != subtotal or \
                        dec(order.get('priced_subtotal'), 'priced subtotal') != subtotal or \
                        total != subtotal + dec(request['charges']['shipping'], 'shipping') + dec(request['charges']['tax'], 'tax'):
                    reasons['V3'].append('subtotal/total mismatch')
            except (ValueError, TypeError) as exc:
                reasons['V3'].append(str(exc))
            identity = oracle.get('reviewer_identity')
            if not isinstance(identity, dict) or identity.get('kind') != 'human' or \
                    not isinstance(identity.get('source'), str) or not identity['source'].strip() or \
                    identity.get('name') != request['reviewer'] or draft.get('reviewer') != identity['name'] or \
                    review.get('reviewer') != identity['name']:
                reasons['V4'].append('missing named human reviewer proof')
            if any(x.get('state') != 'PRICED_REQUIRES_REVIEW' or x.get('requires_human_review') is not True
                   for x in (draft, order, review)) or draft.get('review_status') != 'PENDING_NAMED_HUMAN_REVIEW' or \
                    review.get('status') != 'PENDING_NAMED_HUMAN_REVIEW' or \
                    review.get('customer_release_authorized') is not False or \
                    draft.get('total') != order.get('total') or draft.get('blockers') != [] or \
                    order.get('blockers') != []:
                reasons['V4'].append('incomplete priced state or release safety')
            try:
                dec(order.get('total'), 'priced total', True)
                for charge in ('shipping', 'tax'):
                    dec(order['charges'][charge], f'priced {charge}')
            except (ValueError, KeyError, TypeError) as exc:
                reasons['V4'].append(str(exc))
            for lid in expected:
                try:
                    dec(lines.get(lid, {}).get('unit_price'), 'priced unit', True)
                    dec(lines.get(lid, {}).get('extended_price'), 'priced extension', True)
                except ValueError as exc:
                    reasons['V4'].append(f'{lid}: {exc}')
            if not same_lines(answer['pricing_decisions'], expected):
                reasons['V5'].append('pricing decisions line mapping mismatch')
            else:
                for decision in answer['pricing_decisions']:
                    if not all(isinstance(decision.get(k), str) and decision[k].strip() for k in
                               ('method', 'derivation')) or not isinstance(decision.get('uncertainties'), list) or \
                            not all(isinstance(x, str) for x in decision['uncertainties']) or \
                            not amount_equal(decision.get('proposed_unit_price'), lines.get(decision['line_id'], {}).get('unit_price')):
                        reasons['V5'].append(f'{decision["line_id"]}: incomplete/inconsistent pricing decision')
            citations = answer['evidence']
            identities = set()
            covered = set()
            for cite in citations:
                if not isinstance(cite, dict):
                    reasons['V5'].append('malformed citation')
                    continue
                lid = cite.get('line_id')
                source_keys = (cite.get('quote_no'), cite.get('item_no'), cite.get('source_path'))
                try:
                    quantity = dec(cite.get('quantity'), 'citation quantity', True)
                except ValueError:
                    quantity = None
                key = (lid, *source_keys, quantity)
                if lid not in expected or key in identities or quantity is None or \
                        not all(isinstance(x, str) and (x.strip() or i == 1)
                                for i, x in enumerate(source_keys)):
                    reasons['V5'].append('extra line/duplicate or malformed citation identity')
                    continue
                identities.add(key)
                covered.add(lid)
                if not isinstance(cite.get('admission_reason'), str) or not cite['admission_reason'].strip():
                    reasons['V5'].append(f'{lid}: incomplete or unrelated citation')
                matches = [r for r in (rows or []) if key == (lid, r['quote_no'], r['item_no'], r['source_path'],
                                                          dec(r['quantity'], 'eligible quantity', True)) and
                           cite.get('pdf_sha256') == r['pdf_sha256'] and cite.get('source_quote_date') == r['quote_date'] and
                           amount_equal(cite.get('quantity'), r['quantity']) and cite.get('part_no') == r['part_no'] and
                           amount_equal(cite.get('source_unit_price'), r['unit_price']) and
                           amount_equal(cite.get('source_printed_extension'), r['extended_price'])]
                if not matches or not any(any(row_matches(p, r) for p in observed) for r in matches):
                    reasons['V5'].append(f'{lid}: citation not eligible and observed verified price')
            if set(expected) - covered:
                reasons['V5'].append('missing cited prior break for priced line')
    if judge is None:
        for key in JUDGE:
            reasons[key].append('judge verdict missing')
    else:
        try:
            judge = object_value(judge, 'judge')
            require(judge.get('case_id') == case_id, 'judge case mismatch')
            hashes = object_value(judge.get('input_sha256'), 'judge hashes')
            require(set(hashes) == {'oracle', 'answer', 'audit'} and
                    isinstance(expected_hashes, dict) and set(expected_hashes) == set(hashes) and
                    all(digest(x) for x in hashes.values()) and hashes == expected_hashes,
                    'judge raw input hashes mismatch')
            criteria = judge.get('criteria')
            require(isinstance(criteria, list) and len(criteria) == 5 and
                    {x.get('id') for x in criteria if isinstance(x, dict)} == set(JUDGE), 'invalid judge criterion IDs')
            for item in criteria:
                require(isinstance(item, dict) and item.get('verdict') in ('pass', 'fail') and
                        isinstance(item.get('reason'), str) and item['reason'].strip() and
                        isinstance(item.get('evidence'), list) and bool(item['evidence']) and
                        all(isinstance(x, str) and x.strip() for x in item['evidence']), 'malformed judge verdict/reason/citations')
                if item['verdict'] == 'fail':
                    reasons[item['id']].append(item['reason'])
        except (ValueError, TypeError) as exc:
            for key in JUDGE:
                reasons[key].append(f'invalid judge: {exc}')
    vp = sum(not reasons[k] for k in VALIDATION)
    jp = sum(not reasons[k] for k in JUDGE)
    report = {'population': 'blinded-historical-quote-workflow', 'case_id': case_id,
            'criteria': {k: {'passed': not v, 'reasons': v} for k, v in reasons.items()},
            'validation_passed': vp, 'judge_passed': jp, 'validation_score': vp / 5,
            'judge_score': jp / 5, 'combined_score': (vp + jp) / 10,
            'all_pass': vp == jp == 5 and draft is not None and
            isinstance(draft, dict) and draft.get('state') == 'PRICED_REQUIRES_REVIEW'}
    report['price_diagnostics'] = price_diagnostics(request, targets, answer, events, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('oracle', 'answer', 'audit', 'out'):
        parser.add_argument(f'--{key}', required=True, type=Path)
    parser.add_argument('--judge', type=Path)
    args = parser.parse_args()
    raw = {}
    values = {}
    errors = []
    for key in ('oracle', 'answer', 'audit'):
        try:
            raw[key] = getattr(args, key).read_bytes()
            values[key] = helpers.trace(getattr(args, key), raw[key]) if key == 'audit' else json.loads(raw[key])
        except (ValueError, OSError, UnicodeError, TypeError) as exc:
            errors.append(f'{key}: {exc}')
            values[key] = [] if key == 'audit' else {}
    try:
        judge = json.loads(args.judge.read_bytes()) if args.judge else None
    except (ValueError, OSError, UnicodeError):
        judge = {}
    try:
        snapshot = helpers.artifacts(values['answer']['draft'], Path.home() / '.local/share/keller-quotes/drafts')
    except (ValueError, OSError, TypeError, KeyError, AttributeError) as exc:
        snapshot = f'artifact validation failed: {exc}'
    hashes = {k: sha256(v).hexdigest() for k, v in raw.items()}
    result = grade(values['oracle'], values['answer'], values['audit'], judge, snapshot, hashes)
    if errors:
        for key in VALIDATION:
            result['criteria'][key]['passed'] = False
            result['criteria'][key]['reasons'].extend(errors)
        result['validation_passed'] = 0
        result['validation_score'] = 0
        result['combined_score'] = result['judge_score'] / 2
        result['all_pass'] = False
        result['price_diagnostics']['grading_result']['validation_passed'] = 0
        result['price_diagnostics']['grading_result']['all_pass'] = False
    parent = args.out.parent
    require(parent.is_dir() and not parent.is_symlink() and parent.stat().st_uid == os.getuid() and
            parent.stat().st_mode & 0o077 == 0, 'output directory must be owner-private')
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
