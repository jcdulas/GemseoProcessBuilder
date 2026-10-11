# GEMSEO Process Builder and gemseo-lso — Evolutions for the automated sizing loop

Status: draft for the owner's review (2026-10-10), updated with the owner's decision of 2026-10-11 (the models delivered without loads, simplified loads computed by `nastran_loads`).

This document details the items of section 5.7 of [ECOSYSTEM-EVOLUTIONS.md](../../ECOSYSTEM-EVOLUTIONS.md) (the catalogue): what GEMSEO Process Builder (GPB) and its plugin `gemseo-lso` must add so that the sizing loop of the ecosystem runs without a human step between two architectures. It amends [SPEC.md](../SPEC.md) and [LARGE_SCALE_OPTIMIZER_SPEC.md](LARGE_SCALE_OPTIMIZER_SPEC.md) (the optimizer spec); neither is edited now, each item says which of their sections it changes.

- GEMSEO 6.3.3, installed in the project venv (`.venv/Lib/site-packages/gemseo`), is the reference for every statement on GEMSEO's API. What could not be verified is marked "to check", with how.
- "Decision of 2026-10-10" marks a choice made while writing this document, for the owner's review; "decision of 2026-10-10 (owner)" marks the owner's decisions of that day (catalogue §7), which withdrew GPB-E2 and moved GPB-E4 to M4; "decision of 2026-10-11 (owner)" marks the owner's decision that the producer delivers its models without loads and that `nastran_loads` computes simplified loads, which replaces the decision of 2026-10-10 that the models arrive loaded; what remains to the owner is in section 10.
- Line numbers refer to the files as they are on 2026-10-10.

## 1. Context

The target process (catalogue §2) has two loops. The **inner loop** sizes one architecture: the disciplines of `gemseo_nastran` (internal loads by `nastran_sv`, reserve factors by `nastran_ssa`, mass, smoothing), driven by a bi-level formulation or by `gemseo-lso`. The **outer loop** is an architecture study: a DOE or a parametric study over integers (frame count, stringer count) whose evaluation asks an external producer for a model (without loads) and a layout, loads the model with `nastran_loads`, then runs the inner sizing as one discipline. Seen from GPB:

| Gap | Item |
|---|---|
| The disciplines of an installed package reach the Library only through a catalog folder pointed at their source files | GPB-E1 |
| One evaluation of the outer loop is a whole sizing (hours); GPB runs locally only (SPEC §1.4, line 53) | GPB-E2, withdrawn: the evaluations run in local processes (section 3) |
| A crash loses every evaluation already done; GPB never sets a discipline cache | GPB-E3 |
| No view of the structure of an evaluation, and GPB's own views are SVG only | GPB-E4 |
| No example of the outer-loop pattern | GPB-E5 |
| At scale, the rows of the reserve factor constraints are chained through the full Jacobian of the loads | LSO-E1 |

Three packages these items rely on are specified in sibling folders of the workspace: `gemseo_nastran`, `nastran_view`, `nastran_refmodels` (their `spec/SPEC.md`). What GPB needs from them is stated as a request in each item and collected in section 10 (open point 8); the names of their modules, classes and commands follow those specifications (`gemseo_nastran.catalog:COMPONENTS`, `StructuralSizing`, `python -m nastran_view`).

## 2. GPB-E1 — Catalog entries from installed packages

### Need

`gemseo_nastran` gives the disciplines of the chain (the producer, the simplified loads of `nastran_loads` and their case table, the solve, the selection, the reserve factors, the mass, the smoothing, the inner sizing; catalogue §3). An engineer building the outer loop must find them in the Library with their descriptions and units, without knowing where the package is installed, and the generated script must import them as a developer would (`from gemseo_nastran.<module> import <Class>`).

### Today

- The Library has three kinds of sections: Built-in, Demos and one per catalog folder (SPEC §7.6, lines 597–603; `static/js/panels/library.js:139-190`).
- A catalog folder is scanned file by file in the worker: `Discipline` subclasses **defined** in a module (imported ones are skipped, `catalog/scanner.py:97-99`), functions marked by `@gemseo_process_builder.runtime.component` (`runtime/decorators.py:20-46`), `*.gpbwrap.json` descriptors. Each file is imported under a private module name (`scanner.py:55-85`); the results are cached by (path, mtime) (`app/catalog_service.py:37-75`).
- An entry of a folder is generated as a local import, with `sys.path` extended to its folder (`codegen/disciplines.py:64-69`). A component whose configuration has a dotted `module` is generated as a plain import (`codegen/disciplines.py:58-59`), as in the Sellar example of SPEC §4.2 (`gemseo.problems.mdo.sellar.sellar_1`).
- A catalog folder pointed at an installed package would import its modules as loose files, so that their relative imports fail and the script inserts a site-packages folder in `sys.path`. A package cannot use `@component` either without depending on GPB, which is not on PyPI (SPEC §14.5, line 1085).
- GEMSEO finds its plugins through the entry-point group `gemseo_plugins` and the variable `GEMSEO_PATH` (`gemseo/core/base_factory.py:120-124, 182-185`); `gemseo-lso` declares it (`plugins/gemseo_lso/pyproject.toml`). That registers classes for `create_discipline("Name")`, without description, units, icon or group, and without functions.

