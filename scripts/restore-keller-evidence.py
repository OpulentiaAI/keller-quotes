#!/usr/bin/env python3
"""Restore Keller operator evidence from a pinned archive."""
import argparse
from hashlib import sha256
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
PART_NAME = re.compile(r"keller-operator-evidence-part-\d+\.private\.zip\Z")
BLOB_NAME = re.compile(r"blobs/([0-9a-f]{64})\Z")
END = object()


class RestoreError(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise RestoreError from None


def digest(path):
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stream_digest_and_size(path):
    h = sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            h.update(chunk)
    return h.hexdigest(), size


def stream_member(member, target):
    h = sha256()
    size = 0
    with member, target.open("xb") as out:
        for chunk in iter(lambda: member.read(1024 * 1024), b""):
            size += len(chunk)
            h.update(chunk)
            out.write(chunk)
    target.chmod(0o400)
    return h.hexdigest(), size


def copy_private_file(source, target):
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)
    target.chmod(0o400)


def safe_relative(value):
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")) or value.endswith("/") or "\x00" in value:
        raise RestoreError
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts) or any("\\" in part for part in parts):
        raise RestoreError
    return value


def safe_hex(value):
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise RestoreError
    return value


def safe_count(value):
    if type(value) is not int or value < 0:
        raise RestoreError
    return value


def no_duplicate_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise RestoreError
        obj[key] = value
    return obj


def is_git_checkout(path):
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() == "true"


def reject_existing_symlink(path):
    if os.path.lexists(path) and Path(path).is_symlink():
        raise RestoreError


def reject_symlink_ancestors(path):
    for ancestor in (path, *path.parents):
        if os.path.lexists(ancestor) and Path(ancestor).is_symlink():
            raise RestoreError


def reject_git_destination(path):
    for ancestor in (path, *path.parents):
        if os.path.exists(ancestor) and Path(ancestor).is_dir() and is_git_checkout(ancestor):
            raise RestoreError


def validate_relative_path(value, trie):
    parts = safe_relative(value).split("/")
    node = trie
    for part in parts:
        if node.get(END):
            raise RestoreError
        node = node.setdefault(part, {})
    if node:
        raise RestoreError
    node[END] = True
    return parts


def safe_text(value):
    if not isinstance(value, str) or not value:
        raise RestoreError
    return value


