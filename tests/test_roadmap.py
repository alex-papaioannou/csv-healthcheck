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
