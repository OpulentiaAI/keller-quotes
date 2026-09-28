#!/usr/bin/env python3
"""Strict, local grader for frozen source-backed MCP quote reissues."""

import argparse
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from uuid import UUID


CENT = Decimal('0.01')
VALIDATION = ('V1', 'V2', 'V3', 'V4', 'V5')
JUDGE = ('J1', 'J2', 'J3', 'J4', 'J5')
SKILL = '.agents/skills/keller-quote-estimator/SKILL.md'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def obj(value, label):
    require(isinstance(value, dict), f'{label} must be an object')
    return value


def dec(value, label, positive=False):
    require(not isinstance(value, bool) and isinstance(value, (str, int, float)), f'{label} must be numeric')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f'{label} must be numeric') from exc
    require(result.is_finite() and (result > 0 if positive else result >= 0), f'{label} must be finite and {"positive" if positive else "nonnegative"}')
    return result


def same_amount(left, right):
    try:
        return dec(left, 'source amount') == dec(right, 'oracle amount')
    except ValueError:
        return False


def day(value, label):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), f'{label} must be an ISO date')
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f'{label} must be an ISO date') from exc


def check(condition, label, failures):
    if not condition:
        failures.append(label)


def pinned_path(value):
    if isinstance(value, str):
        return value == SKILL or value.endswith('/' + SKILL)
    if isinstance(value, dict):
        return any(pinned_path(item) for item in value.values())
    if isinstance(value, list):
        return any(pinned_path(item) for item in value)
    return False


def parsed_json(event):
    content = event['result']['content']
    require(len(content) == 1, f'{event["tool"]}: expected one JSON text result')
    try:
        return json.loads(content[0]['text'])
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{event["tool"]}: invalid JSON result') from exc


def parsed_tool(event):
    value = parsed_json(event)
    require(isinstance(value, dict), f'{event["tool"]}: JSON result must be an object')
    return value.get('content') if isinstance(value.get('content'), dict) else value


