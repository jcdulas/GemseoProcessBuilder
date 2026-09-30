"""The design as an engineer sees it: physical maps, indicators, restarts (spec § 4.8).

A model whose design lies on a grid describes its physics through a protocol
of one of its disciplines, :class:`PhysicalDesign` (structural: the model does
not import the copilot): the physical problem in words, the grid, the design
variable and the constraints laid on it, the geometric features, the supports,
the loads, and physical fields it computes at a point, each with its meaning.

From this the copilot draws, generically:

- **text maps** of at most ``MAP_SIZE`` × ``MAP_SIZE`` characters, a larger grid
  reduced by blocks as each field says (the mean of a density, the maximum of
  a stress), the supports, loads and features marked;
- **physical indicators**: whether solid material carries each load to the
  supports, the width of the members against the smallest one the filter
  allows, the gray and the dead material, the stress hot spots and the feature
  they sit at, checkerboards, where the constraints cost most;
- **restarts**: a starting design made from a past one by transformations on
  the grid (binarize, smooth, fill or empty a region, connect two points,
  blend with another evaluation).

Positions are given in the coordinates of the maps: ``[row, column]``, row 0
at the bottom, one map cell being ``factor`` × ``factor`` cells of the grid.

Example:
    >>> source = DesignSource.find(scenario, snapshot)
    >>> view = source.view(entries, snapshot)
    >>> print(view.text_map("density", "best"))
"""

from gemseo_claude_pilot.design.description import MAP_SIZE
from gemseo_claude_pilot.design.description import DesignError
from gemseo_claude_pilot.design.description import FieldInfo
from gemseo_claude_pilot.design.description import Grid
from gemseo_claude_pilot.design.description import PhysicalDescription
from gemseo_claude_pilot.design.description import PhysicalDesign
from gemseo_claude_pilot.design.description import check_description
from gemseo_claude_pilot.design.indicators import compare
from gemseo_claude_pilot.design.indicators import indicators
from gemseo_claude_pilot.design.maps import text_map
from gemseo_claude_pilot.design.source import DesignSource
from gemseo_claude_pilot.design.transforms import Binarize
from gemseo_claude_pilot.design.transforms import Blend
from gemseo_claude_pilot.design.transforms import Connect
from gemseo_claude_pilot.design.transforms import SetRegion
from gemseo_claude_pilot.design.transforms import Smooth
from gemseo_claude_pilot.design.transforms import Transform
from gemseo_claude_pilot.design.transforms import apply_transforms
from gemseo_claude_pilot.design.transforms import transform_errors
from gemseo_claude_pilot.design.transforms import transforms_help
from gemseo_claude_pilot.design.view import DesignPoint
from gemseo_claude_pilot.design.view import DesignView
from gemseo_claude_pilot.design.view import RestartRecord
from gemseo_claude_pilot.design.view import entry_point

__all__ = [
    "MAP_SIZE",
    "Binarize",
    "Blend",
    "Connect",
    "DesignError",
    "DesignPoint",
    "DesignSource",
    "DesignView",
    "FieldInfo",
    "Grid",
    "PhysicalDescription",
    "PhysicalDesign",
    "RestartRecord",
    "SetRegion",
    "Smooth",
    "Transform",
    "apply_transforms",
    "check_description",
    "compare",
    "entry_point",
    "indicators",
    "text_map",
    "transform_errors",
    "transforms_help",
]
