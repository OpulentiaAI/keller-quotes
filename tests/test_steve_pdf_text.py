"""Synthetic PDFs only; text extraction is not CAD verification or a price oracle."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_steve_source_evidence import ROOT, reader


def pdf_bytes(pages):
    kids = ' '.join(f'{4 + 2 * i} 0 R' for i in range(len(pages)))
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               f'<< /Type /Pages /Count {len(pages)} /Kids [{kids}] >>'.encode(),
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>']
    for i, text in enumerate(pages):
        escaped = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        content = f'BT /F1 12 Tf 40 750 Td ({escaped}) Tj ET'.encode('cp1252') if text else b''
        objects.extend([
            (f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
             f'/Resources << /Font << /F1 3 0 R >> >> /Contents {5 + 2 * i} 0 R >>').encode(),
            f'<< /Length {len(content)} >>\nstream\n'.encode() + content + b'\nendstream'])
    result, offsets = bytearray(b'%PDF-1.4\n'), [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f'{i} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(result)
    result.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        result.extend(f'{offset:010d} 00000 n \n'.encode())
    result.extend((f'trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n'
                   f'startxref\n{xref}\n%%EOF\n').encode())
    return bytes(result)


class PdfTextTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = pdf_bytes(['SYNTHETIC cafe: caf\xe9; length 100 mm', 'SYNTHETIC Deburr all edges', ''])
        self.path = self.root / 'drawing.pdf'
        self.path.write_bytes(self.data)
        self.sha = hashlib.sha256(self.data).hexdigest()
        self.bindings = {'pdfs': str(self.root)}

    def request(self, **changes):
        return {'action': 'pdf_text', 'source_set': 'pdfs', 'path': 'drawing.pdf', 'page': 1, **changes}

    def call(self, **changes):
        return reader.read(self.bindings, reader.validate(self.request(**changes)))

    def test_selected_page_and_unicode_continuations_remain_hash_bound(self):
        first = self.call(limit=23)
        self.assertEqual(first['citation']['pdf_sha256'], self.sha)
        self.assertEqual((first['page'], first['page_count']), (1, 3))
        self.assertEqual(first['status'], 'text_extracted')
        self.assertEqual(first['offset_unit'], 'unicode_characters')
        self.assertTrue(first['has_more'])
        remainder = self.call(offset=first['next_offset'], expected_pdf_sha256=self.sha,
                              expected_text_sha256=first['text_sha256'])
        self.assertIn('caf\xe9; length 100 mm', first['content'] + remainder['content'])
        self.assertEqual(first['text_sha256'], remainder['text_sha256'])
        self.assertFalse(remainder['has_more'])
        page_two = self.call(page=2, expected_pdf_sha256=self.sha)
        self.assertIn('Deburr all edges', page_two['content'])
        self.assertNotIn('length', page_two['content'])
        self.assertIn('not verified geometry', first['extraction_note'])
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_no_text_is_not_absent_specification(self):
        result = self.call(page=3, expected_pdf_sha256=self.sha)
        self.assertEqual(result['status'], 'no_extractable_text')
        self.assertFalse(result['has_more'])
        self.assertIn('OCR or visual review', result['extraction_note'])

    def retained_fixture(self):
        home = self.root / 'home'
        home.mkdir(mode=0o700)
        root = home
        for name in ('.local', 'share', 'keller-quotes', 'intake'):
            root = root / name
            root.mkdir(mode=0o700)
        bundle = root / '00000000-0000-0000-0000-000000000001'
        bundle.mkdir(mode=0o700)
        attachment = bundle / 'attachment-0.bin'
        attachment.write_bytes(self.data)
        attachment.chmod(0o400)
        bundle.chmod(0o500)
        self.addCleanup(lambda: bundle.chmod(0o700))
        request = {'action': 'pdf_text', 'source_set': 'intake', 'page': 1,
                   'locator': f'keller-intake:{bundle.name}/attachment-0.bin',
                   'expected_pdf_sha256': self.sha}
        return home, root, bundle, attachment, request

    def test_retained_attachment_text_uses_exact_locator_and_hash_without_archive_copy(self):
        home, root, _, _, request = self.retained_fixture()
        self.path.unlink()
        with patch.dict(os.environ, {'HOME': str(home)}):
            result = reader.read({'intake': str(root)}, reader.validate(request))
            self.assertIn('length 100 mm', result['content'])
            self.assertEqual(result['citation']['locator'], request['locator'])
            self.assertEqual(result['citation']['pdf_sha256'], self.sha)
            page_two = reader.read({'intake': str(root)}, reader.validate({**request, 'page': 2}))
            self.assertIn('Deburr all edges', page_two['content'])
            with patch.object(reader, 'pdf_command') as command, self.assertRaisesRegex(reader.InvalidRequest, 'PDF hash mismatch'):
                reader.read({'intake': str(root)}, reader.validate({**request, 'expected_pdf_sha256': '0' * 64}))
            command.assert_not_called()

    def test_retained_selection_cannot_list_read_originals_or_omit_hash_binding(self):
        home, root, _, _, request = self.retained_fixture()
        for changes in ({'locator': None}, {'locator': '/etc/passwd'},
                        {'locator': request['locator'].replace('attachment-0.bin', 'original-request.json')},
                        {'locator': request['locator'].replace('attachment-0.bin', 'attachment-20.bin')},
                        {'locator': request['locator'].replace('attachment-0.bin', '../attachment-0.bin')},
                        {'path': 'drawing.pdf'}, {'expected_pdf_sha256': None},
                        {'action': 'list'}, {'action': 'read'}, {'source_set': 'pdfs'}):
            with self.subTest(changes=changes), self.assertRaises(reader.InvalidRequest):
                reader.validate({**request, **changes})
        missing = {k: v for k, v in request.items() if k != 'expected_pdf_sha256'}
        with self.assertRaisesRegex(reader.InvalidRequest, 'requires expected_pdf_sha256'):
            reader.validate(missing)
        with patch.dict(os.environ, {'HOME': str(home)}):
            with self.assertRaisesRegex(reader.InvalidRequest, 'not configured'):
                reader.read({}, reader.validate(request))
            with self.assertRaisesRegex(reader.InvalidRequest, "owner's retained intake root"):
                reader.read({'intake': str(self.root)}, reader.validate(request))
            first = reader.read({'intake': str(root)}, reader.validate({**request, 'limit': 10}))
            remainder = reader.read({'intake': str(root)}, reader.validate({**request,
                'offset': first['next_offset'], 'expected_text_sha256': first['text_sha256']}))
            self.assertIn('length 100 mm', first['content'] + remainder['content'])

    def test_retained_storage_enforces_private_immutable_owner_and_single_link(self):
        home, root, bundle, attachment, request = self.retained_fixture()
        with patch.dict(os.environ, {'HOME': str(home)}):
            for path, bad_mode, valid_mode in ((root.parent, 0o755, 0o700), (root, 0o755, 0o700),
                    (bundle, 0o700, 0o500), (attachment, 0o600, 0o400), (attachment, 0o440, 0o400)):
                path.chmod(bad_mode)
                try:
                    with self.subTest(path=path.name, mode=bad_mode), self.assertRaisesRegex(reader.InvalidRequest, 'private immutable'):
                        reader.read({'intake': str(root)}, reader.validate(request))
                finally:
                    path.chmod(valid_mode)
            with patch.object(reader.os, 'getuid', return_value=os.getuid() + 1):
                with self.assertRaisesRegex(reader.InvalidRequest, 'private immutable'):
                    reader.read({'intake': str(root)}, reader.validate(request))
            alias = self.root / 'hardlink'
            os.link(attachment, alias)
            with self.assertRaisesRegex(reader.InvalidRequest, 'private immutable'):
                reader.read({'intake': str(root)}, reader.validate(request))
            alias.unlink()

    def test_retained_symlink_components_are_rejected(self):
        home, root, bundle, attachment, request = self.retained_fixture()
        with patch.dict(os.environ, {'HOME': str(home)}):
            for target in (attachment, bundle, root.parent):
                parent_mode = target.parent.stat().st_mode & 0o777
                target_mode = target.stat().st_mode & 0o777
                directory = target.is_dir()
                target.parent.chmod(0o700)
                if directory:
                    target.chmod(0o700)
                moved = self.root / 'moved'
                target.rename(moved)
                moved.chmod(target_mode)
                target.symlink_to(moved, target_is_directory=moved.is_dir())
                target.parent.chmod(parent_mode)
                try:
                    with self.subTest(target=target.name), self.assertRaises((reader.InvalidRequest, OSError)):
                        reader.read({'intake': str(root)}, reader.validate(request))
                finally:
                    target.parent.chmod(0o700)
                    target.unlink()
                    if directory:
                        moved.chmod(0o700)
                    moved.rename(target)
                    target.chmod(target_mode)
                    target.parent.chmod(parent_mode)

    def test_explicit_selection_limits_and_owner_confinement(self):
        bad = [{'page': None}, {'page': 0}, {'page': True}, {'page': 10001}, {'page': 2},
               {'offset': 1}, {'offset': -1}, {'limit': 4097}, {'limit': True},
               {'expected_pdf_sha256': 'A' * 64}, {'expected_pdf_sha256': None},
               {'offset': 1, 'expected_pdf_sha256': self.sha}, {'expected_text_sha256': 'bad'},
               {'source_set': 'transcripts'}, {'path': 'drawing.txt'}, {'encoding': 'base64'},
               {'path': '../drawing.pdf'}, {'path': '/etc/passwd'}, {'path': 'secret.pdf'}]
        for change in bad:
            with self.subTest(change=change), self.assertRaises(reader.InvalidRequest):
                reader.validate(self.request(**change))
        request = self.request()
        del request['page']
        with self.assertRaises(reader.InvalidRequest):
            reader.validate(request)
        (self.root / 'alias.pdf').symlink_to(self.path)
        with self.assertRaises((reader.InvalidRequest, OSError)):
            self.call(path='alias.pdf')

    def test_source_and_text_mismatches_fail_without_mixing_pages(self):
        with patch.object(reader, 'pdf_command') as command, self.assertRaisesRegex(reader.InvalidRequest, 'PDF hash mismatch'):
            self.call(expected_pdf_sha256='0' * 64)
        command.assert_not_called()
        with self.assertRaisesRegex(reader.InvalidRequest, 'text hash mismatch'):
            self.call(offset=1, expected_pdf_sha256=self.sha, expected_text_sha256='0' * 64)
        page = self.call()
        with self.assertRaisesRegex(reader.InvalidRequest, 'offset exceeds'):
            self.call(offset=1000, expected_pdf_sha256=self.sha, expected_text_sha256=page['text_sha256'])
        with self.assertRaisesRegex(reader.InvalidRequest, 'page exceeds'):
            self.call(page=4, expected_pdf_sha256=self.sha)
        command = reader.pdf_command

        def mutate(fd, args):
            result = command(fd, args)
            if args[0] == 'pdftotext':
                self.path.write_bytes(self.data + b'\n')
            return result

        with patch.object(reader, 'pdf_command', side_effect=mutate), self.assertRaisesRegex(reader.InvalidRequest, 'changed during'):
            self.call()

    def test_malformed_encrypted_oversized_and_ambiguous_metadata_fail_closed(self):
        for data in (b'not a PDF at all', b'%PDF-1.4\ninvalid objects'):
            self.path.write_bytes(data)
            with self.assertRaises(reader.InvalidRequest):
                self.call()
        self.path.write_bytes(self.data)
        with self.path.open('r+b') as file:
            file.truncate(reader.MAX_PDF_BYTES + 1)
        with self.assertRaisesRegex(reader.InvalidRequest, '32 MiB'):
            self.call()
        self.path.write_bytes(self.data)
        for info in ('Pages: 3\nEncrypted: yes\n', 'Pages: 3\n',
                     'Pages: 999\nPages: 3\nEncrypted: no\n', 'Pages: 10001\nEncrypted: no\n'):
            with self.subTest(info=info), patch.object(reader, 'pdf_command', return_value=info):
                with self.assertRaises(reader.InvalidRequest):
                    self.call()

    def test_dependency_time_output_warning_and_encoding_failures_are_not_empty_pages(self):
        with patch.object(reader.subprocess, 'run', side_effect=FileNotFoundError()):
            with self.assertRaisesRegex(reader.InvalidRequest, 'install poppler-utils'):
                self.call()
        with patch.object(reader.subprocess, 'run', side_effect=subprocess.TimeoutExpired('pdftotext', 4)):
            with self.assertRaisesRegex(reader.InvalidRequest, 'timed out'):
                self.call()
        fd = os.open(self.path, os.O_RDONLY)
        self.addCleanup(lambda: os.close(fd))
        for script in ("import sys; sys.stdout.write('x'*200000)",
                       "import sys; sys.stderr.write('parser warning'); print('partial text')",
                       "import sys; sys.stdout.buffer.write(bytes([255]))"):
            with self.subTest(script=script), self.assertRaises(reader.InvalidRequest):
                reader.pdf_command(fd, [sys.executable, '-c', script])
        with patch.object(reader, 'PDF_TIMEOUT', .05), self.assertRaisesRegex(reader.InvalidRequest, 'timed out'):
            reader.pdf_command(fd, [sys.executable, '-c', 'import time; time.sleep(2)'])
        with patch.dict(os.environ, {'PDF_TEST_SENTINEL': 'not-for-child'}):
            text = reader.pdf_command(fd, [sys.executable, '-c',
                'import os; print(os.environ.get("PDF_TEST_SENTINEL", "absent"))'])
        self.assertEqual(text.strip(), 'absent')

    def test_native_extraction_evidence_survives_retention_and_named_quote_review(self):
        from test_arsumbris_quote import NativeQuoteTest
        native = NativeQuoteTest()
        native.setUp()
        self.addCleanup(native.doCleanups)
        config = self.root / 'sources.json'
        config.write_text(json.dumps(self.bindings))
        config.chmod(0o600)
        script = """import {createPlugin} from './arsumbris/sources/tool.ts';
