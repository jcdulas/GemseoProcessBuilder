# Developer guide

This guide explains how the application is organized and how to extend it. The product is specified in [SPEC.md](../SPEC.md); its implementation was split into the numbered plans of [plans/](../plans/), whose "Implementation notes" record the decisions made along the way. The rules every change follows are in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Architecture

Three kinds of processes:

| Process | Runs | Never runs |
|---|---|---|
| **UI** (`app/`) | Qt, the web page, the project, validation, code generation | GEMSEO, user code |
| **Worker** (`workers/`) | GEMSEO: introspection of components, algorithm lists and settings, catalog scans, dry runs, results reading, post-processings, XDSM, surrogate training, wrapper test runs | — |
| **Runner** (`runner/`) | One run: the generated script, instrumented | — |

`tests/python/test_no_gemseo_in_ui.py` checks that the UI modules never import GEMSEO.

The window is a `QWebEngineView`. The page (`static/`) is served by a Qt scheme handler at `gpb://app/…`: there is no server and nothing is read from the network. It is written in vanilla ES modules, without a build step; d3 and elkjs are vendored in `static/vendor/` and loaded as classic scripts (`window.d3`, `window.ELK`). Every diagram is SVG drawn with d3.

```
gemseo_process_builder/
  app/        Qt application: window, bridge methods (api_*.py), services
  core/       pure model: data model, document and commands, resolver, validation
  codegen/    readable GEMSEO scripts from a project
  results/    run folders, results reading (numpy), surrogate storage
  report/     HTML report builder and PDF printing
  runtime/    code imported by generated scripts (executable wrapper)
  runner/     the process of a run
  workers/    the worker process and its methods
  catalog/    detection of components in catalog folders
  static/     the page: js/lib (pure), js/views, js/panels, css, vendor
```

## The bridge (page ↔ Python)

The page calls Python through QWebChannel with JSON requests `{id, method, params}` and receives `{id, ok, result}` or `{id, ok: false, error: {code, message, details}}`. Python sends events to the page: `{type, payload}`.

On the Python side, `app/bridge.py` holds a `MethodRegistry`. Methods are registered by name; their parameters are validated by the Pydantic model annotating the first argument:

```python
class LevelParams(BaseModel):
    level: str


def level(params: LevelParams) -> dict[str, Any]: ...


bridge.registry.add("resolve.level", level)
bridge.registry.add("results.rows", rows, background=True)  # long: in a thread pool
```

A method raises `BridgeError(ErrorCode.…, "message for the user")` to answer with an error. Methods run in the Qt thread unless they are registered with `background=True`. Qt objects must stay in the Qt thread: a background method that needs one sends it a queued signal, as `report/pdf.py` does.

On the page, `app.api.call(method, params, {timeout})` returns a promise, and `app.api.on(event, listener)` listens to events.

## The document

The project lives in Python (`core/document.py`). The page keeps a mirror (`static/js/store.js`) updated by patches.

- Every change is a **command** (`core/commands.py`): a Pydantic model with a `type`, whose `apply(project)` changes the project and returns an `Effect` with its inverse and the entities it touched. Undo applies the inverses.
- After each change the document publishes the touched entities (`document.patch`: revision and changes); a whole new project is sent as `document.reset`.
- `Document.model_rev` only changes with the model (nodes and links, not descriptions or the view). The resolution cache and the validation follow it.

**Adding a command**:

1. Write a `_Command` subclass in `core/commands.py`, with its `type` literal, `label` and `apply`; return an `Effect` whose `inverse` restores the project.
2. Add it to the `Command` union at the end of the module.
3. Test it in `tests/python/core/`: apply, undo, redo.
4. From the page: `app.store.execute({type: "myCommand", …})`, or `app.store.executeMany([...], label)` for one undo step.

## Resolution and validation

`core/resolver.py` computes the global name of every port, the couplings of every scope (by name and explicit), the free inputs, the loops and the derived ports of containers. `level_view` gives the page what a canvas level needs.

The validation (`core/validation.py`) runs registered rules on a `ValidationContext`. **Adding a rule**:

```python
from gemseo_process_builder.core.validation import Problem, ValidationContext, rule


@rule("my_rule")
def my_rule(context: ValidationContext) -> list[Problem]:
    return [Problem("my_code", "warning", "What is wrong, and how to fix it.", node_id)]
```

