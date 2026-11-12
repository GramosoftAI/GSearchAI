"""Backward-compatible re-export shim; canonical module is `app.modules.connectors.slack`."""

from app.modules.connectors.slack import (  # noqa: F401
    SlackClient,
    SlackConnection,
    SlackEvent,
    SlackService,
    router,
)

__all__ = [
    "router",
    "SlackService",
    "SlackConnection",
    "SlackEvent",
    "SlackClient",
]
