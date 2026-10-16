"""Optional task-local HTTP health, without URLs, bodies, headers or credentials."""
from contextvars import ContextVar
from contextlib import contextmanager

_current = ContextVar("acquisition_http_outcomes", default=None)


def observe(status=None, error=None):
    current = _current.get()
    if current is not None:
        if status is not None:
            current["statuses"].add(status)
        if error is not None:
            current["errors"].add(type(error).__name__)


@contextmanager
def capture():
    outcomes = {"statuses": set(), "errors": set()}
    token = _current.set(outcomes)
    try:
        yield outcomes
    finally:
        _current.reset(token)
