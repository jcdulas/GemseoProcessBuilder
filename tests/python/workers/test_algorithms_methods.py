import io
import json

import pytest

from gemseo_process_builder.app.bridge import dumps
from gemseo_process_builder.workers.algorithms_methods import UnknownAlgorithmError
from gemseo_process_builder.workers.algorithms_methods import describe
from gemseo_process_builder.workers.algorithms_methods import settings_schema
from gemseo_process_builder.workers.algorithms_methods import validate_settings
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


def test_optimization_capabilities() -> None:
    algorithms = {item["name"]: item for item in describe("optimization")}
    slsqp = algorithms["SLSQP"]["capabilities"]
    assert slsqp["handle_inequality_constraints"]
    assert slsqp["handle_equality_constraints"]
    assert slsqp["require_gradient"]
    assert not slsqp["handle_multiobjective"]
    nelder_mead = algorithms["NELDER-MEAD"]["capabilities"]
    assert not nelder_mead["handle_inequality_constraints"]
    assert not nelder_mead["require_gradient"]
    assert algorithms["SLSQP"]["library"] == "SciPy Local"


def test_doe_mda_and_formulation_lists() -> None:
    assert "LHS" in [item["name"] for item in describe("doe")]
    mdas = [item["name"] for item in describe("mda")]
    assert "MDAChain" in mdas
    assert "MDASequential" not in mdas
    formulations = [item["name"] for item in describe("formulation")]
    assert {"MDF", "IDF", "DisciplinaryOpt"} <= set(formulations)


def test_schemas_leave_out_what_json_cannot_hold() -> None:
    schema = settings_schema("mda", "MDAChain")
    assert "coupling_structure" not in schema["properties"]
    assert schema["properties"]["tolerance"]["default"] == 1e-6
    assert settings_schema("doe", "LHS")["required"] == ["n_samples"]
    # Infinite defaults become null for the page.
    assert json.loads(dumps(settings_schema("optimization", "SLSQP")))


def test_validate_settings() -> None:
    assert validate_settings("optimization", "SLSQP", {"max_iter": 10}) == []
    errors = validate_settings("optimization", "SLSQP", {"max_iter": "x", "foo": 1})
    assert [error["field"] for error in errors] == ["max_iter", "foo"]


def test_unknown_algorithm() -> None:
    with pytest.raises(UnknownAlgorithmError, match="No doe algorithm named NOPE"):
        settings_schema("doe", "NOPE")
