"""Training, saving and using surrogates from the page (worker run in-process)."""

import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from builders import component
from builders import project
from doe_runs import rosenbrock_run

from gemseo_process_builder.app.api_surrogates import AddParams
from gemseo_process_builder.app.api_surrogates import IdParams
from gemseo_process_builder.app.api_surrogates import RunParams
from gemseo_process_builder.app.api_surrogates import SaveParams
from gemseo_process_builder.app.api_surrogates import SurrogateController
from gemseo_process_builder.app.api_surrogates import TrainParams
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.results.models import read_info
from gemseo_process_builder.results.store import RunStore
from gemseo_process_builder.results.surrogates import read_metadata
from gemseo_process_builder.workers import surrogate_methods
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel


class InProcessWorker:
    """Runs the surrogate methods of the worker in the test process."""

    def run(self, method: str, params: dict[str, Any]) -> Any:
        if method == "surrogate.variables":
            return surrogate_methods.variables(params["folder"])
        return surrogate_methods.train(
            params["folder"],
            params["inputs"],
            params["outputs"],
            params["algorithm"],
            params["settings"],
            params["n_folds"],
            params["model_file"],
        )

    def call(self, method: str, params: dict[str, Any], timeout: float) -> Any:
        return self.run(method, params)

    def request(
        self,
        method: str,
        params: dict[str, Any],
        callback: Callable[[dict[str, Any]], None],
        timeout: float,
    ) -> str:
        callback({"ok": True, "result": self.run(method, params)})
        return "request-1"


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


@pytest.fixture
def controller(tmp_path: Path) -> SurrogateController:
    session = ProjectSession(tmp_path / "untitled.gpb.json.autosave")
    session.project = project(component("Surrogate", kind="surrogate"))
    session.save(tmp_path / "Rosen.py")
    runs = RunStore(session)
    folder = rosenbrock_run(runs.folder())
    info = read_info(folder)
    assert info is not None
    runs.add(info, folder)
    worker: Any = InProcessWorker()
    return SurrogateController(session, runs, Bridge(MethodRegistry()), worker)


def train_and_save(
    controller: SurrogateController, algorithm: str = "RBFRegressor", **save: Any
) -> dict[str, Any]:
    result = controller.train(
        TrainParams(
            run="r-doe",
            inputs=["x", "y"],
            outputs=["f"],
            algorithm=algorithm,
            n_folds=3,
        )
    )
    return controller.save(
        SaveParams(
            trained=result["trained"],
            name=save.pop("name", "Rosenbrock"),
            run="r-doe",
            algorithm=algorithm,
            result=result,
            **save,
        )
    )


def test_variables(controller: SurrogateController) -> None:
    found = controller.variables(RunParams(run="r-doe"))
    assert [item["name"] for item in found["inputs"]] == ["x", "y"]
    with pytest.raises(BridgeError, match="not available"):
        controller.variables(RunParams(run="r-none"))


def test_train_save_and_use_in_a_component(controller: SurrogateController) -> None:
    saved = train_and_save(controller, node="n-Surrogate")
    node = controller.session.project.find("n-Surrogate")
    assert node.config["surrogate_id"] == saved["id"]
    assert node.config["model_path"] == saved["model_path"]
    assert node.config["summary"].startswith("RBFRegressor trained on 30 samples")
    assert [(p.local_name, p.direction) for p in node.ports] == [
        ("x", "in"),
        ("y", "in"),
        ("f", "out"),
    ]
    assert not (controller.store.folder() / ".training").exists()
    # One undo step restores the component.
    controller.session.document.undo()
    assert controller.session.project.find("n-Surrogate").config == {}


def test_retraining_updates_the_components(controller: SurrogateController) -> None:
    first = train_and_save(controller, node="n-Surrogate")
    second = train_and_save(
        controller, "PolynomialRegressor", name="Rosenbrock poly", replace=first["id"]
    )
    assert second["id"] == first["id"]
    node = controller.session.project.find("n-Surrogate")
    assert node.config["summary"].startswith("PolynomialRegressor")
    assert Path(node.config["model_path"]).name == "Rosenbrock_poly.pkl"
    (entry,) = controller.entries()
    assert entry["name"] == "Rosenbrock poly"


def test_add_and_delete(controller: SurrogateController) -> None:
    saved = train_and_save(controller)
    node_id = controller.add(AddParams(parent="n-root", id=saved["id"]))
    node = controller.session.project.find(node_id)
    assert (node.name, node.kind) == ("Rosenbrock", "surrogate")
    assert [p.local_name for p in node.ports] == ["x", "y", "f"]
    controller.delete(IdParams(id=saved["id"]))
    assert controller.entries() == []


def test_deleting_the_run_keeps_the_surrogate(controller: SurrogateController) -> None:
    saved = train_and_save(controller)
    controller.runs.delete("r-doe")
    metadata = read_metadata(Path(saved["model_path"]))
    assert metadata is not None
    assert metadata.source.deleted
    assert Path(saved["model_path"]).is_file()


def test_only_trained_models_are_saved(
    controller: SurrogateController, tmp_path: Path
) -> None:
    other = tmp_path / "other.pkl"
    other.write_bytes(b"")
    with pytest.raises(BridgeError, match="Only a model trained"):
        controller.save(
            SaveParams(
                trained=str(other), name="A", run="r-doe", algorithm="X", result={}
            )
        )
