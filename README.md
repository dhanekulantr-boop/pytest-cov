# pytest-cov

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![PyPI](https://img.shields.io/badge/pypi-available-green.svg)](https://pypi.org/project/pytest-cov/)

> A comprehensive **code coverage plugin for pytest** that seamlessly integrates coverage reporting into your test suite.

---

## Overview

This plugin provides powerful coverage functionality as a pytest plugin. It handles automatic erasing and combination of `.coverage` files, supports distributed testing with `pytest-xdist`, and produces beautiful reports in multiple formats.

### Key Features

- Automatic coverage data management and combination
- Multiple report formats: **terminal, HTML, XML, JSON, Markdown, LCov**
- Distributed testing support (pytest-xdist)
- Branch coverage support
- Configurable fail-under threshold
- Customizable report precision
- Dynamic context support for detailed test mapping

---

## Installation

```bash
pip install pytest-cov
```

For distributed testing support, also install:

```bash
pip install pytest-xdist
```

---

## Usage

### Basic Usage

Run pytest with coverage on your project:

```bash
pytest --cov=myproject tests/
```

### Generate HTML Report

```bash
pytest --cov=myproject --cov-report=html tests/
```

### Generate Multiple Reports

```bash
pytest --cov=myproject --cov-report=html --cov-report=xml --cov-report=term-missing tests/
```

### Branch Coverage

```bash
pytest --cov=myproject --cov-branch tests/
```

### Fail Under Minimum Coverage

```bash
pytest --cov=myproject --cov-fail-under=80 tests/
```

---

## Configuration Options

| Option | Description |
|--------|-------------|
| `--cov=SOURCE` | Path or package name to measure coverage |
| `--cov-report=TYPE` | Report type: term, term-missing, html, xml, json, markdown, lcov |
| `--cov-config=PATH` | Custom coverage config file (default: .coveragerc) |
| `--cov-branch` | Enable branch coverage analysis |
| `--cov-fail-under=MIN` | Fail if coverage is below MIN percent |
| `--cov-precision=N` | Set decimal precision for coverage reports |
| `--cov-context=CONTEXT` | Enable dynamic contexts (e.g., `--cov-context=test`) |
| `--no-cov` | Disable coverage for debugging |
| `--no-cov-on-fail` | Skip coverage report if tests fail |
| `--cov-append` | Append coverage data instead of erasing |

---

## Project Structure

```
pytest-cov/
├── src/
│   └── pytest_cov/
│       ├── __init__.py    # Package initialization
│       ├── engine.py       # Coverage controller implementations
│       └── plugin.py       # Pytest plugin hooks and options
├── .gitignore
├── LICENSE                 # MIT License
└── README.md
```

---

## Report Examples

### Terminal Report

```
---------- coverage: platform linux, python 3.10.12 ----------
Name                    Stmts   Miss  Cover
-------------------------------------------
myproject/__init__.py       2      0   100%
myproject/core.py         257     13    94%
myproject/utils.py         94      7    92%
-------------------------------------------
TOTAL                      353     20    94%
```

### HTML Report

HTML reports provide interactive coverage visualization with color-coded lines showing covered vs uncovered code.

---

## Fixtures

This plugin provides two pytest fixtures:

### `no_cover`

A marker to disable coverage for specific tests:

```python
def test_heavy_computation(no_cover):
    # This test won't be tracked by coverage
    pass
```

### `cov`

Access to the underlying coverage object:

```python
def test_with_cov_object(cov):
    # Access coverage data programmatically
    assert cov is not None
```

---

## License

This project is licensed under the **MIT License** - see the [LICENSE](LICENSE) file for details.

---

## Contributing

Contributions are welcome! Feel free to submit issues and pull requests.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## Acknowledgements

Built on top of the excellent [`coverage.py`](https://coverage.readthedocs.io/) library and [`pytest`](https://docs.pytest.org/) framework.
