#!/usr/bin/env python3
"""Assess explicitly bound private Keller evidence; never regrade legacy replay."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys


REPO = Path(__file__).resolve().parent.parent
DOMAINS = ('internal_calculation', 'recorded_customer_quote',
           'independently_confirmed_acceptance', 'actual_manufacturing_cost',
           'supported_current_quote', 'optimum_business_outcome')
RECORD_KINDS = {'independently_confirmed_acceptance': 'customer_order_acceptance',
                'actual_manufacturing_cost': 'actual_job_cost',
                'supported_current_quote': 'supported_current_quote'}
IDENTITY_KEYS = ('quote_no', 'item_no', 'customer_id', 'part_no', 'revision', 'drawing_no', 'quantity')
SECRET = re.compile(r'postgres(?:ql)?://|-----BEGIN [A-Z ]*PRIVATE KEY-----|'
                    r'\b(?:password|api[_-]?key|access[_-]?token|secret)\s*["\']?\s*[:=]|'
                    r'\bBearer\s+[A-Za-z0-9._-]+', re.I)


def require(condition, code):
    if not condition:
        raise ValueError(code)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(',', ':'), default=lambda v: str(v) if isinstance(v, Decimal) else v) + '\n').encode()


def parse_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    return json.loads(data.decode('utf-8-sig'), object_pairs_hook=pairs,
                      parse_float=Decimal, parse_constant=lambda _: require(False, 'NONFINITE_JSON'))


def shape(value, keys, required=None):
    require(isinstance(value, dict) and set(value) <= set(keys) and
            set(keys if required is None else required) <= set(value), 'INVALID_SCHEMA')
    return value


def text(value, blank=False):
    require(isinstance(value, str) and (blank or bool(value)) and value == value.strip() and
            len(value) <= 1024 and not re.search(r'[\x00-\x1f\x7f]', value), 'INVALID_TEXT')
    return value


def iso_date(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value), 'INVALID_DATE')
    return date.fromisoformat(value).isoformat()


def timestamp(value):
    require(isinstance(value, str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})', value), 'INVALID_TIME')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def number(value, positive=False, places=5):
    require(not isinstance(value, bool) and isinstance(value, (str, int, Decimal)), 'INVALID_DECIMAL')
    require(bool(re.fullmatch(r'\d+(?:\.\d+)?', str(value))), 'INVALID_DECIMAL')
    result = Decimal(str(value))
    require(result.is_finite() and result >= 0 and (not positive or result > 0) and
            result.as_tuple().exponent >= -places and result <= Decimal(2**53 - 1), 'INVALID_DECIMAL')
    return result


def extension(unit, quantity):
    return (number(unit, True) * number(quantity, True, 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)


def semantic_request_sha256(data, embedded=False):
    node = shutil.which('node')
    require(node is not None, 'JS_REQUEST_HASH_RUNTIME_UNAVAILABLE')
    program = ("const fs=require('node:fs'),crypto=require('node:crypto');"
               "const value=JSON.parse(fs.readFileSync(0,'utf8').replace(/^\\uFEFF/,''));"
               f"const request={'value.request' if embedded else 'value'};"
               "process.stdout.write(crypto.createHash('sha256').update(JSON.stringify(request)).digest('hex'));")
    try:
        result = subprocess.run([node, '-e', program], input=data, capture_output=True, timeout=20,
                                env={'PATH': os.defpath, 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'TZ': 'UTC'})
    except (OSError, subprocess.SubprocessError):
        raise ValueError('JS_REQUEST_HASH_RUNTIME_UNAVAILABLE') from None
    require(result.returncode == 0 and re.fullmatch(rb'[a-f0-9]{64}', result.stdout), 'INVALID_JS_REQUEST_HASH')
    return result.stdout.decode('ascii')


def private_path(value, directory=False, absent=False):
    require(isinstance(value, str) and len(value) <= 1024 and os.path.isabs(value) and
            os.path.normpath(value) == value and os.path.realpath(value) == value and
            not re.search(r'[\x00-\x1f\x7f]', value), 'UNSAFE_PATH')
    path = Path(value)
    require(path != REPO and REPO not in path.parents and path not in REPO.parents and path != Path('/'), 'CHECKOUT_PATH_DENIED')
    parts = list(reversed(path.parents)) + [path]
    for current in parts:
        if absent and current == path:
            require(not current.exists() and not current.is_symlink(), 'OUTPUT_EXISTS')
            continue
        info = current.lstat()
        require(not stat.S_ISLNK(info.st_mode) and info.st_uid in (0, os.getuid()), 'UNSAFE_PATH')
        if current != path or directory:
            require(stat.S_ISDIR(info.st_mode) and not info.st_mode & 0o022, 'UNTRUSTED_ANCESTOR')
    parent = path if directory and not absent else path.parent
    info = parent.lstat()
    require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700, 'PRIVATE_DIRECTORY_REQUIRED')
    return path


def private_bytes(value, limit=64 * 1024 * 1024):
    path = private_path(value)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and before.st_nlink == 1 and
            stat.S_IMODE(before.st_mode) in (0o400, 0o600) and before.st_size <= limit, 'PRIVATE_FILE_REQUIRED')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(limit + 1)
        after = os.fstat(fd)
        current = private_path(value).lstat()
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_mode', 'st_uid', 'st_nlink')
        require(len(data) == opened.st_size and all(getattr(before, key) == getattr(opened, key) ==
                getattr(after, key) == getattr(current, key) for key in fields), 'FILE_CHANGED')
        return data
    finally:
        os.close(fd)


class EvidenceIO:
    def __init__(self):
        self.inputs = {}
        self.cache = {}

    def read(self, reference, limit=64 * 1024 * 1024):
        shape(reference, ('path', 'sha256'))
        require(isinstance(reference['sha256'], str) and re.fullmatch(r'[a-f0-9]{64}', reference['sha256']), 'INVALID_HASH')
        path = reference['path']
        if path in self.cache:
            data = self.cache[path]
        else:
            data = private_bytes(path, limit)
            self.cache[path] = data
        require(digest(data) == reference['sha256'], 'DIGEST_MISMATCH')
        self.inputs[path] = reference['sha256']
        return data

    def json(self, reference):
        data = self.read(reference)
        require(not SECRET.search(data.decode('utf-8-sig')), 'CREDENTIAL_BEARING_INPUT')
        return parse_json(data)

    def recheck(self):
        for path, expected in self.inputs.items():
            require(digest(private_bytes(path)) == expected, 'INPUT_CHANGED')


def pointer(value, locator):
    require(isinstance(locator, str) and (locator == '' or locator.startswith('/')), 'INVALID_LOCATOR')
    if not locator:
        return value
    for token in locator[1:].split('/'):
        require(not re.search(r'~(?![01])', token), 'INVALID_LOCATOR')
        token = token.replace('~1', '/').replace('~0', '~')
        value = value[int(token)] if isinstance(value, list) and re.fullmatch(r'0|[1-9]\d*', token) else value[token]
    return value


def bound_record(reference, evidence):
    shape(reference, ('source', 'pointer'))
    result = pointer(evidence.json(reference['source']), reference['pointer'])
    require(isinstance(result, dict), 'RECORD_REQUIRED')
    return result


def verify_identity(actual, expected, full=False):
    require(isinstance(actual, dict), 'IDENTITY_REQUIRED')
    for key in IDENTITY_KEYS:
        require(key in actual and key in expected, 'IDENTITY_INCOMPLETE')
        if key == 'quantity':
            require(number(actual[key], True, 0) == number(expected[key], True, 0), 'QUANTITY_MISMATCH')
        else:
            require(text(actual[key], blank=key in ('item_no', 'revision', 'drawing_no')) == expected[key], 'IDENTITY_MISMATCH')
    if full:
        require(actual['revision'] not in ('', '-', 'UNKNOWN', 'UNSPECIFIED') and
                actual['drawing_no'] not in ('', '-', 'UNKNOWN', 'UNSPECIFIED'), 'REVISION_OR_DRAWING_MISSING')
        require(re.fullmatch(r'[A-Z]{3}', text(actual.get('currency'))) and text(actual.get('uom')), 'UNIT_BASIS_REQUIRED')
        for key in ('currency', 'uom'):
            if key in expected:
                require(actual[key] == expected[key], 'UNIT_BASIS_MISMATCH')


def verify_financial_record(record, domain, expected, as_of, evidence):
    require(domain in RECORD_KINDS and record.get('kind') == RECORD_KINDS[domain], 'UNSUPPORTED_SOURCE_KIND')
    text(record.get('record_id'))
    text(record.get('issuer'))
    issued = timestamp(record.get('recorded_at'))
    require(issued.date().isoformat() <= as_of, 'LATER_EVIDENCE')
    verify_identity(record.get('identity'), expected, full=True)
    amount = shape(record.get('amount'), ('unit_price', 'extension'))
    unit = number(amount['unit_price'], True)
    require(number(amount['extension'], True, 2) == extension(unit, record['identity']['quantity']), 'EXTENSION_MISMATCH')
    if domain == 'independently_confirmed_acceptance':
        require(record.get('event') == 'customer_accepted_order' and text(record.get('customer_order_no')) and
                record.get('issuer') != 'agent' and record.get('amount_basis') == 'accepted_order', 'ACCEPTANCE_NOT_CONFIRMED')
    elif domain == 'actual_manufacturing_cost':
        require(record.get('amount_basis') == 'actual_closed_job' and text(record.get('job_no')), 'ACTUAL_COST_NOT_CONFIRMED')
        components = record.get('components')
        require(isinstance(components, dict) and set(components) == {'material', 'labor', 'outside', 'setup'}, 'COST_COMPONENTS_REQUIRED')
        require(sum(number(v, places=2) for v in components.values()) == number(amount['extension'], True, 2), 'COST_SUM_MISMATCH')
    else:
        require(record.get('amount_basis') == 'current_supported_quote' and
                iso_date(record.get('valid_from')) <= as_of <= iso_date(record.get('valid_until')), 'CURRENT_QUOTE_EXPIRED')
        assumptions = record.get('manufacturing')
        require(isinstance(assumptions, dict) and set(assumptions) == {'material', 'finish', 'routing', 'tolerances'}, 'MANUFACTURING_REQUIRED')
        for value in assumptions.values():
            text(value)
        costs = record.get('costs')
        require(isinstance(costs, list) and {c.get('component') for c in costs if isinstance(c, dict)} ==
                {'material', 'labor', 'outside', 'setup'} and len(costs) == 4, 'CURRENT_COSTS_REQUIRED')
        for cost in costs:
            source = bound_record(cost.get('evidence'), evidence)
            require(source.get('kind') == 'current_cost_observation' and source.get('component') == cost.get('component') and
                    source.get('basis') == ('job_total' if cost['component'] == 'setup' else 'per_unit'), 'CURRENT_COST_NOT_CONFIRMED')
            text(source.get('record_id'))
            text(source.get('issuer'))
            verify_identity(source.get('identity'), record['identity'], full=True)
            timestamp(source.get('recorded_at'))
            require(source['recorded_at'][:10] <= as_of and iso_date(source.get('valid_from')) <= as_of <=
                    iso_date(source.get('valid_until')), 'STALE_COST')
            require(number(source.get('amount')) == number(cost.get('amount')), 'COST_AMOUNT_MISMATCH')
            cost_extension = number(source['amount'], places=2) if cost['component'] == 'setup' else (
                number(source['amount']) * number(record['identity']['quantity'], True, 0)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
            require(number(source.get('extension'), places=2) == cost_extension, 'COST_EXTENSION_MISMATCH')
        require(number(record.get('margin_pct')) < 100, 'INVALID_MARGIN')
        precision = record.get('unit_precision', 4)
        require(type(precision) is int and precision in (4, 5), 'INVALID_UNIT_PRECISION')
        values = {c['component']: number(c['amount']) for c in costs}
        total_cost = sum(values[k] for k in ('material', 'labor', 'outside')) + values['setup'] / number(record['identity']['quantity'], True, 0)
        expected_unit = (total_cost / (1 - number(record['margin_pct']) / 100)).quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP)
        require(unit == expected_unit, 'COST_PLUS_ARITHMETIC_MISMATCH')
    return record


def read_csv(data):
    reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig'), newline=''))
    require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), 'INVALID_CSV_HEADERS')
    rows = list(reader)
    require(all(None not in row and all(value is not None for value in row.values()) for row in rows), 'INVALID_CSV_ROWS')
    return rows


def dbf_record(data, reference):
    require(len(data) >= 33, 'INVALID_DBF')
    count, start, length = struct.unpack_from('<IHH', data, 4)
    index = reference['record_index']
    require(type(index) is int and 0 <= index < count and reference.get('record_no', index + 1) == index + 1 and
            reference['byte_offset'] == start + index * length and start + count * length <= len(data), 'INVALID_DBF_REFERENCE')
    raw = data[start + index * length:start + (index + 1) * length]
    require(raw[:1] == b' ' and digest(raw) == reference['record_sha256'], 'DBF_RECORD_MISMATCH')
    fields, offset, position = {}, 1, 32
    while position < start and data[position] != 13:
        descriptor = data[position:position + 32]
        require(len(descriptor) == 32, 'INVALID_DBF_SCHEMA')
        name = descriptor[:11].split(b'\0')[0].decode('ascii')
        kind, width = chr(descriptor[11]), descriptor[16]
        require(name not in fields and width and offset + width <= length, 'INVALID_DBF_SCHEMA')
        value = raw[offset:offset + width]
        if kind in ('C', 'N', 'F'):
            fields[name] = value.decode('cp1252').strip(' \0')
        elif kind == 'D':
            token = value.decode('ascii').strip()
            fields[name] = '' if token in ('', '00000000') else iso_date(f'{token[:4]}-{token[4:6]}-{token[6:8]}')
        else:
            fields[name] = {'uninterpreted_field_hex': value.hex()}
        if 'raw_field_hex' in reference:
            require(reference['raw_field_hex'].get(name) == value.hex(), 'DBF_FIELD_MISMATCH')
        offset += width
        position += 32
    require(position < start and data[position] == 13 and offset == length, 'INVALID_DBF_SCHEMA')
    return fields


def printed_pdf(data, reference_date):
    content = data.decode('utf-8')
    require(re.search(r'^\s*(?:QUOTE|QUOTATION)(?:\s|$)', content, re.I | re.M), 'QUOTATION_TITLE_REQUIRED')
    result = {key: set() for key in ('quote_no', 'letter', 'part_no', 'revision', 'inquiry', 'footer', 'customer', 'item')}
    rows, price_body = [], False
    for key, pattern in [('quote_no', r'\bQuote\s*#\s*:\s*(\d{7})\b'),
                         ('letter', r'\bLetter\s*:\s*(\d{8})\b')]:
        result[key].update(re.findall(pattern, content, re.I))
    def printed_date(token):
        month, day, year = map(int, token.split('/'))
        if year < 100:
            year += date.fromisoformat(reference_date).year // 100 * 100
        return date(year, month, day).isoformat()
    result['inquiry'].update(printed_date(token) for token in re.findall(
        r'Inquiry\s+Date\s*:\s*(\d{2}/\d{2}/\d{2,4})\b', content, re.I))
    lines = content.splitlines()
    for index, line in enumerate(lines):
        match = re.search(r'\bP/N\s*:\s*(.*?)\s+Rev\s*:\s*(.*?)\s*$', line, re.I)
        if match:
            result['part_no'].add(match[1].strip())
            result['revision'].add(match[2].strip())
        match = re.search(r'\bTo\s*:\s*(.*?)(?=\s{2,}Buyer\s*:|$)', line, re.I)
        if match:
            result['customer'].add(' '.join(match[1].split()))
        match = re.search(r'Item\s*#\s*:\s*(\d+)\s+Quote', line, re.I)
        if match:
            result['item'].add(str(int(match[1])))
        elif re.search(r'Item\s*#\s*:', line, re.I) and index + 1 < len(lines):
            end = line.lower().find('quote #')
            token = lines[index + 1][:end if end >= 0 else len(line)].strip()
            if re.fullmatch(r'\d+', token):
                result['item'].add(str(int(token)))
        if re.search(r'^\s*By\s*:', line, re.I):
            price_body = False
            tokens = re.findall(r'(?<![\w/])\d{2}/\d{2}/\d{2,4}(?!\d)', line)
            require(len(tokens) == 1, 'FOOTER_CHRONOLOGY_UNRESOLVED')
            result['footer'].add(printed_date(tokens[0]))
        if re.search(r'Description\s+Quantity\s+Price Each\s+Extended Price', line, re.I):
            price_body = True
        elif price_body and '$' in line:
            match = re.search(r'(?<![\w,])([0-9][0-9,]*)\s+\$([0-9][0-9,]*\.\d{2})\s+\$([0-9][0-9,]*\.\d{2})\s*$', line)
            require(match and line.count('$') == 2, 'UNPARSED_PRICE_ROW')
            rows.append(tuple(number(token.replace(',', ''), True) for token in match.groups()))
    require(rows and len({row[0] for row in rows}) == len(rows), 'PRICE_ROWS_INCOMPLETE')
    for key in ('quote_no', 'letter', 'part_no', 'revision', 'inquiry', 'customer', 'item'):
        require(len(result[key]) == 1, 'PRINTED_IDENTITY_AMBIGUOUS')
    require(len(result['footer']) == 1, 'FOOTER_CHRONOLOGY_UNRESOLVED')
    return {key: next(iter(value)) for key, value in result.items()}, rows


def assess(config):
    shape(config, ('schema_version', 'as_of', 'expected_cases', 'evalset', 'bindings', 'raw_bindings',
                   'documents', 'source_manifest', 'candidate_report', 'source_paths', 'confirmed_evidence', 'out', 'max_queue'),
          ('schema_version', 'as_of', 'expected_cases', 'evalset', 'bindings', 'raw_bindings', 'documents',
           'source_manifest', 'candidate_report', 'source_paths', 'out'))
    require(config['schema_version'] == 1 and type(config['expected_cases']) is int and
            0 < config['expected_cases'] <= 10000, 'INVALID_ASSESSMENT_CONFIG')
    as_of = iso_date(config['as_of'])
    evidence = EvidenceIO()
    manifest = evidence.json(config['source_manifest'])['inputs']
    cases = [parse_json(line) for line in evidence.read(config['evalset']).splitlines() if line.strip()]
    require(len(cases) == config['expected_cases'] and len({c['id'] for c in cases}) == len(cases), 'FROZEN_CASES_MISSING_OR_DUPLICATE')
    require(config['evalset']['sha256'] == manifest['frozen_evalset']['sha256'] and
            config['candidate_report']['sha256'] == manifest['candidate_report']['sha256'], 'AUDIT_INPUT_PIN_MISMATCH')
    bindings = read_csv(evidence.read(config['bindings']))
    require(len({row['id'] for row in bindings}) == len(bindings) and
            {row['id'] for row in bindings} <= {c['id'] for c in cases}, 'INVALID_CASE_BINDINGS')
    by_id = {row['id']: row for row in bindings}
    raw = evidence.json(config['raw_bindings'])['records']
    raw_indices = {table: {r['record_index']: r for r in records} for table, records in raw.items()}
    require(all(len(raw_indices[t]) == len(raw[t]) for t in raw), 'DUPLICATE_PHYSICAL_REFERENCE')
    documents = evidence.json(config['documents'])['documents']
    require(isinstance(config['source_paths'], dict) and set(config['source_paths']) <= set(manifest), 'UNKNOWN_SOURCE_PATH')
    sources, source_errors = {}, {}
    for key, path in config['source_paths'].items():
        reference = {'path': path, 'sha256': manifest[key]['sha256']}
        try:
            data = evidence.read(reference)
            require(len(data) == manifest[key]['bytes'], 'SOURCE_SIZE_MISMATCH')
            sources[key] = (data, reference)
        except (ValueError, OSError) as error:
            source_errors[key] = str(error) if isinstance(error, ValueError) else 'SOURCE_UNAVAILABLE'
    def source_by_hash(expected):
        matches = [(key, value) for key, value in sources.items() if value[1]['sha256'] == expected]
        require(len(matches) == 1, 'SOURCE_BYTES_NOT_SUPPLIED')
        return matches[0][1]
    def row(table, reference):
        require(table + '.DBF' in sources, 'SOURCE_BYTES_NOT_SUPPLIED')
        return dbf_record(sources[table + '.DBF'][0], reference)
    try:
        candidate = evidence.json(config['candidate_report'])
        candidate_results = candidate['results']
        require(isinstance(candidate_results, list), 'INVALID_CANDIDATE_REPORT')
    except (ValueError, OSError, KeyError):
        candidate_results = []
    result_groups = defaultdict(list)
    for result in candidate_results:
        result_groups[result.get('id')].append(result)
    require(set(result_groups) <= {c['id'] for c in cases}, 'UNDECLARED_CANDIDATE_CASE')
    confirmations = config.get('confirmed_evidence', [])
    require(isinstance(confirmations, list) and len(confirmations) <= 10000, 'INVALID_CONFIRMED_EVIDENCE')
    confirmed_by_id = defaultdict(list)
    for item in confirmations:
        shape(item, ('case_id', 'domain', 'authority', 'evidence'))
        require(item['case_id'] in {c['id'] for c in cases} and item['domain'] in RECORD_KINDS and
                item['authority'] in ('source_record', 'operator_assertion'), 'INVALID_CONFIRMED_EVIDENCE')
        confirmed_by_id[item['case_id']].append(item)
    assessed = []
    for case in cases:
        case_id = text(case['id'])
        match = re.fullmatch(r'([^|]+)\|(.*)@(\d+)', case_id)
        require(match is not None, 'INVALID_LEGACY_CASE_ID')
        identity = {'quote_no': case['source_quote_no'], 'item_no': match[2],
                    'customer_id': case['input']['customer_id'], 'part_no': case['input'].get('part_no', ''),
                    'revision': '', 'drawing_no': '', 'quantity': int(number(case['input']['quantity'], True, 0))}
        domains = {domain: {'state': 'UNSUPPORTED', 'reason': 'NO_INDEPENDENT_SOURCE_RECORD'} for domain in DOMAINS}
        domains['optimum_business_outcome'] = {'state': 'UNSUPPORTED', 'reason': 'PAIRED_COST_PROFIT_OUTCOME_COMPARISON_REQUIRED'}
        issues = []
        binding = by_id.get(case_id)
        calculation_refs = []
        expected_calculation_refs = []
        try:
            require(binding is not None, 'CASE_BINDING_MISSING')
            for key, value in [('quote_no', identity['quote_no']), ('item_no', identity['item_no']),
                               ('part_no', identity['part_no']), ('customer_id', identity['customer_id'])]:
                require(binding[key] == value, 'CASE_BINDING_IDENTITY_MISMATCH')
            require(number(binding['quantity'], True, 0) == identity['quantity'] == int(match[3]) and
                    number(case['actual_quantity'], True, 0) == identity['quantity'] and
                    number(binding['target_UNIT_SELL'], True) == number(case['actual_unit_price'], True), 'TARGET_BINDING_MISMATCH')
            head_ref = raw_indices['QUOTEN'][int(binding['raw_QUOTEN_record_index'])]
            qty_ref = raw_indices['QUOTQTYS'][int(binding['raw_QUOTQTYS_record_index'])]
            expected_calculation_refs = [{'logical_source': t + '.DBF', 'sha256': manifest[t + '.DBF']['sha256'],
                'physical_record': {k: r[k] for k in ('record_index', 'record_no', 'byte_offset', 'record_sha256')}}
                for t, r in [('QUOTEN', head_ref), ('QUOTQTYS', qty_ref)]]
            head, qty = row('QUOTEN', head_ref), row('QUOTQTYS', qty_ref)
            for key, dbf_key in [('quote_no', 'QUOTE_NO'), ('item_no', 'ITEM_NO'), ('customer_id', 'COMP_ID'), ('part_no', 'PART_NO')]:
                require(head[dbf_key] == identity[key], 'CALCULATION_IDENTITY_MISMATCH')
            require(head['DESCR'] == case['input'].get('description', '') and head['ORG_DATE'] == case['quote_date'] and
                    qty['QUOTE_NO'] == identity['quote_no'] and number(qty['QTY'], True, 0) == identity['quantity'] and
                    number(qty['UNIT_SELL'], True) == number(case['actual_unit_price'], True) and
                    qty['DEL'] == binding['delivery_count_DEL'], 'CALCULATION_VALUE_MISMATCH')
            identity.update(revision=head['REV_NO'], drawing_no=head['DRAWING_NO'])
            require(identity['revision'] == binding['revision'] and identity['drawing_no'] == binding['drawing_no'], 'CALCULATION_REVISION_MISMATCH')
            calculation_refs = [{'source': sources[t + '.DBF'][1], 'physical_record': r} for t, r in
                                [('QUOTEN', head_ref), ('QUOTQTYS', qty_ref)]]
            domains['internal_calculation'] = {'state': 'VERIFIED_SOURCE_BYTES', 'source_field': 'QUOTQTYS.UNIT_SELL',
                'unit_price': str(number(qty['UNIT_SELL'], True)), 'extension': str(extension(qty['UNIT_SELL'], identity['quantity'])),
                'currency': 'UNSPECIFIED_IN_SOURCE', 'uom': 'UNSPECIFIED_IN_SOURCE',
                'delivery_count': qty['DEL'], 'quantity_only_ambiguity': int(binding['csv_quantity_only_match_count']) > 1,
                'actual_cost_or_acceptance': 'NOT_ESTABLISHED', 'evidence': calculation_refs}
        except (ValueError, OSError, KeyError, TypeError) as error:
            reason = str(error) if isinstance(error, ValueError) else 'CALCULATION_REFERENCE_UNAVAILABLE'
            domains['internal_calculation'] = {'state': 'UNVERIFIED', 'reason': reason, 'expected_evidence': expected_calculation_refs}
            issues.append(reason)
        if binding and binding.get('document_path'):
            try:
                matches = [d for d in documents.values() if d['document'] == binding['document_path']]
                require(len(matches) == 1, 'DOCUMENT_REFERENCE_AMBIGUOUS')
                doc = matches[0]
                require(doc['source_pdf_sha256'] == binding['document_sha256'] and
                        doc['source_transcript_sha256'] == binding['transcript_sha256'], 'DOCUMENT_BINDING_HASH_MISMATCH')
                pdf, pdf_ref = source_by_hash(doc['source_pdf_sha256'])
                transcript, transcript_ref = source_by_hash(doc['source_transcript_sha256'])
                require(pdf.startswith(b'%PDF-') and transcript.strip(), 'INVALID_DOCUMENT_BYTES')
                header_rows = [row('QUOTLETT', r) for r in doc['source_header_refs']]
                line_rows = [row('QUOTLINE', r) for r in doc['source_line_refs']]
                require(len(header_rows) == len(line_rows) == 1, 'DOCUMENT_SOURCE_IDENTITY_AMBIGUOUS')
                header, line = header_rows[0], line_rows[0]
                require(header['QUOTLETTER'] == line['QUOTLETTER'] == doc['letter'] and
                        line['QUOTE_NO'] == identity['quote_no'] and line['PART_NO'] == identity['part_no'] and
                        header['COMP_ID'] == identity['customer_id'], 'DOCUMENT_SOURCE_IDENTITY_MISMATCH')
                env = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'TZ': 'UTC'}
                result = subprocess.run(['pdftotext', '-layout', pdf_ref['path'], '-'], capture_output=True,
                                        check=True, timeout=20, env=env)
                require(digest(result.stdout) == doc['layout_text_sha256'] == binding['fresh_layout_sha256'], 'LAYOUT_HASH_MISMATCH')
                printed, printed_rows = printed_pdf(result.stdout, header['DATE_STAMP'])
                revision_display_matches = (printed['revision'] == line['REV_NO'] if line['REV_NO']
                                            else printed['revision'] in ('', '-'))
                require(printed['quote_no'] == identity['quote_no'] and printed['letter'] == doc['letter'] and
                        ' '.join(printed['part_no'].split()) == ' '.join(line['PART_NO'].split()) and
                        printed['item'] == str(int(line['ITEM'])) and revision_display_matches and
                        printed['inquiry'] == header['DATE_STAMP'], 'PRINTED_IDENTITY_MISMATCH')
                customer = ' '.join(header['CNAME'].split())
                customer_relation = 'EXACT' if printed['customer'].casefold() == customer.casefold() else 'PREFIX_ONLY'
                require(customer.casefold().startswith(printed['customer'].casefold()), 'PRINTED_CUSTOMER_MISMATCH')
                curve = doc.get('verified_curve', [])
                require(len(curve) == len(printed_rows) and curve, 'COMPLETE_CURVE_REQUIRED')
                amounts = []
                for c, (q, display, ext) in zip(curve, printed_rows):
                    source_qty = row('QUOTLEIT', c['source_quantity_ref'])
                    require(source_qty['QUOTLETTER'] == doc['letter'] and number(source_qty['ITEM'], True, 0) ==
                            number(line['ITEM'], True, 0) and number(source_qty['QTY'], True, 0) == q == number(c['quantity'], True, 0), 'DOCUMENT_QUANTITY_MISMATCH')
                    field = c['source_price_field']
                    require(field in ('PRICE', 'QUOTEPRICE'), 'UNSUPPORTED_PRICE_FIELD')
                    unit = number(source_qty[field], True)
                    require(unit == number(c['unit_price'], True) and unit.quantize(Decimal('.01'), rounding=ROUND_DOWN) == display and
                            extension(unit, q) == ext == number(c['printed_extension'], True, 2), 'DOCUMENT_ARITHMETIC_MISMATCH')
                    amounts.append({'quantity': str(q), 'unit_price': str(unit), 'extension': str(ext), 'source_field': field})
                selected = [a for a in amounts if number(a['quantity'], True, 0) == identity['quantity']]
                require(len(selected) == 1, 'DOCUMENT_TARGET_QUANTITY_MISSING')
                same_letter = doc['letter'] == binding['quote_letter']
                revision_matches = (domains['internal_calculation']['state'] == 'VERIFIED_SOURCE_BYTES' and
                                    line['REV_NO'] == identity['revision'] and line['DRAWING_NO'] == identity['drawing_no'])
                recorded = header['DATE_STAMP']
                known_dates = [recorded, printed['footer'], header.get('REVISION_D') or recorded]
                domains['recorded_customer_quote'] = {'state': 'VERIFIED_RECORDED_AMOUNT', **selected[0],
                    'identity': {**identity, 'revision': line['REV_NO'], 'drawing_no': line['DRAWING_NO']},
                    'currency': 'DOLLAR_SYMBOL_ONLY', 'uom': 'PRINTED_PRICE_EACH_NOT_INDEPENDENTLY_CONFIRMED',
                    'letter': doc['letter'], 'recorded_date': recorded, 'footer_date': printed['footer'],
                    'chronology': 'CONSISTENT' if printed['footer'] == recorded else 'INQUIRY_FOOTER_CONFLICT',
                    'known_latest_date': max(known_dates), 'original_availability': 'UNPROVEN',
                    'same_associated_letter': same_letter, 'revision_and_drawing_match': revision_matches,
                    'revision_identity': 'RECORDED' if line['REV_NO'] else 'ABSENT_IN_SOURCE',
                    'drawing_identity': 'RECORDED' if line['DRAWING_NO'] else 'ABSENT_IN_SOURCE',
                    'customer_name_support': customer_relation,
                    'target_comparable': same_letter and revision_matches,
                    'numeric_agreement_with_calculation': number(selected[0]['unit_price'], True) == number(case['actual_unit_price'], True),
                    'as_of_eligible': False, 'evidence': [pdf_ref, transcript_ref], 'curve': amounts}
                if not same_letter:
                    issues.append('DIFFERENT_LETTER_NOT_DIRECT_TARGET_PROOF')
                if not revision_matches:
                    issues.append('DOCUMENT_REVISION_OR_DRAWING_MISMATCH')
                if max(known_dates) > case['quote_date']:
                    issues.append('DOCUMENT_LATER_THAN_CALCULATION')
                if printed['footer'] != recorded:
                    issues.append('INQUIRY_FOOTER_AVAILABILITY_UNRESOLVED')
            except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
                reason = str(error) if isinstance(error, ValueError) else 'DOCUMENT_VERIFICATION_UNAVAILABLE'
                domains['recorded_customer_quote'] = {'state': 'UNVERIFIED', 'reason': reason,
                    'expected_evidence': {'document': binding['document_path'], 'pdf_sha256': binding['document_sha256'],
                                          'transcript_sha256': binding['transcript_sha256']}}
                issues.append(reason)
        else:
            reason = ('DOCUMENT_GROUP_PRESENT_TARGET_QUANTITY_ABSENT' if binding and binding.get('document_group_coverage') == 'True'
                      else 'NO_SELECTED_DOCUMENT_GROUP_AT_TARGET_QUANTITY')
            domains['recorded_customer_quote'] = {'state': 'UNSUPPORTED', 'reason': reason}
            issues.append(reason)
        for item in confirmed_by_id[case_id]:
            domain = item['domain']
            try:
                record = bound_record(item['evidence'], evidence)
                if item['authority'] == 'operator_assertion':
                    require(record.get('kind') == 'operator_assertion', 'ASSERTION_KIND_REQUIRED')
                    verify_identity(record.get('identity'), identity)
                    value = {'state': 'OPERATOR_ASSERTION_NOT_INDEPENDENT_TRUTH', 'evidence': item['evidence']}
                else:
                    verify_financial_record(record, domain, identity, as_of, evidence)
                    value = {'state': 'SOURCE_BOUND_INDEPENDENTLY_INSPECTABLE_RECORD', 'record': record,
                             'evidence': item['evidence'], 'authenticity': 'EXTERNAL_SOURCE_APPROVAL_REQUIRED'}
                require(domains[domain]['state'] == 'UNSUPPORTED', 'CONFLICTING_DOMAIN_EVIDENCE')
                domains[domain] = value
            except (ValueError, OSError, KeyError, TypeError, InvalidOperation) as error:
                reason = str(error) if isinstance(error, ValueError) else 'CONFIRMED_EVIDENCE_UNAVAILABLE'
                domains[domain] = {'state': 'UNVERIFIED', 'reason': reason}
                issues.append(reason)
        observed = result_groups[case_id]
        legacy = {'state': 'MISSING_OR_DUPLICATE_ATTEMPT', 'results': observed}
        if len(observed) == 1:
            result = observed[0]
            try:
                require(result['source_quote_no'] == identity['quote_no'] and number(result['quantity'], True, 0) == identity['quantity'] and
                        number(result['actual'], True) == number(case['actual_unit_price'], True) and result['quote_date'] == case['quote_date'], 'CANDIDATE_IDENTITY_MISMATCH')
                predicted = None if result.get('predicted') is None else number(result['predicted'], True)
                signed = None if predicted is None else predicted - number(case['actual_unit_price'], True)
                legacy = {'state': 'PRESERVED_UNCHANGED_NOT_RESCORED', 'result': result,
                          'signed_unit_error': None if signed is None else str(signed),
                          'absolute_unit_error': None if signed is None else str(abs(signed)),
                          'signed_relative_error': None if signed is None else str(signed / number(case['actual_unit_price'], True)),
                          'signed_extension_error': None if predicted is None else str(extension(predicted, identity['quantity']) -
                              extension(case['actual_unit_price'], identity['quantity'])),
                          'legacy_tolerance': 'UNCHANGED_20_PERCENT'}
            except (ValueError, KeyError, TypeError, InvalidOperation):
                legacy = {'state': 'INVALID_CANDIDATE_IDENTITY_OR_PRICE', 'results': observed}
        if legacy['state'] != 'PRESERVED_UNCHANGED_NOT_RESCORED':
            issues.append(legacy['state'])
        for domain, reason in [('independently_confirmed_acceptance', 'INDEPENDENT_CUSTOMER_ACCEPTANCE_RECORD_REQUIRED'),
                               ('actual_manufacturing_cost', 'ACTUAL_CLOSED_JOB_COST_RECORD_REQUIRED'),
                               ('supported_current_quote', 'CURRENT_COST_MANUFACTURING_AND_QUOTE_RECORD_REQUIRED')]:
            if domains[domain]['state'] != 'SOURCE_BOUND_INDEPENDENTLY_INSPECTABLE_RECORD':
                issues.append(reason)
        assessed.append({'id': case_id, 'frozen_case': case, 'identity': identity, 'quote_date': case['quote_date'],
                         'domains': domains, 'legacy_diagnostic': legacy,
                         'remediation_reasons': sorted(set(issues + ['FULL_RFQ_CURRENT_COST_AND_REVIEW_REQUIRED',
                                                                  'ORIGINAL_AVAILABILITY_UNPROVEN']))})
    queue_limit = config.get('max_queue', 10)
    require(type(queue_limit) is int and 1 <= queue_limit <= 10, 'INVALID_QUEUE_BOUND')
    grouped = defaultdict(list)
    for case in assessed:
        for reason in case['remediation_reasons']:
            grouped[reason].append(case['id'])
    priority = lambda reason: (0 if 'MISSING' in reason or 'MISMATCH' in reason or 'UNAVAILABLE' in reason or 'NOT_SUPPLIED' in reason else 1, reason)
    ordered = sorted(grouped, key=priority)
    required_inputs = {
        'SOURCE_BYTES_NOT_SUPPLIED': 'Supply the pinned original DBFs/PDFs/transcripts at the case-level physical/hash references',
        'CASE_BINDING_MISSING': 'Recover the exact frozen case binding without dropping or changing the frozen case',
        'DOCUMENT_REVISION_OR_DRAWING_MISMATCH': 'Inspect original calculation and letter revision/drawing records; do not equate different revisions',
        'DIFFERENT_LETTER_NOT_DIRECT_TARGET_PROOF': 'Inspect the associated original letter at the target quantity, not a selected alternate letter',
        'ORIGINAL_AVAILABILITY_UNPROVEN': 'Obtain independent original issuance/version availability evidence; mtime is insufficient',
        'DOCUMENT_LATER_THAN_CALCULATION': 'Keep the recorded later letter separate; obtain source-time evidence before quote-time replay',
        'INQUIRY_FOOTER_AVAILABILITY_UNRESOLVED': 'Reconcile inquiry, print and revision chronology against independently retained originals',
        'DOCUMENT_GROUP_PRESENT_TARGET_QUANTITY_ABSENT': 'Inspect the original associated letter for this quantity; never interpolate a truth label from other breaks',
        'NO_SELECTED_DOCUMENT_GROUP_AT_TARGET_QUANTITY': 'Locate and inspect the original associated customer letter; missing selected coverage is not a false calculation target',
        'INDEPENDENT_CUSTOMER_ACCEPTANCE_RECORD_REQUIRED': 'Obtain a source-bound customer acceptance/order record with exact identity, UOM, currency, amount and time',
        'ACTUAL_CLOSED_JOB_COST_RECORD_REQUIRED': 'Obtain the closed-job actual cost ledger and its material/labor/outside/setup amounts',
        'CURRENT_COST_MANUFACTURING_AND_QUOTE_RECORD_REQUIRED': 'Obtain current valid component cost records and the exact manufacturing specification, then reconcile the supported quote',
        'FULL_RFQ_CURRENT_COST_AND_REVIEW_REQUIRED': 'Freeze the full RFQ, terms and eligibility; retain real traces/drafts/decisions and independent review execution'}
    queue = [{'id': digest(encode([reason, grouped[reason]])), 'reason': reason, 'case_ids': grouped[reason],
              'status': 'BLOCKED_ON_INDEPENDENT_EVIDENCE', 'attempt_budget': 1,
              'required_input': required_inputs.get(reason, 'Inspect the failed original-source or artifact binding; preserve the full failed attempt'),
              'acceptance': 'Re-run a new versioned assessment; preserve frozen targets, attempts, tolerance and prior results'}
             for reason in ordered[:queue_limit]]
    summary = {'cases': len(assessed), 'domains': {d: dict(Counter(c['domains'][d]['state'] for c in assessed)) for d in DOMAINS},
               'legacy_states': dict(Counter(c['legacy_diagnostic']['state'] for c in assessed)),
               'source_files_verified': len(sources), 'source_errors': dict(Counter(source_errors.values())),
               'queue_items': len(queue), 'deferred_groups': max(0, len(ordered) - queue_limit),
               'completed_quote_gate': 'NOT_ESTABLISHED', 'business_outperformance': 'NOT_ESTABLISHED'}
    signed_relative = [Decimal(c['legacy_diagnostic']['signed_relative_error']) for c in assessed
                       if c['legacy_diagnostic']['state'] == 'PRESERVED_UNCHANGED_NOT_RESCORED' and
                       c['legacy_diagnostic']['signed_relative_error'] is not None]
    mean = sum(signed_relative) / len(signed_relative) if signed_relative else None
    variance = sum((v - mean)**2 for v in signed_relative) / (len(signed_relative) - 1) if len(signed_relative) > 1 else None
    summary['internal_calculation_diagnostic'] = {'numeric_pairs': len(signed_relative),
        'mean_signed_relative_error': None if mean is None else str(mean),
        'mean_absolute_relative_error': str(sum(abs(v) for v in signed_relative) / len(signed_relative)) if signed_relative else None,
        'sample_variance_signed_relative_error': None if variance is None else str(variance),
        'legacy_results': dict(Counter(c['legacy_diagnostic']['result']['status'] if c['legacy_diagnostic']['state'] == 'PRESERVED_UNCHANGED_NOT_RESCORED'
            and c['legacy_diagnostic']['result'].get('status') in ('priced', 'no_analog', 'unreplayable') else 'missing_or_invalid' for c in assessed))}
    report = {'schema_version': 1, 'kind': 'keller-ground-truth-assessment', 'as_of': as_of,
              'case_ids_sha256': digest(encode([c['id'] for c in cases])),
              'implementation_sha256': digest(Path(__file__).read_bytes()), 'inputs': evidence.inputs,
              'declared_input_references': {key: config[key] for key in ('evalset', 'bindings', 'raw_bindings', 'documents', 'source_manifest', 'candidate_report')},
              'source_errors': source_errors, 'summary': summary, 'cases': assessed,
              'remediation_queue': queue, 'deferred_remediation': [{'reason': r, 'case_ids': grouped[r]} for r in ordered[queue_limit:]],
              'limits': 'Private exposed diagnostic; checks bind supplied bytes, not issuer authentication or historical availability. No target, grade or business-outcome promotion.'}
    evidence.recheck()
    return publish(config['out'], report, summary, evidence)


def publish(destination, report, summary, evidence):
    path = private_path(destination, directory=True, absent=True)
    require(all(path not in Path(p).parents and Path(p) not in path.parents and Path(p) != path for p in evidence.inputs), 'OUTPUT_INPUT_ALIAS')
    evidence.recheck()
    path.mkdir(mode=0o700)
    private_path(destination, directory=True)
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    files = {}
    try:
        for name, value in [('assessment.private.json' if report['kind'] == 'keller-ground-truth-assessment' else 'decisions.private.json', report),
                            ('aggregate.json', summary)]:
            data = encode(value)
            require(not SECRET.search(data.decode()), 'CREDENTIAL_BEARING_OUTPUT')
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=directory)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            files[name] = digest(data)
        seal = {'schema_version': 1, 'kind': report['kind'], 'files': files, 'inputs': evidence.inputs}
        fd = os.open('seal.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=directory)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encode(seal))
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(directory)
        current = private_path(destination, directory=True).lstat()
        opened = os.fstat(directory)
        require((current.st_dev, current.st_ino) == (opened.st_dev, opened.st_ino), 'OUTPUT_DIRECTORY_CHANGED')
    finally:
        os.close(directory)
    return {**summary, 'output_sha256': files, 'customer_release_authorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('assess', 'decisions'))
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    data = private_bytes(args.config)
    require(not SECRET.search(data.decode('utf-8-sig')), 'CREDENTIAL_BEARING_CONFIG')
    config = parse_json(data)
    if args.command == 'assess':
        result = assess(config)
    else:
        spec = importlib.util.spec_from_file_location('keller_decision_eval', REPO / 'evals/decision-eval.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = module.evaluate(config, sys.modules[__name__])
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, TypeError, OSError, InvalidOperation, subprocess.SubprocessError):
        print('KELLER_EVIDENCE_VALIDATION_FAILED; inspect private inputs and rerun with a new output path', file=sys.stderr)
        sys.exit(2)
