# GEMSEO Process Builder — Functional and Technical Specification

| | |
|---|---|
| Status | Draft v0.2 |
| Date | 2026-09-24 |
| Target | GEMSEO 6.x · Python ≥ 3.12 · PySide6 · d3.js v7 |
| Platforms | Windows, Linux |
| Distribution | Open source, MIT license, pip package published on PyPI |

---

## 1. Purpose

Build a desktop application that lets users **create, configure, run and analyze GEMSEO processes through a graphical interface**, in the spirit of Ansys ModelCenter, with the goal of offering an **open-source alternative to ModelCenter** for GEMSEO users.

The project is open source under the **MIT license** (see `LICENSE`).

The application is a PySide6 window that displays a web interface (HTML/CSS/JS) in a `QWebEngineView`. All diagrams are drawn as **SVG with d3.js**. **No server** (HTTP or otherwise) is started: the page is loaded from local resources and talks to Python through **QWebChannel**, in the same process.

### 1.1 Users

Two profiles, served by the same interface:

- **Engineers who don't know GEMSEO**: they have optimization basics but don't know the API. The interface must work with sensible defaults and hide advanced options.
- **MDO/GEMSEO experts**: they must reach every option (formulations, MDA settings, algorithm options, namespaces, …).

→ Principle: **simple mode by default, a collapsed "Advanced" section** in every form. Advanced options are generated automatically from GEMSEO 6 Pydantic settings models (§ 8.6).

### 1.2 Guiding principles

1. **The exported script is what runs.** Running from the UI goes through the same code generator as the Python export. There is no second execution path.
2. **Python is the source of truth for the model**; JavaScript is a view/controller that sends commands and receives changes.
3. **User code never runs in the UI process** (scanning, introspection and execution happen in subprocesses).
4. **100 % offline**: all JS dependencies are bundled (vendored), no network access.
5. **Readable generated code**: generated scripts look like code written by a human and are understandable by a developer with two years of experience (§ 10).
6. **Fast tests**: no test lasts more than one second (§ 15).
7. **English only** (§ 1.3).

### 1.3 Language

Everything is written in **English**:

- this specification and all other documentation (README, user guide, developer guide, changelog);
- the user interface (labels, messages, tooltips, errors);
- source code: identifiers, comments, docstrings, log messages, exception messages;
- generated scripts and reports;
- commit messages, issue and pull request descriptions.

### 1.4 Out of scope

- Importing existing GEMSEO Python scripts to turn them into diagrams.
- Running on a cluster/HPC (only local parallelism is supported).
- Internationalization, dark theme.
- Collaborative editing, built-in version control.

---

## 2. ModelCenter → GEMSEO mapping

| ModelCenter | Process Builder | GEMSEO 6 |
|---|---|---|
| Component | **Component** | `Discipline` (analytic, AutoPy, class, executable, surrogate) |
| Quick Wrap / File Wrapper | **Executable wrapper** | Runtime executable discipline (§ 7.5) |
| Assembly | **Assembly** | `MDOChain`, `MDOParallelChain` or `MDAChain` depending on the mode |
| Link | **Link** (explicit) / **Coupling** (implicit, by name) | Name-based coupling + `RemappingDiscipline` / namespaces |
| Optimization Tool | **Optimization driver** | `MDOScenario` + formulation |
| DOE Tool | **DOE driver** | `DOEScenario` |
| Parametric Study | **Parametric study driver** | `DOEScenario` (full factorial / custom) |
| Run once (MDA) | **MDA driver** | `MDAChain` / `MDA*` |
| Nested driver | **Nested driver** | `MDOScenarioAdapter` |
| Response Surface | **Surrogate component** | `SurrogateDiscipline` |
| Data Explorer | **Results view** | `Database` / `Dataset` + post-processings |

---

## 3. Architecture

### 3.1 Overview

```
┌──────────────────────────── UI process (PySide6) ──────────────────────────────┐
│                                                                                │
│  QMainWindow (window + native menu bar)                                        │
│   └─ QWebEngineView ── page gpb://app/index.html (scheme handler, no HTTP)     │
│        │  Vanilla JS (ES modules) + d3 v7 + elkjs                              │
│        │                                                                       │
│        └── QWebChannel ──► Bridge (QObject) ──► Python core                    │
│                                                  ├─ Project model (Pydantic)   │
│                                                  ├─ Commands / undo stack      │
│                                                  ├─ Resolver (couplings)       │
│                                                  ├─ Validator                  │
│                                                  ├─ Codegen                    │
│                                                  ├─ Run manager (QProcess)     │
│                                                  └─ Results store              │
└───────────────┬───────────────────────────────────────────┬────────────────────┘
                │ JSON lines stdin/stdout                   │ JSON lines stdin/stdout
     ┌──────────▼───────────┐                   ┌───────────▼───────────┐
     │ Introspection worker │                   │ Runner (one per run)  │
     │ catalog scan,        │                   │ runs the generated    │
     │ grammars, XDSM,      │                   │ script, emits events  │
     │ dry run, post-proc.  │                   │                       │
     └──────────────────────┘                   └───────────────────────┘
        (user's Python environment with GEMSEO + user code)
```

### 3.2 Loading the page without a server

- Register a custom `gpb://` scheme with `QWebEngineUrlScheme.registerScheme()` **before** creating the `QApplication`, with the flags `SecureScheme | LocalScheme | LocalAccessAllowed | CorsEnabled`.
- A `QWebEngineUrlSchemeHandler` serves the files of the package's `static/` folder (direct file reads, in the same process: this is not a server).
- Reason: Chromium blocks ES modules (`<script type="module">`) over `file://`; the custom scheme allows them without a build step.
- `qwebchannel.js` is read from the Qt resource `:/qtwebchannel/qwebchannel.js` and served at `gpb://app/vendor/qwebchannel.js`.
- `QWebEngineSettings`: remote network access disabled, `LocalContentCanAccessRemoteUrls = False`. Any navigation outside `gpb://` is blocked (`acceptNavigationRequest`).
- DevTools can be enabled in developer mode (`--dev`).

### 3.3 Responsibilities

| Area | Python (UI process) | JavaScript | Subprocesses |
|---|---|---|---|
| Project model | Source of truth, schema validation | Read-only mirror, updated through patches | — |
| Editing | Commands, undo/redo, coupling resolution | Interactions, optimistic updates during a drag | — |
| Rendering | — | Canvas, N2, XDSM, tree, result charts | — |
| Catalog | Cache, preferences | Library panel | Scan + introspection |
| Validation | Static rules | Problems panel | GEMSEO dry run |
| Execution | Run management (QProcess) | Live monitoring | Runner |
| Post-processing | Run storage | d3 charts | Native GEMSEO post-processings |
| Files | Native Qt dialogs, reading/writing | — | — |

### 3.4 QWebChannel bridge

