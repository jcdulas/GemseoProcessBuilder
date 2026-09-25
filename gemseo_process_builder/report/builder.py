"""The HTML report of a project (SPEC § 13).

The report is one standalone file: its CSS is inline, diagrams are inline SVG
and images are embedded in base64, so that it opens offline and can be sent
by e-mail. Its text is generated from the project data only.
"""

import base64
import html
import re
from collections.abc import Callable
from collections.abc import Collection
from datetime import date
from importlib import resources
from pathlib import Path
from string import Template
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError

from gemseo_process_builder import __version__
from gemseo_process_builder.core.drivers import DriverConfig
from gemseo_process_builder.core.model import ComponentNode
from gemseo_process_builder.core.model import DriverNode
from gemseo_process_builder.core.model import Project
from gemseo_process_builder.core.model import iter_nodes
from gemseo_process_builder.core.model import path_of
from gemseo_process_builder.core.resolver import resolve
from gemseo_process_builder.results.models import read_info

IMAGE_TYPES = {".svg": "image/svg+xml", ".png": "image/png"}


class PostprocessingRef(BaseModel):
    """A post-processing of a run to show in the report."""

    run: str
    result: str
    """Its folder in ``postproc/`` of the run."""


class ReportOptions(BaseModel):
    """What the report contains."""

    title: str = ""
    """The title; the project name by default."""

    description: bool = True
    diagrams: bool = True
    inventory: bool = True
    problem: bool = True
    runs: list[str] = []
    postprocessings: list[PostprocessingRef] = []


class Diagram(BaseModel):
    """A diagram drawn by the page: a standalone SVG document."""

    title: str
    svg: str


def _text(value: Any) -> str:
    return html.escape(str(value))


