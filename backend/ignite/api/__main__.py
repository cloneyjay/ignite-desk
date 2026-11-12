"""Run the API: python -m backend.ignite.api"""

from __future__ import annotations

import uvicorn

from backend.ignite.config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "backend.ignite.api.app:create_app",
        factory=True,
        host=settings.bind_host,
        port=settings.bind_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
