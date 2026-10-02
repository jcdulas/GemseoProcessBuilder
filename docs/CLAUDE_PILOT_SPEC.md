# GEMSEO Claude Pilot — Specification

| | |
|---|---|
| Status | Draft v0.1 |
| Date | 2026-09-26 |
| Target | GEMSEO 6.x · Python ≥ 3.12 · GEMSEO Process Builder (SPEC.md) |
| Package | `gemseo-claude-pilot` (import `gemseo_claude_pilot`), in `plugins/gemseo_claude_pilot/` of this repository |
| Distribution | Open source, MIT license, installed from the GitHub repository; **not published on PyPI** (SPEC § 14.5) |

---

## 1. Purpose

Add an **AI copilot** that watches GEMSEO optimizations and DOEs while they run, and adjusts their strategy to make them converge faster and more reliably: algorithm settings, design space, algorithm choice, early stop.

The copilot is a **Python client of Claude** (Anthropic). It works:

- in a plain GEMSEO script, through a small public API (`ClaudePilot`);
- in GEMSEO Process Builder, where it is configured per driver, followed live in the run, and questioned in a chat.

It works with a **Claude API key** (billed per token) or with the user's **Claude subscription** through Claude Code (§ 5).

### 1.1 Users

The same users as the application (SPEC § 1.1):

- **Engineers who don't know GEMSEO**: the copilot explains what goes wrong ("the constraint `g_1` stays violated because…") and proposes fixes in plain words.
- **MDO experts**: they use it to save time on long runs, and keep control through the modes and guardrails.

### 1.2 Guiding principles

1. **Opt-in.** The copilot is off by default. Nothing is sent to Anthropic before the user has enabled it and accepted what is sent (§ 7).
2. **The run never depends on Claude.** A network error, a quota, a malformed answer or a slow answer never fails the run: the optimization goes on with its current settings.
3. **Every decision is explained and recorded** (§ 9). A run piloted by Claude is auditable after the fact.
4. **Guardrails are enforced in code, not in the prompt.** Claude proposes; the plugin validates every decision against the guardrails (§ 4.3) before applying it.
5. **Readable scripts.** A piloted driver produces a script that stays readable (SPEC § 10.2): the copilot appears as a few explicit lines (§ 8).
6. **Fast tests.** No test calls Claude; a fake backend replays scripted answers. The one-second rule applies (SPEC § 15.1).
7. **English only** (SPEC § 1.3), including the prompts sent to Claude.

### 1.3 Out of scope (V1)

- Editing the model itself (components, links, formulation) during a run. The copilot may *suggest* such changes in the chat or the report, never apply them.
- Choosing the algorithm list the copilot may switch to (every installed algorithm compatible with the problem is allowed; see § 4.3).
- Replaying a piloted run without Claude from its journal.
- Local filters that decide whether a periodic call is worth making (events are detected locally, § 4.2, but periodic calls are always made).
- Other LLM providers.

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Copilot** | The feature as a whole, as the user sees it |
| **Pilot** | The `ClaudePilot` object that runs a scenario in segments |
| **Backend** | The way the plugin talks to Claude: API key or Claude Code (§ 5) |
| **Segment** | One `scenario.execute(...)` call with fixed settings; a piloted run is a sequence of segments (§ 4.4) |
| **Trigger** | What makes the pilot call Claude: a period, an event, a user question, the start or the end of the run (§ 4.2) |
| **Decision** | The structured answer of Claude: a diagnosis and at most one action (§ 4.5) |
| **Guardrail** | A limit the pilot enforces on every decision (§ 4.3) |
| **Journal** | The JSON-lines record of every call, decision and segment of a run (§ 9) |

---

## 3. Architecture

```
┌──────────── UI process (PySide6) ───────────┐
│ Driver editor: Copilot tab                   │   no network, no GEMSEO
│ Run tab: Copilot panel + chat                │   (API key read/written in the OS keyring only)
│ Preferences: backend, models, budget, data   │
└──────┬──────────────────────────────┬────────┘
       │ JSON lines (SPEC § 11.2)      │ JSON lines
┌──────▼───────────────────────┐ ┌────▼─────────────────────────────┐
│ Runner (one per run)          │ │ Copilot process (on demand)       │
│  generated script             │ │  pre-run review of a driver,      │
│  └─ ClaudePilot               │ │  chat and report on a finished    │
│      ├─ detectors (local)     │ │  run (reads the run folder)       │
│      ├─ context builder       │ └────┬─────────────────────────────┘
│      ├─ advisor thread ───────┼──────┤ HTTPS
│      ├─ guardrails            │      ▼
│      └─ segment loop          │  Backend: Anthropic API (key)
└──────────────────────────────┘           or Claude Code (subscription)
```

- **The pilot runs in the runner** (SPEC § 11). It reads the `OptimizationProblem` and its `Database` directly, and applies decisions between segments.
- **Calls to Claude run in a background thread** of the runner (the *advisor thread*). GEMSEO never waits for Claude: a decision is applied at the next iteration boundary after it arrives (§ 4.4). The exception is the large-scale optimizer (§ 4.2, § 4.7): its run waits for Claude at the end of an outer iteration, and the call runs inline (`ClaudePilot(threaded=...)`, by default `False` for `LSO_MMA` and `LSO_GCMMA`, `True` for the others).
- **The UI process never talks to the network.** Questions asked in the chat during a run go to the runner on `stdin`; after the run, a short-lived **copilot process** (`python -m gemseo_claude_pilot.session`) answers them from the run folder. The same process performs the pre-run review of a driver.
- Both processes use the interpreter configured in the preferences (SPEC § 14.4). The worker reports whether `gemseo_claude_pilot` is importable there; if not, the Copilot tab explains how to install it.

### 3.1 Package layout

```
plugins/gemseo_claude_pilot/
  pyproject.toml
  src/gemseo_claude_pilot/
    __init__.py            # ClaudePilot, PilotMode, Action (public API)
    pilot.py               # segment loop, application of decisions
    advisor.py             # checks and calls to Claude, in a background thread
    triggers.py            # periodic and event triggers
    snapshots.py           # frozen pictures of a problem and its history
    detectors.py           # stagnation, infeasibility, divergence, failures (pure, no network)
    design/                # the design read physically: maps, indicators, restarts (§ 4.8)
    context.py             # problem and history summaries sent to Claude
    privacy.py             # data levels: full, no_code, anonymized (§ 7)
    decisions.py           # Pydantic models of decisions, validation
    algorithms.py          # installed GEMSEO algorithms and their capabilities
    guardrails.py          # enforcement of the limits (§ 4.3)
    tools.py               # tools Claude may call to read more data (§ 6.3)
    exchange.py            # one exchange: context, tools, decision, one correction
    prompts/               # system prompts, in English, versioned
    backends/
      base.py              # Backend protocol
      api.py               # anthropic SDK, API key
      claude_code.py       # claude-agent-sdk, Claude Code login
      fake.py              # scripted answers, for tests and demos
    auth.py                # key resolution: environment, then keyring
    journal.py             # journal.jsonl writer and reader
    events.py              # runner events and commands (§ 10.2)
    session.py             # copilot process: pre-run review, chat, report
    report.py              # post-run report
  tests/                   # pytest, fake backend only
```

---

## 4. Behavior of the pilot