def trace(path, raw=None):
    events = []
    for number, line in enumerate((raw.decode('utf-8') if raw is not None else Path(path).read_text()).splitlines(), 1):
        try:
            event = obj(json.loads(line), f'audit line {number}')
            require(all(key in event for key in ('startedAt', 'completedAt', 'tool', 'inputs', 'result')), f'audit line {number}: missing fields')
            start = datetime.fromisoformat(event['startedAt'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(event['completedAt'].replace('Z', '+00:00'))
            require(start.tzinfo is not None and end.tzinfo is not None and start <= end, f'audit line {number}: invalid timestamps')
            require(isinstance(event['tool'], str) and event['tool'] and isinstance(event['inputs'], dict), f'audit line {number}: invalid call')
            if event['result'] is not None:
                result = obj(event['result'], f'audit line {number} result')
                if event['tool'] == 'tools/list':
                    require(isinstance(result.get('tools'), list) and
                            all(isinstance(tool, dict) and isinstance(tool.get('name'), str)
                                for tool in result['tools']), f'audit line {number}: invalid tools list')
                else:
                    require(isinstance(result.get('content'), list) and result['content'] and
                            all(isinstance(c, dict) and c.get('type') == 'text' and isinstance(c.get('text'), str)
                                and c['text'] for c in result['content']) and
                            isinstance(result.get('isError', False), bool), f'audit line {number}: invalid MCP result')
                    if event['tool'] in ('keller_polygres', 'keller_quote', 'keller_sources') and not result.get('isError'):
                        parsed_tool(event)
                    elif event['tool'] != 'read_file_pinned' and not result.get('isError'):
                        parsed_json(event)
            else:
                require(isinstance(event.get('error'), str) and event['error'], f'audit line {number}: missing result/error')
            events.append(event)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError(f'malformed audit line {number}: {exc}') from exc
    require(events, 'empty audit')
    return events


def artifacts(response, root):
    identifier = response.get('draft_id')
    require(isinstance(identifier, str) and str(UUID(identifier)) == identifier, 'missing/invalid draft UUID')
    refs = obj(response.get('artifacts'), 'artifact references')
    for key, filename in (('order_json', 'order.json'), ('order_markdown', 'order.md'), ('review_json', 'review.json')):
        require(refs.get(key) == f'quote-draft:{identifier}/{filename}', f'{key} reference mismatch')
    directory = root / identifier / 'output'
    for path in (root / identifier, directory):
        require(path.is_dir() and not path.is_symlink(), f'missing/unsafe artifact directory: {path.name}')
    values = []
    for filename in ('order.json', 'order.md', 'review.json'):
        path = directory / filename
        require(path.exists() and stat.S_ISREG(path.lstat().st_mode), f'missing/unsafe artifact: {filename}')
        values.append(path.read_text())
    try:
        order, review = json.loads(values[0]), json.loads(values[2])
    except ValueError as exc:
        raise ValueError('malformed persisted order/review') from exc
    return order, values[1], review


def grade(oracle, answer, events, judge=None, artifact_snapshot=None, expected_hashes=None):
    case_id = obj(oracle, 'oracle').get('case_id')
    reasons = {key: [] for key in VALIDATION + JUDGE}
    request = obj(oracle.get('request'), 'oracle request')
    require(case_id == request.get('case_id') and isinstance(case_id, str), 'oracle case identity mismatch')
    try:
        answer = obj(answer, 'answer')
        require(answer.get('case_id') == case_id, 'answer case_id mismatch')
        require(isinstance(answer.get('reviewer_handoff'), str) and isinstance(answer.get('customer_message'), str)
                and isinstance(answer.get('unresolved'), list) and all(isinstance(x, str) for x in answer['unresolved'])
                and isinstance(answer.get('evidence'), list), 'malformed answer fields')
        draft = obj(answer.get('draft'), 'answer draft')
        require(isinstance(events, list) and events, 'missing audit')
        for event in events:
            require(isinstance(event, dict) and 'result' in event and 'tool' in event, 'malformed audit')
    except (ValueError, TypeError) as exc:
        for key in VALIDATION:
            reasons[key].append(str(exc))
        draft = None

    if draft is not None:
        skills = [event for event in events if event['tool'] == 'read_file_pinned' and
                  pinned_path(event['inputs']) and isinstance(event['result'], dict) and
                  not event['result'].get('isError') and isinstance(event['result'].get('content'), list) and
                  any(item.get('type') == 'text' and isinstance(item.get('text'), str) and item['text'].strip()
                      for item in event['result']['content'] if isinstance(item, dict))]
        check(bool(skills), 'canonical quote skill was not read through read_file_pinned', reasons['V1'])
        quotes = [event for event in events if event['tool'] == 'keller_quote' and isinstance(event['result'], dict)
                  and not event['result'].get('isError')]
        check(bool(quotes), 'no successful logged keller_quote call', reasons['V1'])
        prices = [event for event in events if event['tool'] == 'keller_polygres' and
                  event['inputs'].get('action') == 'prices' and isinstance(event['result'], dict)
                  and not event['result'].get('isError')]
        check(bool(prices), 'no successful verified prices retrieval', reasons['V1'])
        observed = []
        for event in prices:
            payload = parsed_tool(event)
            if (payload.get('action') == 'prices' and payload.get('corpus') == request.get('corpus') and
                    payload.get('basis') == 'verified issued customer quotation PDF' and isinstance(payload.get('prices'), list)):
                observed.extend(payload['prices'])
        check(bool(observed), 'no verified issued-price rows in selected corpus observed', reasons['V1'])
        response = None
        if quotes:
            responses = [parsed_tool(event) for event in quotes]
            check(responses[-1] == draft and sum(item == draft for item in responses) == 1,
                  'answer.draft is not the unambiguous final successful keller_quote response', reasons['V1'])
            response = responses[-1]
            inputs = quotes[-1]['inputs']
            try:
                submitted = json.loads(inputs['request'])
            except (KeyError, ValueError, TypeError):
                submitted = None
            check(submitted == draft.get('order', {}).get('request') and
                  inputs.get('reviewer') == request.get('reviewer') and inputs.get('corpus') == request.get('corpus'),
                  'logged quote inputs differ from order/reviewer/corpus', reasons['V1'])
            if isinstance(artifact_snapshot, str):
                reasons['V1'].append(artifact_snapshot)
            elif artifact_snapshot != (response.get('order'), response.get('markdown'), response.get('review')):
                reasons['V1'].append('persisted order/markdown/review missing or differs from MCP response')
        order = draft.get('order')
        review = draft.get('review')
        if not isinstance(order, dict) or not isinstance(review, dict):
            for key in ('V2', 'V3', 'V4', 'V5'):
                reasons[key].append('missing native order/review')
        else:
            source = order.get('request', {})
            if not isinstance(source, dict):
                source = {}
            for field in ('order_id', 'quote_date', 'customer', 'customer_id'):
                check(source.get(field) == request.get(field) and
                      (field == 'customer_id' or order.get(field) == request.get(field)),
                      f'{field} differs from frozen request', reasons['V2'])
            expected = request.get('requested_lines')
            require(isinstance(expected, list) and isinstance(oracle.get('lines'), list) and len(expected) == len(oracle['lines']),
                    'invalid oracle line mapping')
            parts, lines, evidence = source.get('parts'), order.get('lines'), answer['evidence']
            for label, items, key in (('request parts', parts, 'V2'), ('priced lines', lines, 'V2'), ('evidence', evidence, 'V5')):
                check(isinstance(items, list) and len(items) == len(expected) and
                      sorted(str(item.get('line_id')) for item in items if isinstance(item, dict)) ==
                      sorted(row['line_id'] for row in expected), f'{label}: omitted, added or duplicate line', reasons[key])
            parts = {p['line_id']: p for p in parts if isinstance(p, dict) and isinstance(p.get('line_id'), str)} if isinstance(parts, list) else {}
            lines = {p['line_id']: p for p in lines if isinstance(p, dict) and isinstance(p.get('line_id'), str)} if isinstance(lines, list) else {}
            evidence = {p['line_id']: p for p in evidence if isinstance(p, dict) and isinstance(p.get('line_id'), str)}
            subtotal = Decimal(0)
            expected_total = Decimal(0)
            for wanted, row in zip(expected, oracle['lines']):
                lid = wanted['line_id']
                part, line, cite = parts.get(lid, {}), lines.get(lid, {}), evidence.get(lid, {})
                line_part = line.get('part') if isinstance(line.get('part'), dict) else {}
                check(all(part.get(k) == wanted[k] for k in ('line_id', 'part_no', 'quantity')) and
                      all(line_part.get(k) == wanted[k] for k in ('part_no', 'quantity')) and
                      line.get('line_id') == lid and row.get('part_no') == wanted['part_no'] and
                      row.get('quote_no') == wanted['quote_no'] and str(row.get('quantity')) == str(wanted['quantity']) and
                      row.get('customer_id') == request.get('customer_id') and row.get('customer') == request.get('customer') and
                      wanted.get('uom') in ('piece', 'pieces'),
                      f'{lid}: identity, quantity, customer or UOM mismatch', reasons['V2'])
                try:
                    unit = dec(line.get('unit_price'), f'{lid} unit', True)
                    original = dec(row.get('unit_price'), f'{lid} source unit', True)
                    ext = dec(line.get('extended_price'), f'{lid} extension', True)
                    printed = dec(row.get('extended_price'), f'{lid} printed extension', True)
                    check(original * Decimal('.8') <= unit <= original * Decimal('1.2'), f'{lid}: outside ±20% source unit guard', reasons['V3'])
                    check(abs(ext - printed) <= CENT, f'{lid}: extension differs from printed source by over one cent', reasons['V3'])
                    check(ext == (unit * wanted['quantity']).quantize(CENT, rounding=ROUND_HALF_UP),
                          f'{lid}: unit and extension do not reconcile', reasons['V3'])
                    check(unit.as_tuple().exponent >= -4 and ext.as_tuple().exponent >= -2,
                          f'{lid}: unsupported precision', reasons['V3'])
                    subtotal += ext
                    expected_total += printed
                except (ValueError, TypeError, KeyError) as exc:
                    reasons['V3'].append(str(exc))
                check(all(cite.get(k) == v for k, v in {
                    'line_id': lid, 'quote_no': row.get('quote_no'), 'part_no': row.get('part_no'),
                    'quantity': wanted['quantity'], 'source_path': row.get('source_document'),
                    'pdf_sha256': row.get('source_document_sha256'), 'source_quote_date': row.get('quote_date'),
                    'rev': row.get('rev')}.items()) and isinstance(cite.get('admission_reason'), str)
                      and bool(cite['admission_reason'].strip()) and
                      same_amount(cite.get('source_unit_price'), row.get('unit_price')) and
                      same_amount(cite.get('source_printed_extension'), row.get('extended_price')),
                      f'{lid}: citation differs from independent source', reasons['V5'])
                check(any(isinstance(entry, dict) and entry.get('source_path') == row.get('source_document') and
                          entry.get('pdf_sha256') == row.get('source_document_sha256') and
                          isinstance(entry.get('row'), dict) and
                          all(k in entry['row'] and entry['row'][k] == row.get(k) for k in
                              ('quote_no', 'item_no', 'quote_date', 'letter_date', 'part_no', 'customer_id',
                               'source_price_field', 'price_basis', 'status')) and
                          all(k in entry['row'] and same_amount(entry['row'][k], row.get(k)) for k in
                              ('quantity', 'unit_price', 'extended_price'))
                          for entry in observed), f'{lid}: verified price row not observed through MCP', reasons['V5'])
                try:
                    check(day(row.get('quote_date'), f'{lid} source quote date') < day(request.get('quote_date'), 'request date') and
                          (not row.get('letter_date') or day(row['letter_date'], f'{lid} letter date') < day(request['quote_date'], 'request date')),
                          f'{lid}: source event is not prior to request', reasons['V5'])
                except ValueError as exc:
                    reasons['V5'].append(str(exc))
            for charge in ('shipping', 'tax'):
                try:
                    amount = dec(request['charges'][charge], charge)
                    check(dec(source['charges'][charge], f'request {charge}') == amount and
                          dec(order['charges'][charge], f'order {charge}') == amount,
                          f'{charge}: differs from explicit frozen amount', reasons['V2'])
                except (KeyError, TypeError, ValueError) as exc:
                    reasons['V2'].append(f'{charge}: {exc}')
            check(order.get('additional_charges') == [] and source.get('additional_charges', []) == [],
                  'unexpected additional charges', reasons['V2'])
            try:
                check(expected_total + dec(request['charges']['shipping'], 'shipping') +
                      dec(request['charges']['tax'], 'tax') ==
                      dec(oracle.get('expected_total_exact_source'), 'oracle exact source total'),
                      'oracle source total does not reconcile with printed extensions and charges', reasons['V3'])
            except (ValueError, KeyError, TypeError) as exc:
                reasons['V3'].append(str(exc))
            try:
                total = dec(order.get('total'), 'order total', True)
                check(dec(order.get('subtotal'), 'subtotal') == subtotal and
                      dec(order.get('priced_subtotal'), 'priced subtotal') == subtotal and
                      total == subtotal + dec(request['charges']['shipping'], 'shipping') + dec(request['charges']['tax'], 'tax') and
                      abs(total - (expected_total + dec(request['charges']['shipping'], 'shipping') +
                                   dec(request['charges']['tax'], 'tax'))) <= CENT * len(expected),
                      'subtotal/total do not reconcile to cents and printed source', reasons['V3'])
            except (ValueError, KeyError, TypeError) as exc:
                reasons['V3'].append(str(exc))
            identity = oracle.get('reviewer_identity')
            check(isinstance(identity, dict) and
                  isinstance(identity.get('name'), str) and bool(identity['name'].strip()) and
                  identity.get('kind') == 'human' and
                  isinstance(identity.get('source'), str) and bool(identity['source'].strip()) and
                  request.get('reviewer') == identity['name'] and
                  draft.get('reviewer') == review.get('reviewer') == identity['name'],
                  'missing named-human oracle proof or reviewer differs from proved human', reasons['V4'])
            check(all(value.get('state') == 'PRICED_REQUIRES_REVIEW' for value in (draft, order, review)) and
                  all(value.get('requires_human_review') is True for value in (draft, order, review)) and
                  draft.get('review_status') == review.get('status') == 'PENDING_NAMED_HUMAN_REVIEW' and
                  review.get('customer_release_authorized') is False and
                  draft.get('reviewer') == review.get('reviewer') == request.get('reviewer') and
                  isinstance(request.get('reviewer'), str) and bool(request['reviewer'].strip()) and
                  draft.get('total') == order.get('total') and order.get('blockers') == draft.get('blockers') == [] and
                  all(isinstance(lines.get(w['line_id'], {}).get('unit_price'), (float, int)) and
                      isinstance(lines.get(w['line_id'], {}).get('extended_price'), (float, int)) for w in expected),
                  'incomplete priced state, reviewer, or release safety', reasons['V4'])
            try:
                dec(order.get('total'), 'priced total', True)
                for charge in ('shipping', 'tax'):
                    dec(order['charges'][charge], f'priced {charge}')
                for wanted in expected:
                    lid = wanted['line_id']
                    dec(lines.get(lid, {}).get('unit_price'), f'{lid} priced unit', True)
                    dec(lines.get(lid, {}).get('extended_price'), f'{lid} priced extension', True)
            except (ValueError, KeyError, TypeError) as exc:
                reasons['V4'].append(str(exc))

    if judge is None:
        for key in JUDGE:
            reasons[key].append('judge verdict missing')
    else:
        try:
            judge = obj(judge, 'judge')
            require(judge.get('case_id') == case_id, 'judge case_id mismatch')
            keys = {'oracle', 'answer', 'audit'}
            hashes = obj(judge.get('input_sha256'), 'judge input_sha256')
            require(set(hashes) == keys and all(isinstance(value, str) and
                    re.fullmatch(r'[0-9a-f]{64}', value) for value in hashes.values()),
                    'judge input_sha256 must contain three SHA256 digests')
            require(isinstance(expected_hashes, dict) and set(expected_hashes) == keys and
                    all(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)
                        for value in expected_hashes.values()) and hashes == expected_hashes,
                    'judge input_sha256 differs from supplied oracle/answer/audit bytes')
            criteria = judge.get('criteria')
            require(isinstance(criteria, list) and len(criteria) == 5, 'judge must contain exactly five criteria')
            ids = [obj(item, 'judge criterion').get('id') for item in criteria]
            require(set(ids) == set(JUDGE) and len(set(ids)) == 5, 'duplicate, missing or unknown judge criterion')
            for item in criteria:
                require(item.get('verdict') in ('pass', 'fail') and isinstance(item.get('reason'), str) and
                        bool(item['reason'].strip()) and isinstance(item.get('evidence'), list) and
                        all(isinstance(x, str) and x.strip() for x in item['evidence']) and
                        (item['verdict'] != 'pass' or item['evidence']), f'{item["id"]}: malformed verdict/reason/evidence')
            for item in criteria:
                if item['verdict'] == 'fail':
                    reasons[item['id']].append(item['reason'])
        except (ValueError, TypeError) as exc:
            for key in JUDGE:
                reasons[key].append(f'invalid judge: {exc}')
    vp = sum(not reasons[k] for k in VALIDATION)
    jp = sum(not reasons[k] for k in JUDGE)
    return {'case_id': case_id, 'criteria': {key: {'passed': not value, 'reasons': value} for key, value in reasons.items()},
            'validation_passed': vp, 'judge_passed': jp, 'validation_score': vp / 5,
            'judge_score': jp / 5, 'combined_score': (vp + jp) / 10,
            'all_pass': vp == jp == 5 and draft is not None and not reasons['V1'] and not reasons['V4']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('oracle', 'answer', 'audit', 'out'):
        parser.add_argument(f'--{key}', required=True, type=Path)
    parser.add_argument('--judge', type=Path)
    args = parser.parse_args()
    oracle_bytes = args.oracle.read_bytes()
    oracle = json.loads(oracle_bytes)
    try:
        judge = json.loads(args.judge.read_text()) if args.judge else None
    except (ValueError, OSError):
        judge = {'case_id': None}
    def snapshot(answer):
        try:
            return artifacts(answer['draft'], Path.home() / '.local/share/keller-quotes/drafts')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return f'artifact validation failed: {exc}'
    hashes = None
    try:
        answer_bytes, audit_bytes = args.answer.read_bytes(), args.audit.read_bytes()
        hashes = {key: sha256(value).hexdigest() for key, value in
                  (('oracle', oracle_bytes), ('answer', answer_bytes), ('audit', audit_bytes))}
        answer = json.loads(answer_bytes)
        events = trace(args.audit, audit_bytes)
    except (ValueError, TypeError, OSError, UnicodeError) as exc:
        answer, events = {'case_id': oracle.get('case_id')}, []
        result = grade(oracle, answer, events, judge, snapshot(answer), hashes)
        for key in VALIDATION:
            result['criteria'][key]['reasons'] = [f'malformed answer/audit: {exc}']
        result['all_pass'] = False
    else:
        result = grade(oracle, answer, events, judge, snapshot(answer), hashes)
    require(args.out.parent.is_dir() and not args.out.parent.is_symlink() and
            args.out.parent.stat().st_mode & 0o077 == 0, 'output directory must be private (0700)')
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