Put it in a module of `core/rules/` imported by `validate`, give it a quick fix in `core/quick_fixes.py` when the fix is obvious, and test it with a small project built with `tests/python/builders.py`.

## The worker

The worker (`workers/server.py`) reads JSON lines on stdin and answers on stdout (`workers/protocol.py`). It imports GEMSEO in the background at startup; methods needing it call `require_gemseo()`.

**Adding a worker method**: write a module in `workers/` with a `register(server)` function (`server.add("name", handler)`), add it to `METHOD_MODULES` in `workers/introspection.py`, and call it from the UI with `WorkerClient.call` (in a background bridge method) or `WorkerClient.request` (with a callback). Worker functions are tested directly, in-process (see `tests/python/workers/`).

## Components

**Adding a component kind**:

1. `core/model.py`: add the kind to the component kinds.
2. The worker computes its ports: `workers/component_methods.py` (`introspect`), and `INTROSPECTED_KINDS` in `app/component_service.py` and `static/js/panels/inspector_component.js`.
3. Its configuration editor: `static/js/panels/inspector_component.js`.
4. Its Library entry: `static/js/lib/builtins.js`.
5. Its code: `codegen/disciplines.py` (`component_discipline`), with a golden script in `tests/python/codegen/golden/` and a project in `tests/python/golden_projects.py`.

## Code generation

`codegen/generator.py` writes a script of named functions (`build_disciplines`, `build_design_space`, `build_scenario`, `execute_scenario`, `main`) and a mapping from GEMSEO names to project nodes. Scripts must read like code written by a developer with two years of experience (SPEC § 10.2):

- explicit imports, named constants for paths;
- one discipline per statement, with its node name;
- a comment explaining each GEMSEO concept the first time it appears (`context.explain`);
- no generated identifiers a person would not write.

The golden scripts of `tests/python/codegen/golden/` are what users read: after a deliberate change, rewrite them with `pytest tests/python/codegen --update-golden` and review the diff by hand. `tools/check.py` lints them and type-checks them with mypy.

## The page

- `static/js/lib/`: **pure** modules (no DOM, no d3), unit-tested with `node --test` in `tests/js/`.
- `static/js/views/`: center tabs (canvas, N2, XDSM, results, editors, wizards).
- `static/js/panels/`: side and bottom panels.
- `static/js/services/`: state shared by views (selection, validation, run states, exports, benchmarks).
- `static/js/components/`: DOM helpers (`el`), dialogs, virtualized lists and tables.

Large lists and tables are virtualized (`components/virtual_list.js`, `editable_table.js`). The canvas only draws the nodes and links near the view (`lib/viewport_cull.js`) and redraws a node only when it changed.

**Adding a results view**: write a class in `static/js/views/results/` with an `update(source)` method, add it to `VIEWS` and to the views of `ResultsTab` in `results_tab.js`, and read the data through `ResultsSource` (`source.js`); heavy computations belong to `results/reader.py`, in the worker.

## Tests

```bash
python tools/check.py              # ruff, format, mypy, golden scripts, pytest, node tests
python -m pytest tests/python      # Python tests only
node --test --test-timeout=1000 "tests/js/**/*.test.js"
```

**No test may last more than one second**, setup included (`pytest-timeout`, `node --test --test-timeout=1000`). A slow test is split or rewritten, never exempted:

- build small projects with `tests/python/builders.py` instead of loading big ones;
- run the worker's functions in-process instead of starting the worker;
- run examples with reduced settings (a few iterations or samples);
- `tests/python/conftest.py` imports GEMSEO, PySide6 and scikit-learn at collection time, where the limit does not apply.

Performance is measured apart, by the benchmarks of `benchmarks/` (see its README).

## Releases

1. Update `CHANGELOG.md` and the version in `gemseo_process_builder/__init__.py`.
2. Run `python tools/third_party_notices.py` if dependencies changed.
3. Go through [release_checklist.md](release_checklist.md) on Windows and Linux.
4. Push a tag `vX.Y.Z`: the release workflow builds the package and keeps the wheel and the sdist as artifacts of the run. The package is **not** published on PyPI (SPEC § 14.5).
