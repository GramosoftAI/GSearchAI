"""Backward-compatible re-export shim; canonical module is `app.modules.connectors.slack.routes`."""

from app.modules.connectors.slack.routes import (  # noqa: F401
    _get_tenant_id,
    connect_slack,
    disconnect_slack,
    list_slack_channels,
    router,
    set_slack_channel,
    slack_events_webhook,
    slack_oauth_callback,
)

__all__ = [
    "router",
    "_get_tenant_id",
    "connect_slack",
    "slack_oauth_callback",
    "list_slack_channels",
    "set_slack_channel",
    "disconnect_slack",
    "slack_events_webhook",
]
