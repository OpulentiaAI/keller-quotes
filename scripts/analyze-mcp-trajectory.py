#!/usr/bin/env python3
"""Reconstruct observations from sealed private MCP artifacts; do not regrade them."""

import argparse
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys


ROOT = Path(__file__).resolve().parent.parent
IDS = tuple(f'{group}{i}' for group in ('V', 'J') for i in range(1, 6))
REQUIRED = {'request', 'criteria', 'answer', 'audit', 'grade'}
SHA = re.compile(r'[0-9a-f]{64}\Z')
LIMIT = 128 * 1024 * 1024


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def path_value(value):
    require(isinstance(value, str) and Path(value).is_absolute() and '..' not in Path(value).parts,
            'unsafe artifact path')
    path = Path(value)
    current = Path(path.anchor)
    for piece in path.parts[1:]:
        current /= piece
        info = current.lstat() if current.exists() or current.is_symlink() else None
        require(info is None or not stat.S_ISLNK(info.st_mode), 'symlink path rejected')
    return path


def read_sealed(path, expected=None):
    path = path_value(path)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= LIMIT,
            'artifact must be a regular singly-linked file within size limit')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        require((opened.st_dev, opened.st_ino, opened.st_size) == (info.st_dev, info.st_ino, info.st_size),
                'artifact changed while opening')
        with os.fdopen(fd, 'rb', closefd=False) as source:
            raw = source.read(LIMIT + 1)
        require(len(raw) == info.st_size and os.fstat(fd).st_size == info.st_size, 'artifact changed while reading')
        digest = sha256(raw).hexdigest()
        require(expected is None or digest == expected, 'artifact SHA256 mismatch')
        return raw, digest, (info.st_dev, info.st_ino)
    finally:
        os.close(fd)


def json_object(raw, label, duplicates=None):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                if duplicates is None:
                    raise Invalid(f'{label} contains duplicate JSON keys')
                duplicates.append(key)
            value[key] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (UnicodeError, ValueError) as exc:
        raise Invalid(f'{label} is not JSON') from exc
    require(isinstance(value, dict), f'{label} must be an object')
    return value


def unique_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON key')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def load_attempt(filename):
    manifest_raw, manifest_hash, manifest_identity = read_sealed(str(filename))
    manifest = json_object(manifest_raw, 'manifest')
    require(manifest.get('schema_version') == 1 and
            all(isinstance(manifest.get(key), str) and manifest[key].strip() for key in ('run_id', 'case_id')),
            'invalid manifest schema or identity')
    refs = manifest.get('artifacts')
    require(isinstance(refs, dict) and REQUIRED <= refs.keys() and
            set(refs) <= REQUIRED | {'session'}, 'invalid artifact mapping')
    execution = manifest.get('execution')
    validity = manifest.get('validity')
    require(isinstance(execution, dict) and isinstance(validity, dict) and
            validity.get('status') in ('valid', 'invalid', 'unknown') and
            isinstance(validity.get('reason'), str), 'invalid execution or validity metadata')
    raw, identities = {}, {manifest_identity}
    for name, ref in refs.items():
        require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'} and
                isinstance(ref['sha256'], str) and SHA.fullmatch(ref['sha256']), 'invalid artifact reference')
        raw[name], _, identity = read_sealed(ref['path'], ref['sha256'])
        require(identity not in identities, 'artifact paths alias each other or the manifest')
        identities.add(identity)
    request = json_object(raw['request'], 'request')
    criteria_source = json_object(raw['criteria'], 'criteria')
    answer = json_object(raw['answer'], 'answer')
    duplicate_grade_keys = []
    grade = json_object(raw['grade'], 'grade', duplicate_grade_keys)
    if 'session' in raw:
        try:
            json.loads(raw['session'])
        except (ValueError, UnicodeError) as exc:
            raise Invalid('session snapshot is not JSON') from exc
    identity_ok = (request.get('case_id') == answer.get('case_id') == grade.get('case_id') ==
                   manifest['case_id'] and
                   ('case_id' not in criteria_source or criteria_source['case_id'] == manifest['case_id']))
    return {'manifest': manifest, 'manifest_sha256': manifest_hash, 'raw': raw,
            'identities': identities, 'identity_ok': identity_ok, 'answer': answer, 'grade': grade,
            'duplicate_grade_keys': duplicate_grade_keys}


