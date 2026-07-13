"""CLI package for observability-aiops.

Re-exports ``app`` so the pyproject entry point
``observability-aiops = "observability_aiops.cli:app"`` works unchanged.
"""

from observability_aiops.cli._root import app

__all__ = ["app"]
