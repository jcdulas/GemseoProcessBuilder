"""The HTML report of the Sellar MDF example."""

import re
import shutil
from datetime import date
from pathlib import Path

import pytest
from golden_projects import example

from gemseo_process_builder.report.builder import Diagram
from gemseo_process_builder.report.builder import ReportOptions
from gemseo_process_builder.report.builder import build_report

SELLAR_RUN = Path(__file__).parents[1] / "results" / "fixtures" / "sellar_run"
DIAGRAM = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="8" viewBox="0 0 10 8">'
    '<rect width="4"/></svg>'
)


@pytest.fixture
def run_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "r-1"
    shutil.copytree(SELLAR_RUN, folder)
    images = folder / "postproc" / "OptHistoryView-20260925"
    images.mkdir(parents=True)
    (images / "objective.svg").write_text("<svg/>", encoding="utf-8")
    (images / "notes.txt").write_text("not an image", encoding="utf-8")
    return folder


def report(run_folder: Path, **options: object) -> str:
    return build_report(
        example("sellar_mdf"),
        ReportOptions.model_validate(options),
        [Diagram(title="Workflow of Model", svg=DIAGRAM)],
        lambda run_id: run_folder if run_id == "r-1" else None,
        date(2026, 9, 25),
    )


def test_all_sections(run_folder: Path) -> None:
    text = report(
        run_folder,
        runs=["r-1", "r-gone"],
        postprocessings=[{"run": "r-1", "result": "OptHistoryView-20260925"}],
    )
    for anchor in ("description", "diagrams", "inventory", "problem", "runs"):
        assert f'<section id="{anchor}">' in text
        assert f'href="#{anchor}"' in text
    assert "<title>Sellar MDF</title>" in text
    assert "on 2026-09-25" in text
    # The diagram is inline, without its XML declaration, as wide as the page at
    # most.
    assert (
        '<figure><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 8" '
        'style="width:100%;max-width:10px;height:auto">'
    ) in text
    assert "<?xml" not in text
    # Inventory: components with their source, variables with global names.
    assert "<td>Model.Optimizer.Sellar1</td>" in text
    assert "<td>x_shared</td><td>in</td><td>2</td>" in text
    # Problem definition.
    assert "<td>MDF</td>" in text
    assert "<td>SLSQP</td><td>max_iter = 100</td>" in text
    assert "<td>c_1</td><td>inequality</td><td>c_1 &lt;= 0</td>" in text
    # Runs: the summary, and the missing one.
    assert "<th>Best obj</th><td>3.41063</td>" in text
    assert "The run folder is missing." in text
    # Post-processing images are embedded; other files are left out.
    assert "<h3>OptHistoryView of r-1</h3>" in text
    assert 'src="data:image/svg+xml;base64,PHN2Zy8+"' in text
    assert "notes" not in text


def test_only_the_selected_sections(run_folder: Path) -> None:
    text = report(run_folder, description=False, diagrams=False, problem=False)
    assert '<section id="inventory">' in text
    for anchor in ("description", "diagrams", "problem", "runs", "postprocessings"):
        assert f'id="{anchor}"' not in text


def test_the_report_is_standalone(run_folder: Path) -> None:
    text = report(
        run_folder,
        runs=["r-1"],
        postprocessings=[{"run": "r-1", "result": "OptHistoryView-20260925"}],
    )
    # No file or address is loaded: only embedded data and anchors.
    assert not re.search(r'(src|href)="(?!data:|#)', text)
    assert "<link" not in text
    assert "<script" not in text
    assert "<style>" in text
