"""Backward-compatible re-export shim; canonical module is `app.modules.connectors.slack.worker`."""

from app.modules.connectors.slack.worker import (  # noqa: F401
    process_slack_event_task,
    slack_event_job,
)

__all__ = ["process_slack_event_task", "slack_event_job"]
