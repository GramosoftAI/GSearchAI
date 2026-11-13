"""Backward-compatible re-export shim; canonical module is `app.modules.connectors.slack.client`."""

from app.modules.connectors.slack.client import SLACK_API_BASE, SlackClient  # noqa: F401

__all__ = ["SLACK_API_BASE", "SlackClient"]
