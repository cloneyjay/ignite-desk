"""Entry point for the single trading process.

Runs uvicorn with the FastAPI factory. In production, this is the only
process needed — it serves the API and runs the trading scheduler.
"""

from __future__ import annotations

import uvicorn

from backend.ignite.api.app import create_app
from backend.ignite.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "backend.ignite.api.app:create_app",
        host=settings.bind_host,
        port=settings.bind_port,
        factory=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()