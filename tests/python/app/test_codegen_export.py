from pathlib import Path
from typing import Any

import pytest
from golden_projects import analytic_chain

from gemseo_process_builder.app.api_codegen import CodegenController
from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import BridgeError
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.bridge import invoke
from gemseo_process_builder.app.project_session import ProjectSession


@pytest.fixture
def bridge(tmp_path: Path) -> tuple[Bridge, list[Path]]:
    session = ProjectSession(tmp_path / "untitled.gpb.json.autosave")
    session.project = analytic_chain()
    session.save(tmp_path / "panel.gpb.json")
    bridge = Bridge(MethodRegistry())
    questions: list[Path] = []

    def ask(suggested: Path) -> Path | None:
        questions.append(suggested)
        return None

    CodegenController(session, bridge, ask).register()
    return bridge, questions


def call(bridge: Bridge, method: str, **params: Any) -> Any:
    return invoke(bridge.registry.get(method), params)


def test_export_writes_the_script_and_its_mapping(
    bridge: tuple[Bridge, list[Path]], tmp_path: Path
) -> None:
    path = tmp_path / "out" / "panel.py"
    path.parent.mkdir()
    result = call(bridge[0], "codegen.export", path=str(path))
    assert result == {"exported": True, "path": str(path)}
    assert "from panel.gpb.json" in path.read_text(encoding="utf-8")
    assert path.with_suffix(".gpb-map.json").exists()


def test_export_asks_where_to_write_next_to_the_project(
    bridge: tuple[Bridge, list[Path]], tmp_path: Path
) -> None:
    assert call(bridge[0], "codegen.export") == {"exported": False}
    assert bridge[1] == [tmp_path / "panel_cost.py"]


def test_preview_and_errors(bridge: tuple[Bridge, list[Path]]) -> None:
    preview = call(bridge[0], "codegen.preview")
    assert preview["source"].startswith('"""Panel cost.')
    with pytest.raises(BridgeError, match="Only the model"):
        call(bridge[0], "codegen.preview", target="n-Area")
