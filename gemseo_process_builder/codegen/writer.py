"""Assembly of a generated module: docstring, imports, constants, functions."""

import sys
from dataclasses import dataclass
from dataclasses import field

from gemseo_process_builder.codegen.pretty import LINE_LENGTH

FIRST_PARTY = "gemseo_process_builder"
STANDARD_LIBRARY = set(sys.stdlib_module_names)


@dataclass
class Function:
    """A top-level function of the generated module."""

    signature: str
    """Like ``def build_disciplines() -> list[Discipline]:``."""

    docstring: str
    body: list[str] = field(default_factory=list)
    """Lines, already indented by four spaces."""


class ModuleWriter:
    """Collect the parts of a generated module and write its source."""

    def __init__(self, docstring: str) -> None:
        self.docstring = docstring
        self.imports: set[tuple[str, str]] = set()
        self.modules: set[str] = set()
        self.constants: list[str] = []
        self.classes: list[str] = []
        """Classes of the module, as source, written before the functions."""

        self.functions: list[Function] = []

    def use(self, module: str, name: str) -> str:
        """Import ``name`` from ``module`` and return ``name``."""
        self.imports.add((module, name))
        return name

    def use_module(self, module: str) -> str:
        """Import a whole module (``import sys``) and return its name."""
        self.modules.add(module)
        return module

    @staticmethod
    def _section(module: str) -> int:
        root = module.split(".")[0]
        if root in STANDARD_LIBRARY:
            return 0
        return 2 if root == FIRST_PARTY else 1

    @staticmethod
    def _from_import(module: str, names: list[str]) -> list[str]:
        # Like ruff's isort defaults: constants, then classes, then functions.
        names = sorted(
            names, key=lambda name: (not name.isupper(), not name[0].isupper(), name)
        )
        line = f"from {module} import {', '.join(names)}"
        if len(line) <= LINE_LENGTH:
            return [line]
        return [f"from {module} import (", *(f"    {name}," for name in names), ")"]

    def _import_lines(self) -> list[str]:
        # Like ruff's isort: plain imports first, then "from" imports.
        sections: dict[int, list[str]] = {0: [], 1: [], 2: []}
        for module in sorted(self.modules):
            sections[self._section(module)].append(f"import {module}")
        names_by_module: dict[str, list[str]] = {}
        for module, name in self.imports:
            names_by_module.setdefault(module, []).append(name)
        for module in sorted(names_by_module):
            sections[self._section(module)].extend(
                self._from_import(module, names_by_module[module])
            )
        lines: list[str] = []
        for section in sections.values():
            if section:
                if lines:
                    lines.append("")
                lines.extend(section)
        return lines

    def source(self) -> str:
        """The whole module, ending with a newline."""
        parts = ['"""' + self.docstring.rstrip() + '\n"""', ""]
        parts.extend(self._import_lines())
        if self.constants:
            parts.extend(["", *self.constants])
        for cls in self.classes:
            parts.extend(["", "", cls])
        for function in self.functions:
            parts.extend(["", "", function.signature])
            parts.append(f'    """{function.docstring}"""')
            parts.extend(function.body)
        parts.extend(["", "", 'if __name__ == "__main__":', "    main()", ""])
        return "\n".join(parts)
