"""Independent JW-22 utility fixtures, not historical workflow acceptance."""

import codecs
import copy
import csv
import hashlib
import io
import unittest

from jw.csv_archive import archive_identity, normalize_csv, export_safe_csv


class CSVArchiveTests(unittest.TestCase):
    def test_bom_duplicate_unknown_headings_and_multiline(self):
        raw = codecs.BOM_UTF8 + (
            'name,name,unknown,date,empty\r\n'
            '"Doe, Jane","line 1\r\nline 2","say ""hi""",03/04/05,\r\n'
        ).encode()
        original = raw[:]
        data = normalize_csv(raw)
        self.assertEqual(data['headings'], ['name', 'name', 'unknown', 'date', 'empty'])
        self.assertEqual(data['rows'], [['Doe, Jane', 'line 1\r\nline 2',
                                        'say "hi"', '03/04/05', '']])
        self.assertEqual(data['encoding'], 'utf-8-sig')
        self.assertEqual(data['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(raw, original)
        self.assertEqual(normalize_csv(raw), data)
        exported = export_safe_csv(data)
        self.assertTrue(exported.startswith(codecs.BOM_UTF8))
        self.assertEqual(normalize_csv(exported)['rows'], data['rows'])

    def test_explicit_windows_encoding_preserves_original(self):
        raw = 'name,note\nAndré,€100\n'.encode('cp1252')
        original = raw[:]
        with self.assertRaises(ValueError):
            normalize_csv(raw)
        data = normalize_csv(raw, encoding='windows-1252')
        self.assertEqual(data['rows'], [['André', '€100']])
        self.assertEqual(data['encoding'], 'windows-1252')
        self.assertEqual(raw, original)
        self.assertEqual(data['sha256'], archive_identity(original))
        exported = export_safe_csv(data)
        self.assertNotEqual(exported, raw)
        self.assertEqual(normalize_csv(exported)['rows'], data['rows'])

    def test_identity_is_exact_bytes_not_logical_rows(self):
        self.assertEqual(archive_identity(b'abc'),
                         'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
        variants = [b'a\nx\n', b'a\r\nx\r\n', b'a\n"x"\n',
                    codecs.BOM_UTF8 + b'a\nx\n']
        self.assertEqual(len({archive_identity(raw) for raw in variants}), 4)
        for raw in variants:
            self.assertEqual(normalize_csv(raw)['rows'], [['x']])
            self.assertEqual(archive_identity(raw), archive_identity(bytes(raw)))

    def test_malformed_inputs_rejected(self):
        for raw in [b'', codecs.BOM_UTF8, b'a,b\n1\n', b'a\n1,2\n',
                    b'a\n"unfinished', b'a\n"x"junk', b'a\nx"y',
                    b'a\n\x00', b'a\n\xff']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_csv(raw)
        for encoding in ['unknown-encoding', 'base64_codec', None]:
            with self.subTest(encoding=encoding), self.assertRaises(ValueError):
                normalize_csv(b'a\nx', encoding)

    def test_size_boundary_and_large_field(self):
        raw = b'a\n' + b'x' * (5 * 1024 * 1024 - 2)
        prior_limit = csv.field_size_limit()
        self.assertEqual(len(normalize_csv(raw)['rows'][0][0]), len(raw) - 2)
        self.assertEqual(csv.field_size_limit(), prior_limit)
        with self.assertRaises(ValueError):
            normalize_csv(raw + b'x')

    def test_record_endings_empty_cells_and_header_only(self):
        for ending in ['\n', '\r', '\r\n']:
            raw = ('a,b' + ending + ',' + ending + '"",x').encode()
            self.assertEqual(normalize_csv(raw)['rows'], [['', ''], ['', 'x']])
        self.assertEqual(normalize_csv(b'a,b\n')['rows'], [])
        self.assertEqual(normalize_csv(b'a\n\n')['rows'], [['']])

    def test_formula_safe_export_headings_values_and_idempotence(self):
        dangerous = ['=1+1', '+SUM(A1)', '-2', '@SUM(A1)', '  =1',
                     '\ttext', '\rtext', ' \ttext', '\ntext',
                     '\u2003@cmd', '  +2', '  -2', '  @x', '\t', '\r']
        ordinary = ['', 'text', '  text', "'=1", 'a=b', 'line\nbreak']
        cells = dangerous + ordinary
        data = {'headings': cells[:], 'rows': [cells[:]]}
        before = copy.deepcopy(data)
        exported = export_safe_csv(data)
        # Independent stdlib reader verifies literal cell contents and quoting.
        parsed = list(csv.reader(io.StringIO(exported.decode('utf-8-sig'), newline='')))
        expected = ["'" + value for value in dangerous] + ordinary
        self.assertEqual(parsed, [expected, expected])
        self.assertEqual(data, before)
        self.assertEqual(export_safe_csv(data), exported)
        self.assertEqual(export_safe_csv(normalize_csv(exported)), exported)

    def test_export_shape_validation(self):
        for data in [None, {}, {'headings': [], 'rows': []},
                     {'headings': ['a'], 'rows': [['x', 'y']]},
                     {'headings': ['a'], 'rows': [[None]]},
                     {'headings': ['a'], 'rows': [['\x00']]},
                     {'headings': {'a': 'b'}, 'rows': []}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                export_safe_csv(data)

    def test_bytes_required(self):
        for value in ['a\nx', bytearray(b'a\nx'), None]:
            for function in [archive_identity, normalize_csv]:
                with self.subTest(function=function, value=value), self.assertRaises(TypeError):
                    function(value)


if __name__ == '__main__':
    unittest.main()
