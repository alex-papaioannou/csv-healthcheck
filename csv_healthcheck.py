"""Inspect CSV structure without third-party runtime dependencies."""

__version__ = "0.1.0"

import argparse
import csv
import codecs
import json
import gzip
import itertools
import os
import threading
import sqlite3
import sys
import tempfile
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path


_field_lock = threading.RLock()


@contextmanager
def field_limit(value):
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
        raise ValueError("field_size_limit must be a positive integer")
    with _field_lock:
        previous = csv.field_size_limit()
        try:
            if value is not None:
                csv.field_size_limit(value)
            yield
        finally:
            csv.field_size_limit(previous)


class Issues(list):
    def __init__(self, limit):
        super().__init__()
        self.limit = limit
        self.total = 0
        self.details = []

    def append(self, message, code="quality", record=None, column=None):
        self.total += 1
        if self.limit is None or len(self) < self.limit:
            super().append(message)
            self.details.append({"code": code, "message": message, "record": record, "column": column})


@contextmanager
def duplicate_index(storage):
    """Yield a callable that records a row and reports whether it was seen before."""
    if storage == "memory":
        seen = set()

        def record(row):
            key = tuple(row)
            duplicate = key in seen
            seen.add(key)
            return duplicate

        yield record
    else:
        with tempfile.TemporaryDirectory(prefix="csv-healthcheck-") as directory:
            with closing(sqlite3.connect(str(Path(directory) / "rows.sqlite"))) as database:
                database.execute("PRAGMA cache_size = -2048")
                database.execute("CREATE TABLE seen (row_key TEXT PRIMARY KEY) WITHOUT ROWID")

                def record(row):
                    # JSON preserves field boundaries without hash collisions.
                    key = json.dumps(row, ensure_ascii=True, separators=(",", ":"))
                    cursor = database.execute("INSERT OR IGNORE INTO seen VALUES (?)", (key,))
                    return cursor.rowcount == 0

                yield record


def inspect_csv(path, delimiter=",", required_columns=(), duplicate_storage="memory", encoding="utf-8-sig", quotechar='"', escapechar=None, header=True, blank_records="keep", field_size_limit=None, max_issues=None):
    """Return structural quality counts and issues for a CSV file."""
    if blank_records not in ("keep", "skip"):
        raise ValueError("blank_records must be keep or skip")
    if not isinstance(header, bool):
        raise ValueError("header must be boolean")
    if not isinstance(quotechar, str) or len(quotechar) != 1 or quotechar in "\r\n\0":
        raise ValueError("quotechar must be one character other than a newline or NUL")
    if escapechar is not None and (not isinstance(escapechar, str) or len(escapechar) != 1 or escapechar in "\r\n\0"):
        raise ValueError("escapechar must be a single non-newline, non-NUL character")
    codecs.lookup(encoding)
    if duplicate_storage not in ("memory", "disk"):
        raise ValueError("duplicate_storage must be 'memory' or 'disk'")
    if not isinstance(delimiter, str) or len(delimiter) != 1 or delimiter in "\r\n\0":
        raise ValueError("delimiter must be one character other than a newline or NUL")
    if isinstance(required_columns, str):
        raise ValueError("required_columns must be a sequence of column names")
    required = []
    for name in required_columns:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("required column names must be nonempty strings")
        if name.strip() not in required:
            required.append(name.strip())
    if max_issues is not None and (isinstance(max_issues, bool) or not isinstance(max_issues, int) or max_issues < 0):
        raise ValueError("max_issues must be a nonnegative integer")
    issues = Issues(max_issues)
    has_header = header
    missing = duplicates = rows = 0
    if hasattr(path, "read"):
        source_context = nullcontext(path)
    elif str(path).lower().endswith(".gz"):
        source_context = gzip.open(path, "rt", encoding=encoding, newline="")
    else:
        source_context = Path(path).open(encoding=encoding, newline="")
    with source_context as source, field_limit(field_size_limit), duplicate_index(duplicate_storage) as record:
        reader = csv.reader(source, strict=True, delimiter=delimiter, quotechar=quotechar, escapechar=escapechar)
        if blank_records == "skip":
            reader = (row for row in reader if row)
        header = next(reader, None)
        if header is None:
            issues.append("Empty file", "empty_file")
            return {"rows": 0, "columns": 0, "missing_values": 0,
                    "duplicate_rows": 0, "issues": issues, "issue_count": issues.total,
                    "issue_details": issues.details, "issues_truncated": issues.total - len(issues)}
        if not has_header:
            reader = itertools.chain([header], reader)
            header = [f"column_{i + 1}" for i in range(len(header))]
        names = [name.strip() for name in header]
        if not names or any(not name for name in names):
            issues.append("Header contains an empty column name", "empty_header")
        if len(set(names)) != len(names):
            issues.append("Header contains duplicate column names", "duplicate_header")
        for name in required:
            if name not in names:
                issues.append(f"Missing required column: {name}", "required_column", column=name)
        for row in reader:
            rows += 1
            if len(row) != len(header):
                issues.append(f"Record {rows}: expected {len(header)} fields, got {len(row)}", "row_width", record=rows)
            missing += sum(not value.strip() for value in row)
            missing += max(0, len(header) - len(row))
            if record(row):
                duplicates += 1
    if missing:
        issues.append(f"Missing values: {missing}", "missing_values")
    if duplicates:
        issues.append(f"Duplicate rows: {duplicates}", "duplicate_rows")
    return {"rows": rows, "columns": len(header), "missing_values": missing,
            "duplicate_rows": duplicates, "issues": issues, "issue_count": issues.total,
            "issue_details": issues.details, "issues_truncated": issues.total - len(issues)}


