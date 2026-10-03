import logging

import numpy as np
import pytest
from gemseo import create_design_space
from gemseo import create_scenario
from lso_disciplines import RowsLocal

from gemseo_lso.benchmarks.synthetic import LocalConstraints
from gemseo_lso.gemseo.live import LiveRun
from gemseo_lso.gemseo.live import live_run

logging.getLogger("gemseo").setLevel(logging.WARNING)
logging.getLogger("gemseo_lso").setLevel(logging.WARNING)

SIZE = 60


def scenario(start=0.5):
    discipline = RowsLocal(LocalConstraints(SIZE, active_share=0.05, seed=1))
    space = create_design_space()
    space.add_variable("x", size=SIZE, lower_bound=0.0, upper_bound=1.0, value=start)
    study = create_scenario(
        [discipline], "f", space, formulation_name="DisciplinaryOpt"
    )
    study.add_constraint("g", "ineq")
    return study


def piloted(study, act):
    """Run ``act(run, report)`` after each outer iteration, as a pilot would."""
    problem = study.formulation.optimization_problem
    runs: list[LiveRun] = []

    def attach(_):
        run = live_run(problem)
        if run is not None and not runs:
            runs.append(run)
            run.watch(lambda report: act(run, report))

    problem.database.add_new_iter_listener(attach)
    return runs


def test_a_setting_changed_live_applies_at_the_next_iteration():
    study = scenario()
    seen = []

    def act(run, report):
        seen.append((report.iteration, run.settings["screening_margin"]))
        if report.iteration == 2:
            run.change({"screening_margin": 0.1, "screening_margin_min": 0.02})

    runs = piloted(study, act)
    study.execute(algo_name="LSO_MMA", max_iter=8)  # A few iterations are enough.
    assert seen[:4] == [(1, 0.3), (2, 0.3), (3, 0.1), (4, 0.1)]
    assert len(runs[0].reports) == len(seen)
    assert live_run(study.formulation.optimization_problem) is None  # Closed.


def test_settings_that_cannot_change_live_are_refused():
    study = scenario()
    errors = []

    def act(run, report):
        if report.iteration == 1:
            for change in (
                {"max_iter": 5},
                {"move_limit": 2.0},
                {"jacobian_mode": "hybrid"},
            ):
                with pytest.raises(ValueError) as error:
                    run.change(change)
                errors.append(str(error.value))
            run.stop("enough")

    piloted(study, act)
    study.execute(algo_name="LSO_MMA", max_iter=200)
    assert "cannot change during a run: max_iter" in errors[0]
    assert "move_limit" in errors[1]
    assert "jacobian_mode" in errors[2]
    assert "enough" in study.optimization_result.message


def test_mma_switches_to_gcmma_live():
    study = scenario()
    methods = []

    def act(run, report):
        methods.append(report.method)
        if report.iteration == 2:
            run.switch("gcmma")

    piloted(study, act)
    study.execute(algo_name="LSO_MMA", max_iter=200)
    assert methods[:4] == ["mma", "mma", "gcmma", "gcmma"]
    assert study.optimization_result.is_feasible


def test_a_stopped_run_resumes_where_it_stopped(tmp_path):
    straight = scenario()
    straight.execute(algo_name="LSO_GCMMA", max_iter=200)
    path = tmp_path / "state.h5"

    first = scenario()
    piloted(first, lambda run, report: report.iteration == 4 and run.stop("later"))
    first.execute(algo_name="LSO_GCMMA", max_iter=200, save_state=str(path))
    assert "later" in first.optimization_result.message

    resumed = scenario()
    resumed.execute(algo_name="LSO_GCMMA", max_iter=200, resume_from=str(path))
    expected = straight.optimization_result.x_opt
    assert resumed.optimization_result.x_opt == pytest.approx(expected, abs=1e-12)
    assert np.array_equal(resumed.optimization_result.x_opt, expected)


