import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from csv_healthcheck import inspect_csv, main


class CsvTests(unittest.TestCase):
    def report(self, content, delimiter=","):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            path.write_text(content, encoding="utf-8")
            return inspect_csv(path, delimiter=delimiter)

    def test_semicolon_delimiter_preserves_quoted_fields(self):
        result = self.report('name;value\n"a;b";1\n', delimiter=";")
        self.assertEqual(result["columns"], 2)
        self.assertEqual(result["issues"], [])

    def test_tab_delimiter_detects_missing_values(self):
        result = self.report("a\tb\n1\t\n", delimiter="\t")
        self.assertEqual(result["columns"], 2)
        self.assertEqual(result["missing_values"], 1)

    def test_invalid_delimiters(self):
        for delimiter in ("", "||", "\n", "\r", "\0", None):
            with self.subTest(delimiter=delimiter), self.assertRaises(ValueError):
                self.report("a,b\n1,2\n", delimiter=delimiter)

    def test_cli_delimiter(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            path.write_text("a;b\n1;2\n", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([str(path), "--delimiter", ";"]), 0)
            self.assertIn('"columns": 2', output.getvalue())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(path), "--delimiter", "||"]), 2)

    def test_valid_quoted_csv(self):
        result = self.report('name,value\n"a,b",1\n"two\nlines",2\n')
        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["issues"], [])

    def test_empty_file(self):
        self.assertEqual(self.report("")["issues"], ["Empty file"])

    def test_missing_values_and_short_rows(self):
        result = self.report("a,b,c\n1, ,3\n2\n")
        self.assertEqual(result["missing_values"], 3)
        self.assertIn("Record 2: expected 3 fields, got 1", result["issues"])

    def test_duplicates_are_exact(self):
        result = self.report("a\nx\nx\n x\n")
        self.assertEqual(result["duplicate_rows"], 1)

    def test_header_validation(self):
        self.assertIn("Header contains duplicate column names",
                      self.report("a, a\n1,2\n")["issues"])
        self.assertIn("Header contains an empty column name",
                      self.report("a,\n1,2\n")["issues"])

    def test_bom(self):
        self.assertEqual(self.report("\ufeffa,b\n1,2\n")["issues"], [])

    def test_extra_fields(self):
        self.assertIn("Record 1: expected 1 fields, got 2",
                      self.report("a\n1,2\n")["issues"])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(path)]), 2)
                path.write_text("a\n1\n", encoding="utf-8")
                self.assertEqual(main([str(path)]), 0)
                path.write_text("a,b\n1,\n", encoding="utf-8")
                self.assertEqual(main([str(path)]), 1)
                path.write_text('a\n"unterminated', encoding="utf-8")
                self.assertEqual(main([str(path)]), 2)


if __name__ == "__main__":
    unittest.main()
