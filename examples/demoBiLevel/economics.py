"""The economics of the aircraft, computed after its mission.

A chain of disciplines of every kind GEMSEO offers:

1. the fuel burnt, an analytic formula;
2. three evaluations that do not depend on each other, run in parallel:
   - the CO2 emissions, a Python function whose argument is renamed;
   - the noise, an external code;
   - the maintenance cost, a surrogate model (see maintenance.py);
3. the operating cost, a discipline class of its own.
"""

from pathlib import Path

from gemseo.core.chains.chain import MDOChain
from gemseo.core.chains.parallel_chain import MDOParallelChain
from gemseo.core.discipline import Discipline
from gemseo.disciplines.analytic import AnalyticDiscipline
from gemseo.disciplines.auto_py import AutoPyDiscipline
from gemseo.disciplines.remapping import RemappingDiscipline
from gemseo.typing import StrKeyMapping
from maintenance import maintenance_surrogate
from numpy import array, float64
from numpy.typing import NDArray

from gemseo_process_builder.runtime.executable import ExecutableDiscipline

NOISE_WRAPPER = Path(__file__).parent / "noise" / "noise.gpbwrap.json"
"""The description of the external code computing the noise."""

FUEL_BURN = array([250.0])
FLIGHT_RANGE = array([2000.0])


def emissions(
    fuel_burn: NDArray[float64] = FUEL_BURN,
    flight_range: NDArray[float64] = FLIGHT_RANGE,
) -> NDArray[float64]:
    """Compute the CO2 emitted over a flight, in tonnes."""
    co2 = 3.16e-3 * fuel_burn * flight_range / 1000.0
    return co2


class OperatingCost(Discipline):  # type: ignore[misc]  # GEMSEO is not typed.
    """The cost of a flight: fuel, carbon, maintenance and noise fees."""

    def __init__(self, fuel_price: float = 0.8, carbon_price: float = 90.0) -> None:
        """Create the discipline with its prices.

        Args:
            fuel_price: The price of the fuel, per unit burnt.
            carbon_price: The price of a tonne of CO2.

        """
        super().__init__(name="OperatingCost")
        self.io.input_grammar.update_from_names(
            ["fuel_burn", "co2", "maintenance", "noise_db"]
        )
        self.io.output_grammar.update_from_names(["cost"])
        self.default_input_data.update(
            {
                "fuel_burn": array([250.0]),
                "co2": array([1.5]),
                "maintenance": array([300.0]),
                "noise_db": array([90.0]),
            }
        )
        self.fuel_price = fuel_price
        self.carbon_price = carbon_price

    def _run(self, input_data: StrKeyMapping) -> StrKeyMapping:
        noise_fee = 2.0 * input_data["noise_db"]
        cost = (
            self.fuel_price * input_data["fuel_burn"]
            + self.carbon_price * input_data["co2"]
            + input_data["maintenance"]
            + noise_fee
        )
        return {"cost": cost}


def build_emissions() -> Discipline:
    """Create the CO2 emissions, the range of the aircraft (y_4) as flight_range."""
    discipline = AutoPyDiscipline(emissions)
    discipline.name = "Emissions"
    return RemappingDiscipline(
        discipline,
        input_mapping={"fuel_burn": "fuel_burn", "y_4": "flight_range"},
        output_mapping={"co2": "co2"},
    )


def build_economics() -> Discipline:
    """Create the chain computing the operating cost from the mission."""
    fuel_burn = AnalyticDiscipline({"fuel_burn": "1000*y_34/y_24"}, name="FuelBurn")
    noise = ExecutableDiscipline.from_descriptor(NOISE_WRAPPER)
    evaluations = MDOParallelChain(
        [build_emissions(), noise, maintenance_surrogate()], name="Evaluations"
    )
    return MDOChain([fuel_burn, evaluations, OperatingCost()], name="Economics")
