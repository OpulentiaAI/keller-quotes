#!/usr/bin/env python3
"""Generate a private, versioned customer-document target set from a verified CSV."""
import argparse
import csv
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat


DATASET = 'keller-document-eval-v2'
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
SHA = re.compile(r'^[0-9a-f]{64}$')
UNIT = re.compile(r'^\d+(?:\.\d{1,5})?$')
REQUIRED = {'quote_no', 'quote_date', 'letter_date', 'quote_letter', 'part_no', 'description',
            'customer_id', 'quantity', 'unit_price', 'extended_price', 'price_basis', 'status',
            'source_document', 'source_document_sha256', 'source_transcript_sha256', 'source_price_field'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def rank(salt, key):
    return digest((salt + '\n' + key).encode())


def preflight(register, destination):
    repo = Path(__file__).resolve().parent.parent
    destination = Path(os.path.abspath(destination))
    register = Path(os.path.abspath(register))
    if destination.suffix != '.jsonl' or destination == register or \
            destination == destination.with_suffix('.manifest.json') or \
            destination == repo or repo in destination.parents:
        raise ValueError('output must be a new private .jsonl file outside the checkout and distinct from input')
    manifest = destination.with_suffix('.manifest.json')
    if manifest == register:
        raise ValueError('manifest aliases input')
    if not destination.parent.is_dir():
        raise ValueError('output directory does not exist')
    private_ancestor = False
    for parent in (destination.parent, *destination.parent.parents):
        if parent.is_symlink():
            raise ValueError(f'symlink output ancestor: {parent}')
        info = parent.stat()
        if info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0:
            private_ancestor = True
    if not private_ancestor:
        raise ValueError('output requires an owner-only private ancestor')
    for path in (destination, manifest):
        if path.exists() or path.is_symlink():
            raise FileExistsError(f'refusing existing output: {path}')
    return destination, manifest


def generate(register, destination, count):
    if count <= 0:
        raise ValueError('count must be positive')
    destination, manifest_path = preflight(register, destination)
    raw = register.read_bytes()
    families = {}
    identities = set()
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8'), newline=''))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames) or \
            not REQUIRED.issubset(reader.fieldnames):
        raise ValueError('duplicate or missing CSV headers')
    for i, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f'row {i}: malformed CSV field count')
        if row['price_basis'] != 'customer_quote_pdf' or row['status'] != 'unknown':
            raise ValueError(f'row {i}: unverified price basis/outcome')
        if row.get('won_date', '').strip():
            raise ValueError(f'row {i}: document outcome has nonblank won_date')
        path = row['source_document']
        if not path.endswith('.pdf') or path.startswith('/') or '\\' in path or ':' in path or any(
                not bit or bit in ('.', '..') for bit in path.split('/')):
            raise ValueError(f'row {i}: unsafe document path')
        if not SHA.fullmatch(row['source_document_sha256']) or not SHA.fullmatch(row['source_transcript_sha256']):
            raise ValueError(f'row {i}: missing/invalid document or transcript SHA')
        if row['source_price_field'] not in ('PRICE', 'QUOTEPRICE') or not row['quote_letter'].strip():
            raise ValueError(f'row {i}: missing price-field/letter metadata')
        for field in ('quote_date', 'letter_date'):
            if not DATE.fullmatch(row[field]):
                raise ValueError(f'row {i}: invalid {field}')
            try:
                date.fromisoformat(row[field])
            except ValueError as exc:
                raise ValueError(f'row {i}: invalid {field}') from exc
        if row['quote_date'] != row['letter_date']:
            raise ValueError(f'row {i}: register quote_date must equal verified letter_date')
        if not row['quote_no'].strip() or row['quote_no'] != row['quote_no'].strip() or \
                not (row['part_no'].strip() or row['description'].strip()):
            raise ValueError(f'row {i}: missing source quote or part')
        if not re.fullmatch(r'[1-9]\d*', row['quantity']) or not UNIT.fullmatch(row['unit_price']):
            raise ValueError(f'row {i}: quantity or unit price exceeds precision contract')
        try:
            qty = int(row['quantity'])
            unit = Decimal(row['unit_price'])
            extension = Decimal(row['extended_price'])
        except (ValueError, InvalidOperation) as exc:
            raise ValueError(f'row {i}: invalid price/quantity') from exc
        if qty > 2**53 - 1 or unit <= 0 or not unit.is_finite() or not extension.is_finite() or \
                extension <= 0 or extension.as_tuple().exponent != -2 or \
                (unit * qty).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) != extension:
            raise ValueError(f'row {i}: price or printed extension fails reconciliation')
        identity = (row['quote_no'], row.get('item_no', ''), row['quantity'])
        if identity in identities:
            raise ValueError(f'row {i}: duplicate quote/item/quantity identity')
        identities.add(identity)
        family = re.sub(r'[^A-Z0-9]', '', row['part_no'].upper()) or 'QUOTE:' + row['quote_no']
        families.setdefault(family, []).append(row)
    if len(families) < count:
        raise ValueError(f'only {len(families)} eligible families; requested {count}')
    selected = sorted(families, key=lambda family: (rank(DATASET + '-family', family), family))[:count]
    cases = []
    for family in selected:
        row = min(families[family], key=lambda r: (rank(DATASET + '-break', '\n'.join(
            (r['quote_no'], r['quote_letter'], r['quantity'], r['source_document_sha256']))),
            r['quote_no'], r['quote_letter'], r['quantity']))
        cases.append({
            'id': DATASET + '-' + digest(family.encode())[:20],
            'source_quote_no': row['quote_no'],
            'input': {'part_no': row['part_no'], 'description': row['description'],
                      'quantity': int(row['quantity']), 'customer_id': row['customer_id']},
            'actual_unit_price': float(row['unit_price']),
            'quote_date': row['letter_date'],
            'target_quote_letter': row['quote_letter'], 'status': 'unknown',
            'target_unit_price': row['unit_price'],
            'target_price_basis': row['price_basis'], 'target_document': row['source_document'],
            'target_document_sha256': row['source_document_sha256'],
            'target_transcript_sha256': row['source_transcript_sha256'],
            'target_source_field': row['source_price_field'],
            'target_printed_extension': row['extended_price'],
        })
    data = ''.join(json.dumps(case, sort_keys=True) + '\n' for case in cases).encode()
    manifest = {
        'schema_version': 2, 'dataset': DATASET, 'cases': len(cases),
        'eligible_part_families': len(families), 'register_rows': sum(map(len, families.values())),
        'register_sha256': digest(raw), 'cases_sha256': digest(data),
        'generator_sha256': digest(Path(__file__).read_bytes()),
        'selection': 'SHA256 salted family rank, then independently salted break rank; one break per family; no outcomes/errors used',
        'cutoff': 'customer letter_date exclusive (the dated price-bearing PDF event); input register quote_date required equal letter_date; original QUOTEN date is unavailable; later revisions excluded by estimator date_stamp filter',
        'limits': 'Verified PDF targets are issued customer quote prices, not costs or confirmed sales. Frozen snapshot, not a true backtest. Different-register comparison is a data-source experiment, not estimator improvement.',
    }
    created_case = False
    created_manifest = False
    try:
        with os.fdopen(os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as output:
            created_case = True
            output.write(data)
        with os.fdopen(os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
            created_manifest = True
            json.dump(manifest, output, indent=2)
            output.write('\n')
    except Exception:
        if created_manifest:
            manifest_path.unlink()
        if created_case:
            destination.unlink()
        raise
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('verified_document_csv', type=Path)
    parser.add_argument('output_jsonl', type=Path)
    parser.add_argument('--count', type=int, default=250)
    args = parser.parse_args()
    print(json.dumps(generate(args.verified_document_csv, args.output_jsonl, args.count), indent=2))
