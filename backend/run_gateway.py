"""Entry point: python -m backend.run_gateway"""
from __future__ import annotations

import uvicorn

from backend.shared.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "backend.gateway.main:app",
        host=settings.gateway_host,
        port=settings.gateway_port,
        reload=True,
        log_level=settings.log_level.lower(),
    )
