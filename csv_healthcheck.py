"""Inspect CSV structure without third-party runtime dependencies."""

import argparse
import csv
import json
import sys
from pathlib import Path


def inspect_csv(path):
    """Return counts and issues; duplicate detection uses memory proportional to rows."""
    issues = []
    missing = duplicates = rows = 0
    seen = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, strict=True)
        header = next(reader, None)
        if header is None:
            return {"rows": 0, "columns": 0, "missing_values": 0,
                    "duplicate_rows": 0, "issues": ["Empty file"]}
        names = [name.strip() for name in header]
        if not names or any(not name for name in names):
            issues.append("Header contains an empty column name")
        if len(set(names)) != len(names):
            issues.append("Header contains duplicate column names")
        for row in reader:
            rows += 1
            if len(row) != len(header):
                issues.append(f"Record {rows}: expected {len(header)} fields, got {len(row)}")
            missing += sum(not value.strip() for value in row)
            missing += max(0, len(header) - len(row))
            key = tuple(row)
            if key in seen:
                duplicates += 1
            seen.add(key)
    if missing:
        issues.append(f"Missing values: {missing}")
    if duplicates:
        issues.append(f"Duplicate rows: {duplicates}")
    return {"rows": rows, "columns": len(header), "missing_values": missing,
            "duplicate_rows": duplicates, "issues": issues}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    try:
        report = inspect_csv(args.path)
    except (OSError, UnicodeError, csv.Error) as error:
        print(f"Unable to inspect CSV: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 1 if report["issues"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