def mkdir_private(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def mkdir_private_tree(root, path):
    current = root
    if path == root:
        return
    for part in path.relative_to(root).parts:
        current = current / part
        current.mkdir(mode=0o700, exist_ok=True)
        current.chmod(0o700)


def restore(catalog_path, catalog_sha256, out_path):
    catalog = Path(catalog_path)
    out = Path(out_path)
    if not out.is_absolute():
        raise RestoreError
    if not HEX64.fullmatch(catalog_sha256):
        raise RestoreError
    if not catalog.exists() or not catalog.is_file() or catalog.is_symlink():
        raise RestoreError
    reject_symlink_ancestors(catalog.absolute())

    reject_symlink_ancestors(out)
    reject_existing_symlink(out)
    out = out.resolve(strict=False)
    reject_git_destination(out)
    if os.path.lexists(out):
        raise RestoreError

    if digest(catalog) != catalog_sha256:
        raise RestoreError

    try:
        data = json.loads(catalog.read_text(encoding="utf-8"), object_pairs_hook=no_duplicate_keys)
    except Exception as exc:
        raise RestoreError from exc

    if data.get("schema_version") != 1 or data.get("kind") != "KELLER_OPERATOR_EVIDENCE_ARCHIVE" or data.get("scope") != "OPERATOR_ONLY":
        raise RestoreError
    for key in ("repository", "anchor_commit", "created_at"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise RestoreError
    if not isinstance(data.get("family_counts"), dict):
        raise RestoreError
    parts = data.get("parts")
    files = data.get("files")
    excluded = data.get("excluded", [])
    if not isinstance(parts, list) or not isinstance(files, list) or not isinstance(excluded, list):
        raise RestoreError

    part_names = set()
    declared_parts = []
    for part in parts:
        if not isinstance(part, dict):
            raise RestoreError
        name = part.get("name")
        sha = safe_hex(part.get("sha256"))
        size = safe_count(part.get("bytes"))
        if not isinstance(name, str) or not PART_NAME.fullmatch(name):
            raise RestoreError
        if name in part_names:
            raise RestoreError
        part_names.add(name)
        declared_parts.append((name, sha, size))

    actual_parts = set()
    for item in catalog.parent.iterdir():
        if PART_NAME.fullmatch(item.name):
            if item.is_symlink() or not item.is_file():
                raise RestoreError
            actual_parts.add(item.name)
    if actual_parts != part_names:
        raise RestoreError

    if not out.parent.exists() or not out.parent.is_dir():
        raise RestoreError
    parent_stat = out.parent.stat()
    if parent_stat.st_uid != os.getuid() or stat.S_IMODE(parent_stat.st_mode) & 0o022:
        raise RestoreError

    work = Path(tempfile.mkdtemp(prefix=".keller-restore-", dir=out.parent))
    created_out = False
    try:
        blob_dir = work / "blobs"
        mkdir_private(blob_dir)
        blob_sources = {}
        blob_primary = {}
        blob_aliases = {}
        path_trie = {}
        logical_paths = {}

        for item in files:
            if not isinstance(item, dict):
                raise RestoreError
            logical = validate_relative_path(item.get("path"), path_trie)
            safe_text(item.get("original_path"))
            sha = safe_hex(item.get("sha256"))
            size = safe_count(item.get("bytes"))
            key = "/".join(logical)
            if key in logical_paths:
                raise RestoreError
            logical_paths[key] = True
            blob_aliases.setdefault(sha, []).append(key)
            if sha in blob_sources and blob_sources[sha] != size:
                raise RestoreError
            blob_sources[sha] = size

        referenced_blobs = set(blob_aliases)
        if not referenced_blobs:
            raise RestoreError

        seen_parts = set()
        for name, expected_sha, expected_size in declared_parts:
            part_path = catalog.parent / name
            if not part_path.exists() or not part_path.is_file() or part_path.is_symlink():
                raise RestoreError
            part_sha, part_size = stream_digest_and_size(part_path)
            if part_sha != expected_sha or part_size != expected_size:
                raise RestoreError
            seen_parts.add(name)
            try:
                with zipfile.ZipFile(part_path) as archive:
                    found = set()
                    for info in archive.infolist():
                        match = BLOB_NAME.fullmatch(info.filename)
                        mode = info.external_attr >> 16
                        if not match or info.is_dir() or stat.S_ISLNK(mode):
                            raise RestoreError
                        blob = match.group(1)
                        if blob in found or blob in blob_primary:
                            raise RestoreError
                        if blob not in referenced_blobs:
                            raise RestoreError
                        temp_blob = blob_dir / blob
                        with archive.open(info) as member:
                            actual_blob, actual_size = stream_member(member, temp_blob)
                        if actual_blob != blob or actual_size != info.file_size:
                            raise RestoreError
                        if blob_sources[blob] != actual_size:
                            raise RestoreError
                        blob_primary[blob] = temp_blob
                        found.add(blob)
            except zipfile.BadZipFile as exc:
                raise RestoreError from exc

        if seen_parts != part_names or set(blob_primary) != referenced_blobs:
            raise RestoreError

        os.mkdir(out, 0o700)
        created_out = True
        out.chmod(0o700)

        primary_for_blob = {}
        for blob, targets in blob_aliases.items():
            primary = out / targets[0]
            mkdir_private_tree(out, primary.parent)
            os.replace(blob_primary[blob], primary)
            primary.chmod(0o400)
            primary_for_blob[blob] = primary

        restored = 0
        for blob, targets in blob_aliases.items():
            primary = primary_for_blob[blob]
            for target in targets[1:]:
                path = out / target
                mkdir_private_tree(out, path.parent)
                copy_private_file(primary, path)
                restored += 1
            restored += 1

        return {"parts": len(declared_parts), "blobs": len(primary_for_blob), "files": restored, "bytes": sum(blob_sources.values())}
    except Exception as exc:
        if created_out and out.exists():
            shutil.rmtree(out)
        raise RestoreError from exc
    finally:
        if work.exists():
            shutil.rmtree(work)


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--catalog-sha256", required=True)
    parser.add_argument("--out", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
        summary = restore(args.catalog, args.catalog_sha256, args.out)
    except RestoreError:
        print("restore failed", file=sys.stderr)
        return 2
    except Exception:
        print("restore failed", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
