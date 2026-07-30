"""Vercel entrypoint.

Vercel's Python runtime serves ASGI applications natively: any ``api/*.py``
file that exposes a FastAPI/ASGI ``app`` object is mounted as a function.
``vercel.json`` rewrites every route to this file so the whole API
(including ``/`` and ``/api/v1/*``) is served by the FastAPI application.
"""

import os
import sys

# Make the repository root importable when this file is executed as a Vercel
# function (the function's working directory is ./api).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402  — FastAPI ASGI app picked up by Vercel

__all__ = ["app"]
