# GEMSEO Process Builder — working rules

The product is specified in [SPEC.md](SPEC.md). The implementation is split into numbered plans in [plans/](plans/), completed one at a time, in order.

## Non-negotiable rules

- **Never publish the package on PyPI or TestPyPI** (SPEC § 14.5): it is installed from the GitHub repository.
- **Open source, MIT license.** Before adding any dependency or vendored file, check that its license is compatible (SPEC § 14.6): permissive licenses are fine, LGPL only as an imported dependency, never copy or vendor GPL/AGPL code. Record new licenses in `static/vendor/README.md` or `THIRD_PARTY_NOTICES.md`.
- **English only** for every written artifact: code, comments, docstrings, UI text, log and error messages, docs, commit messages.
- **No test may last more than one second** (setup and teardown included). Enforced by `pytest-timeout` and `node --test --test-timeout=1000`. Never exempt a slow test: split or rewrite it. See SPEC § 15.1.
- **Generated GEMSEO scripts must read like human-written code** understandable by a developer with two years of experience. See SPEC § 10.2.
- **User code and GEMSEO never run in the UI process**: only in the worker or the runner subprocesses.
- **No server**: the page is served through the `gpb://` scheme handler, Python ↔ JS goes through QWebChannel.
- **All diagrams are SVG drawn with d3**; no canvas rendering.
- **No JS build step**: vanilla ES modules; d3 and elkjs are vendored and loaded with classic `<script>` tags (`window.d3`, `window.ELK`).
- Code in `gemseo_process_builder/static/js/lib/` is pure (no DOM, no d3) and unit-tested with `node --test`.

## Completing a plan

1. Read the plan (`plans/NN.md`) and the SPEC sections it references. Check that the plans it depends on are `Done`.
2. Implement the steps in order. Stay inside the plan's scope; items listed under "Out of scope" belong to later plans.
3. Run `python tools/check.py` (ruff, format check, mypy, pytest, JS syntax, node tests). Everything must pass, with no test over one second.
4. Tick the checkboxes in the plan, set `Status: Done`, and fill the "Implementation notes" section with any deviation from the plan or the spec, and any decision later plans must know about.
5. If a decision changes the spec, update SPEC.md in the same change.
6. Propose a commit named `Plan NN: <title>`.

## Commands

- Python: **3.12**, in the project venv `.venv` (Windows: `C:\Python\Python_3_12\python.exe -m venv .venv`). The default `python` on this machine is 3.13: always use the venv interpreter (`.venv\Scripts\python.exe` on Windows).
- Setup: see [plans/00.md](plans/00.md).
- Full check: `python tools/check.py`
- Python tests only: `python -m pytest tests/python`
- JS tests only: `node --test --experimental-test-isolation=none --test-timeout=1000 "tests/js/**/*.test.js"` (Node.js 22)
- Run the app: `python -m gemseo_process_builder` (`--dev` enables DevTools)