def grade_snapshot(grade, duplicate_keys=()):
    if duplicate_keys:
        return {'status': 'malformed', 'reason': 'duplicate grade JSON keys'}
    population = grade.get('population')
    if not isinstance(population, str) or not population.strip():
        return {'status': 'malformed', 'reason': 'missing grade population'}
    criteria = grade.get('criteria')
    if not isinstance(criteria, dict) or set(criteria) != set(IDS):
        return {'status': 'malformed', 'reason': 'missing, extra, or duplicate criterion identities'}
    for key in IDS:
        item = criteria[key]
        if not isinstance(item, dict) or type(item.get('passed')) is not bool or not isinstance(item.get('reasons'), list) or \
                any(not isinstance(reason, str) for reason in item['reasons']) or \
                (item['passed'] and bool(item['reasons'])):
            return {'status': 'malformed', 'reason': 'criterion flag or reasons malformed'}
    vp = sum(criteria[key]['passed'] for key in IDS[:5])
    jp = sum(criteria[key]['passed'] for key in IDS[5:])
    if (type(grade.get('validation_passed')) is not int or grade['validation_passed'] != vp or
            type(grade.get('judge_passed')) is not int or grade['judge_passed'] != jp or
            type(grade.get('all_pass')) is not bool or grade['all_pass'] != (vp == 5 and jp == 5)):
        return {'status': 'malformed', 'reason': 'grade counts or all_pass contradict criterion flags'}
    return {'status': 'validated', 'population': population, 'criteria': {key: criteria[key] for key in IDS},
            'validation_passed': vp, 'judge_passed': jp, 'all_pass': grade['all_pass']}


def payload(result):
    content = result.get('content')
    if not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict) or \
            content[0].get('type') != 'text' or not isinstance(content[0].get('text'), str):
        return None
    try:
        value = unique_json(content[0]['text'])
    except (ValueError, Invalid):
        return None
    if not isinstance(value, dict):
        return None
    return value['content'] if isinstance(value.get('content'), dict) else value


