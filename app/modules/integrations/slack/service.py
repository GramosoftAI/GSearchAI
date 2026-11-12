"""Backward-compatible re-export shim; canonical module is `app.modules.connectors.slack.service`."""

from app.modules.connectors.slack.service import SLACK_BOT_SCOPES, SlackService  # noqa: F401

__all__ = ["SLACK_BOT_SCOPES", "SlackService"]