A single `Bridge(QObject)` object is exposed under the name `bridge`, with the slot `call` and the signals `reply` and `page_event`.

**Generic call (JS → Python)**

- Slot `call(request_json: str)` with `{ "id": "<uuid>", "method": "<name>", "params": {...} }`.
- The response comes through the `reply(response_json: str)` signal: `{ "id", "ok": true, "result" }` or `{ "id", "ok": false, "error": { "code", "message", "details" } }`.
- On the JS side, `bridge.js` exposes `await api.call(method, params)` (a Promise with a configurable timeout).
- Long operations (scan, introspection, dry run, post-processing) run in a `QThreadPool` or in a worker; they never block the Qt event loop.

**Events (Python → JS)**

- Signal `page_event(event_json: str)` with `{ "type", "payload" }` (not `event`, which would hide `QObject.event`).
- Types: `document.patch`, `document.reset`, `undo.state`, `catalog.updated`, `validation.updated`, `run.started`, `run.event`, `run.log`, `run.finished`, `worker.status`, `notification`.

**Main methods**

| Method | Purpose |
|---|---|
| `project.new / open / save / saveAs / close` | Project lifecycle (native dialogs on the Python side) |
| `project.get` | Full document snapshot |
| `doc.execute(command)` | Applies an editing command, returns the revision |
| `doc.undo / redo` | History |
| `doc.copy(ids) / paste(target, position)` | Clipboard (MIME type `application/x-gpb-subgraph`) |
| `catalog.list / refresh` | Library |
| `component.introspect(config)` | Computes a component's ports |
| `resolve.couplings(scope)` | Implicit and explicit couplings of a scope |
| `validate(scope?)` | Static validation (+ optional dry run) |
| `algorithms.list(kind)` / `settings.schema(kind, name)` | Algorithm lists and JSON schemas of GEMSEO settings |
| `xdsm.build(driverId)` / `n2.build(scope)` | Data for the XDSM and N2 views |
| `codegen.export(driverId, path)` | Python script export |
| `run.start(driverId) / stop(runId)` | Execution |
| `results.list / load / query / export` | Results |
| `postproc.list / run(runId, name, settings)` | Native GEMSEO post-processings |
| `surrogate.train(config)` | Surrogate training |
| `report.generate(options)` | HTML/PDF report |
| `image.export(svg, format, path)` | SVG/PNG export |
| `prefs.get / set` | Preferences |

### 3.5 Document synchronization

- Each applied command increments a **revision** and produces a list of changes: `{ rev, changes: [ { op: "upsert"|"delete", kind: "node"|"link"|"port"|"driver"|…, id, data? } ] }`.
- JS applies the patches to its mirror (`store.js`) and redraws only the affected elements.
- If a revision is missing or inconsistent, JS requests a full `project.get` (`document.reset`).
- During a drag, positions are updated locally; a single `moveNodes` command is sent at the end of the gesture (one history entry).

### 3.6 Repository layout

```
gemseo_process_builder/
  __main__.py              # python -m gemseo_process_builder / gemseo-process-builder script
  app/                     # Qt: window, web view, scheme handler, bridge, dialogs
  core/
    model.py               # Pydantic project models (versioned schema)
    migrations.py          # schema migrations
    commands.py            # editing commands + undo stack
    resolver.py            # global names, couplings, remappings, namespaces
    validation.py          # static rules
    units.py               # unit handling (pint)
  catalog/                 # folder scanning, cache, descriptors
  workers/
    protocol.py            # shared JSON-lines protocol
    introspection.py       # introspection / dry run / post-processing worker
  codegen/                 # GEMSEO script generation
  runtime/                 # used by generated scripts (no Qt dependency)
    executable.py          # executable discipline (file wrapper)
    decorators.py          # @component to expose functions to the catalog
  runner/                  # entry point of the execution subprocess
  results/                 # run storage, HDF5/CSV reading
  report/                  # report generation
  static/
    index.html
    css/
    js/
      main.js
      bridge.js            # QWebChannel wrapper → Promises
      store.js             # document mirror, patch application
      lib/                 # pure logic (no DOM), testable under Node
      panels/              # library, tree, inspector, console, problems, runs
      views/
        canvas/            # flow diagram
        n2/
        xdsm/
        results/           # history, table, scatter matrix, parallel coordinates, …
      forms/               # forms generated from JSON Schema
    vendor/                # d3.v7.min.js, elk.bundled.js, (xdsmjs if chosen)
tests/
  python/                  # pytest
  js/                      # node --test
examples/                  # reference projects (Sellar, SSBJ, …)
```

---

## 4. Data model

### 4.1 Entities

- **Project**: metadata, project-specific settings (catalog folders, runs folder), root node, surrogates, run index.
- **Node** (identified by a UUID, with a name that is unique **within its parent**):
  - **Assembly**: hierarchical container with `children` and an execution `mode` (§ 6.1).
  - **Component**: discipline; `kind` ∈ `analytic | python_function | python_class | executable | surrogate`.
  - **Driver**: hierarchical container; `kind` ∈ `mda | doe | optimization | parametric`, with `children` and its configuration (§ 6.2).
- **Port**: `local_name`, `direction` (`in`/`out`), `dtype` (`float | int | complex | str | path | object`), `shape` (`[]`, `[n]`, `[n, m, …]`), `unit`, `default`, `description`, `global_name` (derived, § 5).
- **Link**: explicit link `{ from: {node, port}, to: {node, port} }`.
- **Container ports**: derived, never entered by the user (§ 5.4).

### 4.2 Project file

- `.gpb.json` extension, indented JSON that reads well in a diff, with stable key ordering.
- Integer `schema_version`; each version bump ships a migration (`core/migrations.py`) with tests. Opening an older file migrates it in memory and offers to save it.
- Paths (modules, templates, surrogates, runs) are **relative to the project file**.
- Layout data (positions, collapsed states, zoom per level) is stored in a separate `layout` section to keep diffs quiet.

