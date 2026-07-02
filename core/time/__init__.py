"""Time layer — isolated timing utilities."""

import datetime


def now_iso() -> str:
    """Current time in ISO 8601 format."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
