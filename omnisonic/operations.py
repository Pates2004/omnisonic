"""Thread-safe operation state shared by GUI workers and tests."""

from __future__ import annotations

import logging
import threading
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
    finally:
        state.finished_event.set()
    return state
