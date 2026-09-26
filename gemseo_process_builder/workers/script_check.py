"""Checking that a script is a GEMSEO 6 study, before running it (SPEC § 4.2.1).

Reading a script runs it: the code is first read, never run, to refuse what is
not a GEMSEO 6 study (a study for an earlier GEMSEO, or another program). The
script and the modules of its folder it imports, recursively, are checked:

- each import of ``gemseo`` must exist in the GEMSEO installed here, version 6:
  modules and names renamed or removed since earlier versions are found this
  way, with hints for the usual ones;
- calls of the API of earlier versions are found by their shape: a settings
  dictionary given to ``execute``, ``algo_options=``, ``formulation=``, the
  formulation given as the second argument of ``create_scenario``…;
- at least one of the files must import GEMSEO.

Only GEMSEO modules are imported to check the names; the code of the user is
not run.
"""

import ast
import importlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path

MAX_FILES = 50
"""The number of files of a project checked at most."""

RENAMED_MODULES = {
    "gemseo.api": "gemseo",
    "gemseo.core.mdo_scenario": "gemseo.scenarios.mdo_scenario",
    "gemseo.core.doe_scenario": "gemseo.scenarios.doe_scenario",
    "gemseo.core.scenario": "gemseo.scenarios.base_scenario",
    "gemseo.core.chain": "gemseo.core.chains.chain",
    "gemseo.core.mdofunctions": "gemseo.core.mdo_functions",
    "gemseo.problems.sellar": "gemseo.problems.mdo.sellar",
    "gemseo.problems.sobieski": "gemseo.problems.mdo.sobieski",
    "gemseo.problems.aerostructure": "gemseo.problems.mdo.aerostructure",
    "gemseo.problems.propane": "gemseo.problems.mdo.propane",
}
"""Modules of earlier versions, and where GEMSEO 6 has them (a prefix)."""

RENAMED_NAMES = {
    "MDODiscipline": "Discipline (gemseo.core.discipline)",
}

REMOVED_ATTRIBUTES = {
    "default_inputs": "default_input_data",
    "get_input_data_names": "io.input_grammar.names",
    "get_outputs_by_name": "get_output_data",
}
"""Attributes of disciplines removed in GEMSEO 6, and what replaces them."""

FORMULATIONS = {"MDF", "IDF", "BiLevel", "BiLevelBCD", "DisciplinaryOpt"}
SCENARIO_CALLS = {"create_scenario", "MDOScenario", "DOEScenario"}


@dataclass(frozen=True)
class Finding:
    """What makes a script not a GEMSEO 6 study."""

    file: Path
    line: int
    message: str

    def describe(self, folder: Path) -> str:
        """The finding for the user, the file relative to the script folder."""
        try:
            name = self.file.relative_to(folder).as_posix()
        except ValueError:
            name = str(self.file)
        return f"{name}, line {self.line}: {self.message}"


@dataclass
class Check:
    """The result of the check of a script."""

    findings: list[Finding]
    uses_gemseo: bool
    files: list[Path]

    @property
    def ok(self) -> bool:
        """Whether the script can be read as a GEMSEO 6 study."""
        return self.uses_gemseo and not self.findings


def _module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):  # A parent is not a package.
        return False


def _has_name(module: str, name: str) -> bool:
    if _module_exists(f"{module}.{name}"):
        return True
    try:
        return hasattr(importlib.import_module(module), name)
    except Exception:  # GEMSEO modules only: a failure means it is unusable.
        return False


def _renamed_module(name: str) -> str:
    for old, new in RENAMED_MODULES.items():
        if name == old or name.startswith(old + "."):
            return new + name[len(old) :]
    return ""


def _missing_module(name: str) -> str:
    new = _renamed_module(name)
    if new and _module_exists(new):
        return f"{name} is not a module of GEMSEO 6: it is now {new}."
    while "." in new and not _module_exists(new):  # Split since: its package.
        new = new.rsplit(".", 1)[0]
    hint = f": look in {new}" if new and _module_exists(new) else ""
    return f"{name} is not a module of GEMSEO 6{hint}."


