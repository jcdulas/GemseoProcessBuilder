"""The physical view of the design: maps, indicators, transformations (plan 71)."""

import numpy as np
import pytest
from design_samples import BAR
from design_samples import bar_view
from design_samples import description
from design_samples import drawing
from design_samples import plate
from design_samples import view

from gemseo_claude_pilot.design import Binarize
from gemseo_claude_pilot.design import Blend
from gemseo_claude_pilot.design import Connect
from gemseo_claude_pilot.design import DesignError
from gemseo_claude_pilot.design import SetRegion
from gemseo_claude_pilot.design import Smooth
from gemseo_claude_pilot.design import apply_transforms
from gemseo_claude_pilot.design import check_description
from gemseo_claude_pilot.design import indicators
from gemseo_claude_pilot.design import transform_errors

CUT = [
    "#.......",
    "#.......",
    "####.###",
    "#.......",
    "#.......",
    "#.......",
]
"""The bar cut in its middle: the load path open."""


def test_the_density_map_of_a_known_design():
    text = bar_view().text_map("density", "best")
    lines = text.splitlines()
    assert lines[0] == "density: physical density, at best"
    assert "'S' support, 'F' load, 'A' notch" in lines[1]
    assert "one map cell = 1 x 1 cells (mean)" in lines[2]
    assert lines[3:] == [
        "  0       ",
        "  01234567",
        "5 S...A...",
        "4 S.......",
        "3 S######F",
        "2 S.......",
        "1 S.......",
        "0 S.......",
    ]


