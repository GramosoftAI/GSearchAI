"""Backward-compatible re-export shim; canonical module is `app.modules.connectors.slack.schemas`."""

from app.modules.connectors.slack.schemas import (  # noqa: F401
    SlackChannelInfo,
    SlackConnectResponse,
    SlackConnectionResponse,
    SlackDisconnectRequest,
    SlackSetChannelRequest,
)

__all__ = [
    "SlackConnectResponse",
    "SlackChannelInfo",
    "SlackSetChannelRequest",
    "SlackConnectionResponse",
    "SlackDisconnectRequest",
]