### Specification

**Declaration.** Decision of 2026-10-10: an entry-point group `gemseo_process_builder.components` (name: open point 2). An entry points to a list of plain dictionaries, or to a function returning one, so that the package does not depend on GPB:

```toml
# pyproject.toml of gemseo_nastran (illustrative)
[project.entry-points."gemseo_process_builder.components"]
gemseo-nastran = "gemseo_nastran.catalog:COMPONENTS"
```

```python
# gemseo_nastran/catalog/__init__.py: plain data, cheap to import (the disciplines are not imported)
COMPONENTS = [
    {
        "kind": "python_class",
        "module": "gemseo_nastran.sizing",
        "attribute": "StructuralSizing",
        "group": "Outer loop",
        "description": "Sizes one architecture and returns its mass and feasibility.",
        "units": {"mass": "kg"},
    },
]
```

| Key | Required | Meaning |
|---|---|---|
| `kind` | yes | `python_class` (a `Discipline` subclass, SPEC §7.3) or `python_function` (a function for `AutoPyDiscipline`, §7.2) |
| `module`, `attribute` | yes | the dotted module path and the name; the script imports `from <module> import <attribute>` |
| `group` | no | a sub-section of the package's section |
| `description`, `units`, `icon` | no | what the `@component` decorator gives (`runtime/decorators.py:20-36`) |
| `schema` | no | the version of this format (1); unknown keys are ignored with a warning |

**Discovery**, in the worker only (package code never runs in the UI process, and the runs may use another interpreter, SPEC §14.4):

1. `importlib.metadata.entry_points(group="gemseo_process_builder.components")` lists the declarations with their distribution (`entry_point.dist.name`, `.version`), importing nothing.
2. A distribution whose (name, version) is in the catalog cache is not loaded again. An editable install (PEP 610 `direct_url.json`, `dir_info.editable`) is also keyed by the mtime of its declaration file. **Refresh** reloads all.
3. Otherwise the declaration is loaded (`entry_point.load()`), its keys checked, each `module` located with `importlib.util.find_spec` without importing it, and the result cached in the catalog cache. The modules of the disciplines are imported only when a component is placed or introspected (§7.3): a package of heavy native modules does not slow the scan.
4. An error (import, malformed declaration, missing module) is reported for that package only, its traceback in the console, as for a file of a catalog folder (§7.6, line 609).

**Library.** One section per package after the folders, titled with the distribution and its version ("gemseo-nastran 0.3.0"), its entries grouped by `group`; search and drag and drop as for folder entries.

**Project and code.** A component placed from a package keeps the dotted `module` and its class or function, plus `package: {name, version}`. Validation (§9.1): the package missing from the Python of the runs is an error ("Install gemseo-nastran in the Python of the runs"); another version is an info. Codegen uses the dotted-module path that exists: one import line, no `sys.path`. The script reader already turns any other discipline into a Python class component (§4.2.1, line 317); it adds the package when the module belongs to a declared one.

**Request to `gemseo_nastran`**: declare its disciplines in this group. Declaring `gemseo_plugins` as well (for `create_discipline`) is its choice; GPB does not need it.

### Checks

- A fake distribution written in a temporary folder (`*.dist-info` with `entry_points.txt` and `METADATA`, a package with a declaration) put on the `sys.path` of the worker under test: entries found with name and version; a second scan of the same version imports nothing (the declaration module absent from `sys.modules`); a new version, or an edited editable install, is loaded again.
- A declaration raising at import, a missing `module`, a key of the wrong type: one error each, the other packages still listed.
- Golden script: a component from a package is one `from ... import ...` line; `ruff` and `mypy` pass (SPEC §10.4). Validation: package missing, other version.
- `node --test`: the sections and groups of the Library built by a pure `lib/` function. Every test under one second.
- Acceptance: with `gemseo_nastran` installed in the Python of the runs, its disciplines appear in their section, and a study built from them runs from the UI and as a standalone script.