console.log(JSON.stringify(await createPlugin({workspace: process.cwd()}).invoke(JSON.parse(process.argv[1]))));"""
        response = subprocess.run(['node', '--input-type=module', '-e', script, json.dumps(self.request())],
            cwd=ROOT, env={**os.environ, 'KELLER_PYTHON': sys.executable, 'KELLER_SOURCE_CONFIG': str(config)},
            text=True, capture_output=True, check=True, timeout=20)
        result = json.loads(response.stdout)
        self.assertFalse(result.get('isError'), result)
        evidence = result['content']
        self.assertIn('length 100 mm', evidence['content'])
        worksheet = self.root / 'worksheet.json'
        worksheet.write_text('Synthetic estimator-reviewed USD cost inputs, not from drawing text')
        uploads = [{'id': 'drawing', 'path': str(self.path), 'media_type': 'application/pdf'},
                   {'id': 'worksheet', 'path': str(worksheet), 'media_type': 'application/json'}]
        manifest = self.root / 'uploads.json'
        manifest.write_text(json.dumps(uploads))
        original = json.loads((ROOT / 'estimator/examples/should-cost-intake.json').read_text())
        part = original['parts'][0]
        part['source_evidence'][0]['page'] = evidence['page']
        part['geometry'][0]['review']['reason'] = 'Synthetic transcription of length 100 mm; not CAD verification'
        request_file = self.root / 'original.json'
        request_file.write_text(json.dumps(original))
        retained = subprocess.run(['node', str(ROOT / 'estimator/node_modules/tsx/dist/cli.mjs'),
            str(ROOT / 'estimator/src/intake-cli.ts'), str(request_file), '--attachments', str(manifest),
            '--operator', 'Synthetic Operator'], env={**os.environ, 'HOME': str(native.home)},
            capture_output=True, text=True, check=True, timeout=20)
        path = Path(json.loads(retained.stdout)['request_path'])
        self.addCleanup(lambda: path.parent.chmod(0o700))
        request = json.loads(path.read_text())
        drawing = next(a for a in request['intake']['attachments'] if a['id'] == 'drawing')
        self.assertEqual(drawing['sha256'], evidence['citation']['pdf_sha256'])
        retained_selection = {'action': 'pdf_text', 'source_set': 'intake', 'locator': drawing['locator'],
                              'page': 1, 'expected_pdf_sha256': drawing['sha256']}
        def read_retained():
            response = subprocess.run(['node', '--input-type=module', '-e', script, json.dumps(retained_selection)],
                cwd=ROOT, env={**os.environ, 'HOME': str(native.home), 'KELLER_PYTHON': sys.executable,
                               'KELLER_SOURCE_CONFIG': str(config)}, text=True, capture_output=True, check=True, timeout=20)
            return json.loads(response.stdout)
        self.assertTrue(read_retained().get('isError'))
        config.write_text(json.dumps({**self.bindings, 'intake': str(path.parent.parent)}))
        self.path.unlink()
        recovered = read_retained()
        self.assertFalse(recovered.get('isError'), recovered)
        self.assertEqual(recovered['content']['content'], evidence['content'])
        self.assertEqual(recovered['content']['text_sha256'], evidence['text_sha256'])
        self.assertEqual(recovered['content']['citation']['locator'], drawing['locator'])
        quoted = native.invoke(request, corpus=None, no_database=True)
        self.assertFalse(quoted.get('isError'), quoted)
        content = quoted['content']
        self.assertEqual(content['state'], 'PRICED_REQUIRES_REVIEW')
        self.assertEqual(content['total'], 120)
        self.assertEqual(content['order']['lines'][0]['cost_breakdown']['estimated_line_margin_pct']['base'], 25)
        self.assertEqual(content['order']['request'], request)
        self.assertFalse(content['review']['customer_release_authorized'])
        self.assertIsNone(content['order']['provenance']['register_sha256'])
        drawing_bytes = path.parent / 'attachment-0.bin'
        drawing_bytes.chmod(0o600)
        drawing_bytes.write_bytes(pdf_bytes(['SYNTHETIC changed length 200 mm']))
        drawing_bytes.chmod(0o400)
        self.assertTrue(read_retained().get('isError'))
        self.assertTrue(native.invoke(request, corpus=None, no_database=True).get('isError'))


if __name__ == '__main__':
    unittest.main()
