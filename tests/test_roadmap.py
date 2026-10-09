import unittest
import tempfile
import io
import contextlib
import json
from pathlib import Path
from unittest import mock
import csv_healthcheck as app

class FeatureTests(unittest.TestCase):
    def inspect(self, text, **options):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / "data.csv"
            p.write_text(text, encoding="utf-8")
            return app.inspect_csv(p, **options)

    def test_package_metadata_and_entry_point(self):
        import tomllib
        import importlib
        config = tomllib.loads((Path(__file__).parents[1] / 'pyproject.toml').read_text())
        module, name = config['project']['scripts']['csv-healthcheck'].split(':')
        self.assertTrue(callable(getattr(importlib.import_module(module), name)))
        self.assertEqual(config['project']['dependencies'], [])

    def test_version_without_input(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as result:
            app.main(['--version'])
        self.assertEqual(result.exception.code, 0)
        self.assertIn(app.__version__, output.getvalue())

    def test_stream_and_stdin_are_not_closed(self):
        stream = io.StringIO('a\n1\n')
        self.assertEqual(app.inspect_csv(stream)['rows'], 1)
        self.assertFalse(stream.closed)
        stream.seek(0)
        with mock.patch('sys.stdin', stream), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['-']), 0)
        self.assertFalse(stream.closed)

    def test_latin1_file_and_invalid_encoding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'latin.csv'
            path.write_bytes('name\ncafé\n'.encode('latin1'))
            self.assertEqual(app.inspect_csv(path, encoding='latin1')['rows'], 1)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(app.main([str(path), '--encoding', 'not-an-encoding']), 2)

    def test_gzip_and_truncated_gzip(self):
        import gzip
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.csv.gz'
            path.write_bytes(gzip.compress(b'a\n1\n'))
            self.assertEqual(app.inspect_csv(path)['rows'], 1)
            path.write_bytes(path.read_bytes()[:12])
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(app.main([str(path)]), 2)

    def test_custom_quote_character(self):
        self.assertEqual(self.inspect("a,b\n'x,y',1\n", quotechar="'")['issues'], [])
        with self.assertRaises(ValueError): self.inspect('a\n1\n', quotechar='xx')

    def test_escaped_separator(self):
        self.assertEqual(self.inspect('a,b\nx!,y,1\n', escapechar='!')['issues'], [])
        with self.assertRaises(ValueError): self.inspect('a\n1\n', escapechar='')

    def test_headerless_first_record_is_data(self):
        report = self.inspect('1,2\n1,2\n', header=False, required_columns=['column_2'])
        self.assertEqual(report['rows'], 2)
        self.assertEqual(report['duplicate_rows'], 1)
        self.assertNotIn('Missing required column: column_2', report['issues'])

    def test_blank_record_policy(self):
        self.assertEqual(self.inspect('a\n\n1\n')['rows'], 2)
        report = self.inspect('\na\n\n1\n""\n', blank_records='skip')
        self.assertEqual(report['rows'], 2)
        self.assertEqual(report['missing_values'], 1)

    def test_field_size_limit_restored_after_failure(self):
        import csv
        previous = csv.field_size_limit()
        with self.assertRaises(csv.Error): self.inspect('a\nlongvalue\n', field_size_limit=3)
        self.assertEqual(csv.field_size_limit(), previous)
        self.assertEqual(self.inspect('a\nlongvalue\n', field_size_limit=20)['rows'], 1)
        with self.assertRaises(ValueError): self.inspect('a\n1\n', field_size_limit=0)

    def test_issue_cap_preserves_totals_and_failure(self):
        report = self.inspect('a\n1,2\n3,4\n5,6\n', max_issues=1)
        self.assertEqual(report['issue_count'], 3)
        self.assertEqual(report['issues_truncated'], 2)
        self.assertEqual(len(report['issues']), 1)
        with mock.patch('sys.stdin', io.StringIO('a\n1,2\n')), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['-', '--max-issues', '0']), 1)