### Amends

SPEC §7.6: a fourth kind of section, installed packages, with the declaration, the discovery and the cache keyed by distribution version. Also §3.4 (`catalog.list` returns the packages), §4.2 (`package` in a component's configuration), §4.2.1 (package on reading), §9.1 (two rules), §10.1 (a script also depends on the installed packages of its components), §15.2 (tests).

## 3. GPB-E2 — Execution on a cluster (withdrawn)

Withdrawn by the decision of 2026-10-10 (owner): the loop has no cluster, so GPB runs locally only and the exclusion of its SPEC §1.4 (line 53: "Running on a cluster/HPC (only local parallelism is supported)") stays as it is. The outer loop runs its evaluations as the local processes of a DOE or parametric driver (`n_processes`, SPEC §6.2), each sizing in a process of its own: the disciplines of `gemseo_nastran` are pickled as recipes (SV-E4, still P2 for these processes, started with `spawn` or `forkserver`), and the HDF5 caches of GPB-E3 keep the evaluations already done across a crash. Its specification and its plans are removed; its open points (section 10: 1, 4, 5, 6, 11) are closed.

Note: two defects of GEMSEO 6.3.3 found while reading its job schedulers, kept as facts; no work follows from them.

- The LSF template uses `$queue_name` (`disciplines/wrappers/job_schedulers/templates/LSF`, line 24), which the `LSF` class does not declare: without a `queue_name` option the job file fails with "Value not passed to template for key" (`discipline_wrapper.py:201-216`).
- The docstring example of `wrap_discipline_in_job_scheduler` writes `Discipline.HDF5_CACHE` (`gemseo/__init__.py:1826`), which does not exist in 6.3.3 (`Discipline.CacheType.HDF5`).

## 4. GPB-E3 — Discipline caches set in the inspector

### Need

A crash after 40 of 50 sized architectures must not cost 40 sizings again. GEMSEO's caches keep the outputs of each execution by the hash of its inputs; an HDF5 cache keeps them on disk, where a new run finds them. The outer loop also meets inputs again (a parametric study extended, a DOE run again with more samples).

### Today

- GPB never calls `set_cache` (no occurrence in `gemseo_process_builder/`): every discipline keeps GEMSEO's default, `SimpleCache` (the last execution) when the discipline cache is enabled (`gemseo/core/discipline/base_discipline.py:136-139`); the runner's `configure(...)` leaves that option at its default (`runner/__main__.py:69-73`).
- GEMSEO 6.3.3:
  - `Discipline.set_cache(cache_type, tolerance=0.0, **kwargs)` (`base_discipline.py:256-319`), `Discipline.CacheType` = `SIMPLE`, `HDF5`, `MEMORY_FULL`, `NONE` (lines 59-72); for HDF5, `hdf_node_path` defaults to the discipline's name (line 303).
  - `HDF5Cache(tolerance, name, hdf_file_path="cache.hdf5", hdf_node_path="node", ...)` (`caches/hdf5_cache.py:63-100`) reads the hashes already in its file when built and logs "Found N entries in the cache file" (lines 143-155): a file reused by a new run serves the executions it holds. Strings are stored (`caches/_hdf5_file_singleton.py:142-144, 220-221`). One file is one singleton with a multiprocessing lock (lines 94-107): disciplines may share a file under different nodes.
  - Its docstring: "the use of an HDF5Cache is not supported in parallel on Windows platforms", with `set_optimization_history_backup` as the alternative (`hdf5_cache.py:85-93`).
  - `MemoryFullCache(tolerance, name, is_memory_shared=True)` keeps its entries in a multiprocessing manager dictionary, shared by processes (`caches/memory_full_cache.py:52-79`), and lost with the run.
  - `BaseScenario.set_optimization_history_backup(file_path, at_each_iteration, at_each_function_call, erase, load, plot)` (`scenarios/base_scenario.py:451`) saves the database during the run and reloads it with `load=True`.
  - A parallel DOE evaluates its samples in processes (`algos/doe/base_doe_library.py:298-338`) started with Python's default method (`core/parallel_execution/callable_parallel_execution.py:150`): `spawn` on Windows, `fork` on Linux with Python 3.12 and 3.13.

### Specification

**Setting.** A **Cache** field in the inspector of every component and container:

| Choice | Generated | For |
|---|---|---|
| Last execution (default) | nothing: GEMSEO's default | most components |
| None | `set_cache(Discipline.CacheType.NONE)` | a discipline with side effects that must run each time |
| All executions, in memory | `set_cache(Discipline.CacheType.MEMORY_FULL)` | cheap, repeated inputs; shared by the processes of a DOE |
| All executions, in a file | `set_cache(Discipline.CacheType.HDF5, hdf_file_path=..., hdf_node_path=...)` | expensive evaluations; survives a crash |

- Advanced: the tolerance (0: the inputs must be equal to hit).
- File: by default `caches/<project name>.h5` in the data of the project (§4.2.3), like the surrogates (decision of 2026-10-10; open point 3), or a path the user types. Node: the path of names of the node (`Study/Sizing`), unique where discipline names are not (§4.1).
- The inspector shows the entries of an existing node (counted by the worker with `h5py`) and **Clear** (removes the node). GPB records beside the file (`<file>.gpb.json`) a fingerprint of each node's component (kind, configuration, package version of GPB-E1, mtime of its module or descriptor); when it differs, the inspector warns that the entries come from another version of the component, which GEMSEO's cache cannot know, and offers Clear or Keep.

**Generated code** (§10.2: one statement per concept, a comment on why):

```python
    # The sizing takes hours: its executions are kept in an HDF5 file, so that
    # a run started again after a crash reuses the architectures already sized.
    sizing.set_cache(
        Discipline.CacheType.HDF5,
        hdf_file_path=CACHE_FOLDER / "architecture_study.h5",
        hdf_node_path="Study/Sizing",
    )
```

The cache goes on the object the process uses: after the typed values, before the remapping. `CACHE_FOLDER` is a path constant (§4.2.2). The script reader (§4.2.1) records `set_cache` calls, as it records `add_constraint`, and turns them back into the setting.

**With `n_processes`** (rules of §9.1):

| Cache | `n_processes > 1`, Linux | `n_processes > 1`, Windows |
|---|---|---|
| Last execution | one per process | one per process |
| In memory | shared | shared (to check by a test under `spawn`) |
| In a file | shared through the file's lock | **error**, unsupported by GEMSEO; quick fixes "1 process" and "in memory" |

**Resuming a run.** A run *failed*, *stopped* or *killed* gets **Resume** in the Runs panel (§8.8): a new run executes the run's own `script.py` (kept in its folder, §12.1), so that code and inputs are those of the first run, and its HDF5 caches, outside the run folder, serve what was already computed. A DOE draws the same samples in a new process (GEMSEO's `Seeder` starts from its default seed in each process, `utils/seeder.py:36-49`, unless the seed is set); an optimization from the same start passes through the same points. The new run records `resumed_from` in `run.json`; the console reports the entries reused. A killed run has no `history.h5` (written at the end, §11.3): with "Save the history after each evaluation" (Execution tab) the script calls `set_optimization_history_backup(..., at_each_function_call=True)` and the Results show the partial history. For `gemseo-lso`, `save_state` and `resume_from` (optimizer spec §8) stay the exact resume of the optimizer.

