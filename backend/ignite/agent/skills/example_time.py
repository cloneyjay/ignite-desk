"""Example time skill stub."""

skill_meta = {
    "name": "example_time",
    "description": "Example time skill for demonstration purposes.",
}


def now_timestamp() -> float:
    """Return current Unix timestamp."""
    import time
    return time.time()


def format_timestamp(ts: float) -> str:
    """Format timestamp to ISO string."""
    import datetime
    return datetime.datetime.fromtimestamp(ts).isoformat()
