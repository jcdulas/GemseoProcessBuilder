"""Catalog entries declared by installed packages (SPEC § 7.6, plan 75).

Each test writes fake distributions in a temporary folder put on ``sys.path``:
a ``*.dist-info`` folder with its ``METADATA`` and ``entry_points.txt``, and a
package with its declaration and its disciplines. Their module names are
unique to the test, so that ``sys.modules`` keeps nothing of another test.
"""

import io
import itertools
import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from builders import component
from builders import project
from PySide6.QtCore import QObject
from PySide6.QtCore import Signal

from gemseo_process_builder.app.bridge import Bridge
from gemseo_process_builder.app.bridge import MethodRegistry
from gemseo_process_builder.app.catalog_service import CatalogCache
from gemseo_process_builder.app.catalog_service import CatalogService
from gemseo_process_builder.app.catalog_service import PackageCache
from gemseo_process_builder.app.preferences import PreferencesStore
from gemseo_process_builder.app.project_session import ProjectSession
from gemseo_process_builder.catalog import packages
from gemseo_process_builder.catalog.models import normalized_name
from gemseo_process_builder.catalog.packages import GROUP
from gemseo_process_builder.catalog.packages import check_entry
from gemseo_process_builder.catalog.packages import locate
from gemseo_process_builder.codegen.generator import generate
from gemseo_process_builder.core.resolver import resolve
from gemseo_process_builder.core.rules.structure import package_problems
from gemseo_process_builder.core.validation import ValidationContext
from gemseo_process_builder.workers.component_methods import introspect
from gemseo_process_builder.workers.gemseo_loader import load_gemseo
from gemseo_process_builder.workers.protocol import EventChannel
from gemseo_process_builder.workers.script_reader import read_script

DISCIPLINES = '''"""Disciplines of a fake package."""

import numpy as np
from gemseo.core.discipline import Discipline


class Wing(Discipline):
    """Compute the lift of a wing."""

    def __init__(self) -> None:
        super().__init__()
        self.io.input_grammar.update_from_data({"area": np.array([10.0])})
        self.io.output_grammar.update_from_data({"lift": np.array([0.0])})
        self.io.input_grammar.defaults = {"area": np.array([10.0])}

    def _run(self, input_data):
        return {"lift": 2.0 * input_data["area"]}


def drag(area=10.0):
    drag = 0.1 * area
    return drag
'''

CATALOG = """COMPONENTS = [
    {
        "kind": "python_class",
        "module": "MODULE.disciplines",
        "attribute": "Wing",
        "group": "Aerodynamics",
        "description": "The lift of a wing.",
        "units": {"area": "m**2", "lift": "N"},
    },
    {
        "kind": "python_function",
        "module": "MODULE.disciplines",
        "attribute": "drag",
        "units": {"drag": "N"},
    },
]
"""

COUNTER = itertools.count()


class Context:
    """The request context of the worker methods."""

    def check(self) -> None:
        """Nothing cancels the request."""


@pytest.fixture(scope="module", autouse=True)
def gemseo_ready() -> None:
    load_gemseo(EventChannel(io.StringIO()))


