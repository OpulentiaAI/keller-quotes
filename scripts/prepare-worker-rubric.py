#!/usr/bin/env python3
"""Project a frozen operator rubric into a normative-only worker/judge view."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys


ROOT = Path(__file__).resolve().parent.parent
KEYS = ('version', 'population', 'validation_weight', 'judge_weight', 'acceptance', 'validation', 'judge')
LIMIT = 1024 * 1024


class Invalid(ValueError):
    pass


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Invalid('duplicate JSON key')
        result[key] = value
    return result


def invalid_constant(_value):
    raise Invalid('invalid JSON number')


def read_source(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            raise Invalid('source must be a regular JSON file within size limit')
        with os.fdopen(fd, 'rb', closefd=False) as source:
            raw = source.read(LIMIT + 1)
        if len(raw) != info.st_size or os.fstat(fd).st_size != info.st_size:
            raise Invalid('source changed while reading')
        return raw
    finally:
        os.close(fd)


def project(raw):
    try:
        source = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (UnicodeError, ValueError) as exc:
        raise Invalid('source is not unique-key JSON') from exc
    if not isinstance(source, dict) or any(key not in source for key in KEYS):
        raise Invalid('missing normative rubric fields')
    for group in ('validation', 'judge'):
        criteria = source[group]
        ids = [f'{group[0].upper()}{number}' for number in range(1, 6)]
        if (not isinstance(criteria, list) or len(criteria) != 5 or
                any(not isinstance(item, dict) or not isinstance(item.get('criterion'), str) or
                    not item['criterion'].strip() or not isinstance(item.get('id'), str) for item in criteria) or
                {item['id'] for item in criteria} != set(ids)):
            raise Invalid('incomplete or duplicate criterion IDs or prose')
    return {key: source[key] for key in KEYS}


def output_location(value, source):
    path = Path(value)
    if not path.is_absolute() or '..' in path.parts or str(path) != os.path.normpath(value):
        raise Invalid('output must be a canonical absolute path')
    parent = path.parent
    current = Path(path.anchor)
    for part in parent.parts[1:]:
        current /= part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise Invalid('unsafe output parent')
    info = parent.lstat()
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise Invalid('output parent must be owner-private')
    if path == source or path == ROOT or ROOT in path.parents:
        raise Invalid('output must be outside the repository and source')
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        raw = read_source(args.source)
        normative = project(raw)
        target = output_location(args.out, Path(args.source).absolute())
        encoded = (json.dumps(normative, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
        proof = project(encoded) == normative
        if not proof:
            raise Invalid('normative equality check failed')
        parent_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(parent_fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise Invalid('output parent must be owner-private')
            fd = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent_fd)
            with os.fdopen(fd, 'wb') as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(encoded)
        finally:
            os.close(parent_fd)
        print(json.dumps({'source_sha256': sha256(raw).hexdigest(),
                          'worker_view_sha256': sha256(encoded).hexdigest(),
                          'normative_equal': proof, 'normative_keys': list(KEYS)}))
        return 0
    except (Invalid, OSError, UnicodeError, ValueError) as exc:
        print(f'rubric preparation failed: {exc if isinstance(exc, Invalid) else type(exc).__name__}',
              file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
