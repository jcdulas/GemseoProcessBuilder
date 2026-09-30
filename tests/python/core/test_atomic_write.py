"""Atomic writes leave the previous file intact when writing fails."""

from pathlib import Path

import pytest

from gemseo_process_builder.core import atomic_write
from gemseo_process_builder.core.atomic_write import write_bytes_atomically
from gemseo_process_builder.core.atomic_write import write_text_atomically


def test_write_and_replace(tmp_path: Path) -> None:
    path = tmp_path / "folder" / "project.gpb.json"
    write_text_atomically(path, "first\n")
    write_text_atomically(path, "second\n")
    assert path.read_bytes() == b"second\n"
    write_bytes_atomically(path, b"\x89PNG")
    assert path.read_bytes() == b"\x89PNG"
    assert [file.name for file in path.parent.iterdir()] == ["project.gpb.json"]


def test_a_failure_mid_write_keeps_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "project.gpb.json"
    path.write_text("original", encoding="utf-8")

    def crash(source: str, target: Path) -> None:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(atomic_write.os, "replace", crash)
    with pytest.raises(OSError, match="disk full"):
        write_text_atomically(path, "half written")
    assert path.read_text(encoding="utf-8") == "original"
    # The temporary file is removed.
    assert [file.name for file in tmp_path.iterdir()] == ["project.gpb.json"]