### 4.1 Modes

Chosen per driver, with a default in the preferences:

| Mode | What Claude does | What the user does |
|---|---|---|
| **Observer** | Diagnoses and explains; no action is proposed | Reads the panel, asks questions |
| **Advisor** (default) | Proposes actions | Accepts or rejects each proposal in the Copilot panel; the run goes on meanwhile |
| **Pilot** | Decides; valid decisions are applied at once | Watches, can stop the run, can switch the run back to Advisor |

- In Advisor mode, an unanswered proposal expires when a newer one arrives or when the state it was based on is too old (by default 2 segments or 50 iterations later; for the large-scale optimizer, 10 outer iterations later: GCMMA makes several evaluations per iteration, and in the first piloted bracket a restart expired after 77 evaluations but 26 iterations). The same age applies to a decision in Pilot mode.
- In a standalone script (no UI), Advisor mode is not available: the pilot falls back to Observer and logs why.
- The mode can be changed during the run from the Copilot panel (command `copilot.mode`, § 10.2).

### 4.2 Triggers

All four families are available, each can be turned off:

| Trigger | Default | Detail |
|---|---|---|
| **Periodic** | every 25 iterations, and at least 60 s apart | Also a time period (every T seconds) for slow evaluations; for an algorithm reporting its outer iterations (the large-scale optimizer), checked at each outer iteration: a first call after the first outer iteration, to judge whether the run started from a viable point (`first_iteration`), then, at the end of an outer iteration, a call every 10 outer iterations (`period_iterations`) or every 2 minutes (`launch_pause`, 120 s, counted from the start of the last call), whichever comes first. The call blocks the optimizer: Claude has the time to think and to define a strategy, which applies from the next outer iteration |
| **Events** | on | Detected locally by `detectors.py`, without calling Claude: |
| | | • *stagnation*: best objective improved by less than a relative 1e-4 over the last 20 iterations; |
| | | • *persistent infeasibility*: no feasible point in the last 30 iterations; |
| | | • *divergence*: objective or constraint violation growing over 10 iterations; |
| | | • *failed evaluations*: an evaluation raised, or returned NaN/inf; |
| | | • *oscillation*: design variables moving back and forth with a shrinking step; |
| | | • *bounds*: more than half of the design variables at a bound; |
| | | • for an algorithm reporting its outer iterations (the large-scale optimizer), the stagnation, infeasibility, divergence, oscillation and bounds detectors read its iterates only, in outer iterations (§ 4.9): its inner iterations and repairs are not its progress; failed evaluations are still read on every evaluation; |
| | | • for the large-scale optimizer, the symptoms of § 4.7; *stuck*: its best KKT residual has not decreased by 10 % over 20 outer iterations while above 10 × `kkt_tolerance`, or its constraints stayed violated over 20 outer iterations without their violation halving (slightly infeasible iterates are normal while MMA descends) (§ 4.8); *plateau*: its objective improved by less than 0.5 % over 10 outer iterations — Claude weighs the gain left against the iterations, and stops or restarts the run rather than let it spend them for nothing. |
| **On demand** | on | A question in the chat, or the *Ask now* button |
| **Start and end** | on | Pre-run review (before the first segment) and post-run analysis (§ 9.2) |

- A minimum interval between two calls (default 30 s) applies to periodic and event triggers; events that happen meanwhile are queued and sent together.
- The detectors' thresholds are settings of the pilot (advanced section of the Copilot tab).
- Only one call is in flight at a time; questions from the chat are answered first.

### 4.3 Actions and guardrails

Actions Claude may take (each can be forbidden per driver):

| Action | Content | Validation |
|---|---|---|
| **Change settings** | New values of settings of the current algorithm (tolerances, `max_iter` of the segment, step sizes, …) | Validated against the algorithm's GEMSEO Pydantic settings model |
| **Change design space** | New lower/upper bounds and/or new starting values of some design variables; scaling | Bounds **inside the user's original bounds**; value inside the new bounds; integer variables stay integer |
| **Switch algorithm** | Another algorithm, with its settings | Installed, and compatible with the problem (constraints, equality constraints, gradients, multi-objective, integers), with the same rules as the driver editor (SPEC § 6.4) |
| **Stop** | Stop the run, with a reason (`converged`, `hopeless`, `budget`) | Always allowed when enabled |
| **Add samples** (DOE) | A new sampling segment: method, number of samples, optionally a sub-region of the design space | Same bounds rule; counted in the evaluation budget |
| **Change a sub-optimization** (BiLevel) | Another algorithm and/or other settings of one sub-optimization | The sub-optimization exists; validated against the settings model of its algorithm |
| **Steer** | Move the current design toward where it heads, the optimizer going on: extrapolate the trend of the design variables (`anticipate`), transform a described design on its grid (§ 4.8), set some variables; with a statement of where the design heads | Something moves; transformations need a described design, inside its maps; values inside the bounds; the moved design clipped into them. Applied at the next outer iteration of `LSO_MMA`/`LSO_GCMMA` without a new segment (their state kept), a new segment from the moved design otherwise |
| **Compare** (`LSO_MMA`, `LSO_GCMMA`) | One or two other strategies — other live settings, or the other method — tried from the current state: each branch and the current strategy, as the reference, run 3 to 10 outer iterations from the same state; the best end goes on (§ 4.9) | `LSO_*` only; the settings are valid and none is `max_iter`, `resume_from`, `save_state` or `method`; the branches spend at most half of the evaluations left; at most `max_comparisons` (2) per run |
| **Restore feasibility** (`LSO_MMA`, `LSO_GCMMA`) | Bring the iterate back within the constraints now: smaller moves and a heavier cost of the violation until it is feasible, which the optimizer does by itself only near the end of its budget | `LSO_*` only, and the last iterate violates a constraint. Applied at the next outer iteration without a new segment |
| **Explore** (`LSO_MMA`, `LSO_GCMMA`; needs a scenario factory) | One to four runs of the problem from other starting designs, each in a process of its own, for at most 50 outer iterations, with the user's algorithm and settings, which Claude does not guide (§ 4.11) | A factory was given (`ClaudePilot(exploration=ExplorationSettings(factory=...))`); at most `max_explorations` (2) per run and one at a time; at most `max_processes` (4) starts, with different labels, each moving something; values inside the bounds, transformations inside the maps; the iterations clipped to `max_iterations` (50). Starts from the best feasible design, the current iterate or an evaluation, moved by `anticipate`, `transforms`, `variables` or a random `perturb` |
| **Adopt** (an exploration has ended) | Move the main run onto an exploration: its best feasible design and the optimizer state it saved (§ 4.11) | The exploration has ended without error and its state was saved |
| **Restart** (a model describing its design, § 4.8) | A new segment from another design: the best, the current or a past evaluation, transformed on its grid, and the physical diagnosis it answers | The model describes its design; the base evaluation exists; the regions inside the maps; at most `max_restarts` (3) per run, never with less than 20 % of the budget left |

Guardrails, enforced by `guardrails.py` whatever the mode:

- **Original bounds**: the design space can only be narrowed (or widened back up to the original bounds), never widened beyond them.
- **Evaluation budget**: the total number of evaluations of all segments never exceeds the budget of the user's driver (`max_iter` for an optimization, `n_samples` for a DOE). A decision that would exceed it is clipped to what remains.
- **Call budget** (§ 5.4): when it is spent, the pilot keeps running the current segment to the end and only answers nothing more.
- A decision that fails validation is **not** applied; the validation error is sent back to Claude once, in the same exchange, so it can correct itself; a second failure is recorded in the journal and ignored.

### 4.4 Segments and warm start

GEMSEO cannot change an algorithm while it runs, so a piloted run is a **sequence of segments** on the same scenario:

1. The pilot runs the first segment with the user's algorithm and settings.
2. When a decision must be applied (Pilot mode, or accepted in Advisor mode), the pilot raises an internal *end-of-segment* exception at the next iteration boundary, through the same mechanism as the stop command (SPEC § 11.4). GEMSEO finishes cleanly.
3. The pilot updates the design space (bounds, current value set to the **best feasible point** so far, or the least violated one) and the algorithm or its settings.
4. It runs the next segment on the **same `OptimizationProblem`**: its `Database` is kept, so points already evaluated are not evaluated again, and `history.h5` holds the whole run.
5. The run ends when a segment ends normally and Claude does not ask for another, when Claude stops it, when the evaluation budget is spent, or on the user's Stop.

Each segment is recorded (`segment` event, journal) with its index, algorithm, settings, design space changes, first and last iteration, and the decision that started it. The History view shows segment boundaries as vertical markers with the reason in a tooltip.

Settled in plan 58 (open point 1), on GEMSEO 6.3:

- the end-of-segment exception raised by the new-iteration listener goes through `scenario.execute`; the database keeps every evaluation, but the current value of the design space is not updated: the pilot sets it to the best point, clipped into the current bounds;
- `max_iter` counts the iterations of one `execute` (GEMSEO resets its counters), including points already in the database, which are not evaluated again: a segment with `max_iter` equal to the evaluations left cannot exceed the budget;
- each `execute` creates a new driver: no algorithm state is left from the previous segment;
- GEMSEO does not check the current value against the bounds: the pilot clips it when it changes them;
- at the end, the pilot gives back the bounds the user set and sets the design space to the best evaluation of the whole run; `scenario.optimization_result` is the one of the last segment.

### 4.5 Decisions

Claude answers with a structured decision (tool call or structured output, § 6.2):

```json
{
  "diagnosis": "The objective has not improved for 20 iterations; the step is at the tolerance.",
  "severity": "info | warning | problem",
  "action": {
    "kind": "none | change_settings | change_design_space | switch_algorithm | stop | add_samples | change_sub_scenario | restart | steer",
    "...": "fields of the action, as in § 4.3"
  },
  "rationale": "Why this action, in two or three sentences.",
  "expected_effect": "What should be seen in the next iterations.",
  "confidence": 0.7
}
```

The pilot checks the *expected effect* at the next call: the context of the next call includes the decisions already taken and what happened after each.

### 4.6 Driver kinds

| Driver | What the copilot does |
|---|---|
| **Optimization** (MDF, IDF, DisciplinaryOpt) | Everything in § 4.1–4.5 |
| **BiLevel** | Pilots the **system** scenario with segments. It may change the algorithm or the settings of a sub-optimization (*Change a sub-optimization*): applied at the next system iteration, without ending the segment, never during a sub-optimization. The context lists the sub-optimizations (name, algorithm, settings, design variables, objective) and the components of all levels; the system has no gradients. |
| **DOE** | Triggers at the end of each sampling segment; actions *Add samples* and *Stop*; no warm start, no detector events. Typical use: a first space-filling sampling, then more samples where the responses vary most or near the constraint boundaries |
| **Surrogates** | In a run whose model contains surrogate components (SPEC § 7.4): each is described to Claude by its regression model, its training size and its R² on its training data, so the pre-run review and the post-run report can say how far it can be trusted. For a DOE that trains a surrogate, *Add samples* aims where the model error is highest |
| **Parametric study, MDA** | Not piloted; the chat and the post-run report remain available |

Settled in plan 63 (open point 2), on GEMSEO 6.3:

- **BiLevel**: the adapter of a sub-optimization runs `scenario.execute()` with the settings stored by `set_algorithm`; the pilot calls `set_algorithm` on the sub-scenario at the next system iteration, and the next system evaluation uses it. The adapters are not rebuilt.
- **DOE budget**: the budget is `n_samples`; a DOE without it (`CustomDOE`, …) runs as the user set it, without the copilot. When *Add samples* is allowed and the method has a seed, the first segment draws **half** of the samples, and Claude places the others; the samples Claude leaves are drawn at the end, as the user asked. A method without a seed would draw the same points again: it keeps all its samples in one segment.
- **Seeds**: a later segment with a seeded method gets another seed (unless the user or Claude set one), or it would draw the same points again.
- **Region**: GEMSEO sets the design space to the best point of the whole database at the end of a DOE, which fails when the bounds were narrowed. The bounds are therefore never changed: the points of a region are drawn with `compute_doe` in a copy of the design space narrowed to it, then evaluated with `CustomDOE`.

### 4.7 The large-scale optimizer (plan 70)

`LSO_MMA` and `LSO_GCMMA` (package `gemseo-lso`, docs/LARGE_SCALE_OPTIMIZER_SPEC.md § 8) open a *live run* on their problem while they run (`gemseo_lso.gemseo.live`). The pilot, which imports `gemseo-lso` only for these algorithms:

- **telemetry**: watches the report of each outer iteration, keeps the last 200 in the snapshot (`algorithm_state`), records each in the journal (`algorithm`) and publishes it (`copilot.algorithm`); the context gives the last 10 reports in full and earlier ones per window of 20 (`optimizer`);
- **live decisions**: `change_settings` on live settings (all the settings of the core but `method`, `max_iter`, `ftol_rel`, `xtol_rel`, `stall_iterations`, the tolerances GEMSEO checks the result with and `jacobian_mode`), and `switch_algorithm` between `LSO_MMA` and `LSO_GCMMA` (the `max_iter` the guardrails add is dropped: the running execution keeps its budget), are applied at the next outer iteration **without ending the segment**, like `change_sub_scenario`; the optimizer keeps its asymptotes, multipliers and working set. The guardrails validate the settings against the model of the algorithm first, the live run checks them again (their ranges, their cross checks); a refused change is recorded (`status` `refused`) and dropped. Any other decision starts a new segment, as for other algorithms;
- **detectors** (§ 4.2), from the reports: screening repairs at each of the last 5 outer iterations (`repairs`), a working set changing by more than 30 % of its size per iteration (`churn`), asymptotes narrowed below 2 % of the ranges (`asymptotes`), 5 GCMMA inner iterations per outer iteration or more (`inner_iterations`), reused rows while the step is repaired (`stale_rows`), 80 % of `max_row_evaluations` spent (`row_budget`);
- **large vectors**: a constraint of more than 10 components is summarized at the best point in the context (`summary_at_best`: the counts and share of its violated and active components, its quantiles and its 10 largest components; counts only in `anonymized`), and `get_constraint(name, components)` gives up to 20 components at the best point (their states only in `anonymized`). Measured: 1,050 tokens for a problem with a constraint of 10⁶ components, 2,100 with 200 reports of the optimizer;
- **prompt**: version 2 of the system prompt explains the reports and the live settings of the optimizer, and what their symptoms call for.