### Checks

- Golden scripts: the four choices; the order typed values, cache, remapping; the script reader round trip.
- In process, a small discipline with an HDF5 cache in a temporary folder: run, then built again on the same file and run with the same inputs, the second time with no execution (a counter); two components in one file under two nodes.
- Rules: an HDF5 cache with two processes on Windows (platform patched); a fingerprint that differs. Clear and the entry count on a small file. Every test under one second; a parallel DOE with caches (its processes import GEMSEO) is a benchmark.
- Acceptance: the GPB-E5 example killed after a few architectures, then resumed: the sized ones are not computed again.

### Amends

SPEC §4.2.1 (reading `set_cache`), §4.2.3 (`caches/` in the data of a project), §6.4 (Execution: the history after each evaluation), §8.7 (Cache field), §8.8 (Resume), §9.1 (rules), §10.2, §10.3 (generated lines), §11.1 (a resumed run), §12.1 (`resumed_from`).

## 5. GPB-E4 — The 3D view of `nastran_view` opened from a run

### Need

In an architecture study, a row of the results is a whole structure: its model, its layout, its reserve factors. Seeing where the critical zones are, and comparing two architectures, takes a 3D view; GPB's rule is that all its diagrams are SVG drawn with d3, without canvas (CLAUDE.md; SPEC §1, line 19).

### Today

