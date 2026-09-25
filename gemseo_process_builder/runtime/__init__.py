"""Helpers used by generated scripts and by user code (no Qt dependency).

``ExecutableDiscipline`` needs GEMSEO: it is imported from
``gemseo_process_builder.runtime.executable`` so that this package stays light.
"""

from gemseo_process_builder.runtime.decorators import component

__all__ = ["component"]
