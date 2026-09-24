import time

import pytest

import gemseo_process_builder


def test_version_is_a_string() -> None:
    assert isinstance(gemseo_process_builder.__version__, str)


@pytest.mark.skip(reason="manual check of the one-second timeout")
def test_timeout_is_enforced() -> None:
    time.sleep(1.5)
