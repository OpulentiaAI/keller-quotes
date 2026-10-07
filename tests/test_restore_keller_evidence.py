import json
import os
from hashlib import sha256
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "restore-keller-evidence.py"


def digest(path):
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def encode_catalog(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


class RestoreArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def blob(self, text):
        data = text.encode("utf-8")
        return sha256(data).hexdigest(), data

    def bundle(self, *, files=None, parts=None, catalog_overrides=None, extra_files=None, extra_parts=None):
        files = files or []
        parts = parts or []
        catalog = {
            "schema_version": 1,
            "kind": "KELLER_OPERATOR_EVIDENCE_ARCHIVE",
            "repository": "opulentiaai/keller-quotes",
            "anchor_commit": "a" * 64,
            "scope": "OPERATOR_ONLY",
            "created_at": "2026-10-07T12:00:00Z",
            "family_counts": {"files": len(files), "parts": len(parts)},
            "parts": [],
            "files": files,
            "excluded": [{"kind": "metadata-only"}],
        }
        if catalog_overrides:
            catalog.update(catalog_overrides)
        parts_data = []
        for index, blobs in enumerate(parts, 1):
            name = f"keller-operator-evidence-part-{index:03d}.private.zip"
            path = self.root / name
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
                for blob_hash, data in blobs:
                    archive.writestr(f"blobs/{blob_hash}", data)
            parts_data.append({"name": name, "sha256": digest(path), "bytes": path.stat().st_size})
        if extra_parts:
            for item in extra_parts:
                parts_data.append(item)
        catalog["parts"] = parts_data
        catalog_path = self.root / "catalog.json"
        catalog_bytes = encode_catalog(catalog)
        catalog_path.write_bytes(catalog_bytes)
        return catalog_path, digest(catalog_path), catalog

    def run_cli(self, catalog, catalog_sha, out, success=True):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--catalog", str(catalog), "--catalog-sha256", catalog_sha, "--out", str(out)],
            capture_output=True,
            text=True,
            check=False,
        )
        if success:
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr.strip(), "restore failed")
        return proc

    def valid_bundle(self):
        dbf_hash, dbf = self.blob("dbf bytes")
        fpt_hash, fpt = self.blob("fpt bytes")
        copy_hash, copy = self.blob("dbf bytes")
        note_hash, note = self.blob("notes")
        files = [
            {"path": "logical/customer/assembly.dbf", "sha256": dbf_hash, "bytes": len(dbf),
             "original_path": "/home/user/legacy/records/customer-001/assembly.dbf"},
            {"path": "logical/customer/assembly-copy.dbf", "sha256": dbf_hash, "bytes": len(dbf),
             "original_path": "/workspace/archive/records/customer-001/assembly-copy.dbf"},
            {"path": "logical/customer/assembly.fpt", "sha256": fpt_hash, "bytes": len(fpt),
             "original_path": "/home/user/legacy/records/customer-001/assembly.fpt"},
            {"path": "logical/customer/notes/readme.txt", "sha256": note_hash, "bytes": len(note),
             "original_path": "/workspace/archive/records/customer-001/notes/readme.txt"},
        ]
        parts = [
            [(dbf_hash, dbf), (fpt_hash, fpt)],
            [(note_hash, note)],
        ]
        return self.bundle(files=files, parts=parts)

    def test_success_restores_paths_aliases_and_modes(self):
        catalog, catalog_sha, _ = self.valid_bundle()
        out = self.root / "restore"
        result = self.run_cli(catalog, catalog_sha, out)
        self.assertEqual(result, {"blobs": 3, "bytes": 23, "files": 4, "parts": 2})
        dbf = out / "logical/customer/assembly.dbf"
        copy = out / "logical/customer/assembly-copy.dbf"
        fpt = out / "logical/customer/assembly.fpt"
        note = out / "logical/customer/notes/readme.txt"
        self.assertTrue(dbf.exists())
        self.assertTrue(copy.exists())
        self.assertTrue(fpt.exists())
        self.assertTrue(note.exists())
        self.assertEqual(dbf.read_text(), "dbf bytes")
        self.assertEqual(fpt.read_text(), "fpt bytes")
        self.assertEqual(note.read_text(), "notes")
        self.assertNotEqual(os.stat(dbf).st_ino, os.stat(copy).st_ino)
        for path in (dbf, copy, fpt, note):
            self.assertEqual(os.stat(path).st_nlink, 1)
        for path in (out, out / "logical", out / "logical/customer", out / "logical/customer/notes"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        for path in (dbf, copy, fpt, note):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o400)

    def test_part_corruption_is_rejected(self):
        catalog, catalog_sha, _ = self.valid_bundle()
        part = self.root / "keller-operator-evidence-part-001.private.zip"
        with part.open("ab") as stream:
            stream.write(b"x")
        out = self.root / "corrupt-out"
        proc = self.run_cli(catalog, catalog_sha, out, success=False)
        self.assertFalse(out.exists())
        self.assertEqual(proc.stdout, "")

    def test_catalog_pin_mismatch_is_rejected(self):
        catalog, catalog_sha, _ = self.valid_bundle()
        out = self.root / "pinned-out"
        proc = self.run_cli(catalog, "b" * 64, out, success=False)
        self.assertFalse(out.exists())
        self.assertEqual(proc.stdout, "")

    def test_traversal_absolute_and_backslash_paths_are_rejected(self):
        bad_paths = ["../escape.txt", "/abs.txt", "nested/../escape.txt", "nested\\escape.txt"]
        for bad in bad_paths:
            with self.subTest(bad=bad):
                dbf_hash, dbf = self.blob("dbf bytes")
                files = [{"path": bad, "sha256": dbf_hash, "bytes": len(dbf),
                          "original_path": "/workspace/archive/records/customer-001/assembly.dbf"}]
                catalog, catalog_sha, _ = self.bundle(files=files, parts=[[(dbf_hash, dbf)]])
                out = self.root / f"bad-{abs(hash(bad))}"
                self.run_cli(catalog, catalog_sha, out, success=False)
                self.assertFalse(out.exists())

    def test_existing_destination_is_rejected(self):
        catalog, catalog_sha, _ = self.valid_bundle()
        out = self.root / "existing"
        out.mkdir()
        (out / "keep.txt").write_text("stay")
        self.run_cli(catalog, catalog_sha, out, success=False)
        self.assertTrue((out / "keep.txt").exists())

    def test_writable_output_parent_is_rejected(self):
        catalog, catalog_sha, _ = self.valid_bundle()
        parent = self.root / "shared-output"
        parent.mkdir(mode=0o700)
        parent.chmod(0o777)
        self.run_cli(catalog, catalog_sha, parent / "restore", success=False)
        self.assertFalse((parent / "restore").exists())

    def test_existing_output_file_is_left_alone(self):
        catalog, catalog_sha, _ = self.valid_bundle()
        out = self.root / "competing"
        out.write_text("stay")
        self.run_cli(catalog, catalog_sha, out, success=False)
        self.assertEqual(out.read_text(), "stay")

    def test_git_checkout_destination_is_rejected(self):
        catalog, catalog_sha, _ = self.valid_bundle()
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        out = repo / "restore"
        self.run_cli(catalog, catalog_sha, out, success=False)
        self.assertFalse(out.exists())

    def test_symlink_destination_is_rejected(self):
        catalog, catalog_sha, _ = self.valid_bundle()
        target = self.root / "target"
        target.mkdir()
        out = self.root / "symlink-out"
        out.symlink_to(target, target_is_directory=True)
        self.run_cli(catalog, catalog_sha, out, success=False)
        self.assertTrue(out.is_symlink())

    def test_duplicate_and_conflicting_catalog_paths_are_rejected(self):
        dbf_hash, dbf = self.blob("dbf bytes")
        cases = [
            [
                {"path": "logical/customer/assembly.dbf", "sha256": dbf_hash, "bytes": len(dbf),
                 "original_path": "/workspace/archive/records/customer-001/assembly.dbf"},
                {"path": "logical/customer/assembly.dbf", "sha256": dbf_hash, "bytes": len(dbf),
                 "original_path": "/workspace/archive/records/customer-001/assembly-copy.dbf"},
            ],
            [
                {"path": "logical/customer", "sha256": dbf_hash, "bytes": len(dbf),
                 "original_path": "/workspace/archive/records/customer-001/assembly.dbf"},
                {"path": "logical/customer/assembly.dbf", "sha256": dbf_hash, "bytes": len(dbf),
                 "original_path": "/workspace/archive/records/customer-001/assembly-copy.dbf"},
            ],
        ]
        for files in cases:
            with self.subTest(files=files):
                catalog, catalog_sha, _ = self.bundle(files=files, parts=[[(dbf_hash, dbf)]])
                out = self.root / f"dup-{abs(hash(tuple(item['path'] for item in files)))}"
                self.run_cli(catalog, catalog_sha, out, success=False)
                self.assertFalse(out.exists())

    def test_duplicate_json_keys_are_rejected(self):
        catalog, _, _ = self.valid_bundle()
        raw = catalog.read_text()
        raw = raw.replace('"kind":"KELLER_OPERATOR_EVIDENCE_ARCHIVE"',
                          '"kind":"KELLER_OPERATOR_EVIDENCE_ARCHIVE","kind":"KELLER_OPERATOR_EVIDENCE_ARCHIVE"', 1)
        catalog.write_text(raw)
        out = self.root / "dup-keys"
        self.run_cli(catalog, digest(catalog), out, success=False)
        self.assertFalse(out.exists())

    def test_symlink_zip_entries_are_rejected(self):
        dbf_hash, dbf = self.blob("dbf bytes")
        part = self.root / "keller-operator-evidence-part-001.private.zip"
        with zipfile.ZipFile(part, "w", compression=zipfile.ZIP_STORED) as archive:
            info = zipfile.ZipInfo(f"blobs/{dbf_hash}")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/tmp/target")
        catalog = {
            "schema_version": 1,
            "kind": "KELLER_OPERATOR_EVIDENCE_ARCHIVE",
            "repository": "opulentiaai/keller-quotes",
            "anchor_commit": "a" * 64,
            "scope": "OPERATOR_ONLY",
            "created_at": "2026-10-07T12:00:00Z",
            "family_counts": {"files": 1, "parts": 1},
            "parts": [{"name": part.name, "sha256": digest(part), "bytes": part.stat().st_size}],
            "files": [{"path": "logical/customer/assembly.dbf", "sha256": dbf_hash, "bytes": len(dbf),
                        "original_path": "/workspace/archive/records/customer-001/assembly.dbf"}],
            "excluded": [{"kind": "metadata-only"}],
        }
        catalog_path = self.root / "catalog.json"
        catalog_path.write_bytes(encode_catalog(catalog))
        out = self.root / "symlink-entry"
        self.run_cli(catalog_path, digest(catalog_path), out, success=False)
        self.assertFalse(out.exists())

    def test_exact_blob_accounting_rejects_missing_or_extra_blobs(self):
        dbf_hash, dbf = self.blob("dbf bytes")
        fpt_hash, fpt = self.blob("fpt bytes")
        extra_hash, extra = self.blob("extra")
        missing_files = [
            {"path": "logical/customer/assembly.dbf", "sha256": dbf_hash, "bytes": len(dbf),
             "original_path": "/workspace/archive/records/customer-001/assembly.dbf"},
            {"path": "logical/customer/assembly.fpt", "sha256": fpt_hash, "bytes": len(fpt),
             "original_path": "/workspace/archive/records/customer-001/assembly.fpt"},
            {"path": "logical/customer/missing.txt", "sha256": extra_hash, "bytes": len(extra),
             "original_path": "/workspace/archive/records/customer-001/missing.txt"},
        ]
        missing_catalog, missing_sha, _ = self.bundle(files=missing_files, parts=[[(dbf_hash, dbf), (fpt_hash, fpt)]])
        extra_catalog, extra_sha, _ = self.bundle(
            files=[
                {"path": "logical/customer/assembly.dbf", "sha256": dbf_hash, "bytes": len(dbf),
                 "original_path": "/workspace/archive/records/customer-001/assembly.dbf"},
            ],
            parts=[[(dbf_hash, dbf), (extra_hash, extra)]],
        )
        for catalog, catalog_sha in ((missing_catalog, missing_sha), (extra_catalog, extra_sha)):
            with self.subTest(catalog=catalog.name):
                out = self.root / f"account-{abs(hash(catalog.name))}"
                self.run_cli(catalog, catalog_sha, out, success=False)
                self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
