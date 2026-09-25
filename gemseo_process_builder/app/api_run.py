"""Runs for the page: ``run.*`` methods."""

from typing import Any

from pydantic import BaseModel

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import ErrorCode
from gemseo_process_builder.app.run_manager import RunError
from gemseo_process_builder.app.run_manager import RunManager
from gemseo_process_builder.app.validation_service import dry_run_targets


class StartParams(BaseModel):
    """Parameters of ``run.start``."""

    target: str | None = None
    """The driver (or the model) to run; the first top-level driver by default."""


class StopParams(BaseModel):
    """Parameters of ``run.stop``."""

    run_id: str | None = None
    """The run to stop; every active run by default."""


def register_run_methods(bridge: Bridge, runs: RunManager) -> None:
    """Register ``run.start``, ``run.stop`` and ``run.state``."""

    def start(params: StartParams) -> dict[str, Any]:
        target = params.target or dry_run_targets(runs.session.project)[0].id
        try:
            return runs.start(target).to_dict()
        except RunError as error:
            raise BridgeError(ErrorCode.CONFLICT, str(error)) from None

    def stop(params: StopParams) -> None:
        run_ids = [params.run_id] if params.run_id else [r.id for r in runs.active()]
        for run_id in run_ids:
            runs.stop(run_id)

    def state() -> dict[str, Any]:
        return {"runs": [run.to_dict() for run in runs.runs.values()]}

    bridge.registry.add("run.start", start)
    bridge.registry.add("run.stop", stop)
    bridge.registry.add("run.state", state)
