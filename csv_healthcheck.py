"""Inspect CSV structure without third-party runtime dependencies."""

__version__ = "0.1.0"

import argparse
import csv
import codecs
import json
import sqlite3
import sys
import tempfile
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path


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


def inspect_csv(path, delimiter=",", required_columns=(), duplicate_storage="memory", encoding="utf-8-sig"):
    """Return structural quality counts and issues for a CSV file."""
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
    issues = []
    missing = duplicates = rows = 0
    source_context = nullcontext(path) if hasattr(path, "read") else Path(path).open(encoding=encoding, newline="")
    with source_context as source, duplicate_index(duplicate_storage) as record:
        reader = csv.reader(source, strict=True, delimiter=delimiter)
        header = next(reader, None)
        if header is None:
            return {"rows": 0, "columns": 0, "missing_values": 0,
                    "duplicate_rows": 0, "issues": ["Empty file"]}
        names = [name.strip() for name in header]
        if not names or any(not name for name in names):
            issues.append("Header contains an empty column name")
        if len(set(names)) != len(names):
            issues.append("Header contains duplicate column names")
        for name in required:
            if name not in names:
                issues.append(f"Missing required column: {name}")
        for row in reader:
            rows += 1
            if len(row) != len(header):
                issues.append(f"Record {rows}: expected {len(header)} fields, got {len(row)}")
            missing += sum(not value.strip() for value in row)
            missing += max(0, len(header) - len(row))
            if record(row):
                duplicates += 1
    if missing:
        issues.append(f"Missing values: {missing}")
    if duplicates:
        issues.append(f"Duplicate rows: {duplicates}")
    return {"rows": rows, "columns": len(header), "missing_values": missing,
            "duplicate_rows": duplicates, "issues": issues}


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
    args = parser.parse_args(argv)
    try:
        source = sys.stdin if str(args.path) == "-" else args.path
        report = inspect_csv(source, delimiter=args.delimiter,
                             required_columns=args.require_column,
                             duplicate_storage=args.duplicate_storage, encoding=args.encoding)
    except (OSError, UnicodeError, csv.Error, ValueError, LookupError, sqlite3.Error) as error:
        print(f"Unable to inspect CSV: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 1 if report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
