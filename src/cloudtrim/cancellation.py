from __future__ import annotations

import threading
from typing import Optional


class OperationCancelled(Exception):
    """Raised when a running operation is cancelled by the user."""


def raise_if_cancelled(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise OperationCancelled
