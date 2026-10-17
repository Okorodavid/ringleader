"""Vercel entry point: exposes the FastAPI app as one serverless function (see vercel.json)."""
from app.main import app  # noqa: F401 - Vercel looks for a module-level ASGI `app`