### 4.8 The design, read physically (plan 71)

A model whose design lies on a grid may describe its physics, so that Claude understands the design as an engineer would, not as statistics of numbers. In the first piloted run of the stress-constrained bracket, Claude received quantiles of 10⁴ densities: it judged the design "gray everywhere" while two thirds were at a bound, and changed settings blindly; the runs of the bracket also end in different local optima, which settings do not change.

**Three layers** (package `gemseo_claude_pilot.design`):

1. **The model describes its physics** through the protocol `PhysicalDesign` of one of its disciplines (structural: the model does not import the copilot), found by the pilot on the disciplines of the scenario like the row mode finds `RowJacobian`:
   - `physical_description()`: the physical problem in a few sentences (physics, material law, objective, constraints, filter, units); the grid (rows, columns, cell size, row 0 at the bottom); the design variable and the constraints laid on it (a cell per component); the geometric features (a reentrant corner, a hole), the supports (what they block) and the loads (direction, magnitude), each at some cells; the fields it computes, each with its quantity, unit, role (`density`, `stress_ratio`, `energy`, `principal_sign`, `other`), how to reduce it over a block (mean, maximum) and how to read it; the minimum member size. Checked (`PhysicalDescription`): cells inside the grid, one per component; a wrong description turns the view off, with a warning.
   - `physical_fields(input_data)`: the fields at a point, one value per component.
2. **The copilot interprets**, generically:
   - **text maps** of at most 40 × 40 characters, a larger grid reduced by blocks as each field says, with the supports (`S`), loads (`F`) and features (`A`, `B`…) marked, a legend with the unit, row and column numbers;
   - **indicators**: `material` (volume fraction, solid, gray and void shares), `load_path` (whether solid material — density above 0.5 — connects each load to a support, 4-connected; if not, the gap and its two ends; the floating parts), `members` (the width along their middle, from a distance transform, against the minimum member size; the thin ones), `checkerboard` (alternating 2 × 2 blocks), `dead_material` (solid with a strain energy below 1 % of the mean of the solid), `hot_spots` (the zones of stress ratio above 0.98, their peak, violated cells, and the feature within three minimum member sizes), and for the large-scale optimizer `price:<constraint>` and `stationarity` (its multipliers and the projected gradient of its Lagrangian, from its live run) with their largest places; positions in map cells;
   - `compare(before, after)`: the changes of material, hot spots and load path.
3. **Claude reads them with a physics primer** (system prompt version 3): SIMP and gray material, the relaxed stress, reentrant corners, load paths, member size, checkerboards, tension and compression; to explain a stuck run physically before acting, and to prefer a targeted restart when the design is at fault.

**When**: at every call — Claude anticipates where the design heads and steers it — the physical problem (`design.physics`), the points prepared and the fields available, the indicators and the maps of the density and of the stress at the best point (`design.detail`), and where the design is heading (`design.heading`: the trend of the design variable over the last 5 iterates of the optimizer as a map — `^` up by 0.3 or more, `v` down —, the shares of cells going up and down, and the design the trend leads to as far again, with its indicators and map); the restarts applied, with the indicators before, of the design restarted from, and now (`design.restarts`). Measured on the bracket at 10⁴ elements: a context of 2,800 tokens with the detail of the design, 1,900 without it, 1,160 without the design. Tools: `get_design_view(field, point)` (any field at the best point, the current one or an evaluation — an evaluation has the design variable and the constraints only), `get_design_indicators(point)`, `list_design_transforms()`.

**Fields at hand**: the pilot prepares the design in the optimizer's thread at each check (the model is not computing then): the current point (the model has its state at hand), the best point (computed again only when it changes), the starting point before any evaluation.

**Steer** (`steer` decision): the goal is the optimum in as few iterations as possible. From the last iterate of the optimizer (not its inner evaluations), in order: `anticipate` extrapolates the trend of all the design variables (`x + factor (x - x_past)`, `iterations` iterates back, a factor up to 3), `transforms` apply to a described design as for a restart, `variables` set values; clipped into the bounds; `toward` says where the design heads. The large-scale optimizer takes it at its next outer iteration without a new segment (`LiveRun.move`: one evaluation, the past iterates and the asymptotes moved with the point, the multipliers and the working set kept); another algorithm starts a new segment from the moved design. Computed when applied, from the iterate then: never from a stale point.

**Restart** (`restart` decision): a base (`best`, `current` or an evaluation) and transformations on the grid, in map cells, applied to the design variable normalized by its bounds: `binarize(threshold)`, `smooth(radius)`, `set_region` (a rectangle or a disk, filled or emptied), `connect(start, end, width)` (a bar closing a load path), `blend(evaluation, weight)`; and `answers`, the physical diagnosis it answers. Applied as a new segment (§ 4.4) from the transformed design, the other design variables at the base point; the database and the budget are kept; an LSO algorithm starts afresh (asymptotes, multipliers, working set). Recorded in the journal (`restart`: the indicators and density maps before and after).

