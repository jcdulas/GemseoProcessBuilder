# Contributing

Thank you for helping! Bug reports, ideas and pull requests are welcome. Please read the [code of conduct](CODE_OF_CONDUCT.md) first.

## License of contributions

GEMSEO Process Builder is distributed under the [MIT license](LICENSE). Contributions are accepted under the same license (*inbound = outbound*): by opening a pull request, you agree that your contribution is distributed under the MIT license.

Dependencies and vendored files must have a license compatible with MIT (SPEC § 14.6): permissive licenses are fine, LGPL only as an imported dependency, and GPL or AGPL code must never be copied or vendored. Record new licenses in `static/vendor/README.md` and regenerate `THIRD_PARTY_NOTICES.md` with `python tools/third_party_notices.py`.

## Development setup

Python 3.12 (the minimum and reference version) and Node.js (for the JavaScript tests) are needed.

```bash
python3.12 -m venv .venv                     # Windows: C:\Path\To\Python312\python.exe -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"  # Windows: .venv\Scripts\python.exe
.venv/bin/python -m gemseo_process_builder --dev   # --dev opens the DevTools
```

Always use the interpreter of the virtual environment.

## Rules

- **English only** for every written artifact: code, comments, docstrings, UI text, log and error messages, documentation, commit messages.
- **No test may last more than one second**, setup included. It is enforced by `pytest-timeout` and `node --test --test-timeout=1000`; a slow test is split or rewritten, never exempted.
- **Generated GEMSEO scripts must read like human-written code**, understandable by a developer with two years of experience (SPEC § 10.2). Golden scripts are reviewed by hand.
- **User code and GEMSEO never run in the UI process**: only in the worker or the runner.
- **No server**: the page is served by the `gpb://` scheme handler; Python and JavaScript talk through QWebChannel.
- **All diagrams are SVG drawn with d3**, and there is **no JavaScript build step**: vanilla ES modules, vendored libraries.
- Code in `static/js/lib/` is pure (no DOM, no d3) and unit-tested with `node --test`.

The [developer guide](docs/developer_guide.md) explains the architecture and how to add commands, validation rules, component kinds and results views.

## Before opening a pull request

```bash
python tools/check.py        # ruff, formatting, mypy, pytest, node tests; add --fix to format first
```

Everything must pass. Add tests for what you change, update the documentation, and describe the change in `CHANGELOG.md` under "Unreleased". If a decision changes the specification, update `SPEC.md` in the same pull request.

Keep pull requests focused: one change, explained in its description.

## Reporting bugs

Open an issue with the bug report template: what you did, what you expected, what happened, and the details copied from the error dialog or the Console panel. Attach a small project file when you can. Security issues are reported privately, see [SECURITY.md](SECURITY.md).
