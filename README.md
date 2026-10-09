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

This is a structural checker, not a data-type or financial-data validator. Duplicate
detection stores unique rows in memory; use it for files that fit available memory.
Issue output also grows with the number of malformed records.

## Development

CI calls the shared workflow in `alex-papaioannou/python-ci-workflows` on pushes
and pull requests. It checks syntax and runs tests on Python 3.11, 3.12, and 3.13.
The workflow reference is pinned to a specific commit in the shared repository.
Update that SHA through a pull request when adopting workflow changes.

Useful next contributions: schema validation and an
optional disk-backed duplicate index. Include tests and usage examples with PRs.