- The Results views are SVG (§12.2); the 3D response surface is "a surface drawn in SVG, turned by dragging" (line 1006); plan 72 left out a rotatable 3D view because "WebGL is not SVG" (`plans/72.md:55`).
- A run stores numbers (`history.h5`, `dataset.csv`, §12.1): GEMSEO's database holds function values, not the string outputs of disciplines, so the folder of an evaluation is nowhere in a run.
- GPB already starts other programs without importing them: the code editor (`app/api_python_files.py:257-259`, `subprocess.Popen(command, close_fds=True)`).
- `nastran_view`'s technology is decided: three.js in a Qt WebEngine view, in a window of its own (decision of 2026-10-10 (owner); its `spec/SPEC.md` §6.1). Its specification (§3.1) takes the command line below.

### Specification

**Principle** (decision of 2026-10-10): `nastran_view` is another application, with its own window and process, started by GPB with the interpreter of the runs (§14.4); it is an optional dependency of that environment, not of GPB. GPB's page never holds a WebGL or canvas view: the rule of CLAUDE.md is unchanged.

**What GPB passes.** The folder of an evaluation, written by `gemseo_nastran` (request to its specification): under a root folder given as an input of its disciplines, one folder per evaluation with a manifest (`evaluation.json`: the inputs and their hash, the producer's `producer.json`, the paths of the model, the layout and the reserve factors). The worker indexes the manifests under the root of a run (the value of that input in the run's snapshot) and matches them to the rows by the values of the design variables, or by the hash of the architecture parameters. The command line is `nastran_view`'s, to agree in its specification, for instance `python -m nastran_view <folder> [--compare <folder>] [--title <text>]`, passed as an argument list (no shell).

**UI.** In the Data table, the XY plot and the scatter matrix (context menu of a row or a point) and in the Summary (the best evaluation): **Open in the 3D view**; two rows selected: **Compare in the 3D view**. Enabled when the worker finds `nastran_view` in the Python of the runs (`importlib.util.find_spec`) and the row has a folder; otherwise disabled, the reason in the tooltip. Bridge methods `view3d.available(runId)` and `view3d.open(runId, rows)` (§3.4).

### Checks

- The index of a temporary root with three manifests, one malformed (reported); rows matched by values and by hash.
- The command for one and two folders, with `subprocess.Popen` patched (nothing started); the availability rule; the menu state in a pure `lib/` function under `node --test`. Every test under one second.
- Acceptance: from a run of the GPB-E5 example, a row opens its structure in `nastran_view`; two rows are compared.

### Amends

SPEC §12.2 (the two actions), §3.4 (two methods), §14.4 (`nastran_view`, optional, in the Python of the runs). §12.1 is unchanged: the folders belong to `gemseo_nastran`.

## 6. GPB-E5 — Example project: an architecture study with an external producer

### Need

The outer loop is a pattern, not a component: engineers need a working study to start from, with the producer as an external code, the loads and the inner sizing as disciplines, and the caches.

### Today

- The demos are the scripts of `examples/` (SPEC §7.6, lines 599–602); reference cases and hand-written demos are listed in §15.3 (lines 1154–1166).
- An external code is wrapped by `ExecutableDiscipline` (§7.5); a `file` rule gives the path of a produced **file**, not of a folder (`runtime/parsing.py:129-131`); working folders are kept by `retention` and created under `workdir_root` (`runtime/spec.py:157-161`).
- Design variables may be integers (`core/drivers.py:66`). DOE and parametric drivers have responses, no constraints (`core/drivers.py:329-332`), so their results have no feasibility column (`results/reader.py:132-148`).

### Specification (to be written as a plan)

`examples/architectureStudy/`, named like `demoBiLevel/` and `wingBiLevel/`:

| File | Content |
|---|---|
| `architecture_study.py` | the study; its docstring says "Run it with: python architecture_study.py" and names the packages it needs |
| `producer.gpbwrap.json` | the stand-in producer of `nastran_refmodels`, wrapped as an executable component; it writes the aircraft description of the example beside the model |
| `README.md` | the pattern and the expected results |

**The study.** A parametric study (full factorial) over `n_frames` and `n_stringers` (integers, a few levels each, within the ranges `nastran_refmodels` supports: to check in its specification), whose process is a chain producer (unloaded model) → `nastran_loads` (`LoadModel`) → `StructuralSizing`:

1. **Producer** (executable component). A template writes `parameters.json` from the inputs; the command runs the stand-in producer (to agree with `nastran_refmodels`, for instance `{python} -m nastran_refmodels.produce parameters.json {workdir}`), which writes, per the producer contract (catalogue §4), the structural model without loads (decision of 2026-10-11 (owner), replacing the decision of 2026-10-10 that the model arrives loaded), the layout and mapping tables, `producer.json` with the free ID ranges left to `nastran_loads`, and, outside the contract, the aircraft description of the example. `file` rules give `model_file`, `layout_manifest`, `producer_file` and `aircraft_description_file` (`path` outputs). `retention: always` and a persistent `workdir_root`: the loads and the sizing read the files afterwards, and a cached evaluation refers to them.
2. **Loads**, `LoadModel` from the `gemseo-nastran` section of the Library (GPB-E1): `nastran_loads` computes the simplified loads from the aircraft description and the initial structural mass, applies them to the model in its free ID ranges and checks them; it gives `loaded_model_path`, `case_table_path` and `diagrams_path`.
3. **Inner sizing**, `StructuralSizing` from the same section: one discipline taking those paths and giving `mass`, `feasible` (1 or 0), `min_reserve_factor` and its evaluation folder (GPB-E4); its bi-level formulation re-applies the loads with the structural mass of the sizing at each system iteration (the mass snowball); names to agree with `gemseo_nastran` (its SPEC §3.4, §3.6).

Responses: `mass`, `feasible`, `min_reserve_factor`. Caches (GPB-E3): HDF5 on the producer, the loads and the sizing. Processes: 2, local (no cluster: decision of 2026-10-10 (owner)).

**What the results show.** Parametric view: the mass over the two parameters as a heat map (§12.2, line 1009). XY plot: the mass against `n_stringers`, colored by `feasible` (coloring by a variable, line 1003, standing in for the feasibility DOE runs lack: open point 7). The table sorted by mass. With GPB-E4, a row opened in 3D.

**Tests and tools.** A fixture project in `tests/python/fixtures/examples/` and its golden script (`tools/build_examples.py`, §15.3); a smoke test with fakes, a producer script without GEMSEO writing four small files, a "loads" step that copies the model, and an analytic "sizing": the chain runs, and a second run hits the caches, under one second. `tools/smoke_installed.py` runs the real study when `gemseo_nastran`, `nastran_loads` and `nastran_refmodels` are installed and skips it otherwise; its duration is recorded as a benchmark.

### Amends

SPEC §15.3 (the demo and its requirements), §7.6 (a demo whose packages are missing is listed with a note naming them).

## 7. LSO-E1 — Rows chained through an intermediate discipline by vector-Jacobian products

### Need

In the large-scale inner sizing, the reserve factors (`nastran_ssa`) are computed from internal loads computed by `nastran_sv`, in two disciplines (catalogue §5.7). Each iteration of `gemseo-lso` asks for the rows of its working set only (optimizer spec §3.2). A row is dRF_i/dx = ∂RF_i/∂x + ∂RF_i/∂loads · dloads/dx: forming dloads/dx (the loads of the selected cases by the design variables, 10⁵–10⁶ by 10⁴–10⁵ at fuselage scale) costs one solve per variable or per load component, while the products w · dloads/dx for the rows asked for cost one adjoint per row and subcase.

### Today

- Rows come from `RowJacobian.compute_jacobian_rows(output_name, rows, input_data)` of the constraint's discipline (optimizer spec §6, lines 262–273; `sources.py:47-57`). Its inputs computed by other disciplines are chained (spec line 271): `_source` gathers their producers into an `MDOChain` (`sources.py:233-275`); `Source.upstream_jacobian` linearizes it with respect to the design variables for all those outputs, i.e. it forms **the full Jacobian of the intermediate outputs** (`sources.py:173-187`); `rows_of` multiplies each block of rows by it (`block @ part`, lines 295–305). The same in forward mode for the directional derivatives (`directional_of`, lines 309–335).
- One chain per constraint (`sources.py:272`), its linearization kept for one point: two constraints fed by the same loads linearize them twice per point, unless the leaf discipline's cache serves the second (to check with a counter). `adapter.constraint_rows` asks each constraint in turn (`adapter.py:209-240`).
- Tested on a two-discipline chain (`Halved` upstream of `RowsLocal`, `tests/test_lso_gemseo.py:139-149`); a coupled discipline is refused (`sources.py:219-226`).
- Open point 5 is about **coupled** disciplines (an MDA; spec line 355), whereas this intermediate is uncoupled and already chained: LSO-E1 removes the cost of the uncoupled case and gives open points 4 and 5 their primitive. Open point 4, the weighted adjoint (Jᵀw in one solve), is a later mode (§1.2 line 31, §10 line 317); open point 7 chose a protocol on the discipline over GEMSEO's `JacobianOperator`, built in `linearize` for all outputs at once (line 357).
- `nastran_sv` gives `DesignProblem.vjp(x, weights, block=None, sink=None)`: weights per response name, shaped (rows, items), the same rows for every response; one adjoint solve per row and subcase, by blocks of 256 rows (`nastran_sv/python/nastran_sv/design.py:1256-1287`); and `jvp` (lines 1289–1317).