```json
{
  "schema_version": 1,
  "metadata": { "name": "Sellar", "description": "", "created": "2026-09-24T10:00:00Z", "gpb_version": "0.1.0" },
  "settings": { "catalog_paths": ["./disciplines"], "runs_dir": "./Sellar.runs" },
  "root": {
    "id": "n-root", "type": "assembly", "name": "Model", "mode": "auto",
    "children": [
      {
        "id": "n-opt", "type": "driver", "kind": "optimization", "name": "Optimizer",
        "config": {
          "formulation": { "name": "MDF", "settings": { "main_mda_name": "MDAGaussSeidel" } },
          "design_space": [
            { "variable": "x_local", "lower": [0.0], "upper": [10.0], "value": [1.0], "type": "float" },
            { "variable": "x_shared", "lower": [-10.0, 0.0], "upper": [10.0, 10.0], "value": [4.0, 3.0], "type": "float" }
          ],
          "objectives": [ { "variable": "obj", "sense": "minimize" } ],
          "constraints": [
            { "variable": "c_1", "type": "ineq", "operator": "<=", "value": 0.0 },
            { "variable": "c_2", "type": "ineq", "operator": "<=", "value": 0.0 }
          ],
          "observables": [],
          "algorithm": { "name": "SLSQP", "settings": { "max_iter": 100 } }
        },
        "children": [
          {
            "id": "n-s1", "type": "component", "kind": "python_class", "name": "Sellar1",
            "config": { "module": "gemseo.problems.mdo.sellar.sellar_1", "class": "Sellar1", "init_args": {} },
            "ports": [ { "local_name": "x_local", "direction": "in", "dtype": "float", "shape": [1], "unit": "" } ]
          }
        ]
      }
    ]
  },
  "links": [],
  "surrogates": [],
  "runs": [ { "id": "r-20260924-101500", "driver": "n-opt", "path": "./Sellar.runs/r-20260924-101500" } ],
  "layout": { "n-opt": { "x": 120, "y": 80, "collapsed": false } }
}
```

### 4.3 Identifiers and paths

- Internal identifier: UUID (stable, used by links and layout).
- Displayed path: `Model.Optimizer.Sellar1.x_local`, as in ModelCenter.
- Renaming a node never breaks a link. A variable's global name (§ 5) does not change when a node is renamed, unless the variable is isolated by a namespace.

---

## 5. Variable linking (hybrid model)

GEMSEO couples disciplines **by global variable name**, whereas ModelCenter connects variables through **explicit links**. The Process Builder combines both.

### 5.1 Rules

1. Each port has a `global_name`, equal by default to its `local_name`.
2. **Implicit coupling**: within the scope of a driver (or of the root model), an output and an input with the same `global_name` are coupled. The diagram shows them as **dashed links**.
3. **Explicit link**: drawing a link from an output `a` to an input `b` sets `global_name(b) := global_name(a)`. It is shown as a **solid line**. Deleting the link restores `b`'s default name.
4. An input has **at most one producer**. Two outputs with the same `global_name` in the same scope are an **error**.
5. An output can feed several inputs.
6. **Namespace isolation**: a component or an assembly can be marked `isolated`. Its ports then get the `<name>:` prefix (GEMSEO namespaces), which allows several instances of the same component. Only explicit links cross an isolation boundary.
7. Experts can edit a port's global name in the inspector; the diagram updates accordingly.

### 5.2 GEMSEO translation (codegen)

- A component with at least one `global_name` that differs from its `local_name` (namespaces aside) is wrapped in `RemappingDiscipline(discipline, input_mapping=…, output_mapping=…)`.
- Isolation uses `discipline.add_namespace_to_input/output` (GEMSEO 6 namespaces API).
- Unit conversion (§ 5.5): a generated conversion discipline (`AnalyticDiscipline` or `LinearDiscipline`) is inserted.

### 5.3 Coupling loops

- The resolver computes the dependency graph (strongly connected components). Feedback links are drawn in a **dedicated color** with a backward arrow.
- A loop inside an assembly in `chain` mode is an error, with the quick fix "Switch to MDA". A loop inside an assembly in `auto` or `mda` mode is solved by an MDA.

### 5.4 Container ports

- **Inputs of an assembly or driver**: the inputs of its descendants that are not produced inside it.
- **Outputs**: all the outputs of its descendants, except internal outputs the user has hidden. A driver only exposes the variables declared "exposed" (§ 6.3).
- Seen from the parent, a collapsed container shows these derived ports. Multiple links between two containers are aggregated into one link with a counter.

### 5.5 Units

- A unit is a **pint**-compatible string. Empty string: dimensionless; `null`: not specified.
- Sources: user input, `@component(units=…)` decorator, wrapper descriptor, or grammar metadata when present.
- Check on each coupling:
  - incompatible dimensions → **error**;
  - compatible but different units (`mm` → `m`) → **warning**, with automatic conversion inserted at generation time (can be disabled per link);
  - unit missing on one side → **info**.

### 5.6 Variable types

- Scalars and vectors (`shape` `[]` / `[n]`): the standard GEMSEO case.
- Matrices / N-D arrays: allowed. **Warning** when an N-D variable is a coupling variable solved by an MDA, or a design variable (GEMSEO expects 1-D vectors). Codegen: automatic flattening and reshaping if the user accepts it.
- `str` / `path`: allowed as component inputs/outputs (external codes in particular). **Error** when used as a design variable, objective, constraint or MDA coupling.

---

## 6. Hierarchy and drivers

### 6.1 Assembly

| Mode | GEMSEO translation |
|---|---|
| `auto` (default) | `MDAChain` if there are loops, otherwise `MDOChain` (topological order) |
| `chain` | `MDOChain`, in the displayed order |
| `parallel` | `MDOParallelChain` (error if there are internal dependencies) |
| `mda` | `MDAChain` with explicit settings (inner solver: Jacobi, GaussSeidel, Newton, hybrid; tolerance; maximum iterations, …) |

An assembly can be marked `transparent`: its children are then flattened into the parent driver's list of disciplines instead of becoming one composite discipline. This is useful to let the MDF formulation build its own MDA.

### 6.2 Drivers

All drivers are **containers**. The workflow they drive is made of their children, as in ModelCenter.

| Driver | Translation | Configuration |
|---|---|---|
| **MDA** | `MDAChain` executed once | Input values, MDA settings |
| **DOE** | `DOEScenario` | Formulation (default `DisciplinaryOpt`, or MDF/IDF), design space, responses, DOE algorithm and settings, `n_samples`, `n_processes` |
| **Optimization** | `MDOScenario` | Formulation (MDF, IDF, DisciplinaryOpt, BiLevel), design space, objectives, constraints, observables, algorithm and settings |
| **Parametric study** | `DOEScenario` (full factorial or custom) | 1 to n variables, levels (linspace / list), responses |

Specifics:

- **DOE**: GEMSEO requires an objective. The UI only offers "Responses"; the first one becomes the technical objective and the others become observables. This detail is hidden in simple mode.
- **Multi-objective**: allowed if the algorithm supports it, otherwise a validation error.
- **BiLevel**: the system driver contains child optimization drivers (disciplinary sub-scenarios) and possibly other disciplines. Codegen passes the sub-scenarios to the `BiLevel` formulation.

### 6.3 Nested drivers

- A driver placed inside an assembly or another driver becomes a discipline through `MDOScenarioAdapter`.
- In the driver's "Interface" tab, the user picks the **exposed inputs** (the variables the parent provides, for example shared variables) and the **exposed outputs** (for example the optimum and the constraints). Advanced settings: `reset_x0_before_opt`, `set_x0_before_opt`, etc.
- Example: a DOE around an optimization.

