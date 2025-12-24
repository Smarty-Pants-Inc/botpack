"""Interactive TUI testing helpers.

This package intentionally keeps its surface small and dependency-free:
- tmux wrapper for launching TUIs with transcript capture
- matrix artifact helpers for recording results
"""

from .matrix import MatrixRun, MatrixStatus  # noqa: F401
from .tmux import TmuxSession  # noqa: F401
