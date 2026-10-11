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


@pytest.mark.parametrize(("refusals", "written"), [(2, True), (3, False)])
def test_a_replacement_refused_for_a_moment_is_tried_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusals: int, written: bool
) -> None:
    # On Windows, an antivirus opening the file just written: access denied.
    path = tmp_path / "wing.py"
    path.write_text("original", encoding="utf-8")
    replace = atomic_write.os.replace
    attempts = []

    def refused(source: str, target: Path) -> None:
        attempts.append(source)
        if len(attempts) <= refusals:
            raise PermissionError(13, "Access is denied")
        replace(source, target)

    monkeypatch.setattr(atomic_write, "RETRY_PAUSES", (0.0, 0.0))
    monkeypatch.setattr(atomic_write.os, "replace", refused)
    if written:
        write_text_atomically(path, "saved")
        assert path.read_text(encoding="utf-8") == "saved"
    else:
        with pytest.raises(PermissionError):
            write_text_atomically(path, "saved")
        assert path.read_text(encoding="utf-8") == "original"
    assert len(attempts) == 3
    assert [file.name for file in tmp_path.iterdir()] == ["wing.py"]