def render_text(report):
    lines = [f"Rows: {report['rows']} | Columns: {report['columns']}",
             f"Missing values: {report['missing_values']} | Duplicate rows: {report['duplicate_rows']}"]
    lines.extend(report["issues"])
    if report["issues_truncated"]:
        lines.append(f"Omitted issue messages: {report['issues_truncated']}")
    if not report["issue_count"]:
        lines.append("No quality issues found")
    return "\n".join(lines)


def write_report(path, content):
    target = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=target.parent, prefix=".csv-report-", delete=False) as out:
            temporary = Path(out.name)
            out.write(content + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("path", type=Path)
    parser.add_argument("--delimiter", default=",", help="Field separator (default: comma)")
    parser.add_argument("--require-column", action="append", default=[],
                        help="Require a header name; repeat for multiple columns")
    parser.add_argument("--duplicate-storage", choices=("memory", "disk"), default="memory",
                        help="Store unique rows in memory or temporary SQLite storage")
    parser.add_argument("--encoding", default="utf-8-sig", help="File text encoding; streams are already decoded")
    parser.add_argument("--quotechar", default='"', help="Single quoting character")
    parser.add_argument("--escapechar", help="Optional CSV escape character")
    parser.add_argument("--no-header", action="store_true", help="Generate column_1, column_2, ... names")
    parser.add_argument("--blank-records", choices=("keep", "skip"), default="keep")
    parser.add_argument("--field-size-limit", type=int, help="Maximum CSV field length in characters")
    parser.add_argument("--max-issues", type=int, help="Maximum stored messages; counts remain complete")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    parser.add_argument("--output", type=Path, help="Atomically replace a report file")
    args = parser.parse_args(argv)
    try:
        if args.output and str(args.path) != "-" and args.output.resolve() == args.path.resolve():
            raise ValueError("Output must not overwrite input")
        source = sys.stdin if str(args.path) == "-" else args.path
        report = inspect_csv(source, delimiter=args.delimiter,
                             required_columns=args.require_column,
                             duplicate_storage=args.duplicate_storage, encoding=args.encoding, quotechar=args.quotechar, escapechar=args.escapechar, header=not args.no_header, blank_records=args.blank_records, field_size_limit=args.field_size_limit, max_issues=args.max_issues)
    except (OSError, EOFError, UnicodeError, csv.Error, ValueError, OverflowError, LookupError, sqlite3.Error) as error:
        print(f"Unable to inspect CSV: {error}", file=sys.stderr)
        return 2
    content = render_text(report) if args.format == "text" else json.dumps(report, indent=2)
    try:
        if args.output:
            write_report(args.output, content)
        else:
            print(content)
    except OSError as error:
        print(f"Unable to write report: {error}", file=sys.stderr)
        return 2
    return 1 if report["issue_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
