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

The developer tools of the page open with **F12**, **Tools › Developer tools**, or a right click where no other menu opens (`--dev` opens them at startup). `window.app` holds the services of the page.

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
node --test --experimental-test-isolation=none --test-timeout=1000 "tests/js/**/*.test.js"
```

**No test may last more than one second**, setup included (`pytest-timeout`, `node --test --test-timeout=1000`). A slow test is split or rewritten, never exempted:

- build small projects with `tests/python/builders.py` instead of loading big ones;
- run the worker's functions in-process instead of starting the worker;
- run examples with reduced settings (a few iterations or samples);
- `tests/python/conftest.py` imports GEMSEO, PySide6 and scikit-learn at collection time, where the limit does not apply.

Performance is measured apart, by the benchmarks of `benchmarks/` (see its README).

## The Claude copilot plugin

`plugins/gemseo_claude_pilot/` is a separate package, `gemseo-claude-pilot`, specified in [CLAUDE_PILOT_SPEC.md](CLAUDE_PILOT_SPEC.md). It depends on GEMSEO but not on the application, so that plain GEMSEO scripts can use it too. Install it in the development venv:

```bash
pip install -e plugins/gemseo_claude_pilot
```

`tools/check.py` covers it (ruff, mypy, and its tests in `plugins/gemseo_claude_pilot/tests/`). Its pieces:

| Module | Role |
|---|---|
| `snapshots.py` | frozen pictures of a problem and its history, read from a GEMSEO `OptimizationProblem` |
| `detectors.py` | events found without calling Claude: stagnation, infeasibility, divergence, failed evaluations, oscillation, bounds |
| `context.py` | the JSON context of a call, compressed to about 8,000 tokens |
| `privacy.py` | the data levels `full`, `no_code`, `anonymized`, and the anonymizer that translates decisions back |
| `decisions.py`, `guardrails.py`, `algorithms.py` | what Claude may decide, and the limits a decision must respect |
| `exchange.py` | one exchange: context, read tools, decision, one correction if it is refused |
| `triggers.py`, `advisor.py` | when to call Claude, and the calls themselves, in a background thread (or inline, for reproducible runs) |
| `tools.py` | the read tools Claude may call, and their answers |
| `pilot.py` | `ClaudePilot`: the segments, the warm start from the best point, the application of the decisions; a DOE samples in segments (a region is drawn with `compute_doe` and evaluated with `CustomDOE`), a BiLevel sub-optimization is retuned with `set_algorithm` |
| `journal.py` | `journal.jsonl`, written as the run goes |
| `backends/claude_code.py`, `backends/api.py` | Claude Code (the default, the user's subscription) and the Messages API with a key; `create_backend` chooses by name |
| `auth.py`, `budget.py`, `pricing.py` | the API key (environment, then keyring), the budget of a run, the estimated cost with a key |
| `events.py` | the channel to the process running the pilot: events out, the user's commands in (Advisor mode) |
| `session.py` | the copilot process: questions on a finished run, reviews before a run; one JSON request in, one answer out |

In the application, a driver's `copilot` settings (`core/drivers.py`, with `copilot_actions` for the actions that apply to a driver kind) make codegen run the scenario through `ClaudePilot` (`codegen/scenarios.py`); the script reader records `ClaudePilot.execute` instead of running it; `runner/copilot.py` forwards the pilot's events and passes the `run.copilot` commands to it, and the journal goes to `copilot/` in the run folder. The application never imports the plugin. In the page, `lib/copilot.js` holds the pure logic (settings, consent, the `CopilotLog` built from the live events, kept by `RunAccumulator`, or from the journal); `panels/driver_editor/copilot_tab.js`, `shell/copilot_preferences.js` and `views/results/copilot.js` show it; the worker's `copilot_methods.py` checks the backend and keeps the API key, since it runs the interpreter of the runs.
| `backends/` | the `Backend` protocol and `FakeBackend`, which replays scripted answers |
| `prompts/` | the system prompts, versioned |

No test calls Claude: they script `FakeBackend` (with `then=` for the answer once the script is over). The Sellar scenarios the tests read are solved once, at collection time (`tests/conftest.py`); the pilot tests run an analytic Rosenbrock scenario without MDA, with an inline advisor (`threaded=False`) so that they are reproducible. The plugin tests set `GEMSEO_CLAUDE_PILOT_BACKEND=off`: a pilot without an explicit backend never calls Claude; the backends are tested with a stand-in client (API) and a stand-in `query` calling the pilot's MCP tools as Claude Code does.

Smoke test with a real backend, by hand, never in `tools/check.py` (it spends the subscription or the key): run a Sellar scenario with `ClaudePilot(mode="pilot", backend="claude_code", budget=Budget(max_calls=3))`, or `backend="api_key"` with `ANTHROPIC_API_KEY` set, and read the journal in `<script>.pilot/journal.jsonl`. Claude Code must be installed and logged in (`claude auth status`).

## The large-scale optimizer plugin

`plugins/gemseo_lso/` is the package `gemseo-lso`, specified in [LARGE_SCALE_OPTIMIZER_SPEC.md](LARGE_SCALE_OPTIMIZER_SPEC.md): MMA and GCMMA for 10⁵ to 10⁶ variables and constraints. Install it in the development venv with `pip install -e plugins/gemseo_lso`; `tools/check.py` covers it. Its core (`gemseo_lso.core`) depends on NumPy and SciPy only:

| Module | Role |
|---|---|
| `problem.py` | the `LargeScaleProblem` protocol (values, objective gradient, rows of the constraints on request) and `DenseProblem` for the tests |
| `approximation.py` | the MMA approximations from the rows and their absolute values (``p`` and ``q`` never formed for all constraints), the asymptotes, the move limits |
| `dual.py` | the subproblem: L-BFGS-B on its dual, or a primal-dual interior point for small subproblems |
| `optimizer.py` | `Optimizer`: the outer loop, GCMMA's inner loop, the KKT and stall criteria, one iteration per step |
| `state.py`, `report.py`, `settings.py` | the state saved in HDF5, the report of each iteration, the frozen settings replaced between two steps |

## Releases

1. Update `CHANGELOG.md` and the version in `gemseo_process_builder/__init__.py`.
2. Run `python tools/third_party_notices.py` if dependencies changed.
3. Go through [release_checklist.md](release_checklist.md) on Windows and Linux.
4. Push a tag `vX.Y.Z`: the release workflow builds the package and keeps the wheel and the sdist as artifacts of the run. The package is **not** published on PyPI (SPEC § 14.5).
