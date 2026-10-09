# CSV Healthcheck

A dependency-free Python CLI for checking CSV files before loading a data pipeline.
Reports missing values, exact duplicate rows, inconsistent widths, and invalid headers.

```sh
python csv_healthcheck.py examples/clean.csv
python -m unittest discover -s tests -v
```

For semicolon-separated input, pass `--delimiter ';'`. For tab-separated input
in Bash or Zsh, pass `--delimiter $'\t'`:

```sh
python csv_healthcheck.py data.csv --delimiter ';'
python csv_healthcheck.py data.tsv --delimiter $'\t'
```

The separator must be exactly one character, excluding newlines and NUL.
Quoted fields retain normal CSV escaping rules. Python callers can use
`inspect_csv(path, delimiter=";")` or `inspect_csv(path, delimiter="\t")`.

Python 3.11+ required. Output is JSON. Exit codes: `0` clean, `1` quality issues,
`2` unreadable or malformed input. UTF-8 and UTF-8 BOM are supported. Blank and
whitespace-only cells count as missing, including absent trailing fields. Duplicate
comparison preserves whitespace. The first record is always the header.

To enforce required headers, repeat `--require-column`:

```sh
python csv_healthcheck.py examples/clean.csv --require-column symbol --require-column price
```

Names are case-sensitive and stripped of surrounding whitespace. Extra columns
and any column order are allowed. Missing required names produce quality issues
(exit code 1); blank required names are invalid configuration (exit code 2).
The Python API accepts `required_columns=["symbol", "price"]`.

For large files, use `--duplicate-storage disk` (or `duplicate_storage="disk"`
in Python). Exact row keys are stored in a temporary SQLite database with a
2 MiB page-cache target. The database is closed and removed on normal completion
or a handled error. Abrupt process termination can leave temporary files behind.
The default `memory` mode is faster for smaller files. Disk mode requires enough
space in the system temporary directory; it performs no network operations.

This is a structural checker, not a data-type or financial-data validator. Disk
mode bounds the duplicate index's cache, not total process memory: individual rows
and issue output can still grow with input. There is no automatic mode selection.

## Development

CI calls the shared workflow in `alex-papaioannou/python-ci-workflows` on pushes
and pull requests. It checks syntax and runs tests on Python 3.11, 3.12, and 3.13.
The workflow reference is pinned to a specific commit in the shared repository.
Update that SHA through a pull request when adopting workflow changes.

Useful next contributions: data-type validation and configurable issue limits.
Include tests and usage examples with PRs.

## Installation

From a checkout, run `python -m pip install .`, then `csv-healthcheck data.csv`.
The existing `python csv_healthcheck.py` and `python -m csv_healthcheck` entry points remain supported. Installation needs a build backend; runtime uses only the standard library. This repository is not yet published to PyPI.

Use `csv-healthcheck --version` to print the package version without opening an input file.

Pipe text using `cat data.csv | csv-healthcheck -`. The Python API also accepts text streams and leaves caller-owned streams open. Stdin uses the interpreter's text decoding.

Use `--encoding latin1` (API: `encoding="latin1"`) for explicitly encoded files. The default is UTF-8 with optional BOM. Invalid encoding names and undecodable input return exit code 2; no guessing or lossy replacement is performed.

Files ending in `.gz` are decompressed as a stream, including uppercase `.GZ`. Use `csv-healthcheck input.csv.gz`; malformed or truncated gzip input returns exit code 2. Compressed stdin is not auto-detected.

`--quotechar` selects a single quoting character (default double quote). For example, use `--quotechar "'"` for single-quoted fields; newline and NUL are rejected.

`--escapechar` enables CSV escaping, for example `--escapechar '!'` treats `x!,y` as one field. Escaping is disabled by default; doubled quotes remain supported.

`--no-header` (API: `header=False`) treats the first record as data, fixes width from that record, and names columns `column_1`, `column_2`, etc. An empty file remains a quality issue.

`--blank-records skip` omits truly empty records before header selection and validation. The default is `keep`. Quoted empty fields and whitespace-only fields are data records, not blank records. Reported record numbers count retained data records.

`--field-size-limit 1000000` sets a positive maximum field length in characters for this inspection. The previous Python CSV limit is restored even on errors. Calls within this module serialize limit changes; unrelated code calling `csv.field_size_limit` concurrently is outside this lock.

`--max-issues N` limits retained messages without stopping validation. `issue_count` counts all diagnostic messages and `issues_truncated` counts omitted messages. Zero stores no messages but still exits 1 for quality failures. Aggregate missing/duplicate messages each count as one issue.

`issue_details` adds stable machine-readable `code` and `message` fields alongside the backward-compatible `issues` string list. Both lists obey `max_issues`. Codes include `empty_file`, `empty_header`, `duplicate_header`, `required_column`, `row_width`, `missing_values`, and `duplicate_rows`.

Diagnostic `record` is a one-based retained data-record number (multiline fields count as one record). `column` is a header name when applicable. Header, aggregate, and file-level diagnostics use null where no specific location applies.

`--format text` prints a compact human-readable report, including omitted-message counts. JSON remains the default; formatting does not change validation or exit status.

`--output report.json` writes UTF-8 to a temporary file beside the destination and atomically replaces it after writing. Existing reports remain intact if writing or replacement fails; failures return 2. Parent directories must exist. The input path cannot also be the output path.

## JSON configuration

`--config rules.json` loads inspection options using Python API names, such as `{"delimiter":";","required_columns":["id"]}`. Explicit CLI options override corresponding configuration values; unspecified options retain configured values. Unknown keys are rejected. CLI long-option abbreviations are disabled to keep precedence unambiguous.

Configuration errors identify unknown keys or invalid value types. Column lists must be arrays of strings, booleans must be JSON booleans, and issue/field limits must be integers (not booleans). Invalid configuration returns exit code 2.
