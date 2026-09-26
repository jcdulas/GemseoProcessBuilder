"""Scripts checked to be GEMSEO 6 studies before they are run."""

import io
from pathlib import Path

import pytest

from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.gemseo_loader import version_error
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.script_check import check_script
from gemseo_process_builder.workers.script_reader import read_script
from gemseo_process_builder.workers.server import WorkerError

SCRIPTS = Path(__file__).parent / "scripts"

GEMSEO_5 = """\
from gemseo.api import create_scenario
from gemseo.core.discipline import MDODiscipline
from gemseo.problems.sellar.sellar import Sellar1


class Wing(MDODiscipline):
    def _run(self):
        self.local_data.update(self.default_inputs)


scenario = create_scenario([Sellar1()], "MDF", "obj", design_space)
scenario.execute({"algo": "SLSQP", "max_iter": 10})
scenario.execute(algo_name="SLSQP", algo_options={"ftol_rel": 1e-6})
"""


def messages(script: Path) -> list[str]:
    return [
        finding.describe(script.parent) for finding in check_script(script).findings
    ]


def test_the_scripts_of_gemseo_6_are_accepted() -> None:
    for script in SCRIPTS.glob("*.py"):
        assert check_script(script).ok, messages(script)


def test_a_study_for_gemseo_5_is_refused_with_hints(tmp_path: Path) -> None:
    script = tmp_path / "old.py"
    script.write_text(GEMSEO_5, "utf-8")
    assert messages(script) == [
        "old.py, line 1: gemseo.api is not a module of GEMSEO 6: it is now gemseo.",
        "old.py, line 2: gemseo.core.discipline has no MDODiscipline in GEMSEO 6: "
        "it is Discipline (gemseo.core.discipline).",
        "old.py, line 3: gemseo.problems.sellar.sellar is not a module of GEMSEO 6: "
        "look in gemseo.problems.mdo.sellar.",
        "old.py, line 8: default_inputs was removed in GEMSEO 6: use "
        "default_input_data.",
        "old.py, line 11: create_scenario(disciplines, formulation, objective, "
        "design_space) is the API of GEMSEO 5: GEMSEO 6 takes "
        "create_scenario(disciplines, objective_name, design_space, "
        'formulation_name="...").',
        'old.py, line 12: execute({"algo": ...}) is the API of GEMSEO 5: GEMSEO 6 '
        'takes execute(algo_name="...", **settings).',
        "old.py, line 13: algo_options= is the API of GEMSEO 5: GEMSEO 6 takes the "
        "settings of the algorithm as keyword arguments.",
    ]


def test_another_program_is_refused(tmp_path: Path) -> None:
    script = tmp_path / "tool.py"
    script.write_text("import json\nprint(json.dumps({}))\n", "utf-8")
    check = check_script(script)
    assert (check.uses_gemseo, check.findings, check.ok) == (False, [], False)
    script.write_text("def broken(:\n", "utf-8")
    assert messages(script) == [
        "tool.py, line 1: it is not valid Python: invalid syntax."
    ]


def test_the_modules_of_the_project_are_checked_too(tmp_path: Path) -> None:
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "__init__.py").write_text("", "utf-8")
    (tmp_path / "models" / "wing.py").write_text(
        "from gemseo.core.discipline import MDODiscipline\n", "utf-8"
    )
    (tmp_path / "helpers.py").write_text("from .models import wing\n", "utf-8")
    script = tmp_path / "study.py"
    script.write_text("import helpers\nfrom models.wing import Wing\n", "utf-8")
    check = check_script(script)
    assert check.uses_gemseo  # Through its modules only.
    assert [finding.describe(tmp_path) for finding in check.findings] == [
        "models/wing.py, line 1: gemseo.core.discipline has no MDODiscipline in "
        "GEMSEO 6: it is Discipline (gemseo.core.discipline)."
    ]
    assert len(check.files) == 4


def test_a_refused_script_is_not_run(tmp_path: Path) -> None:
    load_gemseo(EventChannel(io.StringIO()))
    script = tmp_path / "old.py"
    script.write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_name('ran').write_text('yes')\n"
        "from gemseo.api import create_scenario\n",
        "utf-8",
    )
    with pytest.raises(WorkerError, match="is not a GEMSEO 6 study") as error:
        read_script(script)
    assert error.value.code == "not_gemseo6"
    assert "- old.py, line 3: gemseo.api" in str(error.value)
    assert not (tmp_path / "ran").exists()
    script.write_text("print('hello')\n", "utf-8")
    with pytest.raises(WorkerError, match="does not import GEMSEO"):
        read_script(script)


def test_only_gemseo_6_is_used() -> None:
    assert version_error("6.3.3") == ""
    assert version_error("5.3.2").startswith("GEMSEO 6 is required")
    assert "GEMSEO 7.0.0" in version_error("7.0.0")
