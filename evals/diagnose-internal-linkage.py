#!/usr/bin/env python3
"""Operator-only metadata linkage, never pricing or admission into an eval worker."""
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation

PINS = {
    'cases': '12414d36a0f2d721d86d74dea61a66673c043931668f7573ece4f27553445311',
    'internal_register': '6ed19d0cf550f3e65f420b676bbc4354c8dfaf05912d1f5f4edefb4bc8b24cfe',
    'development_diagnostic': 'd8badace6227784d57bf7f89a0b03e2b3e448caf0970f7481de3898f813ba8cf',
}
FIELDS = ('quote_no', 'item_no', 'part_no', 'customer_id', 'quote_date', 'date_stamp', 'letter_date', 'rev', 'drawing_no', 'material', 'comment')
SOURCE_PINS = {
    'QUOTEM': 'dcd1afd8e7d79253ebb98f572e8da129e39f54d81d0a3399d09c622df6623b2b',
    'QUOTOPER': 'd79e19b3c537f1207e58e98fca527a256643192e03bbaa932cfb520eac17d51c',
    'QUOTCAD': '1e2f59d4938ae817895226255de487ca6e5e05d2f6ff440ea3819ed455132549',
}
def sha(data):
    return hashlib.sha256(data).hexdigest()
def norm(value):
    return re.sub('[^A-Z0-9]', '', value.upper())
def before(value, cutoff):
    try:
        return date.fromisoformat(value).isoformat() == value and value < cutoff
    except ValueError:
        return False
def historical_metadata(group, cutoff):
    return all(before(r['quote_date'], cutoff) and all(not r[k] or before(r[k], cutoff) for k in ('date_stamp', 'letter_date')) for r in group)

def dbf_links(path, table, quote_ids):
    data = path.read_bytes()
    assert sha(data) == SOURCE_PINS[table]
    count = int.from_bytes(data[4:8], 'little')
    header_len = int.from_bytes(data[8:10], 'little')
    record_len = int.from_bytes(data[10:12], 'little')
    assert len(data) >= header_len + count * record_len
    fields = {}
    pos, offset = 32, 1
    while data[pos] != 13:
        assert pos + 32 <= header_len
        field = data[pos:pos+32]
        name = field[:11].split(b'\x00')[0].decode('ascii')
        assert name not in fields
        fields[name] = (offset, offset+field[16], chr(field[11]))
        offset += field[16]
        pos += 32
    assert offset == record_len and fields['QUOTE_NO'][2] == 'C'
    result = {q: {'active_rows': 0, 'deleted_rows': 0, 'positive_fields': {}, 'nonblank_fields': {}} for q in sorted(quote_ids)}
    numeric = ('THICKNESS', 'PART_L', 'PART_W', 'STOCK_L', 'STOCK_W', 'WGHT_PIECE') if table == 'QUOTEM' else ('SUTIME', 'RUNTIME') + tuple(f'{p}_V{i}' for p in ('SU', 'RUN') for i in range(1, 11)) if table == 'QUOTOPER' else ()
    text = ('ID',) if table == 'QUOTEM' else ('OPER_ID', 'SU_FORM_ID', 'RU_FORM_ID') if table == 'QUOTOPER' else ('CAD_FILE',)
    assert all(fields[f][2] == 'N' for f in numeric)
    assert all(fields[f][2] == 'C' for f in text)
    for i in range(count):
        row = data[header_len+i*record_len:header_len+(i+1)*record_len]
        start, end, _ = fields['QUOTE_NO']
        q = row[start:end].decode('ascii').strip()
        if q not in result:
            continue
        assert row[:1] in (b' ', b'*')
        if row[:1] == b'*':
            result[q]['deleted_rows'] += 1
            continue
        result[q]['active_rows'] += 1
        for f in numeric:
            start, end, _ = fields[f]
            raw = row[start:end].strip()
            try:
                value = Decimal(raw.decode('ascii')) if raw else Decimal(0)
                positive = value.is_finite() and value > 0
            except InvalidOperation:
                raise ValueError('invalid numeric source') from None
            result[q]['positive_fields'][f] = result[q]['positive_fields'].get(f, False) or positive
        for f in text:
            start, end, _ = fields[f]
            result[q]['nonblank_fields'][f] = result[q]['nonblank_fields'].get(f, False) or bool(row[start:end].strip())
    return result