### 6.4 Driver editor

It opens in the inspector, and full-panel when the driver header is double-clicked. Tabs:

1. **Design variables**: table (variable, size, lower, upper, initial value, float/int type, advanced scaling). The picker offers **only the free inputs** of the scope. Vectors are edited element by element, or with a single value applied to every element.
2. **Objectives**: variable (outputs of the scope), minimize/maximize.
3. **Constraints**: variable, type (`eq`/`ineq`), operator (`<=`/`>=`), threshold value.
4. **Observables / Responses**.
5. **Algorithm**: choice among the installed GEMSEO algorithms (factories), with a generated settings form (§ 8.6). Algorithms that are incompatible with the problem (constraints, gradients, multi-objective) are grayed out, with a tooltip explaining why.
6. **Formulation**: choice and settings (main MDA, etc.).
7. **Interface** (nested drivers only).
8. **Execution**: `n_processes`, working directory, history saving.

---

## 7. Components

### 7.1 Analytic

- Expressions typed in an editor (`y = x**2 + sin(z)`); inputs are inferred from the symbols.
- Immediate syntax check in the worker (sympy). Units entered per port.
- Translation: `AnalyticDiscipline(expressions, name=…)`.

### 7.2 Python function

- `module:function` reference, from a catalog file or a free path.
- Ports inferred from the signature and the `return` statement, as `AutoPyDiscipline` does.
- Translation: `AutoPyDiscipline(py_func)`.

### 7.3 Python class

- `module:Class` reference, for any `Discipline` subclass.
- `init_args`: form generated from the `__init__` signature (annotated types, default values).
- Introspection: the worker instantiates the class with the `init_args` and reads its grammars (names, types, shapes when known, default values).

### 7.4 Surrogate

- Built **from a DOE run of the project**: "Build surrogate" wizard (from a run or from the library). Steps:
  1. choose the run and the inputs/outputs;
  2. choose the algorithm (RBF, GPR, polynomial, …) and its settings;
  3. train in the worker;
  4. display quality measures (R², RMSE, cross-validation, predicted-vs-observed chart in d3).
- It is saved as a pickle in `<project>.surrogates/`; the component references it. Translation: `SurrogateDiscipline` loaded from the file.
- The link to the source run is kept for traceability. If the run is deleted, the surrogate stays usable.

### 7.5 Executable wrapper (Quick Wrap / File Wrapper equivalent)

A discipline provided by `runtime/executable.py`. It builds on GEMSEO 6's executable base class if it fits; **to be checked** in work package 7.

Configuration:

- **Command**: command line with `{input_file}`, `{workdir}`, etc. tokens; executable and arguments; environment variables; timeout.
- **Working directory**: one temporary folder per execution (mandatory when `n_processes > 1`), with a retention policy (`always | on_error | never`) and files to copy.
- **Input templates**: template files with `{{variable}}` markers and a number format (`{{x:.6e}}`), for scalars and vectors.
- **Output parsing**: one rule per output:
  - `regex` with a capture group;
  - `marker`: line after a marker, column n;
  - `key=value`;
  - `table`: block of lines → vector;
  - `file`: the output is the path of a produced file.
- **Error handling**: expected return code, error pattern in standard output.

Graphical editor:

- Load a sample input file. Selecting a number turns it into a marker and creates the matching port.
- Load a sample output file. Selecting a value creates a parsing rule, with a preview of the extracted value.
- "Test run" button: runs the wrapper with default values in the worker, then shows the extracted outputs and the logs.

A wrapper can be saved as a **reusable descriptor** `*.gpbwrap.json` in a catalog folder.

### 7.6 Catalog (library)

- Sections:
  - **Built-in**: Analytic, Python function, Python class, Executable wrapper, Surrogate, Assembly, MDA/DOE/Optimization/Parametric drivers.
  - One node per configured **catalog folder** (global and project preferences).
- Detection in each folder (in a subprocess, never imported in the UI):
  - `Discipline` subclasses **defined** in `*.py` modules (not the ones they import);
  - functions decorated with `@gemseo_process_builder.runtime.component(...)`, which can provide units, description and icon;
  - `*.gpbwrap.json` descriptors.
- Cache keyed by (path, mtime), **Refresh** button, and folder watching (`QFileSystemWatcher`) with debounced refresh.
- A module import error is shown in the library (warning icon + traceback in the console) without blocking the others.
- Full-text search; add to the canvas or the tree by drag and drop.

---

## 8. User interface

### 8.1 Layout

Qt provides the window, the native menu bar and the file dialogs. The rest of the interface is HTML.

```
┌ File  Edit  View  Model  Run  Tools  Help ───────────────────────────────────────┐
│ [New][Open][Save] │ [Undo][Redo] │ [Validate][Run ▶][Stop ■] │ [Layout][Fit] [🔍] │
├───────────────┬──────────────────────────────────────────────┬───────────────────┤
│ Library │Tree │ Workflow │ N2 │ XDSM │ Results: run-003 ×    │ Inspector         │
│ ┌───────────┐ │ Model › Optimizer ›                          │ ┌───────────────┐ │
│ │ search…   │ │                                              │ │ Sellar1       │ │
│ ├───────────┤ │   ┌─────────┐          ┌─────────┐           │ │ Properties    │ │
│ │▸ Built-in │ │ ─►│ Sellar1 │─ y_1 ───►│ Sellar2 │─┐         │ │ Variables     │ │
│ │▸ Drivers  │ │   └─────────┘◄─ y_2 ───└─────────┘ │         │ │ ┌───┬───┬───┐ │ │
│ │▸ disc/    │ │        ▲                           ▼         │ │ │nam│val│uni│ │ │
│ │  aero.py  │ │        └──────── ┌──────────────┐           │ │ └───┴───┴───┘ │ │
│ │  struct.py│ │                  │ SellarSystem │           │ └───────────────┘ │
│ └───────────┘ │                  └──────────────┘  ┌─────┐  │                   │
│               │                                    │mini │  │                   │
│               │                                    │ map │  │                   │
├───────────────┴────────────────────────────────────┴─────┴──┴───────────────────┤
│ Console │ Problems (2) │ Runs                                                    │
│ 10:15:02 INFO  Optimization problem: minimize obj(x_local, x_shared)             │
└──────────────────────────────────────────────────────────────────────────────────┘
```

- All panels can be resized (splitters) and collapsed; the layout is saved in the preferences.
- Status bar: project path, modified state, worker status, current run with progress.

### 8.2 "Workflow" canvas (d3, SVG)

**Navigation**

- Zoom and pan (`d3.zoom`), "Fit to view", zoom to selection.
- **Hierarchical navigation**: double-click an assembly or a driver to enter it, with a clickable breadcrumb (`Model › Optimizer › Aero`). Containers can also be expanded in place.
- **Minimap** (bottom-right corner) with a draggable viewport rectangle.
- **Search** (Ctrl+F) for components and variables by name, with navigation between results, re-centering and highlighting.