### Specification

**Protocol**, in `gemseo_lso.gemseo.sources`, exported like `RowJacobian`:

```python
class AdjointJacobian(Protocol):
    def compute_vector_jacobian_products(
        self,
        weights: Mapping[str, NDArray | sparray],  # by output name: (k, output size), the same k rows
        input_data: Mapping[str, NDArray],
        input_names: Sequence[str],                # the inputs that lead to the design variables
    ) -> Mapping[str, NDArray | sparray]:          # by input name: (k, input size), the sum over outputs of W_o @ dO/dI
        ...
```

Decision of 2026-10-10: the weights of several outputs go in one call, rather than one output per call as in the catalogue's sketch, since one adjoint pass serves all the outputs (`vjp` takes several responses with the same rows; open point 9). A discipline of `gemseo_nastran` wrapping `nastran_sv` implements it with `vjp` (request to its specification). Sparse weights are accepted: a reserve factor depends on the loads of its own item.

**Chaining by reverse accumulation**, replacing `upstream_jacobian` where it applies:

1. At a point, the adapter gathers the rows asked for of **every** constraint given row by row and asks each constraint discipline for its rows, as today.
2. The blocks with respect to inputs computed upstream become pending weights by variable name; the blocks with respect to design variables are kept.
3. The upstream disciplines are visited once, in reverse dependency order, over the union of the chains of all these constraints. A discipline offering `AdjointJacobian` receives its pending weights, stacked over the constraints and split at `row_batch_size`, and returns products that become weights of its own inputs or blocks of design variables. A discipline without it is linearized once per point and its products formed locally, as today. A discipline offering the protocol is a leaf of the search, like those offering rows (`sources.py:121-122`).
4. The rows are assembled, scaled to the normalized space and signed as in `rows_of`. The full Jacobian of an intermediate offering the protocol is never formed.

