# Release checklist

Go through this list on **Windows and Linux** before tagging a release, in a fresh virtual environment where the package was installed from its wheel (the package is not published on PyPI):

```bash
python -m build
python3.12 -m venv /tmp/gpb && /tmp/gpb/bin/python -m pip install dist/gemseo_process_builder-*.whl
```

Write the results (version, OS, date, problems found) in the release notes.

## Package

- [ ] `pip show gemseo-process-builder` gives the version, the MIT license and the project URLs.
- [ ] The installed package contains `static/`, `static/vendor/LICENSES/`, `LICENSE` and `THIRD_PARTY_NOTICES.md` (in the `.dist-info` folder).
- [ ] `gemseo-process-builder --version` answers without opening a window.
- [ ] `python tools/check.py` passes in a development install.
- [ ] `python benchmarks/run.py` meets the targets of SPEC § 14.1 (copy its table in the release notes).

## Every example

For each script of `examples/`, open it, validate it (F7, no error), run it, and check its result:

| Example | Driver to run | Expected result |
|---|---|---|
| `sellar_mdf.py` | Optimizer | obj ≈ 3.18 at x_shared ≈ (1.98, 0) |
| `sellar_idf.py` | Optimizer | obj ≈ 3.18 |
| `sellar_disciplinary_opt.py` | Optimizer | obj ≈ 3.18 |
| `rosenbrock_doe.py` | Study | 30 evaluations |
| `rosenbrock_parametric.py` | Study | 15 evaluations; Parametric view shows the grid |
| `rosenbrock_doe.py` | Study, then Build surrogate on its run | the surrogate is saved in `Rosenbrock DOE.surrogates/` (the optimization on a surrogate runs in `tools/smoke_installed.py`) |
| `sobieski_bilevel.py` | System | converges (y_4 ≈ 1948 with default settings) |
| `doe_around_optimization.py` | Study | one optimization per sample |
| `external_code/external_code.py` | Optimizer | f = 1.125 at (0.75, 1.75) |

## Features

- [ ] New project: drag an Analytic component, a Python function (from a catalog folder) and an Optimization driver; link variables through the link panel; undo and redo.
- [ ] Canvas: cards, one link per pair, the link panel; auto-layout; minimap; search; enter and leave containers; expand in place.
- [ ] N2 and XDSM views of Sellar MDF.
- [ ] Driver editor: design variables, objective, constraints, algorithm settings form.
- [ ] Run, stop a long run, compare two runs; every results view; one GEMSEO post-processing.
- [ ] Export the Python script of Sellar MDF and run it with `python script.py` outside the application.
- [ ] Wrapper editor: rebuild the external code example from `solver.py` samples, test it, save it as a descriptor.
- [ ] Surrogate wizard on the Rosenbrock DOE: training, quality charts, save, retrain.
- [ ] Export images (SVG and PNG 2×) of the canvas, the N2, the XDSM and a chart; export the report as HTML and PDF.
- [ ] Robustness: kill the application while a project has unsaved changes, reopen it and recover the autosave; open the same project in two windows (the second is read-only); restart the worker while idle.
