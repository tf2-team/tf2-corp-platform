from __future__ import annotations

import os

import uvicorn

from aiops.api import create_app


def run() -> None:
    """Start the AIOps API process from validated environment settings."""
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=int(os.environ.get("AIOPS_PORT", "8080")),
        log_level=os.environ.get("AIOPS_LOG_LEVEL", "info").lower(),
        access_log=False,
    )


if __name__ == "__main__":
    run()