**Node rendering**

- Component: box with a header (type icon, name, execution status dot), input ports on the left and output ports on the right. Port display: `all | connected | none`, with a counter of hidden ports.
- Assembly and driver: containers whose header is styled by type (driver color and icon); they can be collapsed.
- Validation state: red or orange border, with a tooltip listing the problems.

**Links**

- Bézier curves: solid for an explicit link, dashed for an implicit coupling, dedicated color for feedback, thickness or badge for an aggregated link.
- Hovering a link: tooltip with the variables, units and conversions.
- Hovering a port: highlights its links and its producer.

**Editing**

- Drag and drop from the library.
- Draw a link by dragging from an output port to an input port, with visual compatibility feedback (type, shape, unit) during the gesture.
- Dragging a port onto a container's background exposes it.
- Single or multiple selection (click, Ctrl+click, rectangle), move, delete.
- Copy, cut, paste and duplicate. Pasting suffixes conflicting names.
- Group the selection into a new assembly (Ctrl+G), ungroup (Ctrl+Shift+G).
- Context menu: Rename, Isolate namespace, Set as design variable / objective / constraint (shortcuts that open the pre-filled driver editor), Show in tree, Show in N2.
- **Undo/redo**, practically unlimited (bounded history, 500 by default), with composite gestures grouped into one entry.

**Auto-layout**: elkjs (`layered` algorithm, ordered ports, hierarchy) running in a **Web Worker**. It applies to the current level or the selection; manual positions are kept elsewhere.

### 8.3 Model tree

- Tree: Model › assemblies/drivers › components › variables (inputs and outputs, with role icons: design variable, objective, constraint, coupling).
- Selection synchronized with the canvas, the N2 and the inspector. In-place renaming, drag and drop to re-parent, same context menu as the canvas.
- Virtualized list: only the visible rows are in the DOM.

### 8.4 N2 view

- N2 matrix of the current scope, built by the resolver: disciplines on the diagonal, couplings off the diagonal.
- Collapsible blocks per assembly; click a cell to see the coupled variables; order can be changed by drag and drop (no effect on execution, except in `chain` mode where order matters).
- **Virtualized** SVG rendering (only visible cells are drawn), level of detail depending on zoom.

### 8.5 XDSM view

