"""Aggregated Integrations Router for Dynamic Router Loader."""

from fastapi import APIRouter
from .slack.routes import router as slack_router

router = APIRouter()
router.include_router(slack_router)