Sub-points: (a) forward mode the same way, an intermediate offering `TangentJacobian` propagating the directions of `hybrid` (`nastran_sv`'s `jvp`); (b) a constraint discipline may offer `AdjointJacobian` instead of `RowJacobian`, its rows being products with unit weights.

**Relation with the open points.** Open point 4: the weighted adjoint of an augmented Lagrangian is this product with k = 1 and the multipliers as weights; LSO-E1 fixes its interface, not the mode. Open point 5: coupled disciplines stay refused; a matrix-free coupled adjoint (a Krylov solve of the transposed coupling system with these products) is the route that avoids GEMSEO's full coupled Jacobians, which the prototype of plan 68 still computes; it stays open.

### Checks

- A synthetic chain in `tests/lso_disciplines.py`: x → `Loads` (a sparse linear map plus a nonlinear term, offering `AdjointJacobian`, with counters) → `Stresses` (`RowJacobian`, a local function of the loads and of x). The rows equal those of today's full-Jacobian path to 1e-12; `Loads._compute_jacobian` is never called during a whole run, the objective's gradient included; one product call per point and batch.
- Two constraint disciplines fed by the same `Loads`: one call with stacked weights. Two intermediates in series; one with the protocol beside one without.
- Signs and normalization as `test_normalization_and_signs`; `row_batch_size`; sub-point (a) against finite differences; a GCMMA run on the small chain ends at the optimum of the full-Jacobian path. Every test under one second.
- Benchmark (`plugins/gemseo_lso/benchmarks/`): the stress-constrained topology problem split into displacements (the intermediate, its products by adjoint on the reused factorization) and stresses (rows), against the full-Jacobian path, at 10⁴ and 10⁵ elements: time and memory per iteration.

### Amends

Optimizer spec §5 (the protocol), §6 (chaining by products, one batch over the constraints), §9 (tests), §10 (the weighted adjoint uses the protocol), §12 (plan), §13 (open point 4: interface fixed; open point 5: the route above).

## 8. The items

| ID | Priority | Milestone | Depends on |
|---|---|---|---|
| GPB-E1 | P2 | M3 | — (first user: the declaration of `gemseo_nastran`) |
| GPB-E2 | withdrawn | — | decision of 2026-10-10 (owner): no cluster, GPB runs locally only (section 3) |
| GPB-E3 | P2 | M4 | — |
| GPB-E4 | P3 | M4 (decision of 2026-10-10 (owner)) | `nastran_view` read-only (M2) and its command line; the evaluation folders of `gemseo_nastran` (M3) |
| GPB-E5 | P2 | M4 | GPB-E1, GPB-E3; SV-E4 and picklable disciplines of `gemseo_nastran` for its local processes; the inner sizing discipline and `LoadModel` of `gemseo_nastran` (M4) with `nastran_loads`; the stand-in producer of `nastran_refmodels` (M1, its models without loads and their aircraft description); LAYOUT-E1 |
| LSO-E1 | P2 | M3 | plan 68 (row mode, done); a loads discipline of `gemseo_nastran` offering the protocol through `nastran_sv`'s `vjp`; ssa V6 for the cost at scale |

## 9. Proposed plans

Plans 75 and 76 belong to M3, 77 to 80 to M4 (GPB-E4 included, decision of 2026-10-10 (owner)); the two plans of GPB-E2 are withdrawn with it. Each follows the structure of `plans/README.md`.

| # | Title | Depends on | SPEC |
|---|---|---|---|
| 75 | Catalog entries from installed packages | 09, 10 | § 3.4, 4.2, 4.2.1, 7.6, 9.1, 10.1, 15.2 |
| 76 | Large-scale optimizer: rows chained by vector-Jacobian products | 68 | LSO § 5, 6, 9, 10, 12, 13 |
| 77 | Discipline caches | 23, 47, 49 | § 4.2.1, 4.2.3, 8.7, 9.1, 10.2, 10.3 |
| 78 | Resuming a run from its caches | 19, 77 | § 6.4, 8.8, 11.1, 12.1 |
| 79 | Example: an architecture study with an external producer | 28, 75, 78; `gemseo_nastran`, `nastran_loads`, `nastran_refmodels` | § 7.5, 7.6, 12.2, 15.3 |
| 80 | The 3D view of `nastran_view` opened from a run | 21, 79; `nastran_view` | § 3.4, 12.2, 14.4 |

## 10. Open points

| # | Topic | Action |
|---|---|---|
| 1 | Lifting the exclusion of SPEC §1.4 through GEMSEO's job schedulers only (GPB-E2) | Decided, decision of 2026-10-10 (owner): no cluster, SPEC §1.4 unchanged, GPB-E2 withdrawn |
| 2 | The entry-point group `gemseo_process_builder.components` | The owner's, before plan 75 |
| 3 | Where HDF5 caches live: the data of the project (the script then holds an absolute path and runs on this machine only, as with surrogates, §4.2.3 line 371) or beside the script | The owner's, before plan 77 |
| 4 | A Windows workstation submitting to a Linux cluster | Closed: GPB-E2 withdrawn |
| 5 | Details of GEMSEO's job schedulers on a cluster | Closed: GPB-E2 withdrawn |
| 6 | A non-blocking submission, job arrays | Closed: GPB-E2 withdrawn |
| 7 | Feasibility of DOE and parametric runs: constraints on these drivers (GEMSEO's DOE scenarios accept them), giving the results a feasibility column | Decide in plan 79; the example colors by a response meanwhile |
| 8 | Contracts with the new packages: `gemseo_nastran` (its declaration, the evaluation folders and `evaluation.json`, the names of the responses, picklable disciplines with SV-E4, the loads discipline offering `AdjointJacobian`, the inputs and outputs of `LoadModel`), `nastran_view` (command line, comparison of two folders), `nastran_refmodels` (producer command, parameter ranges, the aircraft description of the example) | In their specifications |
| 9 | The form of the LSO-E1 protocol: several outputs per call (chosen) or one, as the catalogue sketches it | Confirm in plan 76 |
| 10 | The cost of `vjp` for rows whose weights vanish on most subcases (a reserve factor row is per case): one solve per row and subcase (`design.py:1258-1260`) | To check with `nastran_sv` (ssa V6) |
| 11 | Pickles exchanged in the shared folder of the jobs | Closed: GPB-E2 withdrawn |
| 12 | The "Working folder" of the driver Execution tab (SPEC §6.4, line 503; `static/js/panels/driver_editor/settings_tabs.js:226-229`, stored at `core/drivers.py:126`), stored and shown but read neither by the generator nor by the runner, which works in the run folder (`runner/__main__.py:248`) | Remove it, or give it a meaning, in a plan of its own (the plan of GPB-E2 that was to settle it is withdrawn) |
| 13 | GPB-E4 at M5 while its prerequisites are at M2 (`nastran_view` read-only) and M3 (`gemseo_nastran`) | Decided, decision of 2026-10-10 (owner): GPB-E4 at M4 |
