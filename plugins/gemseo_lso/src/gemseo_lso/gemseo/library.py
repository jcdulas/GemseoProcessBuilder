"""``LSO_MMA`` and ``LSO_GCMMA``: the optimizer as GEMSEO algorithms (spec § 6).

Example:
    >>> from gemseo import create_discipline, create_design_space, create_scenario
    >>> discipline = create_discipline(
    ...     "AnalyticDiscipline", expressions={"f": "x**2 + y**2", "g": "1 - x - y"})
    >>> space = create_design_space()
    >>> space.add_variable("x", lower_bound=0.0, upper_bound=2.0, value=1.5)
    >>> space.add_variable("y", lower_bound=0.0, upper_bound=2.0, value=1.5)
    >>> scenario = create_scenario([discipline], "f", space,
    ...     formulation_name="DisciplinaryOpt")
    >>> scenario.add_constraint("g", constraint_type="ineq")
    >>> _ = scenario.execute(algo_name="LSO_GCMMA", max_iter=100)
    >>> [round(float(v), 3) for v in scenario.optimization_result.x_opt]
    [0.5, 0.5]
"""

import logging
from dataclasses import dataclass
from dataclasses import replace
from typing import Any
from typing import ClassVar

from gemseo.algos.base_driver_library import BaseDriverLibrary
from gemseo.algos.opt.base_optimization_library import BaseOptimizationLibrary
from gemseo.algos.opt.base_optimization_library import OptimizationAlgorithmDescription
from gemseo.algos.optimization_problem import OptimizationProblem

from gemseo_lso.core.optimizer import Optimizer
from gemseo_lso.core.state import State
from gemseo_lso.gemseo.adapter import GemseoProblem
from gemseo_lso.gemseo.live import close_run
from gemseo_lso.gemseo.live import open_run
from gemseo_lso.gemseo.settings import BaseLSOSettings
from gemseo_lso.gemseo.settings import LSO_GCMMA_Settings
from gemseo_lso.gemseo.settings import LSO_MMA_Settings
from gemseo_lso.gemseo.settings import core_settings

LOGGER = logging.getLogger(__name__)

WEBSITE = (
    "https://github.com/jcdulas/GemseoProcessBuilder/blob/main/docs/"
    "LARGE_SCALE_OPTIMIZER_SPEC.md"
)

STATUSES = {
    "converged": 0,
    "stalled": 1,
    "max_iter": 2,
    "ftol": 3,
    "xtol": 4,
    "stopped": 5,
    "running": 6,
    "max_rows": 7,
}
"""The status of the result, from the status of the core."""


@dataclass
class LSOAlgorithmDescription(OptimizationAlgorithmDescription):  # type: ignore[misc]
    """The description of an LSO algorithm."""

    library_name: str = "gemseo-lso"
    Settings: type[BaseLSOSettings] = BaseLSOSettings


class LargeScaleOptimization(BaseOptimizationLibrary[BaseLSOSettings]):  # type: ignore[misc]
    """MMA and GCMMA with a working set of constraints, for large problems."""

    ALGORITHM_INFOS: ClassVar[dict[str, OptimizationAlgorithmDescription]] = {
        "LSO_MMA": LSOAlgorithmDescription(
            algorithm_name="LSO_MMA",
            internal_algorithm_name="mma",
            description=(
                "Method of Moving Asymptotes for 10^5 to 10^6 variables and "
                "constraints: the gradients of the constraints close to activity "
                "only; switches to GCMMA when it cycles"
            ),
            handle_equality_constraints=True,
            handle_inequality_constraints=True,
            require_gradient=True,
            website=WEBSITE,
            Settings=LSO_MMA_Settings,
        ),
        "LSO_GCMMA": LSOAlgorithmDescription(
            algorithm_name="LSO_GCMMA",
            internal_algorithm_name="gcmma",
            description=(
                "Globally convergent MMA for 10^5 to 10^6 variables and "
                "constraints: the gradients of the constraints close to activity "
                "only"
            ),
            handle_equality_constraints=True,
            handle_inequality_constraints=True,
            require_gradient=True,
            website=WEBSITE,
            Settings=LSO_GCMMA_Settings,
        ),
    }

    def _pre_run(self, problem: OptimizationProblem) -> None:
        # GEMSEO evaluates every Jacobian at the starting point for the
        # algorithms requiring gradients: 10^10 entries for 10^5 variables and
        # constraints. The optimizer asks for the rows it needs itself.
        description = self.ALGORITHM_INFOS[self._algo_name]
        self.ALGORITHM_INFOS = {  # type: ignore[misc]
            **type(self).ALGORITHM_INFOS,
            self._algo_name: replace(description, require_gradient=False),
        }
        try:
            super()._pre_run(problem)
        finally:
            del self.ALGORITHM_INFOS

    def _check_stopping_criteria(self) -> None:
        # GEMSEO compares the objective and the point of its last evaluations
        # (ftol, xtol): GCMMA's inner iterations and the repairs evaluate points
        # close to each other, taken for a stagnation (a piloted bracket
        # stopped after 13 of its 160 iterations). The optimizer applies these
        # tolerances at its outer iterations, at feasible points; GEMSEO keeps
        # max_iter and max_time.
        BaseDriverLibrary._check_stopping_criteria(self)

    def _run(self, problem: OptimizationProblem) -> tuple[str, Any]:
        settings = self._settings
        method = self.ALGORITHM_INFOS[self._algo_name].internal_algorithm_name
        adapted = GemseoProblem(problem, settings)
        restore = adapted.detach_row_outputs()
        state = State.load(settings.resume_from) if settings.resume_from else None
        optimizer = Optimizer(adapted, core_settings(settings, method), state)
        if state is not None:
            # A resumed run goes on, even if it had ended: GEMSEO's criteria
            # stop it (the budget of the new execution).
            state.status, state.message = "running", ""
        live = open_run(
            problem,
            self._algo_name,
            optimizer.settings,
            adapted.constraint_slices,
            adapted.offsets,
            adapted.optimizer_point,
        )
        try:
            while not optimizer.finished:
                live.apply(optimizer)
                if optimizer.finished:
                    break
                report = optimizer.step()
                live.publish(report)
                LOGGER.info(
                    "Iteration %d (%s): objective %.6g, max constraint %.2e, "
                    "KKT %.2e, working set %d, rows %d, directional derivatives %d",
                    report.iteration,
                    report.method,
                    report.objective,
                    report.max_constraint,
                    report.kkt_residual,
                    report.working_set,
                    report.rows_computed,
                    report.directional_derivatives,
                )
        finally:
            close_run(problem)
            restore()
            if settings.save_state:
                optimizer.state.save(settings.save_state)
        result = optimizer.result
        message = (
            f"{result.message} {adapted.rows_given} constraint gradients and "
            f"{result.directional_derivatives} directional derivatives asked for."
        )
        return message, STATUSES[result.status]
