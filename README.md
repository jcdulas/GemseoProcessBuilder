# GEMSEO Process Builder

A desktop application to build, run and analyze [GEMSEO](https://gemseo.readthedocs.io) processes through a graphical interface, in the spirit of Ansys ModelCenter. The full specification is in [SPEC.md](SPEC.md); the implementation is organized in sequential plans in [plans/](plans/README.md).

> Status: early development (pre-alpha).

## Setup

Python 3.12 or newer and Node.js (only for the JavaScript tests) are required.

Windows:

```powershell
C:\Path\To\Python312\python.exe -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

## Checks

Run every check (ruff, formatting, mypy, pytest, JavaScript tests) with the virtual environment interpreter:

```bash
python tools/check.py        # add --fix to apply ruff fixes and formatting first
```

No test may last more than one second (see SPEC § 15.1).

## Running

```bash
python -m gemseo_process_builder
```

## License

MIT, see [LICENSE](LICENSE).