- Data produced by the worker from the scenario built by the generated code (GEMSEO's `XDSMizer`, XDSM JSON).
- d3 SVG rendering: either by reusing vendored **xdsmjs** or with a custom renderer if xdsmjs causes problems (decision in work package 6).
- HTML export (standalone xdsmjs) and PDF export (pyxdsm, only when LaTeX is available; otherwise the option is grayed out).

### 8.6 Generated forms

- GEMSEO 6 settings (optimization and DOE algorithms, MDAs, formulations, surrogates, post-processings) are Pydantic models. The worker returns their `model_json_schema()`.
- `forms/` builds the form from the JSON Schema: simple types, enumerations, arrays, bounds, descriptions as tooltips, default values, and an "Advanced" section for non-essential fields (a list of essential fields for common algorithms is maintained in the code).
- Validation on the Python side relies on the Pydantic model; errors are shown below the fields.

### 8.7 Inspector

Depends on the selection:

- **Properties**: name, description, type, component-specific configuration (§ 7), assembly mode, namespace.
- **Variables**: editable table (local name, global name, direction, type, shape, unit, default value, description, role). Filter and sort; virtualized.
- **Driver**: driver editor (§ 6.4).
- **Link**: variables, units, conversion.

### 8.8 Console, Problems, Runs

- **Console**: logs from the application, the worker and the runs, with levels (filter), search, copy and clear.
- **Problems**: validation results (error, warning, info); click to locate the element, "Quick fix" when possible.
- **Runs**: run history of the project (id, driver, date, duration, status, best objective). Open, rename, delete, compare, export.

### 8.9 Keyboard shortcuts

`Ctrl+N/O/S/Shift+S`, `Ctrl+Z / Ctrl+Y`, `Ctrl+C/X/V/D`, `Del`, `Ctrl+A`, `Ctrl+F`, `Ctrl+G / Ctrl+Shift+G`, `F5` (Run), `Shift+F5` (Stop), `F7` (Validate), `Ctrl+L` (Auto-layout), `F` (Fit), `Backspace` / `Alt+↑` (go up one level).

---

## 9. Validation

### 9.1 Static validation (UI process, continuous, debounced by 300 ms)

| Rule | Level |
|---|---|
| Two producers for the same global name in a scope | Error |
| More than one explicit link to the same input | Error |
| Type, shape or unit dimension mismatch on a coupling | Error |
| Loop in a `chain` assembly, dependency in a `parallel` assembly | Error |
| Design variable that is not a free input of the scope | Error |
| Optimization without an objective, DOE without a response | Error |
| `str`/`path` variable used as a design variable, objective, constraint or MDA coupling | Error |
| Inconsistent bounds, initial value out of bounds | Error |
| Incompatible algorithm (constraints, gradients, multi-objective) | Error |
| Component whose introspection failed | Error |
| Free input without a default value | Warning |
| Different but compatible units (conversion inserted) | Warning |
| N-D variable in an MDA coupling or as a design variable | Warning |
| Unused output | Info (can be disabled) |

### 9.2 Dry run (on demand, and automatically before each run)

The worker runs the generated script in `build_only` mode: disciplines and scenario are built, nothing is executed. GEMSEO exceptions are reported in Problems and attached to the relevant node when possible.

---

## 10. Code generation

### 10.1 Principles

- `codegen` produces a **standalone Python script**. It depends only on `gemseo`, the user's modules, and `gemseo_process_builder.runtime` **only** for features without a GEMSEO equivalent (executable wrapper, component decorator).
- Script contract: `build_scenario()` builds the disciplines and the scenario, `execute_scenario(scenario)` runs the algorithm with its settings, and `main()` calls both, then saves the history and the dataset. The runner **imports** the module, calls `build_scenario()`, attaches its instrumentation (§ 11.3), calls `execute_scenario()`, then saves the outputs into the run folder itself. `main()` is only used for standalone runs.
- The mapping between discipline names and diagram node ids, needed by the runner, is written to a **sidecar file** (`script.gpb-map.json`), never into the script.

### 10.2 Readability requirements

The generated code must look like code written by a human and be understandable by a **developer with two years of experience** who knows Python but not necessarily GEMSEO.

**Naming**

- Variables and functions use meaningful `snake_case` names derived from the diagram names (`aerodynamics`, `structure_mda`, `wing_optimization`), never UUIDs, generic counters (`d1`, `disc_17`) or technical prefixes.
- GEMSEO variable names are written as plain string literals, as they appear in the diagram.

**Structure**

- Reads top to bottom: imports, constants, then one short function per step (`build_disciplines`, `build_design_space`, `build_scenario`, `execute_scenario`, `main`), in the order they are used.
- One statement per diagram concept: one discipline creation per component, one `add_variable` per design variable, one `add_constraint` per constraint. Loops only for genuinely repetitive data (for example vector bounds).
- Functions of at most about 40 lines; beyond that, a helper named after the diagram element (`build_wing_subsystem()`).
- Uses the high-level GEMSEO API (`create_discipline`, `create_design_space`, `create_scenario`, `create_mda`) where it exists, and explicit keyword arguments.
- Only settings that differ from GEMSEO defaults are written.
- Numeric values are written as the user typed them (`1e-6`, not `1.0000000000000002e-06`).

**Forbidden in generated code**

- `exec`, `eval`, `getattr`/`setattr` on computed names, `importlib` tricks, metaclasses, monkey-patching.
- Generic data-driven builders (for example a big dict of specs fed to a factory loop) when explicit statements are clearer.
- Nested comprehensions, one-line lambdas with side effects, clever idioms.
- Instrumentation, tracking or UI-related code.
- Dead code, unused imports, `# noqa` comments.

**Comments**

- A module docstring stating the project, the source file, the generation date and how to run the script.
- One short comment per section explaining *what* the section builds and *why*, for example why an MDA is needed (coupling loop between `aerodynamics` and `structure`) or why a remapping is used (the diagram links `lift` to `load`).
- The first use of a GEMSEO concept (formulation, MDA, namespace, remapping, adapter) gets a one-line explanation. No line-by-line paraphrasing.

**Formatting**

- PEP 8, emitted already formatted as `ruff format` would format it (`ruff` is not a runtime dependency). Tests check that generated scripts pass `ruff format --check`, `ruff check` with the project rule set without any warning, and `mypy`.
- Type hints on every function signature.

### 10.3 Example of expected output

```python
"""Sellar optimization problem.

Generated by GEMSEO Process Builder 0.1.0 from Sellar.gpb.json on 2026-09-24.
Run it with: python sellar_optimization.py
"""

from gemseo import configure_logger
from gemseo import create_design_space
from gemseo import create_discipline
from gemseo import create_scenario
from gemseo.algos.design_space import DesignSpace
from gemseo.core.discipline import Discipline
from gemseo.scenarios.mdo_scenario import MDOScenario


def build_disciplines() -> list[Discipline]:
    """Create the three disciplines of the Sellar problem."""
    sellar_1 = create_discipline("Sellar1")
    sellar_2 = create_discipline("Sellar2")
    sellar_system = create_discipline("SellarSystem")
    return [sellar_1, sellar_2, sellar_system]


def build_design_space() -> DesignSpace:
    """Define the variables the optimizer is allowed to change."""
    design_space = create_design_space()
    design_space.add_variable("x_local", lower_bound=0.0, upper_bound=10.0, value=1.0)
    design_space.add_variable(
        "x_shared",
        size=2,
        lower_bound=[-10.0, 0.0],
        upper_bound=[10.0, 10.0],
        value=[4.0, 3.0],
    )
    return design_space


def build_scenario() -> MDOScenario:
    """Set up the optimization of the objective under the two constraints."""
    # MDF formulation: an MDA solves the coupling between Sellar1 and Sellar2
    # (y_1 <-> y_2) at each optimizer iteration.
    scenario = create_scenario(
        build_disciplines(),
        "obj",
        build_design_space(),
        formulation_name="MDF",
        main_mda_name="MDAGaussSeidel",
    )
    scenario.add_constraint("c_1", constraint_type="ineq")
    scenario.add_constraint("c_2", constraint_type="ineq")
    return scenario


def execute_scenario(scenario: MDOScenario) -> None:
    """Run the SLSQP optimizer for at most 100 iterations."""
    scenario.execute(algo_name="SLSQP", max_iter=100)


def main() -> None:
    configure_logger()
    scenario = build_scenario()
    execute_scenario(scenario)
    scenario.save_optimization_history("history.h5")
    scenario.to_dataset().to_csv("dataset.csv")


if __name__ == "__main__":
    main()
```

The exact GEMSEO calls must be checked against the targeted 6.x version; the style is what this example fixes.

### 10.4 Checks

- Snapshot tests: every reference project (§ 15.3) has a golden script, reviewed by a human when it changes.
- Every generated script is checked with `ruff check`, `ruff format --check` and `mypy`.
- Equivalence: running the exported script alone gives the same results as a run from the UI.

---

## 11. Execution

### 11.1 Launch

- `Run` executes the selected driver, or else the top-level driver. If the model has no driver, it is evaluated once (MDA equivalent).
- Sequence:
  1. static validation;
  2. snapshot of the project saved in the run folder;
  3. script generation;
  4. dry run;
  5. runner started through `QProcess` with the configured Python interpreter (`sys.executable` by default).
- One run at a time by default; concurrent runs are a preference option.
- During a run, the model can still be browsed, but **the running driver cannot be edited**.

### 11.2 Runner ↔ UI protocol (no server)

- At startup, the runner duplicates the original `stdout` descriptor for its **event channel**, then redirects `sys.stdout` to `stderr`. That way `print` calls in user code cannot corrupt the protocol.
- Events (JSON lines on the event channel):
  - `started { run_id, pid }`;
  - `log { level, logger, message, time }` (dedicated `logging` handler);
  - `status { node_id, state: pending|running|done|failed }`;
  - `progress { current, total, unit: "iteration"|"sample" }`;
  - `iteration { index, x, f, g, h, observables, feasible }`;
  - `sample { index, inputs, outputs }`;
  - `finished { state: completed|stopped|failed, summary, error? }`.
- Commands (JSON lines on `stdin`): `stop`.
- `stderr` is shown in the console, at `WARNING` level for unstructured lines.

### 11.3 Instrumentation

- **Iterations and samples**: new-iteration listener on the optimization problem's `Database`.
- **Component states**: observers on the execution status of GEMSEO 6 disciplines. If no suitable observation API exists, a wrapper around `execute` is used. **To be checked** in work package 3. `node_id`s come from the sidecar mapping file (§ 10.1).
- **With `n_processes > 1`**: no per-component state (executions happen in child processes); only progress and aggregated samples are reported.
- Event rate limited to 20 messages per second per type, aggregated beyond that.

### 11.4 Stopping

1. `Stop` sends `stop` on `stdin`.
2. The runner raises a stop exception at the next instrumentation point, lets GEMSEO finish cleanly, saves the partial history and emits `finished { state: "stopped" }`.
3. If there is no answer after 10 s (configurable), the process tree is killed (`psutil`, including `n_processes` children) and the run is marked `killed`.

### 11.5 Live monitoring in the UI

- **Live logs** in the console (run tab).
- **Component coloring** on the canvas (pending, running with a subtle animation, done, failed).
- **Progress bar** (iterations or samples) and Stop button.
- **Live history**: the run's Results tab opens automatically. Convergence charts (objective, constraints, design variables) or DOE sample cloud, updated as the run progresses.

---

## 12. Results and post-processing

### 12.1 Storage

```
<project>.runs/<run_id>/
  run.json              # metadata: driver, dates, duration, status, versions, summary
  project.gpb.json      # project snapshot at launch
  script.py             # executed script
  script.gpb-map.json   # discipline name → node id mapping
  history.h5            # GEMSEO history (Database / OptimizationProblem)
  dataset.csv           # tabular export (inputs, outputs, feasibility)
  run.log               # full logs
  postproc/             # images of GEMSEO post-processings
```

- The project references its runs; a run can be reopened after closing and reopening the project.
- Deleting a run: confirmation, then the folder is deleted.

### 12.2 Interactive d3 views (Results tab)

- **Summary**: status, duration, number of evaluations, optimum (design variables, objectives, constraints with active/violated indicator), best feasible point.
- **History**: convergence of the objective, of the constraints (with threshold) and of the normalized design variables; log/linear scale toggle.
- **Data table**: virtualized table (sort, filter, column selection), CSV export.
- **Scatter matrix** and **XY plot**: variable selection, coloring by feasibility or by a variable, linked brushing between charts and table.
- **Parallel coordinates**: per-axis filters (brush).
- **Parametric**: one-variable curve, heat map or contour plot for two variables.
- **Compare runs**: overlay of the histories of several runs.

For large volumes (≥ 10,000 points), display-time downsampling and binning in the scatter matrix, while staying in SVG.

### 12.3 Native GEMSEO post-processings

- List of available post-processings (OptHistoryView, ScatterPlotMatrix, Correlations, ParallelCoordinates, QuadApprox, SOM, ConstraintsHistory, …), with a generated settings form (§ 8.6).
- Run in the worker on `history.h5`. The images (SVG, or PNG as a fallback) are saved in `postproc/` and shown in a gallery.

---

## 13. Exports and report

- **Python script** (§ 10).
- **Images**: SVG export (inlined styles) or PNG export (rendered by Qt, 1×/2×/4× scale) of any view: canvas at the current level or in full, N2, XDSM, result charts.
- **XDSM**: standalone HTML, PDF through pyxdsm when available.
- **Report**: standalone HTML (inline SVG, base64 images) and PDF through `QWebEnginePage.printToPdf`. Selectable content:
  - project description;
  - diagrams;
  - inventory of components and variables;
  - problem definition (design space, objectives, constraints, algorithm);
  - results of one or more runs;
  - selected post-processings.

---

## 14. Non-functional requirements

### 14.1 Performance

The target is "very large models". Targets measured with the synthetic model generator (`benchmarks/`, § 15.5):

| Measure | Target |
|---|---|
| Reference model | 2,000 components, 50,000 variables, 6 levels |
| Project opening (excluding GEMSEO import) | < 3 s |
| Pan/zoom on a 300-node level | ≥ 30 fps |
| Applying an editing command (bridge round trip + rendering) | < 100 ms |
| Full static validation | < 1 s |
| 2,000 × 2,000 N2: scrolling | smooth (≥ 30 fps), virtualized rendering |
| Auto-layout of a 300-node level | < 2 s, without blocking the UI |

Mandatory techniques: render **only the current level** and expanded containers; **viewport culling**; **level of detail** (ports hidden and labels simplified below a zoom threshold); **virtualized** lists and tables; incremental patches; elkjs in a Web Worker; everything stays in **SVG**.

### 14.2 Robustness and security

- User code is only imported in subprocesses (worker, runner). If the worker crashes, it restarts automatically and the error is shown.
- Autosave every 2 minutes to an `.autosave` file, with a recovery offer at startup.
- No network access from the web view.

### 14.3 Startup

- GEMSEO is never imported in the UI process: it is loaded in the worker, which starts in the background at launch. The interface is usable (opening, editing) before the worker is ready; features that depend on GEMSEO show a "loading" state.

### 14.4 Compatibility

- Windows 10/11 and Linux (Ubuntu 22.04+, RHEL 8+), Python 3.12 minimum (**3.12 is also the reference development version**; 3.13 supported when GEMSEO supports it), GEMSEO 6.x, PySide6 ≥ 6.6.
- The worker and the runner use the interpreter configured in the preferences, which can point to another environment containing GEMSEO and the business code.

### 14.5 Packaging

- pip package `gemseo-process-builder` published on **PyPI**, entry point `gemseo-process-builder` (and `python -m gemseo_process_builder`).
- Dependencies: `gemseo>=6,<7`, `PySide6`, `pydantic>=2`, `pint`, `psutil`, `h5py` (through GEMSEO). Optional: `pyxdsm`.
- Development dependencies: `pytest`, `pytest-timeout`, `ruff`, `mypy`.
- JS dependencies (d3 v7, elkjs, xdsmjs if chosen) are vendored in `static/vendor/`, with their licenses and versions listed in `static/vendor/README.md`.

### 14.6 License and third-party code

- The project code is under the **MIT license**. The `LICENSE` file is at the repository root and is included in the wheel and the source distribution.
- Every dependency, Python or vendored JS, must have a license compatible with distributing the project under MIT:
  - permissive licenses (MIT, BSD, ISC, Apache-2.0) are accepted;
  - LGPL libraries are accepted as **unmodified dependencies used through import**, never copied into the repository;
  - vendored files under a weak copyleft license (EPL-2.0) keep their own license file next to them and are not modified;
  - GPL or AGPL code must never be copied or vendored.
- Known licenses at the time of writing:

| Component | License | Use |
|---|---|---|
| GEMSEO | LGPL-3.0 | Imported dependency |
| PySide6 | LGPL-3.0 | Imported dependency |
| Pydantic | MIT | Imported dependency |
| pint | BSD-3-Clause | Imported dependency |
| psutil | BSD-3-Clause | Imported dependency |
| d3 | ISC | Vendored JS |
| elkjs | EPL-2.0 | Vendored JS, unmodified |
| xdsmjs (if chosen) | Apache-2.0 | Vendored JS |
| pyXDSM (optional) | Apache-2.0 | Optional dependency |

- Each license must be confirmed when the dependency is added, and listed in `THIRD_PARTY_NOTICES.md`.
- Pull requests from external contributors are accepted under the MIT license (inbound = outbound, stated in `CONTRIBUTING.md`).

---

## 15. Tests and quality

### 15.1 One-second rule

**No test may last more than one second**, setup and teardown included. This applies to Python and JavaScript tests, on the slowest supported CI platform.

Enforcement:

- Python: `pytest-timeout` with `timeout = 1` in `pyproject.toml`; `--durations=10` in CI to watch tests getting close to the limit.
- JavaScript: `node --test --test-timeout=1000`.
- A test that exceeds the limit is a failing test: it is split, simplified or rewritten, never exempted.

How to stay under one second:

- **Heavy imports** (GEMSEO, PySide6) happen once, at collection time in `conftest.py`, not inside tests.
- **Small problems**: reference cases use reduced settings (few iterations, few samples, small vectors). Numerical correctness is checked against GEMSEO run with the same reduced settings.
- **In-process by default**: codegen and integration tests import the generated module and call `build_scenario()` directly, without starting a subprocess.
- **Subprocess tests** (runner protocol, stop, kill) use a lightweight fake script that does not import GEMSEO.
- **Qt tests** avoid starting a real `QWebEngineView`; the bridge and the scheme handler are tested with plain `QObject`s and fake requests. A single smoke test loading the page is allowed if it fits the limit; otherwise the page is checked manually before each release.
- **Executable wrapper tests** use a tiny Python script as the "external code".
- **Performance** is measured by benchmarks (§ 15.5), not by tests.

### 15.2 Python (pytest)

- Model and migrations.
- Commands and undo/redo.
- Resolver (implicit and explicit couplings, namespaces, units).
- Validation.
- Codegen (golden scripts, lint checks, § 10.4).
- Runner (protocol, stop).
- Results.
- Catalog scanning.
- Executable wrapper.

### 15.3 Reference cases

Stored in `examples/` and run as integration tests with reduced settings, compared with GEMSEO alone:

- Sellar: MDF, IDF, DisciplinaryOpt, MDA only;
- Sobieski SSBJ: BiLevel;
- Rosenbrock: LHS DOE, parametric study, surrogate built from the DOE and then optimized;
- nested DOE around an optimization;
- model with an executable wrapper and a unit conversion.

### 15.4 JavaScript (`node --test`)

Everything in `static/js/lib/` must be pure (no DOM, no d3-selection) and tested: link geometry, culling, patch application to the store, virtualization, JSON Schema → form description conversion, N2 layout computations. Node is only required for development.

### 15.5 Benchmarks

- `benchmarks/` contains the synthetic model generator and the scripts that measure the § 14.1 targets.
- They are not tests: they are run on demand and before each release, and their results are recorded in the release notes.

### 15.6 Code style

- `ruff` (lint + format) and `mypy` on the Python side.
- JSDoc and `// @ts-check` on the JS side (checked by the editor, no build).

---

## 16. Work packages

The whole scope belongs to V1; work packages only set the **development order**. Each package ends with a demonstrable application. The detailed, finer-grained implementation plans that are actually executed live in [plans/](plans/README.md) and supersede this table for ordering.

| Package | Content | Done when |
|---|---|---|
| **0. Foundation** | PySide6 window, `gpb://` scheme, QWebChannel and `call`/`event` protocol, HTML skeleton of the panels, bundled d3, worker (startup, protocol), test tooling with the one-second limit | A JS→Python→JS round trip and a d3 SVG displayed, offline |
| **1. Model and editing** | Pydantic model, project file and migrations, commands, undo/redo, canvas (nodes, ports, links, selection, drag and drop, copy/paste), hierarchical navigation, tree, basic inspector | Create, save and reopen a hierarchical model, with undo |
| **2. Components and couplings** | Catalog (scan, cache, library), Analytic, Python function and Python class components, introspection, hybrid resolver, namespaces, static validation, Problems panel | Sellar built by hand, couplings shown, errors detected |
| **3. Execution** | Codegen, script export, runner, MDA/DOE/Optimization drivers, MDF/IDF/DisciplinaryOpt formulations, driver editor, JSON Schema forms, logs, states, progress, stop, dry run | Sellar MDF run from the UI, clean stop, equivalent readable exported script |
| **4. Results** | Run storage (HDF5, CSV), Runs panel, d3 views (summary, history, table, scatter, parallel coordinates), live history, native post-processings, run comparison | Full analysis of an optimization run and a DOE |
| **5. Advanced hierarchy** | Nested drivers (adapter, exposed interface), BiLevel, parametric study, assembly modes, local parallelism | SSBJ BiLevel and DOE around an optimization |
| **6. Views and ergonomics** | N2, XDSM, minimap, search, elkjs auto-layout, shortcuts | Smooth navigation on a 300-component model |
| **7. External codes, surrogates, units** | Executable wrapper and its editor, `.gpbwrap.json` descriptors, surrogate wizard, pint units and conversions | Wrapper + surrogate reference cases pass |
| **8. Exports, performance, delivery** | Image export, HTML/PDF report, XDSM PDF, large-model optimizations, autosave, pip packaging, user documentation | § 14.1 targets met, package installable |

---

## 17. Open points and risks

| # | Topic | Action |
|---|---|---|
| 1 | GEMSEO 6 API for the executable wrapper (is a base class available and stable?) | Study at the start of package 7; otherwise a standalone implementation in `runtime/` |
| 2 | GEMSEO 6 API for observing discipline statuses | Prototype in package 3; fall back to wrapping `execute` |
| 3 | Loading ES modules and `qwebchannel.js` through a custom scheme under PySide6 (Windows and Linux) | Works on Windows (plan 01, PySide6 6.11). Still to check on Linux (plan 33); fall back to classic (non-module) scripts if needed |
| 4 | Semantics of explicit links that cross an isolated container | Specify in package 2 with test cases |
| 5 | Reusing xdsmjs or writing a custom XDSM renderer | Decision in package 6 |
| 6 | SVG performance on very large N2 matrices | Measure in package 6; if the target is missed, revisit the "SVG only" constraint |
| 7 | N-D variables in MDAs and design spaces (automatic flattening) | Validate the approach in package 5 |
| 8 | Worker Python environment different from the UI's (GEMSEO and Pydantic versions) | Compatibility check when the worker starts, explicit message on mismatch |
| 9 | Some reference cases (SSBJ BiLevel) may not fit in one second even with reduced settings | Reduce the problem further (fewer iterations, sub-problems tested separately); a full-size run belongs in the benchmarks |

---

## 18. Glossary

- **Discipline**: GEMSEO unit of computation (inputs → outputs); "Component" in the UI.
- **Coupling**: variable produced by one discipline and consumed by another.
- **MDA**: Multidisciplinary Analysis, iterative resolution of couplings.
- **Formulation**: how the MDO problem is posed (MDF, IDF, BiLevel, DisciplinaryOpt).
- **Driver**: container that drives the execution of its children (MDA, DOE, optimization, parametric study).
- **Scope**: set of components in which global names are resolved (driver or root).
- **N2 / XDSM**: standard representations of couplings and of the MDO process.
- **Work package**: ordered chunk of development (§ 16).
