# Copyright (c) 2026 UNI Global Union. All rights reserved. See LICENSE.
"""Run both sidecar surfaces in one process so they share in-memory state.

Public surface  → 127.0.0.1:8000 (Nginx public listener, container port 80)
Backend surface → 127.0.0.1:8001 (Nginx backend listener, container port 8080)
"""

import asyncio

import uvicorn

from sidecar.main import app, backend_app


async def main():
    servers = [
        uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="info")),
        uvicorn.Server(uvicorn.Config(backend_app, host="127.0.0.1", port=8001, log_level="info")),
    ]
    tasks = [asyncio.create_task(s.serve()) for s in servers]
    # If either server stops (signal or crash), stop the other one too so
    # supervisord restarts the pair together.
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for s in servers:
        s.should_exit = True
    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