@pytest.fixture
def site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A folder of distributions on ``sys.path``, forgotten after the test."""
    root = tmp_path / "site"
    root.mkdir()
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.setattr(packages, "_DECLARED", None)
    before = set(sys.modules)
    yield root
    for name in set(sys.modules) - before:
        if name.startswith("fake_gpb_"):
            del sys.modules[name]


def distribution(
    root: Path,
    name: str = "",
    version: str = "1.0",
    catalog: str = CATALOG,
    editable: bool = False,
    value: str = "catalog:COMPONENTS",
) -> tuple[str, str]:
    """A fake distribution and its package; its name and its module."""
    module = f"fake_gpb_{next(COUNTER)}_{os.getpid()}"
    name = name or module.replace("_", "-")
    info = root / f"{module}-{version}.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n", "utf-8"
    )
    (info / "entry_points.txt").write_text(
        f"[{GROUP}]\n{name} = {module}.{value}\n", "utf-8"
    )
    if editable:
        url = {"url": root.as_uri(), "dir_info": {"editable": True}}
        (info / "direct_url.json").write_text(json.dumps(url), "utf-8")
    package = root / module
    package.mkdir()
    (package / "__init__.py").write_text("", "utf-8")
    (package / "catalog.py").write_text(catalog.replace("MODULE", module), "utf-8")
    (package / "disciplines.py").write_text(DISCIPLINES, "utf-8")
    return name, module


def scan(known: list[dict[str, Any]] = (), force: bool = False) -> dict[str, Any]:  # type: ignore[assignment]
    """The answer of ``catalog.packages``, for the fake distributions only."""
    results = packages._packages({"known": list(known), "force": force}, Context())
    return {
        result["name"]: result
        for result in results
        if result["name"].startswith("fake-gpb-")
    }


def test_entries_are_found_without_importing_the_components(site: Path) -> None:
    name, module = distribution(site)
    (result,) = scan().values()
    assert (result["name"], result["version"], result["stamp"]) == (name, "1.0", None)
    assert result["errors"] == []
    assert result["warnings"] == []
    wing, drag = result["entries"]
    assert wing["kind"] == "python_class"
    assert (wing["module"], wing["attribute"]) == (f"{module}.disciplines", "Wing")
    assert wing["group"] == "Aerodynamics"
    assert wing["description"] == "The lift of a wing."
    assert wing["metadata"]["units"] == {"area": "m**2", "lift": "N"}
    assert (drag["kind"], drag["group"]) == ("python_function", "")
    # The declaration was imported, the disciplines were not.
    assert f"{module}.catalog" in sys.modules
    assert f"{module}.disciplines" not in sys.modules


def test_a_package_of_the_cache_is_not_loaded_again(site: Path) -> None:
    name, module = distribution(site)
    first = scan()[name]
    del sys.modules[f"{module}.catalog"], sys.modules[module]
    known = [{"name": name, "version": "1.0", "stamp": first["stamp"]}]
    assert scan(known)[name] == {
        "name": name,
        "version": "1.0",
        "stamp": None,
        "unchanged": True,
    }
    assert module not in sys.modules
    assert f"{module}.catalog" not in sys.modules
    # Refresh loads it again.
    assert scan(known, force=True)[name]["entries"]


def test_a_new_version_is_loaded_again(site: Path) -> None:
    name, module = distribution(site)
    known = [{"name": name, "version": "1.0", "stamp": None}]
    info = site / f"{module}-1.0.dist-info"
    text = (info / "METADATA").read_text("utf-8").replace("1.0", "1.1")
    (info / "METADATA").write_text(text, "utf-8")
    info.rename(site / f"{module}-1.1.dist-info")
    result = scan(known)[name]
    assert result["version"] == "1.1"
    assert "unchanged" not in result


def test_an_edited_editable_install_is_loaded_again(site: Path) -> None:
    name, module = distribution(site, editable=True)
    first = scan()[name]
    declaration = site / module / "catalog.py"
    assert first["stamp"] == declaration.stat().st_mtime
    known = [{"name": name, "version": "1.0", "stamp": first["stamp"]}]
    assert scan(known)[name]["unchanged"]
    text = declaration.read_text("utf-8").replace("The lift", "The new lift")
    declaration.write_text(text, "utf-8")
    later = time.time() + 10
    os.utime(declaration, (later, later))
    result = scan(known)[name]
    assert result["stamp"] == later
    # The declaration imported before is executed again.
    assert result["entries"][0]["description"] == "The new lift of a wing."


def test_one_error_per_problem_and_the_other_packages_listed(site: Path) -> None:
    good, _ = distribution(site)
    raising, _ = distribution(site, catalog="raise RuntimeError('broken catalog')\n")
    not_a_list, _ = distribution(site, catalog="COMPONENTS = {'kind': 1}\n")
    malformed, _ = distribution(
        site,
        catalog="""COMPONENTS = [
    {"kind": "python_class", "module": "MODULE.missing", "attribute": "Wing"},
    {"kind": "python_class", "module": "MODULE.disciplines", "attribute": 3},
    {"kind": "python_class", "module": "MODULE.disciplines", "attribute": "Wing"},
]
""",
    )
    results = scan()
    assert results[good]["errors"] == []
    (error,) = results[raising]["errors"]
    assert error["message"] == "RuntimeError: broken catalog"
    assert "Traceback" in error["traceback"]
    assert results[raising]["entries"] == []
    (error,) = results[not_a_list]["errors"]
    assert "is a dict, not a list of dictionaries" in error["message"]
    missing, wrong_type = results[malformed]["errors"]
    assert "the module" in missing["message"]
    assert "cannot be found" in missing["message"]
    assert "attribute is a int, not a str" in wrong_type["message"]
    # The valid entry of the same package is kept.
    assert [entry["name"] for entry in results[malformed]["entries"]] == ["Wing"]


def test_a_function_gives_the_entries_and_unknown_keys_are_warned(site: Path) -> None:
    catalog = "def components():\n    return " + CATALOG.replace(
        "COMPONENTS = ", ""
    ).replace('"units": {"drag": "N"},', '"units": {"drag": "N"}, "color": "red",')
    name, _ = distribution(site, catalog=catalog, value="catalog:components")
    result = scan()[name]
    assert len(result["entries"]) == 2
    assert result["warnings"] == [
        f"Entry 2 of {result['entries'][0]['module'].split('.')[0]}.catalog:"
        "components (drag): the key 'color' is unknown and was ignored."
    ]


def test_the_checks_of_an_entry() -> None:
    entry = {"kind": "python_class", "module": "gemseo.core.discipline"}
    assert check_entry(entry, "E")[1] == ["E has no attribute."]
    entry["attribute"] = "Discipline"
    assert check_entry({**entry, "kind": "class"}, "E")[1] == [
        "E: kind 'class' is not one of python_class, python_function."
    ]
    assert check_entry({**entry, "units": {"x": 1}}, "E")[1] == [
        "E: units must map names to unit texts."
    ]
    assert check_entry({**entry, "schema": True}, "E")[1] == [
        "E: schema is a bool, not a int."
    ]
    found, errors, warnings = check_entry({**entry, "schema": 2}, "E")
    assert found is not None
    assert errors == []
    assert warnings == [
        "E is written in version 2 of the format; the keys of version 1 were read."
    ]


def test_modules_are_located_without_importing_their_packages(site: Path) -> None:
    _, module = distribution(site)
    spec = locate(f"{module}.disciplines")
    assert spec is not None
    assert spec.origin == str(site / module / "disciplines.py")
    assert module not in sys.modules
    assert locate(f"{module}.missing") is None
    assert locate(f"{module}.disciplines.inner") is None
    assert locate("not a module") is None


def test_placed_components_get_the_units_of_their_declaration(site: Path) -> None:
    name, module = distribution(site)
    owner = {"name": name, "version": "1.0"}
    config = {"module": f"{module}.disciplines", "class": "Wing", "package": owner}
    ports = {port["local_name"]: port for port in introspect("python_class", config)}
    assert (ports["area"]["unit"], ports["lift"]["unit"]) == ("m**2", "N")
    config = {"module": f"{module}.disciplines", "function": "drag", "package": owner}
    ports = {p["local_name"]: p for p in introspect("python_function", config)}
    assert ports["drag"]["unit"] == "N"


def test_the_script_of_a_package_component_imports_it_in_one_line(
    site: Path, tmp_path: Path
) -> None:
    name, module = distribution(site)
    wing = component(
        "Wing",
        ins=["area"],
        outs=["lift"],
        kind="python_class",
        config={
            "module": f"{module}.disciplines",
            "class": "Wing",
            "init_args": {},
            "package": {"name": name, "version": "1.0"},
        },
    )
    source = generate(project(wing)).source
    assert f"from {module}.disciplines import Wing" in source.splitlines()
    assert "sys.path" not in source
    # The script runs as it is, and reads back with its package.
    script = tmp_path / "study" / "wing_study.py"
    script.parent.mkdir()
    script.write_text(source, "utf-8")
    namespace: dict[str, Any] = {"__name__": "fake_gpb_study"}
    exec(compile(source, str(script), "exec"), namespace)
    outputs = namespace["build_process"]().execute()
    assert outputs["lift"][0] == pytest.approx(20.0)
    (read,) = read_script(script)["project"]["root"]["children"]
    assert read["config"]["package"] == {"name": name, "version": "1.0"}


def test_the_rules_of_the_packages() -> None:
    def problems(installed: dict[str, str] | None) -> list[tuple[str, str]]:
        node = component(
            "Sizing",
            kind="python_class",
            config={
                "module": "gemseo_nastran.sizing",
                "class": "StructuralSizing",
                "package": {"name": "gemseo-nastran", "version": "0.3.0"},
            },
        )
        model = project(node)
        context = ValidationContext(model, resolve(model), packages=installed)
        return [(item.code, item.message) for item in package_problems(context)]

    assert problems(None) == []  # Not known before the first scan.
    assert problems({"gemseo-nastran": "0.3.0"}) == []
    assert problems({"other": "1.0"}) == [
        (
            "package_missing",
            "Sizing comes from the package gemseo-nastran, missing from the Python "
            "of the runs: install gemseo-nastran in the Python of the runs.",
        )
    ]
    assert problems({normalized_name("Gemseo_Nastran"): "0.4.0"}) == [
        (
            "package_version",
            "Sizing was placed from gemseo-nastran 0.3.0; the Python of the runs "
            "has gemseo-nastran 0.4.0.",
        )
    ]


def test_the_cache_of_the_packages(tmp_path: Path) -> None:
    path = tmp_path / "packages.json"
    cache = PackageCache(path)
    assert cache.versions() is None
    scanned = {"name": "Demo_Tools", "version": "1.0", "stamp": None, "entries": []}
    cache.update([scanned, {"name": "gone", "version": "2", "unchanged": True}])
    cache.save()
    reloaded = PackageCache(path)
    assert reloaded.known() == [{"name": "Demo_Tools", "version": "1.0", "stamp": None}]
    reloaded.update([{"name": "demo-tools", "version": "1.0", "unchanged": True}])
    assert reloaded.versions() == {"demo-tools": "1.0"}
    # A package no longer listed leaves the cache.
    reloaded.update([])
    assert reloaded.versions() == {}
    path.write_text("[not a cache", "utf-8")
    assert PackageCache(path).packages == {}


class FakeWorker(QObject):
    """Answers ``catalog.packages`` with the scans given; scans no file."""

    event_received = Signal(str, object)

    def __init__(self, answers: list[Any]) -> None:
        super().__init__()
        self.answers = answers
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def call(self, method: str, params: dict[str, Any], timeout: float) -> Any:
        self.requests.append((method, params))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_the_catalog_service_lists_the_packages(tmp_path: Path) -> None:
    scanned = {
        "name": "demo-tools",
        "version": "1.0",
        "stamp": None,
        "entries": [
            {"kind": "python_class", "name": "Wing", "module_path": "", "module": "m"}
        ],
    }
    unchanged = {"name": "demo-tools", "version": "1.0", "unchanged": True}
    worker = FakeWorker([[scanned], [unchanged], RuntimeError("worker stopped")])
    bridge = Bridge(MethodRegistry())
    bridge.emit_event = lambda name, payload: None  # type: ignore[method-assign]
    service = CatalogService(
        bridge,
        worker,  # type: ignore[arg-type]
        PreferencesStore(tmp_path / "prefs.json"),
        ProjectSession(tmp_path / "data" / "untitled.gpb.json.autosave"),
        CatalogCache(None),
        PackageCache(tmp_path / "packages.json"),
    )
    changes: list[bool] = []
    service.packages_changed.connect(lambda: changes.append(True))
    assert service.installed_packages() is None
    service._scan(force=False)
    assert worker.requests == [("catalog.packages", {"known": [], "force": False})]
    assert service.state()["packages"][0]["entries"][0]["name"] == "Wing"
    assert service.installed_packages() == {"demo-tools": "1.0"}
    assert changes == [True]
    service._scan(force=True)
    assert worker.requests[1][1] == {
        "known": [{"name": "demo-tools", "version": "1.0", "stamp": None}],
        "force": True,
    }
    assert changes == [True]  # The same versions: nothing to validate again.
    service._scan(force=False)
    assert service.state()["errors"] == ["worker stopped"]
    assert service.installed_packages() == {"demo-tools": "1.0"}


def test_the_modules_missing_are_told_without_importing_them() -> None:
    names = ["json", "a_module_that_does_not_exist", "gemseo.core.discipline"]
    missing = packages._missing({"names": names}, Context())
    assert missing == ["a_module_that_does_not_exist"]