def _table(
    headers: list[str] | None, rows: list[list[Any]], numbers: Collection[int] = ()
) -> str:
    """An HTML table; the columns in ``numbers`` are aligned right.

    Without headers, the first column names the rows.
    """
    if headers is None:
        body = "".join(
            f"<tr><th>{_text(row[0])}</th>"
            + "".join(f"<td>{_text(cell)}</td>" for cell in row[1:])
            + "</tr>"
            for row in rows
        )
        return f"<table><tbody>{body}</tbody></table>"
    head = "".join(f"<th>{_text(header)}</th>" for header in headers)
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="number">{_text(cell)}</td>'
            if index in numbers
            else f"<td>{_text(cell)}</td>"
            for index, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _value(value: Any) -> str:
    """A value as shown in the tables: numbers with 6 significant digits."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list):
        return ", ".join(_value(item) for item in value)
    return str(value)


def _inline_svg(svg: str) -> str:
    """An SVG document to put inside HTML, without its XML declaration.

    It is as wide as the page at most, and never wider than drawn.
    """
    start = svg.find("<svg")
    if start < 0:
        return ""
    svg = svg[start:]
    head_end = svg.find(">")
    head = svg[:head_end]
    width = re.search(r' width="([\d.]+)"', head)
    head = re.sub(r' (width|height)="[\d.]+"', "", head)
    if width is None:
        return svg
    style = f"width:100%;max-width:{width.group(1)}px;height:auto"
    return f'{head} style="{style}"{svg[head_end:]}'


def _template(name: str) -> str:
    return (
        resources.files("gemseo_process_builder.report") / "templates" / name
    ).read_text(encoding="utf-8")


class ReportBuilder:
    """Build the sections of a report."""

    def __init__(
        self,
        project: Project,
        options: ReportOptions,
        diagrams: list[Diagram],
        run_folder: Callable[[str], Path | None],
    ) -> None:
        """
        Args:
            project: The project to report.
            options: The content of the report.
            diagrams: The diagrams drawn by the page.
            run_folder: The folder of a run of the project, from its id.
        """  # noqa: D205, D212
        self.project = project
        self.options = options
        self.diagrams = diagrams
        self.run_folder = run_folder

    # Sections ------------------------------------------------------------------

    def description(self) -> str:
        """The description of the project and its size."""
        metadata = self.project.metadata
        nodes = [node for node, _ in iter_nodes(self.project.root)]
        components = sum(isinstance(node, ComponentNode) for node in nodes)
        drivers = sum(isinstance(node, DriverNode) for node in nodes)
        text = metadata.description.strip() or "No description."
        rows: list[list[Any]] = [
            ["Name", metadata.name],
            ["Created", metadata.created.replace("T", " ")[:16]],
            ["Components", components],
            ["Drivers", drivers],
            ["Explicit links", len(self.project.links)],
            ["Runs", len(self.project.runs)],
        ]
        return f'<p class="description">{_text(text)}</p>' + _table(None, rows)

    def diagram_section(self) -> str:
        """The diagrams drawn by the page."""
        if not self.diagrams:
            return '<p class="hint">No diagram.</p>'
        return "".join(
            f"<figure>{_inline_svg(diagram.svg)}"
            f"<figcaption>{_text(diagram.title)}</figcaption></figure>"
            for diagram in self.diagrams
        )

    def inventory(self) -> str:
        """The components, then the variables of each one."""
        resolution = resolve(self.project)
        components = [
            node
            for node, _ in iter_nodes(self.project.root)
            if isinstance(node, ComponentNode)
        ]
        rows = [
            [
                path_of(self.project, node.id),
                node.kind.replace("_", " "),
                _source(node),
                len([port for port in node.ports if port.direction == "in"]),
                len([port for port in node.ports if port.direction == "out"]),
            ]
            for node in components
        ]
        parts = [
            _table(["Component", "Kind", "Source", "Inputs", "Outputs"], rows, {3, 4})
        ]
        for node in components:
            variables = [
                [
                    port.local_name,
                    port.direction,
                    "×".join(str(size) for size in port.shape)
                    if port.shape
                    else "scalar",
                    port.unit or "",
                    _value(port.default),
                    resolution.global_name(node.id, port.local_name, port.direction)
                    or port.local_name,
                    port.description,
                ]
                for port in node.ports
            ]
            parts.append(f"<h3>{_text(path_of(self.project, node.id))}</h3>")
            parts.append(
                _table(
                    [
                        "Variable",
                        "Direction",
                        "Shape",
                        "Unit",
                        "Default",
                        "Global name",
                        "Description",
                    ],
                    variables,
                )
                if variables
                else '<p class="hint">No variables.</p>'
            )
        return "".join(parts)

    def problem(self) -> str:
        """The problem solved by each driver."""
        drivers = [
            node
            for node, _ in iter_nodes(self.project.root)
            if isinstance(node, DriverNode)
        ]
        if not drivers:
            return '<p class="hint">The model has no driver.</p>'
        return "".join(self._driver(driver) for driver in drivers)

    def _driver(self, driver: DriverNode) -> str:
        parts = [
            f"<h3>{_text(path_of(self.project, driver.id))} ({_text(driver.kind)})</h3>"
        ]
        try:
            config = DriverConfig.model_validate(driver.config)
        except ValidationError:
            return parts[0] + '<p class="hint">Its configuration is not valid.</p>'
        choices = []
        if config.formulation.name:
            choices.append(
                [
                    "Formulation",
                    config.formulation.name,
                    _settings(config.formulation.settings),
                ]
            )
        if config.algorithm.name:
            choices.append(
                [
                    "Algorithm",
                    config.algorithm.name,
                    _settings(config.algorithm.settings),
                ]
            )
        if choices:
            parts.append(_table(["", "Name", "Settings"], choices))
        if config.design_space:
            parts.append(
                _table(
                    [
                        "Design variable",
                        "Size",
                        "Lower bound",
                        "Upper bound",
                        "Initial value",
                    ],
                    [
                        [
                            item.variable,
                            item.size,
                            _value(item.lower),
                            _value(item.upper),
                            _value(item.value),
                        ]
                        for item in config.design_space
                    ],
                    {1},
                )
            )
        if config.objectives:
            parts.append(
                _table(
                    ["Objective", "Sense"],
                    [[item.variable, item.sense] for item in config.objectives],
                )
            )
        if config.constraints:
            parts.append(
                _table(
                    ["Constraint", "Type", "Condition"],
                    [
                        [
                            item.variable,
                            "equality" if item.type == "eq" else "inequality",
                            _condition(item),
                        ]
                        for item in config.constraints
                    ],
                )
            )
        responses = [*config.responses, *config.observables]
        if responses:
            parts.append(f"<p>Outputs recorded: {_text(', '.join(responses))}.</p>")
        if config.levels:
            parts.append(
                _table(
                    ["Parameter", "Values"],
                    [
                        [
                            level.variable,
                            _value(level.values)
                            if level.mode == "list"
                            else f"{level.count} values from {_value(level.lower)} "
                            f"to {_value(level.upper)}",
                        ]
                        for level in config.levels
                    ],
                )
            )
        return "".join(parts)

    def runs(self) -> str:
        """The summary of each selected run."""
        parts = []
        for run_id in self.options.runs:
            folder = self.run_folder(run_id)
            info = read_info(folder) if folder else None
            if info is None:
                parts.append(f"<h3>{_text(run_id)}</h3>")
                parts.append('<p class="hint">The run folder is missing.</p>')
                continue
            summary = info.summary
            rows: list[list[Any]] = [
                ["Driver", info.driver_path or info.driver_name],
                ["Algorithm", info.algorithm],
                ["Formulation", info.formulation],
                ["Status", info.status],
                ["Started", (info.started or info.created).replace("T", " ")],
                [
                    "Duration",
                    f"{info.duration_s:.1f} s" if info.duration_s is not None else "",
                ],
                [
                    "Evaluations",
                    summary.n_evaluations if summary.n_evaluations is not None else "",
                ],
            ]
            if summary.objective:
                rows.append(
                    [f"Best {summary.objective}", _value(summary.best_objective)]
                )
            if summary.is_feasible is not None:
                rows.append(["Feasible", "yes" if summary.is_feasible else "no"])
            parts.append(f"<h3>{_text(info.name or info.id)}</h3>")
            parts.append(_table(None, rows))
            for title, values in (
                ("Design variables at the optimum", summary.x_opt),
                ("Constraints at the optimum", summary.constraints),
                ("Outputs", summary.outputs),
            ):
                if values:
                    parts.append(
                        _table(
                            [title, "Value"],
                            [[name, _value(value)] for name, value in values.items()],
                        )
                    )
        return "".join(parts) or '<p class="hint">No run selected.</p>'

    def postprocessings(self) -> str:
        """The images of the selected post-processings, embedded."""
        parts = []
        for reference in self.options.postprocessings:
            folder = self.run_folder(reference.run)
            output = folder / "postproc" / reference.result if folder else None
            images = (
                sorted(path for path in output.iterdir() if path.suffix in IMAGE_TYPES)
                if output and output.is_dir()
                else []
            )
            name = reference.result.rsplit("-", 1)[0]
            parts.append(f"<h3>{_text(name)} of {_text(reference.run)}</h3>")
            if not images:
                parts.append('<p class="hint">Its images are missing.</p>')
            for image in images:
                data = base64.b64encode(image.read_bytes()).decode("ascii")
                parts.append(
                    f'<figure><img alt="{_text(image.stem)}" '
                    f'src="data:{IMAGE_TYPES[image.suffix]};base64,{data}">'
                    f"<figcaption>{_text(image.stem)}</figcaption></figure>"
                )
        return "".join(parts)

    # Document --------------------------------------------------------------------

    def sections(self) -> list[tuple[str, str, str]]:
        """The selected sections: anchor, title and content."""
        options = self.options
        sections = []
        if options.description:
            sections.append(("description", "Description", self.description()))
        if options.diagrams:
            sections.append(("diagrams", "Diagrams", self.diagram_section()))
        if options.inventory:
            sections.append(("inventory", "Components and variables", self.inventory()))
        if options.problem:
            sections.append(("problem", "Problem definition", self.problem()))
        if options.runs:
            sections.append(("runs", "Results", self.runs()))
        if options.postprocessings:
            sections.append(
                ("postprocessings", "Post-processings", self.postprocessings())
            )
        return sections

    def build(self, today: date | None = None) -> str:
        """The HTML document."""
        title = self.options.title or self.project.metadata.name or "Project report"
        sections = self.sections()
        day = (today or date.today()).isoformat()
        return Template(_template("report.html")).substitute(
            title=_text(title),
            version=_text(__version__),
            date=day,
            meta=_text(f"Project report of {self.project.metadata.name}, {day}"),
            css=_template("report.css"),
            toc="\n".join(
                f'<li><a href="#{anchor}">{_text(name)}</a></li>'
                for anchor, name, _ in sections
            ),
            sections="\n".join(
                f'<section id="{anchor}"><h2>{_text(name)}</h2>{content}</section>'
                for anchor, name, content in sections
            ),
        )


def _condition(constraint: Any) -> str:
    """A constraint as a condition: ``g <= 0``."""
    operator = "=" if constraint.type == "eq" else constraint.operator
    value = constraint.value_text or _value(constraint.value)
    return f"{constraint.variable} {operator} {value}"


def _settings(settings: dict[str, Any]) -> str:
    return (
        ", ".join(f"{key} = {_value(value)}" for key, value in settings.items())
        or "defaults"
    )


def _source(node: ComponentNode) -> str:
    """Where a component comes from, in a few words."""
    config = node.config
    if node.kind == "analytic":
        return "; ".join(
            f"{name} = {formula}"
            for name, formula in config.get("expressions", {}).items()
        )
    if node.kind in ("python_function", "python_class"):
        module = config.get("module") or Path(config.get("module_path", "")).name
        name = config.get("function") or config.get("class") or ""
        return f"{module}.{name}" if module else name
    if node.kind == "executable":
        if config.get("descriptor_path"):
            return f"Wrapper {Path(config['descriptor_path']).name}"
        return f"Wrapper: {config.get('spec', {}).get('command', '')}"
    if node.kind == "surrogate":
        return str(config.get("summary") or Path(config.get("model_path", "")).name)
    return ""


def build_report(
    project: Project,
    options: ReportOptions,
    diagrams: list[Diagram],
    run_folder: Callable[[str], Path | None],
    today: date | None = None,
) -> str:
    """The standalone HTML report of a project."""
    return ReportBuilder(project, options, diagrams, run_folder).build(today)