def test_a_large_grid_is_reduced_by_blocks():
    rows = columns = 125
    ratio = np.full((rows, columns), 0.2)
    ratio[10, 10] = 1.5  # Violated: its block shows it.
    ratio[100, 60] = 0.95  # The maximum of its block is kept.
    large = view({"stress_ratio": ratio}, rows, columns)
    grid = large.grid
    assert grid.factor == 4
    assert (grid.map_rows, grid.map_columns) == (32, 32)
    lines = large.text_map("stress_ratio", "best").splitlines()[5:]
    assert len(lines) == 32
    row = {int(line[:3]): line[3:] for line in lines}
    assert row[10 // 4][10 // 4] == "!"
    assert row[100 // 4][60 // 4] == "9"
    assert row[0][1] == "2"


def test_the_load_path_closed_then_cut():
    closed = indicators(bar_view(), bar_view().points["best"])["load_path"]
    assert closed["loads"] == [{"load": "load", "connected": True}]
    cut_view = bar_view(CUT)
    cut = indicators(cut_view, cut_view.points["best"])["load_path"]
    (load,) = cut["loads"]
    assert load["connected"] is False
    assert load["why"] == "no solid path from the load to a support"
    assert load["gap"] == 1.0
    assert (load["from"], load["to"]) == ([3, 5], [3, 3])
    assert cut["floating_parts"] == 1


def test_a_member_thinner_than_the_filter():
    members = indicators(bar_view(), bar_view().points["best"])["members"]
    assert members["minimum_member_size"] == 3.0
    assert members["median_width"] == 1.0
    assert members["thin_share"] == 1.0
    assert members["thin_members"][0]["width"] == 1.0


def test_gray_and_dead_material():
    lines = ["########", "########", "++++++++", "::::::::", "........", "........"]
    energy = np.ones((6, 8))
    energy[5, :] = 0.0  # The top row carries nothing.
    gray = bar_view(lines, strain_energy=energy)
    found = indicators(gray, gray.points["best"])
    assert found["material"]["gray_share"] == pytest.approx(2 / 6, abs=1e-3)
    assert found["material"]["solid_share"] == pytest.approx(2 / 6, abs=1e-3)
    dead = found["dead_material"]
    assert dead["share_of_solid"] == pytest.approx(8 / 24, abs=1e-3)
    assert dead["zones"][0] == {"at": [5, 4], "cells": 8}


def test_a_checkerboard():
    lines = ["#.#.#.#.", ".#.#.#.#", "########", "#.......", "#.......", "#......."]
    board = bar_view(lines)
    assert indicators(board, board.points["best"])["checkerboard"]["blocks"] == 7


def test_a_hot_spot_at_a_feature():
    ratio = np.full((6, 8), 0.3)
    ratio[5, 3:6] = [0.99, 1.2, 1.1]  # At the notch, violated.
    ratio[0, 0] = 0.985  # Active, far from any feature.
    # Within three minimum member sizes of a feature, a hot spot is at it.
    density = drawing(BAR)
    hot = view(
        {"density": density, "design": density, "stress_ratio": ratio},
        minimum_member_size=1.0,
    )
    spots = indicators(hot, hot.points["best"])["hot_spots"]
    assert spots["violated_cells"] == 2
    assert spots["active_cells"] == 4
    first, second = spots["zones"]
    assert first["peak"] == 1.2
    assert first["at_feature"] == "notch"
    assert first["at"] == [5, 4]
    assert "at_feature" not in second


def test_the_transformations():
    grid = bar_view().grid
    design = drawing(["::::::::"] * 6)
    binarized = apply_transforms(
        design, [Binarize(threshold=0.2)], grid, lambda i: design
    )
    assert (binarized == 1).all()
    region = apply_transforms(
        drawing(BAR),
        [SetRegion(shape="rectangle", rows=(0, 1), columns=(6, 7), value=1.0)],
        grid,
        lambda i: design,
    )
    assert region[0, 6:].tolist() == [1.0, 1.0] and region[1, 6:].tolist() == [1.0, 1.0]
    disk = apply_transforms(
        drawing(BAR),
        [SetRegion(shape="disk", center=(3, 4), radius=0.5, value=0.0)],
        grid,
        lambda i: design,
    )
    assert disk[3, 4] == 0.0 and disk[3, 3] == 1.0
    smooth = apply_transforms(
        drawing(BAR), [Smooth(radius=1.0)], grid, lambda i: design
    )
    assert 0 < smooth[2, 4] < 1
    blended = apply_transforms(
        drawing(BAR), [Blend(evaluation=0, weight=0.5)], grid, lambda i: design
    )
    assert blended[0, 4] == pytest.approx(0.15)


def test_connect_closes_a_cut_load_path():
    cut_view = bar_view(CUT)
    closed = apply_transforms(
        drawing(CUT),
        [Connect(start=(3, 3), end=(3, 5), width=1.0)],
        cut_view.grid,
        lambda i: drawing(CUT),
    )
    after = view({"density": closed, "design": closed})
    assert indicators(after, after.points["best"])["load_path"]["loads"][0]["connected"]


def test_transformations_outside_the_map_are_refused():
    grid = bar_view().grid
    reasons = transform_errors(
        [
            SetRegion(shape="rectangle", rows=(0, 9), columns=(0, 1), value=1.0),
            SetRegion(shape="disk", value=0.0),
            Connect(start=(0, 0), end=(3, 12), width=1.0),
            Blend(evaluation=5, weight=0.5),
        ],
        grid,
        evaluations=4,
    )
    assert reasons == [
        "the rectangle corner [9, 1] is outside the map of 6 rows and 8 columns",
        "a disk needs a center and a radius",
        "the end of the bar [3, 12] is outside the map of 6 rows and 8 columns",
        "there is no evaluation 5 to blend with",
    ]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"variable_cells": [0, 1]}, "2 cells for the 48 components of x"),
        ({"variable": "y"}, "there is no design variable named y"),
        (
            {"loads": [{"name": "load", "cells": [99]}]},
            "the load load has cells outside",
        ),
        ({"constraint_cells": {"h": [0]}}, "there is no constraint named h"),
    ],
)
def test_a_description_that_does_not_fit_is_refused(changes, message):
    with pytest.raises(DesignError, match=message):
        check_description(description(**changes), plate())


def test_the_context_of_the_design():
    hot = bar_view(stress_ratio=np.full((6, 8), 0.5))
    brief = hot.context(detail=False)
    assert set(brief) == {"physics", "points", "fields"}
    assert brief["physics"]["supports"] == [
        {"name": "clamp", "extent": [[0, 0], [5, 0]], "blocks": "x and y"}
    ]
    assert brief["physics"]["features"][0]["at"] == [5, 4]
    detail = hot.context(detail=True)["detail"]
    assert set(detail["maps"]) == {"density", "stress_ratio"}
    assert detail["indicators"]["load_path"]["loads"][0]["connected"]


def test_an_unknown_field_or_point():
    with pytest.raises(DesignError, match="has no field"):
        bar_view().text_map("temperature", "best")
    with pytest.raises(DesignError, match="there is no point current"):
        bar_view().text_map("density", "current")