**Data levels**: the design is sent whatever the data level, `anonymized` included: its description, maps and indicators, with their real names and values (the user's choice: Claude needs the physics to judge the design).

### 4.9 Judging the decisions, on the iterates (large-scale optimizer)

Everything below is computed from the reports of the outer iterations (`progress.py`), whatever the problem; no known optimum is ever given to Claude.

- **Detectors on the iterates.** `stagnation`, `infeasibility`, `divergence`, `oscillation` and `bounds` read the evaluations that end an outer iteration (`snapshots.iterate_entries`), not GCMMA's inner evaluations: in the first piloted bracket, 15 of 35 calls were an `oscillation` of the inner evaluations that Claude each time found to be none. `frozen` also needs the objective to have improved by less than 1 % over 10 outer iterations (a run that still descends has not settled).
- **Effect of a change, with rollback.** After a live change of settings or a switch between MMA and GCMMA, the pilot compares the 5 outer iterations that follow with the 5 before: if the objective gained at least twice less per iteration, with no lower violation nor KKT residual (by 20 %) to pay for it, the change is undone (`rollback` record), Claude is told in the `outcome` of its decision, and the same change is refused afterwards. Otherwise the outcome says it was kept, with the gains.
- **Stop for convergence.** `optimizer.progress` gives the gain per iteration, the iterations left and the gain the objective may still bring over them, if its descent keeps slowing at the rate of the last two windows of 5 iterations (a geometric tail: `progress.remaining_gain`). A `stop` with the reason `converged` is refused, with the reason told to Claude, while that gain exceeds 0.5 % of the objective, or while the last change of settings is not judged yet: a plateau made by a smaller step is not convergence.
- **Comparing strategies** (`compare`). The optimizer saves its state after the iteration at which Claude decided (`LiveRun.save`); the segment ends; each branch is a segment resuming that state (`resume_from`) with its settings, stopped after its iterations (`save_state` keeps its end); the pilot ranks the branches by `merit` — the relative change of the objective since the start plus the violation of the constraints, over the last 3 iterations of the branch — and the next segment resumes the best one. The reports of the other branches leave the reports of the run (they stay in the journal, tagged with their branch, and their evaluations in the database, spending the budget); a `comparison` record gives each branch. Claude is told which strategy was kept and every merit.
- **The rhythm of the consultations, chosen by Claude** (`ClaudePilot(adaptive_review=True)`, the default). The first call comes after the first outer iteration, which gives the time of an iteration. The context carries `pilot.timing`: the seconds an iteration takes (the median of the last 10, model and optimizer), the seconds a call takes (the median of the exchanges so far) and the number of iterations that keeps the calls under a quarter of the time of the run (`suggested_review_in`, at most 25). Every decision may carry `review_in`, the outer iterations that go by before Claude is consulted again, `none` included: a healthy run is left alone. The pilot bounds it (at least 1, at most 25 and half of the iterations left), and it replaces `period_iterations` and `launch_pause`; `review_ceiling` (600 s) calls Claude anyway, and detected events call it at once as before (`Triggers.set_review`, the `review` record of the journal). With `adaptive_review=False` the triggers keep their period and `review_in` is ignored.
- **One change at a time.** A change of live settings, or a switch between MMA and GCMMA, is refused while the last one is not judged (its verdict comes after 5 outer iterations), whatever the number of iterations before it.
- **A stop ends feasible.** A `stop` applied to a running `LSO_MMA` or `LSO_GCMMA` does not end on the last, often slightly infeasible, iterate: the optimizer first brings it back within the constraints (`LiveRun.stop(when_feasible=True)`, at most `restoration_iterations` more iterations), then ends.
- **Calibration on the journals.** `benchmarks/analyze_decisions.py` gives, from a journal, the verdict the rollback would have reached for each live change. On the three piloted runs of the bracket, no change of settings would have been undone (the reductions of `move_limit` of the first run slowed the descent by 6 to 44 % while the violation fell): the thresholds are kept, not tuned on these runs.
- **The pilot follows each run from its opening** (`gemseo_lso.gemseo.live.on_open`): a point already in the database announces nothing, and the first report of a segment resumed on one was lost.

### 4.10 The critique of the analysis (`critical_review`, on by default)

A human engineer in charge of a run does not act on a first impression: he looks for what contradicts his explanation, checks that what he sees is not the effect of his own last change, and says what he expects so that reality can prove him wrong. The pilot asks the same of Claude, for any problem (`critique.py`):

- **The assessment.** Any action comes with an `assessment` (`decisions.Assessment`; a decision without it is sent back, as for any guardrail): one to three hypotheses on what limits the run, each with the evidence for it and the evidence against it; the weaknesses of the analysis; the alternatives considered, going on unchanged included, and why not; and a measurable prediction. `none` needs none, a `stop` no prediction.
- **The prediction** is a metric of the outer iterations (`objective`, `max_constraint`, `kkt_residual`), whether it falls, rises or stays, within how many iterations and by how much. The pilot keeps it with the value of the metric when it was made and reads it when it falls due (`critique.verdict`; a violation near 0 is read against 1 % of the limit): the verdict goes to Claude in the `outcome` of the decision, the `forecast` record of the journal keeps it, and `pilot.track_record` gives the predictions made and how many held, so that Claude calibrates its confidence on its own record.
- **The review of heavy decisions.** A decision that ends the run or changes its strategy or design (`stop`, `compare`, `restart`, `steer`, `switch_algorithm`, `change_design_space`, `restore_feasibility`) is not applied at its first submission: the tool answers with a request for review (`critique.review_request`) giving the budget left in evaluations and iterations, asking for the strongest argument against the decision, the best use of the budget, for a stop the reason with a number why more iterations are not worth their cost, and the record of the predictions. Claude submits again — the same decision, a revised one, or `none` — once; the second submission is the one the guardrails check.
- `ClaudePilot(critical_review=False)` gives back the decisions without assessment nor review. The system prompt, version 10, asks for this discipline.

### 4.11 Exploring other zones (plan-less, optional)

The main run starts from one design and does not start from several: exploring is a decision Claude takes, when it has a reading of the space (a run that settled with variables at a bound, a design that settings cannot improve, two plausible regions), never systematically. It needs the means to build the problem elsewhere:

- **The factory.** `ExplorationSettings(factory=...)`, a function that creates a new scenario of the problem, picklable (a function of a module, or a `functools.partial`). Without it the actions are refused ("no scenario factory"). The user's explicit setting also states that the explorations spend evaluations *besides* the budget of the main run: they are bounded by `max_explorations` (2 per run), `max_processes` (4 at a time) and `max_iterations` (50 outer iterations each), and by a time limit (`timeout`, 1 hour), after which a process is ended.
- **The processes.** One process per start, started with the `spawn` method (the problem, its database and its disciplines keep a state: nothing is shared with the main run), each with its share of the cores (`cores // (max_processes + 1)` threads for BLAS and Numba) so that the main run is not starved. A process builds its scenario, sets the starting design, and runs the user's algorithm and settings of the start of the run. For `LSO_MMA` and `LSO_GCMMA` it counts the reports and, after the iterations asked, stops on a feasible point (`LiveRun.stop(when_feasible=True)`) and saves its optimizer state. No Claude is in the process: Claude does not guide it.
- **The starts.** Each start is a design of the run — the best feasible, the current iterate or an evaluation — moved by an extrapolation of the trend (`anticipate`, current iterate only), transformations of a described design (§ 4.8), values set on variables, or a random perturbation (`perturb`: a share of the range, a seed): the same moves as `steer`, plus the perturbation, which needs no knowledge of the problem. Each carries a `label` and the reason it is worth a look (`why`).
- **The main run goes on** while they run. When they have all ended, Claude is consulted (trigger `exploration`, journal records `exploration`, `exploration_result`): for each, the iterations and evaluations spent, the best feasible objective, the objective and violation of its last iterate, its gain per iteration over its last 10 iterations, and its distance to the main run's best feasible objective (`vs_main_best_feasible`, negative when better), set against the main run (`pilot.explorations.main`). Claude decides whether to `adopt`.
- **Adopting.** The main run ends its segment; the next one resumes the state the exploration saved (`resume_from`) from the exploration's best feasible design, which is evaluated again in the main database; the reports of the run start again, the previous ones belonged to another path (`adoption` record). The other explorations are dropped.

A decision to explore or adopt is a heavy one: it goes through the review of § 4.10.

**What tells Claude a run settled early** (read from the reports of any problem; found on the first piloted run of the bracket, which saturated its bounds by iteration 30 of 104, gained 3 to 4 % afterwards and ended on a plateau with 63 % of its budget unspent, Claude calling it "close to a local optimum" and finding nothing to change):

- `optimizer.saturation` (`context.optimizer_saturation`): the iteration at which half, three quarters and nine tenths of the design variables were held at a bound, the objective then and the share of it gained since. A run that gained little after its variables saturated has a structure fixed early, which no setting of the run changes.
- `optimizer.progress.evaluations_left` and `budget_left_share`: what is unspent.
- The event `settled` (`detectors._settled`): a plateau while at least half of the variables are held at a bound (`settled_share`): the run is on a local optimum, and a better one lies in another zone. The events `plateau`, `frozen` and `settled` also tell how much of the budget is unspent when it is above 30 % (`unspent_share`), and that going on as is is a choice to justify, another zone being explorable with it when `pilot.explorations` is in the context.
- The prompt, version 12, asks that a run converged with much of its budget unspent either explore or state in its assessment why it does not.

---

## 5. Backends and authentication

### 5.1 Two backends

| Backend | Library | Account |
|---|---|---|
| **Claude Code** (default) | `claude-agent-sdk` (official Python SDK, drives the Claude Code CLI) | The user's own Claude Code login: Pro/Max subscription |
| **API key** | `anthropic` (official Python SDK) | Anthropic Console account, billed per token (§ 5.2) |

- Preference `copilot.backend`: `claude_code` (default) or `api_key`, chosen in **Preferences → Copilot** (§ 10.1). There is no automatic choice: the backend in use is always the one the user sees in the preferences.
- No silent fallback: when the chosen backend is not available (Claude Code not installed or not logged in, no API key), the copilot is off for the run, and the Copilot panel says why, with a button opening the preferences. The pilot never switches to the paid API on its own.
- The Claude Code backend removes `ANTHROPIC_API_KEY` from the environment of the Claude Code process it starts, so that Claude Code uses the subscription login and not a key found in the environment.
- In a standalone script, the backend is `claude_code` unless the environment variable `GEMSEO_CLAUDE_PILOT_BACKEND` says `api_key` or `off` (no call, the scenario runs as is); the generated script never names it (§ 8).
- Claude Code is locked down (plan 59): none of its built-in tools (`tools=[]`), only the pilot's tools, served in process by an MCP server and pre-approved, any other tool refused (`permission_mode="dontAsk"`, `strict_mcp_config`), no user, project or local settings (`setting_sources=[]`), an empty working folder. Its check runs `claude auth status` and keeps only the login state and the kind of subscription.
- Before a run, the pilot checks its backend; when it cannot be used, the pilot says why and runs the scenario as is.
- Both implement the same `Backend` protocol (`backends/base.py`): send a conversation with tools, get back text, tool calls and token usage. The rest of the plugin does not know which backend it uses.
- **The plugin never handles an OAuth token or a claude.ai session.** With the Claude Code backend, authentication is entirely Claude Code's: the user logs in with `claude` in a terminal, once. The plugin only checks that it works (a status check in the preferences, and before a run).
- **Terms of use** (open point 3): Anthropic does not let third-party products offer claude.ai login or use subscription limits on their users' behalf without approval. The Claude Code backend is therefore documented as a way for users to run *their own* installed Claude Code; the application does not bundle, install or log in to Claude Code, and the docs send users to Anthropic's terms. This must be confirmed before the backend is released; if it is not allowed, the Claude Code backend is dropped and only the API key remains.
- With a subscription, the plan's usage limits apply: a rate-limit answer is treated as a temporary failure (§ 5.3).

### 5.2 API key

Resolved in the runner and the copilot process, in this order:

1. environment variable `ANTHROPIC_API_KEY`;
2. OS keyring (`keyring` package), service `gemseo-claude-pilot`, user `anthropic-api-key`.

- The Preferences dialog writes and deletes the key in the keyring (the UI process imports `keyring` only; no network). The field shows whether a key is set, never its value.
- The key never appears in the project, the run folder, the journal, the logs, the generated script or a runner event.

### 5.3 Failures

- API key backend: each request has a timeout (default 90 s) and at most 2 retries with backoff on network errors, 429 and 5xx (the SDK's own). Claude Code backend: a whole conversation has a timeout (default 180 s); Claude Code retries by itself.
- A backend that cannot be used (Claude Code missing, no API key) turns the pilot off at once, like a refused login.
- After 3 consecutive failed calls, the pilot turns itself off for the rest of the run, emits a `copilot.status { state: "disabled", reason }` event and the run goes on with its current settings.
- An authentication failure turns the pilot off at once, with a message saying which backend and what to do.

### 5.4 Models and budget

- Two model roles, each a preference and a driver setting, chosen in a list: Claude Opus 5.5 (`claude-opus-5-5`), Claude Sonnet 5.5 (`claude-sonnet-5-5`), Claude Sonnet 5 (`claude-sonnet-5`), Claude Haiku 4.5 (`claude-haiku-4-5`), Claude Opus 5 (`claude-opus-5`), Claude Fable 5.1 (`claude-fable-5-1`); a model saved before and missing from the list stays offered:
  - **watch model**, for periodic calls: default `claude-opus-5-5`;
  - **decision model**, for events, questions, the pre-run review and the report: default `claude-opus-5-5`.
- **Effort** of every call, a preference (`low`, `medium`, `high`, `xhigh`, `max`; default `low`), passed to the runner in `GEMSEO_CLAUDE_PILOT_EFFORT`: the API key backend sends it as `output_config.effort`, the Claude Code backend as the effort of the conversation; not sent to Claude Haiku 4.5, which takes none. At a low effort, Claude Opus 5.5 answers in seconds to a minute: the run is followed closely. In the first piloted run of the bracket, Claude Sonnet 5 at its default effort took more than the 3 minutes a call may last with Claude Code, twice.
- **Budget per run**: maximum number of calls (default 30) and maximum number of tokens, input + output (default 1,000,000). With the API key backend, an optional maximum cost in USD, estimated from a price table in the plugin (`pricing.py`, to be kept up to date; the estimate is labelled as such).
- **Usage counter** in the Copilot panel: calls, input/output/cached tokens, and with the API key backend the estimated cost. With Claude Code, cost is not shown (the subscription is not billed per token).
- **Prompt caching** (API key backend): the system prompt and the problem description are marked cacheable, since they are identical in every call of a run.

---

## 6. Dialogue with Claude

### 6.1 Context of a call

Built by `context.py`, then filtered by the data level (§ 7):

- **Problem**: formulation, design variables (name, size, bounds, current value, type), objective(s) and direction, constraints (type, threshold), observables, algorithm and settings, evaluation budget and what remains, derivatives origin (SPEC § 9.3).
- **Run state**: iteration count, elapsed time, time per evaluation, best feasible point and its objective, least violated point, current segment.
- **History, compressed**: the last 20 iterations in full (objective, maximum violation per constraint, step norm, gradient norm when available); earlier iterations as statistics per window of 20.
- **Large design spaces** (thousands of variables and more, as in plan 56): never the full vectors. Instead, per variable group: size, share at a bound, mean normalized step, and the 20 most important components ranked as in the Results filter bar (SPEC § 12.2).
- **Detector events** since the last call.
- **Design** (§ 4.8), when the model describes its physics: the physical problem, and the maps and indicators of the design when the run is stuck, at the review and for the report.
- **Decisions already taken** and what followed each (§ 4.5).
- **Chat question**, when the trigger is a question.

The target size of a context is about 8,000 tokens; beyond it, the history windows are merged further.

### 6.2 Answers

- With the API key backend: Messages API with tools; the decision is a call of the tool `submit_decision` whose input schema is the decision model (§ 4.5).
- With the Claude Code backend: the same tools, exposed through an **in-process MCP server** of the Agent SDK. **Claude Code's built-in tools are all disabled** (no shell, no file access, no web), and user and project settings of Claude Code are not loaded: Claude can only call the pilot's tools.
- Chat questions get a free-text answer, with an optional decision when the user asks for one ("should I tighten the bounds?").

### 6.3 Tools Claude may call

Read-only tools, answered by the pilot from the problem and its database, each counted in the call budget's tokens:

| Tool | Returns |
|---|---|
| `get_iterations(first, last, variables?)` | Iterations in a range, optionally with some design variables |
| `get_variable(name, components?)` | Bounds, history and gradient of one design variable (or some components) |
| `get_constraint(name)` | History of a constraint, active/violated state at the best point |
| `list_algorithms()` | Algorithms installed and compatible with the problem, with their family (as in the algorithm guide, SPEC § 6.4) |
| `get_algorithm_settings(name)` | JSON schema of an algorithm's settings |
| `get_component(name)` | Inputs, outputs, and source code (only at the `full` data level) |
| `get_design_view(field, point?)`, `get_design_indicators(point?)`, `list_design_transforms()` | The design read physically (§ 4.8): a map, the indicators, the transformations of a restart; only when the model describes its physics |
| `submit_decision(decision)` | Ends the call with a decision |

At most 8 tool calls per exchange.

---

## 7. Data sent and consent

### 7.1 Data levels

A project setting (in the Copilot section of the project, default `no_code`):

| Level | Sent |
|---|---|
| **full** | Names, values, history, descriptions and source code of the components |
| **no_code** | Names, values and history; never source code or file contents |
| **anonymized** | Design variables, objective, inequality and equality constraints and observables renamed `x1…`, `f1`, `g1…`, `h1…`, `o1…`; design values normalized to [0, 1] by the bounds the user set; the objective and each constraint divided by a fixed positive scale (their first nonzero magnitude), which keeps the sign of constraints; no tolerances, no component names, no descriptions, no code; past decisions only by their kind |

- In `anonymized`, the mapping stays in the runner: decisions come back with anonymous names and are translated before validation. The journal stores what was actually sent.
- The Copilot tab shows, for the chosen level, an example of the context that would be sent for this driver (built in the copilot process, no call made).

### 7.2 Consent

- The first time the copilot is enabled, a dialog explains what is sent, to whom (Anthropic, through the chosen backend), and that Anthropic's terms and privacy policy apply. The acceptance is stored in the application preferences as the most open data level accepted (plan 61: a project is a script, which has no place for it; a script written by hand with `ClaudePilot` is the user's own choice).
- Enabling the copilot, or changing the data level, to a level more open than the one accepted asks again.

---

## 8. Generated scripts

A driver with the copilot enabled generates its `execute_scenario` with an explicit pilot. This is an **allowed exception** to "no instrumentation in generated code" (SPEC § 10.2): the copilot is a feature the user turned on, and the script must behave the same outside the application (principle 1 of SPEC § 1.2).

```python
from gemseo_claude_pilot import Budget, ClaudePilot


def execute_scenario(scenario: MDOScenario) -> None:
    """Run the SLSQP optimizer for at most 100 iterations, with Claude adjusting it."""
    # Claude watches the convergence and may change the algorithm settings, switch
    # algorithm or stop the run; it never widens the bounds nor spends more
    # evaluations than the budget of the optimizer.
    pilot = ClaudePilot(
        mode="pilot",
        allowed_actions=["change_settings", "switch_algorithm", "stop"],
        budget=Budget(max_calls=10),
    )
    pilot.execute(scenario, algo_name="SLSQP", max_iter=100)
```

(`tests/python/codegen/golden/sellar_mdf_piloted.py`.)

- Only settings that differ from the pilot's defaults (Advisor mode, every action, `no_code`, 30 calls) are written (SPEC § 10.2); the comment says what Claude may do with the actions allowed.
- No key, no backend secret, no model id unless the user changed it.
- The script depends on `gemseo_claude_pilot` only when the copilot is enabled; codegen tests check that a script without copilot does not import it.
- Run outside the application, the pilot writes its journal next to the script (`<script>.pilot/journal.jsonl`) and logs its decisions with the `logging` module.
- Reading back (SPEC § 4.2.1, § 4.2.2): a `ClaudePilot(...)` / `pilot.execute(...)` pair in `execute_scenario` is read as the driver's copilot settings.

---

## 9. Journal and report

### 9.1 Journal

In the run folder (SPEC § 12.1):

```
runs/<run_id>/
  copilot/
    journal.jsonl     # one line per record, below
    report.md         # post-run analysis (§ 9.2)
```

Records: `call` (trigger, backend, model, context sent, token usage, duration), `answer` (raw text and tool calls), `decision` (validated or rejected, and why; `live` when applied to a running large-scale optimizer, § 4.7), `user` (accepted/rejected in Advisor mode, mode changes, chat questions), `segment` (§ 4.4), `algorithm` (the report of an outer iteration of the large-scale optimizer, § 4.7), `design` (the maps and indicators sent, § 4.8), `restart` (a restart applied, with the design before and after, § 4.8), `status` (disabled, budget spent, errors).

The journal is written as the run goes, flushed after each record, and kept when the run is stopped or fails.

### 9.2 Post-run report

At the end of the run (trigger `report`, after the end call), Claude writes a short analysis in Markdown: what happened, the segments and why, the final result and how much to trust it (active constraints, bounds reached, surrogate quality), and what to try next. It is written to `copilot/report.md`, published as a `copilot.message` of kind `report`, shown in the Copilot view and offered in the report of the application (SPEC § 13). Claude only reads for it (no `submit_decision`). When the model describes its design (§ 4.8), the pilot appends the density map of the final design and, for each restart, the maps before and after it. No report once the budget is spent, or with `ClaudePilot(report=False)`.

---

## 10. Integration in GEMSEO Process Builder

### 10.1 User interface

- **Preferences → Copilot**: the backend, as two choices, *Claude Code (subscription)*, selected by default, and *API key*, each with a *Check* button and its result (Claude Code installed and logged in; key present and accepted); the API key field (keyring), shown with the *API key* choice; watch and decision models; default budget; default mode; default data level. The choice is stored in the application preferences and passed to the runner and the copilot process through `GEMSEO_CLAUDE_PILOT_BACKEND`.
- **Driver editor → Copilot tab** (an optimization or a DOE run on its own; the actions offered depend on the driver: *Add samples* and *Stop* for a DOE, *Change a sub-optimization* too for a BiLevel system): the state of the backend with a link to the preferences; enable; mode; allowed actions; data level with what it sends; calls per run. *Review with Claude*: a review of the problem before its run, by the copilot process from the generated script (trigger `start` with a review question, read tools only), shown in the tab. The triggers keep their defaults; the preview of the data sent is not done.
- **Results of a run → Copilot view**, shown for a piloted run: state and reason, usage (with the estimated cost only with an API key), the mode, changeable while the run goes on; the timeline of diagnoses, answers, decisions and proposals, each with what it does and its rationale; *Accept* / *Reject* on the open proposal while the run goes on, and how each proposal ended; for the large-scale optimizer, a chart of the working set and of the rows computed per outer iteration; the segments. It reads the live events during the run, then the journal (`copilot.journal`) and the summary of `run.json`. The start of each segment after the first is marked on the History charts. A question box: asked while the run goes on, the question goes to the pilot (`copilot.ask` command), answered at the next iteration boundary or between segments, the answer published with its question; asked after the run, the copilot process answers from `history.h5` and the journal, and records the question and the answer in the journal.
- **Copilot process** (plan 62): `python -m gemseo_claude_pilot.session`, one JSON request on its input (`ask` or `review`), one JSON answer on its output; started by the UI process (`copilot.ask`, `copilot.review`, in a background thread) with the interpreter and the environment of the runs, never importing GEMSEO or reaching the network itself.

### 10.2 Runner protocol additions

New events on the event channel (SPEC § 11.2), published by the pilot through `gemseo_claude_pilot.events` and forwarded by the runner:

- `copilot.status { state: "watching"|"thinking"|"waiting"|"disabled"|"off", mode?, reason?, proposal? }`;
- `copilot.message { kind: "diagnosis"|"answer"|"decision"|"proposal"|"closed", text?, id?, decision?, how?, evaluation? }`: a proposal has an `id`; `closed` tells how it ended (`accepted`, `rejected`, `replaced`, `expired`, `unanswered`, `run ended`);
- `copilot.usage { calls, input_tokens, output_tokens, cached_tokens, cost_usd }`;
- `copilot.segment { index, algo_name, settings, first_evaluation, reason }`;
- `copilot.summary { stop_reason, segments, decisions, best_evaluation, evaluations, disabled, usage, calls }`, also in the summary of `finished`;
- `copilot.algorithm { iteration, evaluation, working_set, rows_computed, rows_reused, screening_repairs, inner_iterations, kkt_residual, method, … }`: the report of an outer iteration of `LSO_MMA` or `LSO_GCMMA` (§ 4.7), charted in the Copilot view.

New commands on `stdin`, as `{ command, params }`: `copilot.accept { id }`, `copilot.reject { id }`, `copilot.mode { mode }` (plan 60), `copilot.ask { text }` (plan 62). The runner also passes `stop` to the pilot, which ends a wait for the user's answer.

`copilot.status` and `copilot.usage` go through the rate limit of SPEC § 11.3, keeping the latest; the other events are sent at once, never aggregated.

In Advisor mode, a proposal made while a segment runs is applied at the next iteration boundary once accepted; a proposal made when a segment ends by itself makes the pilot wait for the answer (120 s by default), then the run ends. The Advisor mode needs a listener: in a plain script, it falls back to Observer.

### 10.3 Changes to SPEC.md

Made in plan 60:

- § 1.2, principle 4: the application works fully offline; the copilot is the only feature that uses the network, it is opt-in, and only the runner and the copilot process reach the network; the web view never does.
- § 10.1 and § 10.2: the copilot exception (§ 8 above).
- § 11.2: the events and commands of § 10.2.
- § 12.1: the `copilot/` folder of a run.
- § 13: the post-run analysis section of the report.
- § 14.6: the new dependencies (§ 11).

---

## 11. Dependencies and licenses

| Component | License | Use | Note |
|---|---|---|---|
| `claude-agent-sdk` | MIT | Imported dependency | Claude Code backend, the default; does not bundle the Claude Code CLI |
| `mcp` | MIT | Imported dependency (through `claude-agent-sdk`) | Kept below 2: mcp 2 needs Pydantic 2.12, GEMSEO 6.3 caps it at 2.11.9 |
| `anthropic` | MIT | Imported dependency | API key backend |
| Claude Code CLI | Anthropic's commercial terms | Installed and logged in by the user, never bundled or vendored | Open point 4 |
| `keyring` | MIT | Imported dependency | API key storage |
| `pydantic` | MIT | Imported dependency | Decisions, settings |

Each license is confirmed when the dependency is added and listed in `THIRD_PARTY_NOTICES.md` (SPEC § 14.6). Installation:

```
pip install "gemseo-claude-pilot @ git+https://github.com/jcdulas/GemseoProcessBuilder.git#subdirectory=plugins/gemseo_claude_pilot"
```

---

## 12. Tests

- **No network in tests.** Every test uses `backends/fake.py`, which replays scripted answers (text, tool calls, decisions, errors, delays) and records the requests it received.
- One second per test (SPEC § 15.1): pilot tests run on analytic problems (Rosenbrock, Sellar) with a few iterations per segment.
- Coverage:
  - detectors on synthetic histories (pure functions);
  - context builder: size limits, large design spaces, data levels (no name or code leaks in `anonymized`, no code in `no_code`);
  - guardrails: bounds, evaluation budget, incompatible algorithm, invalid settings, correction round trip;
  - segment loop: the database is kept, no point evaluated twice, budget respected, stop and end-of-segment interplay with the runner's stop;
  - failures: timeout, 429, auth error, 3 consecutive failures turn the pilot off, the run completes;
  - Advisor mode: accept, reject, expiry;
  - journal: records written and readable after a stopped run; no API key in any output;
  - codegen: the generated `execute_scenario` with a pilot passes the readability checks of SPEC § 10.2, and is read back into the same settings;
  - JS: pure logic of the Copilot panel (timeline, markers) in `static/js/lib/`, under `node --test`.
- A manual smoke test with a real backend is described in `docs/developer_guide.md`, never run by `tools/check.py`.

---

## 13. Proposed plans

Numbered after the existing plans; each ends with a working, tested application.

| # | Title | Content |
|---|---|---|
| 57 | Pilot package and fake backend | Package skeleton, `Backend` protocol, fake backend, decision models, guardrails, detectors, context builder with data levels |
| 58 | Segments and warm start | `ClaudePilot.execute`, segment loop on optimizations, prototype of open point 1, journal, Observer and Pilot modes in standalone scripts |
| 59 | Real backends | Claude Code backend, the default (Agent SDK, MCP tools, built-in tools disabled, `ANTHROPIC_API_KEY` removed), API key backend (keyring, retries, caching, usage), budget |
| 60 | Copilot in the runner | Runner events and commands, Advisor mode, codegen of piloted drivers and reading back, SPEC.md updates |
| 61 | Copilot in the interface | Preferences, Copilot tab, consent, Copilot panel, History markers, usage counter |
| 62 | Chat, review and report | Copilot process, pre-run review, chat during and after the run, post-run report and report section |
| 63 | DOE, BiLevel and surrogates | *Add samples* segments, BiLevel sub-scenario settings, surrogate quality in reviews and reports |

---

## 14. Open points and risks

| # | Topic | Action |
|---|---|---|
| 1 | GEMSEO 6: counting of `max_iter` and algorithm state over successive `execute` calls on one problem; setting the current value from the best point | Settled in plan 58 (§ 4.4) |
| 2 | BiLevel: where to change sub-scenario settings between system iterations without rebuilding the adapters | Settled in plan 63 (§ 4.6): `set_algorithm` on the sub-scenario, used by its adapter at the next system evaluation |
| 3 | Anthropic's terms for the Claude Code backend (subscription used through the user's own Claude Code, in an open-source tool) | Check the current terms before plan 59; drop the backend if not allowed |
| 4 | License and packaging of `claude-agent-sdk` (does it bundle the Claude Code CLI, under which terms?) | Settled in plan 59: MIT, and the wheel does not bundle the CLI, which the user installs; its dependencies are all permissive (`THIRD_PARTY_NOTICES.md`) |
| 5 | Latency: a decision may arrive many iterations after the state it was based on | Record the age of each decision; discard decisions older than the expiry of § 4.1 |
| 6 | Relevance of the decisions: an LLM may propose changes that do not help | Measure on the reference cases (Sellar, SSBJ, wing sizing) against unpiloted runs; publish the comparison in the docs |
| 7 | Name of the package (use of "Claude" in a third-party package name) | Check Anthropic's brand guidelines before the first release |
