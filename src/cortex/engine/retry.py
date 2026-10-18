"""Retry policy: classify task failures transient vs permanent."""

TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "RateLimitError",
    "APIConnectionError",
    "InternalServerError",
    "APITimeoutError",
    "TargetClosedError",
    "BrowserError",
    "connection",
    "crash",
)

# These failure reasons are deliberate — retrying cannot change the outcome.
PERMANENT_MARKERS = (
    "domain_blocked",
    "session_expired",
    "session_in_use",
    "approval denied",
    "cancelled",
    "agent_unavailable",
)


class TransientTaskError(Exception):
    """Raised by the runner when a task fails with a retryable error."""


def classify(exc_or_msg: BaseException | str) -> str:
    """Return 'transient' | 'permanent' for an exception or error string."""
    if isinstance(exc_or_msg, BaseException):
        text = f"{type(exc_or_msg).__name__} {exc_or_msg}"
    else:
        text = exc_or_msg
    lowered = text.lower()
    if any(m.lower() in lowered for m in PERMANENT_MARKERS):
        return "permanent"
    if any(m.lower() in lowered for m in TRANSIENT_MARKERS):
        return "transient"
    # Unknown failures are permanent — retrying what we don't understand
    # wastes money and can loop forever.
    return "permanent"
