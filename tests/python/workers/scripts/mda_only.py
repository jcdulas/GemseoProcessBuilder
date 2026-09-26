"""An MDA of two coupled formulas, executed once."""

from gemseo import create_discipline, create_mda

if __name__ == "__main__":
    disciplines = create_discipline(
        "AnalyticDiscipline",
        expressions={"y1": "x + 0.5*y2"},
        name="First",
    ), create_discipline("AnalyticDiscipline", expressions={"y2": "2 - 0.2*y1"}, name="Second")
    mda = create_mda("MDAChain", list(disciplines))
    print(mda.execute())