def finite_price(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return False
    try:
        return Decimal(str(value)).is_finite() and Decimal(str(value)) > 0
    except InvalidOperation:
        return False


def timeline(raw, answer):
    observations, matches = [], []
    for ordinal, line in enumerate(raw.splitlines(), 1):
        try:
            event = unique_json(line)
        except (ValueError, UnicodeError, Invalid):
            event = None
        if not isinstance(event, dict):
            observations.append({'audit_ordinal': ordinal, 'status': 'malformed',
                                 'event_sha256': sha256(line).hexdigest()})
            continue
        result = event.get('result')
        tool = event.get('tool')
        item = {'audit_ordinal': ordinal, 'started_at': event.get('startedAt'),
                'completed_at': event.get('completedAt'), 'tool': tool if isinstance(tool, str) else None,
                'input_sha256': fingerprint(event['inputs']) if 'inputs' in event else None,
                'result_sha256': fingerprint(result) if 'result' in event else None,
                'action': event['inputs'].get('action') if isinstance(event.get('inputs'), dict) and
                          isinstance(event['inputs'].get('action'), str) else None,
                'draft_id': None, 'status': 'unknown'}
        if not isinstance(tool, str) or 'inputs' not in event or not isinstance(event['inputs'], dict) or 'result' not in event:
            item['status'] = 'malformed'
        elif event.get('error') or event.get('error_code') or isinstance(result, dict) and result.get('isError') is True:
            item['status'] = 'error'
            if isinstance(event.get('error_code'), str):
                item['error_code'] = event['error_code']
        elif result is None:
            item['status'] = 'unknown'
        elif not isinstance(result, dict) or result.get('isError', False) is not False:
            item['status'] = 'malformed'
        elif tool == 'tools/list':
            tools = result.get('tools')
            item['status'] = 'success' if isinstance(tools, list) and all(
                isinstance(t, dict) and isinstance(t.get('name'), str) for t in tools) else 'malformed'
        elif not isinstance(result.get('content'), list) or not result['content'] or not all(
                isinstance(c, dict) and c.get('type') == 'text' and isinstance(c.get('text'), str) and c['text']
                for c in result['content']):
            item['status'] = 'malformed'
        elif tool != 'keller_quote':
            item['status'] = 'success'
            for content in result['content']:
                try:
                    decoded = unique_json(content['text'])
                    if tool in ('keller_polygres', 'keller_sources') and not isinstance(decoded, dict):
                        item['status'] = 'malformed'
                        break
                except Invalid:
                    item['status'] = 'malformed'
                    break
                except ValueError:
                    if tool in ('keller_polygres', 'keller_sources'):
                        item['status'] = 'malformed'
                        break
        else:
            draft = payload(result)
            if draft is None:
                item['status'] = 'malformed'
            else:
                item['draft_id'] = draft.get('draft_id') if isinstance(draft.get('draft_id'), str) else None
                order = draft.get('order')
                lines = order.get('lines') if isinstance(order, dict) else None
                if not isinstance(lines, list) or not lines or any(not isinstance(x, dict) for x in lines):
                    item['status'] = 'malformed'
                elif any(x.get('unit_price') is not None and not finite_price(x['unit_price']) for x in lines):
                    item['status'] = 'malformed'
                elif draft.get('state') == 'PRICED_REQUIRES_REVIEW':
                    item['status'] = 'success' if all(finite_price(x.get('unit_price')) for x in lines) else 'malformed'
                elif draft.get('state') in ('BLOCKED', 'HELD'):
                    item['status'] = 'unpriced' if any(x.get('unit_price') is None for x in lines) else 'held'
                else:
                    item['status'] = 'malformed'
                if isinstance(answer.get('draft'), dict) and draft == answer['draft']:
                    matches.append(ordinal)
        observations.append(item)
    return observations, {'draft_id': answer.get('draft', {}).get('draft_id') if isinstance(answer.get('draft'), dict) else None,
                          'linked_audit_ordinal': matches[0] if len(matches) == 1 else None,
                          'matching_audit_ordinals': matches, 'ambiguous': len(matches) > 1}


def describe(attempt):
    manifest = attempt['manifest']
    observations, linkage = timeline(attempt['raw']['audit'], attempt['answer'])
    grade = grade_snapshot(attempt['grade'], attempt['duplicate_grade_keys'])
    evidence_ok = bool(observations) and all(item['status'] not in ('malformed', 'unknown') for item in observations)
    provenance_known = all(isinstance(manifest['execution'].get(key), str) and
                           manifest['execution'][key].strip() and
                           manifest['execution'][key].strip().lower() not in ('unknown', 'unavailable')
                           for key in ('checkout', 'model', 'skill'))
    return {'run_id': manifest['run_id'], 'case_id': manifest['case_id'],
            'manifest_sha256': attempt['manifest_sha256'], 'artifacts': manifest['artifacts'],
            'observation_digests': 'input_sha256/result_sha256 hash sorted-key compact UTF-8 JSON values; malformed event_sha256 hashes the original line bytes without line terminator',
            'source_binding': 'artifact hashes supplied by reconstruction manifest; not retroactive proof of original grading inputs or cryptographic attestation',
            'execution': manifest['execution'], 'execution_provenance_known': provenance_known,
            'validity': manifest['validity'],
            'artifact_identity_valid': attempt['identity_ok'], 'audit_readable': evidence_ok,
            'session': {'status': 'snapshot_recorded', 'reference': manifest['artifacts']['session']} if 'session' in manifest['artifacts'] else {'status': 'unavailable'},
            'trajectory': observations, 'final_answer': linkage, 'original_grade': grade,
            'price_diagnostics': {'artifact': 'grade', 'json_pointer': '/price_diagnostics',
                                  'status': 'recorded_not_recomputed'} if 'price_diagnostics' in attempt['grade'] else {'status': 'unavailable'}}


def comparison(current, baseline):
    a, b = current['original_grade'], baseline['original_grade']
    issues = []
    if current['case_id'] != baseline['case_id']:
        issues.append('case_id differs')
    if a.get('population') != b.get('population'):
        issues.append('grade populations differ')
    for key in ('request', 'criteria'):
        if current['artifacts'][key]['sha256'] != baseline['artifacts'][key]['sha256']:
            issues.append(f'{key} bytes differ')
    for side, report in (('current', current), ('baseline', baseline)):
        if report['validity']['status'] != 'valid' or not report['execution_provenance_known'] or \
                not report['artifact_identity_valid'] or not report['audit_readable'] or report['original_grade']['status'] != 'validated':
            issues.append(f'{side} validity, identity, evidence, or grade untrustworthy')
    differences = {key: {'baseline': baseline['execution'].get(key), 'current': current['execution'].get(key)}
                   for key in set(current['execution']) | set(baseline['execution'])
                   if current['execution'].get(key) != baseline['execution'].get(key)}
    if issues:
        return {'status': 'not_comparable', 'reasons': issues, 'execution_differences': differences}
    losses, gains = [], []
    for key in IDS:
        before, after = b['criteria'][key], a['criteria'][key]
        change = {'criterion': key, 'before_reasons': before['reasons'], 'after_reasons': after['reasons']}
        if before['passed'] and not after['passed']:
            losses.append(change)
        elif not before['passed'] and after['passed']:
            gains.append(change)
    return {'status': 'regression' if losses else 'no_observed_criterion_loss', 'losses': losses,
            'gains': gains, 'execution_differences': differences,
            'warning': 'No observed criterion loss does not establish all-pass or accuracy improvement.'}


def output_path(path, identities):
    require('..' not in Path(path).parts, 'unsafe output path')
    path = Path(os.path.abspath(path))
    require(path.suffix == '.json' and
            path != ROOT and ROOT not in path.parents, 'output must be private JSON outside checkout')
    parent = path.parent
    require(parent.is_dir() and not parent.is_symlink(), 'output parent must exist')
    path_value(str(parent))
    info = parent.stat()
    require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) & 0o077 == 0,
            'output parent must be owner-only')
    require(not path.exists() and not path.is_symlink(), 'output already exists')
    require(all(path != Path(ref) for ref in identities), 'output aliases input')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--baseline')
    parser.add_argument('--fail-on-regression', action='store_true')
    args = parser.parse_args()
    if args.fail_on_regression and not args.baseline:
        parser.error('--fail-on-regression requires --baseline')
    try:
        attempt = load_attempt(args.manifest)
        baseline = load_attempt(args.baseline) if args.baseline else None
        result = {'schema_version': 1, 'attempt': describe(attempt)}
        if baseline:
            result['baseline'] = describe(baseline)
            result['comparison'] = comparison(result['attempt'], result['baseline'])
        inputs = {str(Path(args.manifest).absolute()), *(ref['path'] for ref in attempt['manifest']['artifacts'].values())}
        if baseline:
            inputs |= {str(Path(args.baseline).absolute()), *(ref['path'] for ref in baseline['manifest']['artifacts'].values())}
        destination = output_path(args.out, inputs)
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(result, stream, indent=2)
            stream.write('\n')
        return int(args.fail_on_regression and result['comparison']['status'] != 'no_observed_criterion_loss')
    except (Invalid, OSError, UnicodeError, ValueError) as exc:
        print(f'analysis failed: {exc if isinstance(exc, Invalid) else type(exc).__name__}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
