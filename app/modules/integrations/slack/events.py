"""Backward-compatible re-export shim; canonical module is `app.modules.connectors.slack.events`."""

from app.modules.connectors.slack.events import (  # noqa: F401
    SLACK_SESSION_NAMESPACE,
    clean_slack_text,
    format_slack_response,
    generate_slack_session_id,
    generate_slack_user_id,
    is_bot_event,
)

__all__ = [
    "SLACK_SESSION_NAMESPACE",
    "clean_slack_text",
    "generate_slack_session_id",
    "generate_slack_user_id",
    "is_bot_event",
    "format_slack_response",
]
