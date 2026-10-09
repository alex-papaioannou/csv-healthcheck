import contextlib
import csv
import io
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from csv_healthcheck import inspect_csv, main


class CsvTests(unittest.TestCase):
    def report(self, content, delimiter=",", **options):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            path.write_text(content, encoding="utf-8")
            return inspect_csv(path, delimiter=delimiter, **options)

    def test_disk_duplicates_match_memory_for_complex_rows(self):
        content = 'a,b\n"x,y",z\nx,"y,z"\n"x,y",z\n"two\nlines",é\n"two\nlines",é\n'
        memory = self.report(content)
        disk = self.report(content, duplicate_storage="disk")
        self.assertEqual(disk, memory)
        self.assertEqual(disk["duplicate_rows"], 2)

    def test_disk_index_handles_many_distinct_rows(self):
        content = "a\n" + "".join(f"{i}\n" for i in range(10000)) + "42\n42\n"
        result = self.report(content, duplicate_storage="disk")
        self.assertEqual(result["rows"], 10002)
        self.assertEqual(result["duplicate_rows"], 2)

    def test_disk_index_cleanup_on_success_and_parse_error(self):
        factory = tempfile.TemporaryDirectory
        for content in ("a\n1\n", 'a\n"unterminated'):
            with self.subTest(content=content), factory() as parent:
                path = Path(parent) / "data.csv"
                path.write_text(content, encoding="utf-8")
                with mock.patch("csv_healthcheck.tempfile.TemporaryDirectory",
                                side_effect=lambda **kwargs: factory(dir=parent, **kwargs)):
                    if "unterminated" in content:
                        with self.assertRaises(csv.Error):
                            inspect_csv(path, duplicate_storage="disk")
                    else:
                        inspect_csv(path, duplicate_storage="disk")
                self.assertEqual(list(Path(parent).iterdir()), [path])

    def test_disk_cli_and_invalid_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            path.write_text("a\n1\n1\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(path), "--duplicate-storage", "disk"]), 1)
            with self.assertRaises(ValueError):
                inspect_csv(path, duplicate_storage="unknown")

    def test_required_columns_allow_order_and_trim_whitespace(self):
        result = self.report(" value ,name\n1,x\n",
                             required_columns=["name", " value "])
        self.assertEqual(result["issues"], [])

    def test_missing_required_columns_are_case_sensitive_and_deduplicated(self):
        result = self.report("name,value\nx,1\n",
                             required_columns=["Name", "price", "price"])
        self.assertEqual(result["issues"], ["Missing required column: Name",
                                             "Missing required column: price"])
        self.assertEqual(result["rows"], 1)

    def test_invalid_required_column_names(self):
        for names in ([""], [" "], [7], "name"):
            with self.subTest(names=names), self.assertRaises(ValueError):
                self.report("name\nx\n", required_columns=names)

    def test_cli_required_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.csv"
            path.write_text("name,value\nx,1\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(path), "--require-column", "name",
                                       "--require-column", "value"]), 0)
                self.assertEqual(main([str(path), "--require-column", "price"]), 1)
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main([str(path), "--require-column", ""]), 2)

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