def _gemseo_imports(tree: ast.Module, file: Path) -> tuple[bool, list[Finding]]:
    uses, findings = False, []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] != "gemseo":
                    continue
                uses = True
                if not _module_exists(alias.name):
                    findings.append(
                        Finding(file, node.lineno, _missing_module(alias.name))
                    )
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module.split(".")[0] != "gemseo":
                continue
            uses = True
            if not _module_exists(node.module):
                findings.append(
                    Finding(file, node.lineno, _missing_module(node.module))
                )
                continue
            for alias in node.names:
                if alias.name == "*" or _has_name(node.module, alias.name):
                    continue
                hint = RENAMED_NAMES.get(alias.name, "")
                message = f"{node.module} has no {alias.name} in GEMSEO 6" + (
                    f": it is {hint}." if hint else "."
                )
                findings.append(Finding(file, node.lineno, message))
    return uses, findings


def _called(node: ast.Call) -> str:
    function = node.func
    if isinstance(function, ast.Attribute):
        return function.attr
    return function.id if isinstance(function, ast.Name) else ""


def _old_calls(tree: ast.Module, file: Path) -> list[Finding]:
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in REMOVED_ATTRIBUTES:
            message = (
                f"{node.attr} was removed in GEMSEO 6: use "
                f"{REMOVED_ATTRIBUTES[node.attr]}."
            )
            findings.append(Finding(file, node.lineno, message))
        if not isinstance(node, ast.Call):
            continue
        called = _called(node)
        keywords = {keyword.arg for keyword in node.keywords}
        if called == "execute" and any(
            isinstance(argument, ast.Dict)
            and any(
                isinstance(key, ast.Constant) and key.value == "algo"
                for key in argument.keys
            )
            for argument in node.args
        ):
            message = (
                'execute({"algo": ...}) is the API of GEMSEO 5: GEMSEO 6 takes '
                'execute(algo_name="...", **settings).'
            )
            findings.append(Finding(file, node.lineno, message))
        if "algo_options" in keywords:
            message = (
                "algo_options= is the API of GEMSEO 5: GEMSEO 6 takes the "
                "settings of the algorithm as keyword arguments."
            )
            findings.append(Finding(file, node.lineno, message))
        if called in SCENARIO_CALLS and "formulation" in keywords:
            message = (
                "formulation= is the API of GEMSEO 5: GEMSEO 6 takes formulation_name=."
            )
            findings.append(Finding(file, node.lineno, message))
        if (
            called in SCENARIO_CALLS
            and len(node.args) >= 4
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in FORMULATIONS
        ):
            message = (
                f"{called}(disciplines, formulation, objective, design_space) is "
                f"the API of GEMSEO 5: GEMSEO 6 takes {called}(disciplines, "
                'objective_name, design_space, formulation_name="...").'
            )
            findings.append(Finding(file, node.lineno, message))
    return findings


def _local_modules(tree: ast.Module, file: Path, root: Path) -> list[Path]:
    """The files of the project a file imports (in its folder or the script's)."""
    wanted: list[tuple[list[Path], str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            wanted += [([file.parent, root], alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level:
            base = file.parent
            for _ in range(node.level - 1):
                base = base.parent
            modules = [node.module] if node.module else []
            modules += [
                f"{node.module}.{alias.name}" if node.module else alias.name
                for alias in node.names
            ]
            wanted += [([base], module) for module in modules]
        elif isinstance(node, ast.ImportFrom) and node.module:
            wanted.append(([file.parent, root], node.module))
            wanted += [
                ([file.parent, root], f"{node.module}.{alias.name}")
                for alias in node.names
            ]
    found = []
    for folders, module in wanted:
        relative = Path(*module.split("."))
        for folder in folders:
            for candidate in (
                folder / relative.with_suffix(".py"),
                folder / relative / "__init__.py",
            ):
                if candidate.is_file():
                    found.append(candidate.resolve())
    return found


def check_script(script: Path) -> Check:
    """Check that a script, with the modules of its folder, is a GEMSEO 6 study."""
    root = script.resolve().parent
    pending: list[Path] = [script.resolve()]
    seen: set[Path] = set()
    findings: list[Finding] = []
    uses = False
    while pending and len(seen) < MAX_FILES:
        file = pending.pop(0)
        if file in seen:
            continue
        seen.add(file)
        try:
            tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        except SyntaxError as error:
            message = f"it is not valid Python: {error.msg}."
            findings.append(Finding(file, error.lineno or 0, message))
            continue
        except (OSError, UnicodeDecodeError) as error:
            findings.append(Finding(file, 0, f"it cannot be read: {error}."))
            continue
        imports_gemseo, found = _gemseo_imports(tree, file)
        uses = uses or imports_gemseo
        findings += sorted(
            found + _old_calls(tree, file), key=lambda finding: finding.line
        )
        pending += [
            path for path in _local_modules(tree, file, root) if path not in seen
        ]
    return Check(findings, uses, sorted(seen))