def test_the_multipliers_and_the_stationarity_of_the_last_iteration():
    study = scenario()
    seen = []

    def act(run, report):
        seen.append((report.kkt_residual, run.multipliers(), run.stationarity()))
        if report.iteration == 3:
            run.stop()

    piloted(study, act)
    study.execute(algo_name="LSO_MMA", max_iter=200)
    kkt, multipliers, stationarity = seen[-1]
    (name,) = multipliers
    assert "g" in name
    assert multipliers[name].shape == (SIZE,)
    assert (multipliers[name] >= 0).all() and multipliers[name].max() > 0
    assert stationarity["x"].shape == (SIZE,)
    # The residual is the largest stationarity relative to a scale.
    assert np.abs(stationarity["x"]).max() > 0 or kkt == 0


def test_feasibility_is_restored_on_request():
    study = scenario(start=0.0)  # Infeasible at its first iterations.
    asked: list[int] = []
    reports = []

    def act(run, report):
        reports.append(report)
        if report.max_constraint > 1e-3 and not asked:
            asked.append(report.iteration)
            run.restore_feasibility()

    piloted(study, act)
    study.execute(algo_name="LSO_MMA", max_iter=10)
    assert asked  # The run is infeasible at some iteration.
    after = next(report for report in reports if report.iteration == asked[0] + 1)
    assert after.restoration >= 1
    # Without the request, the run would have gone on unrestored at this point.
    assert reports[asked[0] - 1].restoration == 0


def test_a_pilot_learns_of_a_run_when_it_opens():
    from gemseo_lso.gemseo.live import forget
    from gemseo_lso.gemseo.live import on_open

    study = scenario()
    problem = study.formulation.optimization_problem
    opened: list[LiveRun] = []
    first: list[int] = []

    def follow(run):
        opened.append(run)
        run.watch(lambda report: first.append(report.iteration))

    on_open(problem, follow)
    study.execute(algo_name="LSO_MMA", max_iter=6)
    forget(problem)
    assert len(opened) == 1
    assert first[0] == 1  # Before any point is announced: no report is missed.


def test_a_stop_can_wait_for_the_iterate_to_be_feasible():
    results = {}
    for when_feasible in (False, True):
        study = scenario(start=0.0)  # Infeasible at its first iteration.
        reports = []

        def act(run, report, when_feasible=when_feasible, reports=reports):
            reports.append(report)
            if report.iteration == 1:
                run.stop("done", when_feasible=when_feasible)

        piloted(study, act)
        study.execute(algo_name="LSO_MMA", max_iter=40)
        results[when_feasible] = reports
    assert len(results[False]) == 1  # Stopped at once, outside the constraints.
    assert results[False][-1].max_constraint > 1e-3
    waiting = results[True]
    assert len(waiting) > 1
    assert waiting[-1].max_constraint <= 1e-3  # Ends on a feasible point.
    assert waiting[-1].status == "stopped"


def test_constraints_relaxed_live_are_reported_then_brought_back():
    study = scenario()
    seen = []

    def act(run, report):
        seen.append((report.iteration, report.relaxed))
        if report.iteration == 2:
            run.relax({"g": [0, 1, 5]}, 0.2)
        if report.iteration == 4:
            assert run.relaxation()["g"][[0, 1, 5]] == pytest.approx(0.2)
            run.tighten(0.0)

    piloted(study, act)
    study.execute(algo_name="LSO_MMA", max_iter=10)
    relaxed = dict(seen)
    assert relaxed[2] == 0  # Asked for after the iteration.
    assert relaxed[3] == 3
    assert relaxed[4] == 3
    assert relaxed[5] == 0  # Brought back at the next one.


def test_the_relaxation_asked_for_live_is_checked():
    study = scenario()
    errors = []

    def act(run, report):
        if report.iteration == 1:
            for call in (
                lambda: run.relax({"nothing": [0]}, 0.1),
                lambda: run.relax({"g": [SIZE]}, 0.1),
                lambda: run.relax({"g": [0]}, -0.1),
                lambda: run.tighten(1.5),
            ):
                with pytest.raises(ValueError) as error:
                    call()
                errors.append(str(error.value))

    piloted(study, act)
    study.execute(algo_name="LSO_MMA", max_iter=3)
    assert len(errors) == 4
    assert "Unknown constraint nothing" in errors[0]
    assert "numbered 0 to 59" in errors[1]
