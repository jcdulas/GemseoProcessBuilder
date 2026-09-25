"""A discipline running an external code (SPEC § 7.5).

Each execution:

1. creates a working folder of its own (safe when samples run in parallel);
2. copies the needed files and writes the input files from their templates;
3. runs the command there, with a timeout;
4. checks the return code and looks for error patterns in the output;
5. reads each output with its rule;
6. keeps or removes the folder, following the retention policy.

GEMSEO 6 has a public ``DiscFromExe``, limited to one template in its own
syntax, and private base classes: this discipline derives from the public
``Discipline`` instead (SPEC § 17, risk 1).
"""

import contextlib
import logging
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
from gemseo.core.discipline import Discipline
from gemseo.typing import StrKeyMapping

from gemseo_process_builder.runtime.parsing import read_output
from gemseo_process_builder.runtime.spec import STDOUT
from gemseo_process_builder.runtime.spec import ExecutableSpec
from gemseo_process_builder.runtime.spec import PortSpec
from gemseo_process_builder.runtime.spec import load_descriptor
from gemseo_process_builder.runtime.templates import render

LOGGER = logging.getLogger(__name__)

TEXT_TYPES = {"str", "path"}


class ExecutableError(RuntimeError):
    """A run of the external code that failed; the message says why and where."""


def _quote(path: str) -> str:
    """A path for a command line, quoted when needed."""
    if sys.platform == "win32":
        return subprocess.list2cmdline([path])
    return shlex.quote(path)


def _kill_tree(pid: int) -> None:
    """Kill a process and every process it started."""
    import psutil

    try:
        parent = psutil.Process(pid)
        processes = [*parent.children(recursive=True), parent]
    except psutil.NoSuchProcess:
        return
    for process in processes:
        with contextlib.suppress(psutil.NoSuchProcess):
            process.kill()


def _default(port: PortSpec) -> Any:
    if port.dtype in TEXT_TYPES:
        return str(port.default if port.default is not None else "")
    values = port.default if port.default is not None else 0.0
    array = np.atleast_1d(np.asarray(values, dtype=float))
    return np.resize(array, port.size)


