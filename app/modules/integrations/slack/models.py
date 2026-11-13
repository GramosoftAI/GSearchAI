"""Backward-compatible re-export shim; canonical module is `app.modules.connectors.slack.models`."""

from app.modules.connectors.slack.models import SlackConnection, SlackEvent  # noqa: F401

__all__ = ["SlackConnection", "SlackEvent"]
