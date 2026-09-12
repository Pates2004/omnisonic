"""Thread-safe operation state shared by GUI workers and tests."""

from __future__ import annotations

import logging
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


class OperationCancelled(Exception):
    """Raised by a cooperative worker after cancellation was requested."""


@dataclass
class OperationState:
    name: str = "operation"
    cancel_event: threading.Event = field(default_factory=threading.Event)
    finished_event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Exception | None = None
    _progress: tuple[int, int, str] = (0, 0, "")
    _progress_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set_progress(self, done: int, total: int, message: str = "") -> None:
        with self._progress_lock:
            self._progress = (max(0, min(done, total)), max(0, total), message)

    def get_progress(self) -> tuple[int, int, str]:
        with self._progress_lock:
            return self._progress

    @property
    def cancel_flag(self) -> bool:
        """Compatibility property for existing worker code."""
        return self.cancel_event.is_set()

    @cancel_flag.setter
    def cancel_flag(self, value: bool) -> None:
        if value:
            self.cancel_event.set()
        else:
            self.cancel_event.clear()

    @property
    def finished(self) -> bool:
        return self.finished_event.is_set()

    @property
    def succeeded(self) -> bool:
        return self.finished and not self.cancel_flag and self.error is None

    def request_cancel(self) -> None:
        self.cancel_event.set()

    def check_cancelled(self) -> None:
        if self.cancel_flag:
            raise OperationCancelled()


def execute_worker(state: OperationState, worker: Callable[..., Any], *args: Any) -> OperationState:
    """Execute a worker and always capture its result, error, and completion."""
    try:
        state.check_cancelled()
        state.result = worker(state, *args)
        state.check_cancelled()
    except OperationCancelled:
        state.request_cancel()
    except Exception as exc:
        state.error = exc
        logger.exception("%s failed", state.name)
        # Keep the error message, not model/tensor references in worker frames.
        seen = set()
        error = exc
        while error is not None and id(error) not in seen:
            seen.add(id(error))
            traceback.clear_frames(error.__traceback__)
            error = error.__cause__ or error.__context__
    finally:
        state.finished_event.set()
    return state