class ExecutableDiscipline(Discipline):  # type: ignore[misc] # GEMSEO has no types.
    """Run an external code through input files, a command and output files."""

    def __init__(self, spec: ExecutableSpec, base_folder: Path | str = ".") -> None:
        """
        Args:
            spec: What to write, run and read.
            base_folder: The folder the relative paths of the spec refer to.
        """  # noqa: D205, D212
        super().__init__(spec.name)
        self.spec = spec
        self.base_folder = Path(base_folder)
        self.io.input_grammar.update_from_data(
            {port.name: _default(port) for port in spec.inputs}
        )
        self.io.output_grammar.update_from_data(
            {port.name: _default(port) for port in spec.outputs}
        )
        self.default_input_data = {port.name: _default(port) for port in spec.inputs}
        self.last_workdir: Path | None = None
        """The working folder of the last run (when it is kept)."""

    @classmethod
    def from_descriptor(cls, path: Path | str) -> "ExecutableDiscipline":
        """The discipline of a ``.gpbwrap.json`` descriptor."""
        spec, folder = load_descriptor(Path(path))
        return cls(spec, folder)

    # Execution ---------------------------------------------------------------

    def _write_inputs(self, workdir: Path, input_data: StrKeyMapping) -> None:
        """Copy the files and write the input files."""
        for name in self.spec.files:
            source = self.base_folder / name
            if not source.exists():
                msg = f"{self.name}: the file {source} to copy does not exist."
                raise ExecutableError(msg)
            if source.is_dir():
                shutil.copytree(source, workdir / source.name)
            else:
                shutil.copy2(source, workdir / source.name)
        values = {name: input_data[name] for name in input_data}
        for template in self.spec.templates:
            text = (self.base_folder / template.template).read_text(encoding="utf-8")
            content = render(text, values, self.spec.vector_separator)
            (workdir / template.target).write_text(content, encoding="utf-8")

    def command_line(self, workdir: Path) -> str:
        """The command with its tokens replaced."""
        input_file = self.spec.input_file or (
            self.spec.templates[0].target if self.spec.templates else ""
        )
        return self.spec.command.format(
            python=_quote(sys.executable),
            workdir=_quote(str(workdir)),
            input_file=input_file,
            output_file=self.spec.output_file,
        )

    def _run_command(self, workdir: Path) -> subprocess.CompletedProcess[str]:
        """Run the command; raise on timeouts, return codes and error patterns."""
        command = self.command_line(workdir)
        environment = None
        if self.spec.environment:
            environment = {**os.environ, **self.spec.environment}
        LOGGER.info("%s: running %s in %s", self.name, command, workdir)
        start = time.perf_counter()
        # The command line of the user runs in a shell, like in a terminal.
        process = subprocess.Popen(
            command,
            shell=True,
            cwd=workdir,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=self.spec.timeout)
        except subprocess.TimeoutExpired:
            # Killing the shell alone would leave the code running.
            _kill_tree(process.pid)
            process.communicate()
            msg = (
                f"{self.name}: the command did not finish within "
                f"{self.spec.timeout} s (working folder {workdir})."
            )
            raise ExecutableError(msg) from None
        result = subprocess.CompletedProcess(
            command, process.returncode, stdout, stderr
        )
        LOGGER.info("%s: done in %.2f s", self.name, time.perf_counter() - start)
        if result.returncode not in self.spec.return_codes:
            msg = (
                f"{self.name}: the command returned {result.returncode} "
                f"(working folder {workdir}).\n{result.stderr.strip()[-2000:]}"
            )
            raise ExecutableError(msg)
        output = result.stdout + result.stderr
        for pattern in self.spec.error_patterns:
            found = re.search(pattern, output, re.MULTILINE)
            if found:
                msg = (
                    f"{self.name}: the output contains {found.group(0)!r} "
                    f"(error pattern {pattern!r}, working folder {workdir})."
                )
                raise ExecutableError(msg)
        return result

    def _read_outputs(self, workdir: Path, stdout: str) -> dict[str, Any]:
        """The outputs, read by their rules."""
        texts: dict[str, str] = {STDOUT: stdout}
        dtypes = {port.name: port.dtype for port in self.spec.outputs}
        outputs: dict[str, Any] = {}
        for rule in self.spec.rules:
            if rule.kind != "file" and rule.file not in texts:
                path = workdir / rule.file
                if not path.is_file():
                    msg = (
                        f"{self.name}: the output file {rule.file} of "
                        f"{rule.variable} was not produced (working folder {workdir})."
                    )
                    raise ExecutableError(msg)
                texts[rule.file] = path.read_text(encoding="utf-8", errors="replace")
            try:
                value = read_output(rule, texts.get(rule.file, ""), workdir)
            except ValueError as error:
                msg = f"{self.name}: {error} (working folder {workdir})"
                raise ExecutableError(msg) from None
            is_text = dtypes.get(rule.variable) in TEXT_TYPES
            outputs[rule.variable] = value if is_text else np.atleast_1d(value)
        return outputs

    def _run(self, input_data: StrKeyMapping) -> StrKeyMapping | None:
        root = Path(self.spec.workdir_root) if self.spec.workdir_root else None
        if root is not None:
            root.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(prefix=f"{self.name}_", dir=root))
        failed = True
        try:
            self._write_inputs(workdir, input_data)
            result = self._run_command(workdir)
            outputs = self._read_outputs(workdir, result.stdout)
            failed = False
            return outputs
        finally:
            keep = self.spec.retention == "always" or (
                failed and self.spec.retention == "on_error"
            )
            self.last_workdir = workdir if keep else None
            if not keep:
                shutil.rmtree(workdir, ignore_errors=True)
