"""The area of a rectangular wing: an example of a Python function component.

GEMSEO Process Builder reads the function as GEMSEO's AutoPyDiscipline does:
its arguments are the inputs, their default values the default inputs, and
the names it returns are the outputs. Edit it and save the file: the component
follows.
"""


def wing_area(span=10.0, chord=2.0):
    """The area and the aspect ratio of a rectangular wing."""
    area = span * chord
    aspect_ratio = span / chord
    return area, aspect_ratio
