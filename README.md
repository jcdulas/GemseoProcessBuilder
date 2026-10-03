# GEMSEO Process Builder

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Checks](https://github.com/jcdulas/GemseoProcessBuilder/actions/workflows/check.yml/badge.svg)](https://github.com/jcdulas/GemseoProcessBuilder/actions/workflows/check.yml)

A desktop application to build, run and analyze [GEMSEO](https://gemseo.readthedocs.io) processes graphically, in the spirit of Ansys ModelCenter.

- Draw a model with components (analytic expressions, Python functions and classes, external codes, surrogate models), assemblies and drivers (MDA, DOE, optimization, parametric study), and link their variables.
- Check it continuously, and look at it as an N2 matrix or an XDSM diagram.
- Run it in a separate process and follow its progress; explore the results with interactive charts and GEMSEO's post-processings.
- Export a readable GEMSEO script, images of every view, and a project report.

> Status: alpha. The file format may still change between versions.

![The Sellar problem on the canvas after a run, with the variables of a link](docs/images/canvas_link_panel.png)

| Results of an optimization | Quality of a surrogate |
|---|---|
| ![History of the objective, constraints and design variables](docs/images/results_history.png) | ![Cross-validated quality of a surrogate](docs/images/surrogate_quality.png) |

## A tour of the interface

![The workspace: the library of nodes, the workflow canvas and the inspector](docs/images/ui_workspace.png)

*The workspace, on the bi-level wing sizing described below: the library of components, containers and drivers (left), the workflow canvas (center) and the inspector (right).*

| Every model is a tree of levels | The N2 matrix of a level |
|---|---|
| ![The model tree](docs/images/model_tree.png) | ![The N2 matrix of the system level](docs/images/wing_n2.png) |

| A driver, set up in tabs | Its algorithm, with advice and costs |
|---|---|
| ![The formulation of a driver](docs/images/driver_formulation.png) | ![The algorithm of a driver](docs/images/driver_algorithm.png) |

## What you can do with it

| Use case | Example project | What the application gives you |
|---|---|---|
| Couple disciplines and optimize | [Sellar](examples/sellar_mdf.py) with MDF, IDF and a disciplinary formulation; [Sobieski](examples/sobieski_bilevel.py) bi-level | The N2 matrix and XDSM of the couplings, the formulation chosen in a list, the history of the objective, the constraints and the design variables |
| Explore a design space | [Rosenbrock DOE and parametric study](examples/rosenbrock_doe.py); [a DOE around an optimization](examples/doe_around_optimization.py) | Samplings, interactive charts, GEMSEO's post-processings |
| Reuse the code you already have | A [chain of Python functions](examples/beam_chain.py), a Python class, an [external program](examples/external_code/) driven through its input and output files | Components wrapped without writing glue code; the generated script shows what runs |
| Replace costly models | A [wing sizing optimized on surrogates](examples/wingBiLevel/), checked against the normal models | Surrogates trained from samples, their cross-validated quality, and the check of the optimum on the model it replaced |
| Go to very many variables | The same wing with [100,000 variables](examples/wingBiLevel100k/), on gradients and post-optimal sensitivities | Runs in a separate process, followed live |
| Size structures under stress constraints | An L-shaped bracket of 10⁴ to 10⁵ plane-stress elements, one von Mises constraint per element (benchmark of [gemseo-lso](plugins/gemseo_lso/)) | The large-scale optimizer, optionally piloted by Claude (below) |
| Test an optimizer against the literature | Trusses of 10, 25 and 72 bars, Svanberg's beam, Hock–Schittkowski problems ([`run_literature.py`](plugins/gemseo_lso/benchmarks/run_literature.py)) | The published optima, reproduced |

## Use case in detail: a bi-level wing sizing

The example [`examples/wingBiLevel`](examples/wingBiLevel/) sizes the wing of an aircraft at three levels: a system level chooses the shape of the wing, and each discipline optimizes its own variable for the shape it is given. The costly models (an aerodynamic and a structural solver) are replaced by surrogates, and the optimum is checked against the normal models. Open it with `gemseo-process-builder examples/wingBiLevel/wing_bilevel.py`: the files are the graph of the study, and the application reads them as a project.

| Level | What it holds | Design variables | Objective |
|---|---|---|---|
| **Model** (the root) | The `SystemOptimizer` and the results of the workflow | | |
| **SystemOptimizer** (a BiLevel optimization) | Two sub-optimizations and the `Performance` component | `area` (10 to 60 m²) and `span` (8 to 30 m) | The range, maximized |
| **AeroOptimizer** | The aerodynamic surrogate | `camber` of the airfoil (0 to 0.12) | The drag, minimized |
| **StructureOptimizer** | The structural surrogate | `thickness` of the wing box | The weight, minimized |

`Performance` computes the range (Breguet's formula) and the wing loading from the weight and the drag; the wing loading is constrained to 3000. The aerodynamics gives its maneuver load to the structure, and the structure gives its weight back: these are the couplings of the N2 matrix and the XDSM below.

| Level 0: the model | Level 1: the system optimization |
|---|---|
| ![The root of the model: one optimization and its results](docs/images/wing_level_0_model.png) | ![The system level: two sub-optimizations and the performance](docs/images/wing_level_1_system.png) |

| Level 2: the aerodynamics | Level 2: the structure |
|---|---|
| ![AeroOptimizer: the aerodynamic surrogate](docs/images/wing_level_2_aero.png) | ![StructureOptimizer: the structural surrogate](docs/images/wing_level_2_structure.png) |

Double-click a container to go into it; the breadcrumb (*Model › SystemOptimizer › AeroOptimizer*) takes you back up. The XDSM shows the whole process, with its two sub-optimizations (orange) and the MDA loops that solve the couplings (purple):

![The XDSM of the system optimization](docs/images/wing_xdsm.png)

The driver of the system level is set up in tabs: its design variables, then its formulation (BiLevel) and its algorithm (here `NLOPT_COBYLA`, 60 iterations at most):

![The design variables of the system optimization](docs/images/driver_variables.png)

**Run it.** The run starts in its own process and the results tab fills while it goes, with the progress in the status bar and a **Stop** button:

![A run in progress: the history of the objective, the constraint and the design variables](docs/images/run_live.png)

On this machine the run took 1 minute 10 seconds and 46 evaluations. It ends at a range of 3460 km, with `area` 28.81 m², `span` 25.62 m, `camber` 0.05924 and `thickness` 0.1866, the wing-loading constraint active:

![The summary of the run: the optimum, the active constraint and the best feasible point](docs/images/results_summary.png)

| Parallel coordinates | Response surface of the range |
|---|---|
| ![Parallel coordinates of the evaluations: feasible in green, infeasible in red](docs/images/results_parallel.png) | ![A Kriging response surface of the range over the area and the span, with the constraint boundary](docs/images/results_response_surface.png) |

The response surface is learned from the evaluations of the run (a Kriging model, 46 evaluations and two design variables, here with an R² of 1.00 for the range and 0.98 for the constraint on the 9 evaluations left aside) and draws the boundary of the constraint; the same data are also in a table, a scatter matrix and GEMSEO's post-processings. The script the run executed is one click away (*Open the script*), and the project is saved as a readable GEMSEO script.

## Installation

Python 3.12 or 3.13, on Windows or Linux. The package is not published on PyPI: install it from this repository.

```bash
python -m pip install git+https://github.com/jcdulas/GemseoProcessBuilder.git
gemseo-process-builder
```

Open a project with `gemseo-process-builder model.py`: projects are saved as readable GEMSEO scripts, and GEMSEO scripts written by hand open as projects. The [examples/](examples/) folder has ready-made projects, as GEMSEO scripts, also opened from the Demos of the Library: the Sellar problem with three formulations, Rosenbrock DOE and parametric study, the Sobieski BiLevel optimization, a DOE around an optimization, a wing sizing with coupled analytic disciplines, a beam computed by a chain run in order, an optimization as a step of a sequence, an external code, a bi-level optimization written by hand in several files, using every kind of component ([examples/demoBiLevel](examples/demoBiLevel/)), a bi-level wing sizing optimized on surrogates checked by their normal models ([examples/wingBiLevel](examples/wingBiLevel/)), and its variant with 100,000 variables, on gradients and post-optimal sensitivities ([examples/wingBiLevel100k](examples/wingBiLevel100k/)).

## Optimization augmented by AI

Two optional packages, installed in the Python that runs your models, work together. Neither is needed to build, run or analyze a process.

### `gemseo-lso`: an optimizer for large problems

[`gemseo-lso`](plugins/gemseo_lso/) adds `LSO_MMA` and `LSO_GCMMA` to GEMSEO: the method of moving asymptotes (Svanberg, 1987 and 2002) for 10⁵ to 10⁶ design variables and as many constraints, whose gradients are costly ([specification](docs/LARGE_SCALE_OPTIMIZER_SPEC.md)). It is written in NumPy, SciPy and Numba and runs one iteration at a time.

- **Working set**: each iteration asks only for the gradients of the constraints close to activity, checks the step against the values of all of them, and solves again when a screened-out constraint would be violated. On a stress-constrained L-shaped bracket (10⁴ elements, `LSO_MMA`), it reaches the design of the run that asks for every row with about a quarter of the rows (482,288 against 2,000,000): a volume fraction of 0.3467 in 160 iterations, against 0.348 in 200 iterations, not converged, with every row.
- **Colored Jacobians** (off by default): for constraints that depend on a few neighbouring variables, a few tens of directional derivatives replace one gradient per constraint.
- **Feasibility**: a run that ends outside its constraints brings itself back within them (smaller steps, GCMMA) and returns the best feasible point it met.
- **Path through the constraints** (`descent_iterations`, off by default): from a neutral start, the design first goes down with soft constraints, toward the lightest design (for a structure, the fully stressed one), then comes back to feasibility.
- **Outside the feasible domain**: from a design that violates most of the constraints, the working set keeps the most violated ones only, and a step is checked against the constraints it makes worse, not against all the violated ones (`violated_share`, `violated_working_set`).
- **Relaxing constraints** (`relax`, `tighten`): some inequality constraints can be relaxed to `g ≤ amount` and brought back by steps, from the state the run is in. Its reports, its best feasible point and its result stay those of the original problem, and the relaxation is saved with the state.
- **Speed**: the products with the rows run on every core with Numba, and the projected Newton method of the dual (`dual_solver="newton"`) factorizes its system by Cholesky from a parallel loop. `auto` still takes L-BFGS-B on the bracket.
- **Steppable, with a saved state**: its settings can change between two iterations, the state is saved and resumed exactly, and each report gives the KKT residual, the working set and the variables sitting at a bound.

It was checked on problems with published optima (`plugins/gemseo_lso/benchmarks/run_literature.py`): the 10-, 25- and 72-bar trusses (5060.85, 545.16 and 379.62 lb), Svanberg's beam up to 10⁴ segments, and Hock–Schittkowski 71, 100 and 113. Known limit: on the 10-bar truss, GCMMA from a neutral start lands in the local optimum of 5076.85 lb.

### `gemseo-claude-pilot`: Claude as a copilot of the run

[`gemseo-claude-pilot`](plugins/gemseo_claude_pilot/) lets Claude watch an optimization or a DOE while it runs, explain what happens and act on it ([specification](docs/CLAUDE_PILOT_SPEC.md)). You turn it on in the **Copilot** tab of a driver; the same run works from the generated script, outside the application.

**Who decides.** Three modes: *Observer* (Claude explains, changes nothing), *Advisor* (Claude proposes, you accept or reject) and *Pilot* (Claude applies its decisions). With the large-scale optimizer, the run waits for Claude at the end of an iteration (every 10 iterations or every 2 minutes, whichever comes first), so that it can think and define a strategy that applies from the next one; with the other algorithms, the optimizer never waits for Claude: a decision applies at the next iteration.

**What Claude sees.** The problem (bounds, constraints, algorithm and settings, budget), the history, the report of each outer iteration of `LSO_MMA` and `LSO_GCMMA` (objective, maximum constraint, KKT residual, working set, repairs, step), the symptoms found by simple rules (stagnation, infeasibility, divergence, oscillation, `plateau`, `stuck`, and `frozen`, below), its own earlier decisions and what followed, and how each surrogate was trained. A model whose design lies on a grid can describe its physics: Claude then reads maps of the design, whether the material carries the loads to the supports, and where the stresses concentrate.

**What Claude can do.** Change the settings of the algorithm, narrow the design space, switch algorithm, stop the run, add samples to a DOE, retune a sub-optimization of a bi-level study, steer the design toward where it is heading, or restart it from a transformed design. With the large-scale optimizer, changes of settings, switches between MMA and GCMMA and steering apply at the next iteration, with the asymptotes, multipliers and working set kept. It also may compare strategies from the same state, ask for feasibility to be restored, relax the constraints that hold the run back and bring them back by steps (below), return to a checkpoint, and, if you give it a scenario factory, explore other starting designs in processes of their own. It reads the values the settings have now, defaults included, and a change that changes nothing is refused.

**Limits and privacy.** Claude never widens your bounds, never spends more evaluations than you allowed, restarts a run at most three times, relaxes constraints at most twice, returns to a checkpoint at most three times and makes a limited number of calls. Nothing is sent before you accept, and you choose the level: *Anonymized*, *Without code* (the default) or *Full*. It reaches Claude through your Claude Code subscription or an API key (Claude Opus 5.5 at a low effort by default). What is sent goes to Anthropic. Every call, decision and report is kept in a journal, and the run ends with a short report of what happened and how far to trust the result.

**In the application.** The Copilot tab of a driver turns the copilot on and sets its mode, what it may do, the data it may send and its number of calls; the connection and the models are chosen once in the preferences.

| The Copilot tab of a driver | The preferences of the copilot |
|---|---|
| ![The Copilot tab of the system optimization](docs/images/driver_copilot.png) | ![The Claude copilot section of the preferences: connection, models, defaults of a new copilot](docs/images/preferences_copilot.png) |

**Testing for a local optimum.** The optimizer converges to a local one, and a variable that reached its bound early may have decided which. The reports list the variables at or within 1 % of a bound and what moving them would cost; the `frozen` event fires when the run settles with some; Claude may then lift the cheapest ones with a steering and see whether the run comes back to the same design.

**Relaxing the constraints that hold the run back (the pump).** A converged run is at the best design its active constraints allow from where it started, and the multipliers say what each constraint costs the objective. Claude can elect a batch of the constraints that cost the most, `relax` them by an amount, and bring them back in steps, each once the objective has settled. With `cycles` above 1 this is a *pump*: the run settles at the original constraints between two cycles, and the pilot judges each cycle on the objective it ended on and on how far the design moved: `better`, `moved`, `returned` (the same objective on the same design: too weak to leave the basin), or `worse`. After a `returned` cycle the next one relaxes more constraints by a larger amount (`grow`); after a `worse` one the run returns to the state saved before the cycle. Checkpoints of the optimizer are saved at each consultation, at the best feasible design and before a relaxation, and Claude may return to one (`resume`). The batch and the amount are chosen from the multipliers and from what the earlier cycles did, so the method is not tailored to a problem.

**What we measured.** On the 10-bar truss (published optimum 5060.85 lb), one run for each configuration (the piloted ones with 15 seconds per iteration, so that Claude can answer between two iterations):

| Configuration | Weight (lb) | Claude's decisions |
|---|---|---|
| GCMMA alone, no descent | 5076.67 (local optimum) | none |
| GCMMA alone, descent of 5 iterations | 5060.86 (published optimum) | none |
| Piloted, no descent, first prompt | 5076.67 | 1 |
| Piloted, descent, first prompt | 5060.89 | 4 |
| Piloted, no descent, with the local-optimum test | 5060.88 in one run, 5076.65 in another | 3, then 2 |
| Piloted, descent, with the local-optimum test | 5072.55 (last iterates at 5076.67) in one run, 5060.91 in another | 1, then none |

These are single runs: they show that the descent is what reaches the published optimum most often, and that Claude's test of a local optimum sometimes finds it and sometimes does not. Claude answers in about ten to fifteen seconds, so it cannot steer a run that finishes in less: it is meant for costly simulations, where minutes pass between two iterations.

**The bracket, with the optimizer waiting for Claude.** The stress-constrained L-shaped bracket (10⁴ elements, `LSO_MMA`, at most 600 evaluations), piloted by Claude Opus 5.5 at a low effort through Claude Code, the optimizer waiting for each answer (called every 10 iterations or every 2 minutes, and on detected events). In the first run Claude was judged on its own decisions only; in the second, its decisions were judged on the iterates, with comparisons and feasibility on request:

| | First run | Second run | Working set, alone | Every row, alone |
|---|---|---|---|---|
| Volume fraction | 0.3544 | 0.3593 | 0.3467 | 0.348 |
| Largest stress | 1.0000 of the limit | 1.0000 of the limit | | |
| Outer iterations | 140 (454 evaluations) | 123 (356 evaluations) | 160 | 200 (not converged) |
| Constraint rows computed | 378,171 | 437,281 | 482,288 | 2,000,000 |
| Calls to Claude | 35 (32 on an event) | 20 (8 on an event) | | |
| Duration | 1,787 s | 1,866 s | | |

Both runs ended by Claude's decision to stop, on a plateau. The first took 5 decisions: a rounded reentrant corner (`steer`), a wider screening, then `move_limit` lowered to 0.1, 0.05 and 0.03. The second took 4: the same `steer`, `keep_factor` 3, `screening_margin` 0.45 and one `restore_feasibility` at its iteration 118, after which the objective went on falling; its stop was accepted because the gain the objective could still bring over the 84 iterations left was estimated at 0.27 %, under the 0.5 % that makes the pilot refuse a stop. The detectors read the iterates in the second run, which cut the calls on detected events from 32 to 8 (the 15 false oscillations of the first run did not come back). Claude did not use `compare` in this run, and no change of settings was undone.

These are single runs, and they do not show that the new mechanisms improve the design: the second run is 0.005 heavier than the first, and both are 2 to 4 % heavier than the run without Claude (0.3467), so on this problem the copilot saved rows and iterations, not volume. The difference between the two runs is within what two runs of the same configuration may give, Claude's answers not being deterministic; showing an effect needs several runs of each configuration, which these are not.

**The bracket, with explorations, then a pump of the constraints.** Later runs of the same bracket (Claude Sonnet 5.5 at a low effort, the optimizer waiting for each answer, at most 600 evaluations):

| Starts explored | No pump | Weak pump | Strong pump |
|---|---|---|---|
| ![L-shaped bracket, with explorations](docs/images/lso_bracket_piloted_explorations.png) | ![L-shaped bracket, no pump](docs/images/lso_bracket_piloted_no_pump.png) | ![L-shaped bracket, weak pump](docs/images/lso_bracket_piloted_weak_pump.png) | ![L-shaped bracket, strong pump](docs/images/lso_bracket_piloted_pump.png) |

| | Starts explored | No pump | Weak pump | Strong pump |
|---|---|---|---|---|
| Volume fraction | 0.3402 | 0.3400 | 0.3404 | 0.3397 |
| Duration | 1,344 s | 726 s | 949 s | 1,287 s |
| What Claude did | Widened the screening margin (0.3 to 0.6); explored two starts, a perturbed design (0.366) and a smoothed one, ended after 908 s outside the feasible domain; kept the main run | Nothing: judged a relaxation not worth it for a remaining gain of 0.2 %, with 62 % of the budget unspent | Pump of 3 cycles, 10 components out of 690 relaxed by at most 0.05: each cycle came back to 0.3408 | Pump of 3 cycles, 350 then 350 then 560 components, by 0.2, 0.14 and 0.224: the first cycle was `better` (6.5 % of the variables moved, 0.3461 to 0.3414), the two others `returned` |

The four designs are the same fan of members from the reentrant corner, and the volumes differ by 0.1 %, which is within what two runs of the same configuration may give. The pump moves the design when its batch is large enough, but the run comes back to the same optimum: on this problem, relaxing constraints from a design that has already settled does not change its load paths. The load paths seem to be decided in the first 40 iterations, when the design is still gray: 90 % of the variables sit at a bound from then on. A design with other load paths is believed to exist and to be lighter; none of the methods tried finds it; a continuation on the penalization of the model, started on a convex problem, was tried and stopped, its iterations costing five times more.

## Documentation

- [User guide](docs/user_guide.md): building a model, linking variables, drivers, running, results, wrappers, surrogates, exports, shortcuts.
- [Developer guide](docs/developer_guide.md): architecture, protocols, extending the application, tests.
- [Specification](SPEC.md) of the product, and the [plans](plans/) it was built with.
- [Large-scale optimizer](docs/LARGE_SCALE_OPTIMIZER_SPEC.md) and [Claude copilot](docs/CLAUDE_PILOT_SPEC.md) specifications.
- [Changelog](CHANGELOG.md).

## Development

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"      # Windows: .venv\Scripts\python.exe
.venv/bin/python tools/check.py                  # ruff, formatting, mypy, pytest, JS syntax, node tests
.venv/bin/python -m gemseo_process_builder --dev # the application, with the DevTools
```

Node.js is needed for the JavaScript tests. No test may last more than one second. See [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

## License

GEMSEO Process Builder is free software under the [MIT license](LICENSE). It uses third-party components under their own licenses (GEMSEO and Qt for Python under the LGPL, d3, elkjs and others), all listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