def main():
    if not __debug__:
        raise ValueError('input assertions must be enabled')
    os.umask(0o077)
    cases_path, register_path, development_path, source_root, output = map(Path, sys.argv[1:])
    parent = output.parent
    assert output.is_absolute() and parent.resolve() == parent
    st = parent.stat()
    assert st.st_uid == os.getuid() and not st.st_mode & 0o077
    git = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], cwd=parent, capture_output=True, check=False)
    assert git.returncode != 0
    for key, path in zip(PINS, (cases_path, register_path, development_path)):
        assert sha(path.read_bytes()) == PINS[key]
    development = json.loads(development_path.read_bytes())
    ids = {r['case_id'] for r in development['cases']}
    assert len(ids) == 208 and development['summary']['all_case_denominator'] == 250
    cases = [json.loads(line) for line in cases_path.read_text().splitlines()]
    assert len(cases) == 250 and len({c['id'] for c in cases}) == 250
    all_cohort_sources = {c['source_quote_no'] for c in cases}
    selected = [c for c in cases if c['id'] in ids]
    assert len(selected) == len(ids)
    groups = defaultdict(list)
    row_count = 0
    with register_path.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        assert set(FIELDS) <= set(reader.fieldnames)
        for row in reader:
            row_count += 1
            projected = {k: row[k].strip() for k in FIELDS}
            groups[(projected['quote_no'], projected['item_no'])].append(projected)
    by_part = defaultdict(list)
    for key, rows in groups.items():
        parts = {norm(r['part_no']) for r in rows}
        assert len(parts) == 1
        if any('?' in r['part_no'] or '*' in r['part_no'] for r in rows):
            continue
        if norm(rows[0]['part_no']):
            by_part[norm(rows[0]['part_no'])].append((key, rows))
    results = []
    for c in selected:
        p = c['input']
        exact = by_part[norm(p['part_no'])] if norm(p['part_no']) and not any(x in p['part_no'] for x in '?*') else []
        outside = [(k, rs) for k, rs in exact if k[0] not in all_cohort_sources]
        own_customer = [(k, rs) for k, rs in outside if all(r['customer_id'] == p['customer_id'] for r in rs)]
        eligible = [(k, rs) for k, rs in own_customer if historical_metadata(rs, c['quote_date'])]
        results.append({
            'case_id': c['id'],
            'exact_groups_including_excluded_source': len(exact),
            'exact_groups_outside_source': len(outside),
            'same_customer_groups_outside_source': len(own_customer),
            'same_customer_groups_passing_recorded_dates': len(eligible),
            'nonblank_candidate_fields': {f: any(r[f] for _, rs in eligible for r in rs) for f in ('rev', 'drawing_no', 'material', 'comment')},
            'candidate_quote_items_private': [list(k) for k, _ in eligible],
        })
    names = ['exact_groups_including_excluded_source', 'exact_groups_outside_source', 'same_customer_groups_outside_source', 'same_customer_groups_passing_recorded_dates']
    quote_ids = {q for r in results for q, _ in r['candidate_quote_items_private']}
    assert not quote_ids & all_cohort_sources
    linked = {t: dbf_links(source_root / (t + '.DBF'), t, quote_ids) for t in SOURCE_PINS}
    component_summary = {}
    for table, links in linked.items():
        case_tables = [{q: links[q] for q, _ in r['candidate_quote_items_private']} for r in results]
        numeric_fields = sorted({f for r in links.values() for f in r['positive_fields']})
        text_fields = sorted({f for r in links.values() for f in r['nonblank_fields']})
        component_summary[table] = {
            'active_rows_for_candidate_quotes': sum(r['active_rows'] for r in links.values()),
            'deleted_rows_for_candidate_quotes': sum(r['deleted_rows'] for r in links.values()),
            'development_cases_with_active_rows': sum(any(r['active_rows'] for r in c.values()) for c in case_tables),
            'cases_with_any_positive_field': {f: sum(any(r['positive_fields'].get(f, False) for r in c.values()) for c in case_tables) for f in numeric_fields},
            'cases_with_any_nonblank_field': {f: sum(any(r['nonblank_fields'].get(f, False) for r in c.values()) for c in case_tables) for f in text_fields},
        }
    summary = {
        'schema_version': 1,
        'population': '208 development-tagged cases; separate internal-register metadata audit; not an evaluation arm',
        'input_sha256': PINS,
        'original_source_sha256': SOURCE_PINS,
        'all_cohort_source_quotes_excluded_from_linked_candidates': True,
        'script_sha256': sha(Path(__file__).read_bytes()),
        'all_case_denominator': 250,
        'inspected_development_cases': len(results),
        'other_cases_not_drilled_into': 42,
        'internal_register_rows': row_count,
        'internal_quote_item_groups': len(groups),
        'development_cases_with': {k: sum(r[k] > 0 for r in results) for k in names},
        'cases_with_nonblank_candidate_fields': {f: sum(r['nonblank_candidate_fields'][f] for r in results) for f in ('rev', 'drawing_no', 'material', 'comment')},
        'recorded_date_candidate_group_count': sum(r[names[-1]] for r in results),
        'distinct_candidate_quotes': len(quote_ids),
        'candidate_quotes_with_multiple_internal_items': sum(sum(key[0] == q for key in groups) > 1 for q in quote_ids),
        'original_manufacturing_component_presence': component_summary,
        'prices_extracted_or_compared': False,
        'new_pricing_execution': False,
        'frozen_scope_or_policy_changed': False,
        'provider_requests': 0,
        'manufacturing_compatibility': 'unknown',
        'original_version_availability': 'unproven',
        'current_cost_accuracy': None,
        'realized_margin_accuracy': None,
    }
    with output.open('x', encoding='utf-8') as f:
        json.dump({'summary': summary, 'cases': results, 'private_quote_level_component_links': linked}, f, indent=2)
        f.write('\n')
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('LINKAGE_INPUT_OR_EXECUTION_FAILURE', file=sys.stderr)
        sys.exit(2)
