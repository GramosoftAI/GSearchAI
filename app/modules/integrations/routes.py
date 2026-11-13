"""Aggregated Integrations Router for Dynamic Router Loader.

Note: Slack connector routes are registered via `app.modules.connectors.routes`.
"""

from fastapi import APIRouter

router = APIRouter()
