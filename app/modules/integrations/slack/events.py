"""Slack event payload parsing, message cleaning, session generation, and formatting."""

import re
import html
import uuid
from typing import Optional, List, Dict, Any


def clean_slack_text(text: str) -> str:
    """
    Cleans incoming Slack message text:
    - Removes bot mentions `<@U[A-Z0-9]+>`
    - Replaces user mentions `<@U[A-Z0-9]+|label>` with label or removes
    - Replaces URLs `<http...|label>` with label or raw url
    - Decodes HTML entities (&amp;, &lt;, &gt;)
    """
    if not text:
        return ""

    # Unescape HTML entities
    cleaned = html.unescape(text)

    # Remove bot/user mentions without label: <@U12345678>
    cleaned = re.sub(r"<@[A-Z0-9]+>", "", cleaned)

    # Replace mentions with label: <@U12345678|alice> -> alice
    cleaned = re.sub(r"<@[A-Z0-9]+\|([^>]+)>", r"\1", cleaned)

    # Replace special commands: <!here>, <!channel>, <!everyone>
    cleaned = re.sub(r"<!(here|channel|everyone)>", r"\1", cleaned)

    # Replace links with label: <https://example.com|Example> -> Example (https://example.com)
    cleaned = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"\2 (\1)", cleaned)

    # Clean raw URLs: <https://example.com> -> https://example.com
    cleaned = re.sub(r"<(https?://[^>]+)>", r"\1", cleaned)

    # Strip excess whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned


SLACK_SESSION_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def generate_slack_session_id(
    team_id: str,
    channel_id: str,
    thread_ts: Optional[str] = None,
    message_ts: Optional[str] = None,
) -> str:
    """
    Generate a deterministic UUID session ID scoped to the conversation context:
    - If in a thread: binds to thread_ts, keeping multi-turn thread history.
    - If not in a thread: binds to channel_id or top-level message ts.
    Uses uuid.uuid5 to guarantee valid PostgreSQL UUID column format while maintaining determinism.
    """
    context_ts = thread_ts or message_ts or channel_id
    raw_key = f"slack:{team_id}:{channel_id}:{context_ts}"
    return str(uuid.uuid5(SLACK_SESSION_NAMESPACE, raw_key))


def generate_slack_user_id(slack_user_id: Optional[str]) -> str:
    """Generate a deterministic UUID from Slack user ID for database persistence."""
    if not slack_user_id:
        return "00000000-0000-0000-0000-000000000000"
    return str(uuid.uuid5(SLACK_SESSION_NAMESPACE, f"slack:user:{slack_user_id}"))


def is_bot_event(event_data: Dict[str, Any], bot_user_id: Optional[str] = None) -> bool:
    """
    Check if event originated from a bot or sub-type message to prevent recursive loops.
    """
    if not event_data or not isinstance(event_data, dict):
        return True

    # Check bot_id field
    if event_data.get("bot_id"):
        return True

    # Check subtype
    subtype = event_data.get("subtype")
    if subtype in ("bot_message", "message_changed", "message_deleted"):
        return True

    # Check if author matches this bot's user ID
    user = event_data.get("user")
    if bot_user_id and user == bot_user_id:
        return True

    return False


def format_slack_response(
    answer: str,
    sources: Optional[List[Dict[str, Any]]] = None,
    include_sources: bool = False,
) -> str:
    """
    Converts standard Markdown answer to Slack mrkdwn format:
    - If include_sources is False (default for Slack), strips `[Source: ...]` citations
    - If include_sources is True, preserves or appends citations
    - Converts `**bold**` to `*bold*`
    - Preserves lists and tables
    """
    if not answer:
        return ""

    formatted = answer

    # If sources shouldn't be shown in Slack, strip all [Source: ...] tags
    if not include_sources:
        formatted = re.sub(r"\s*\[Source:[^\]]*\]", "", formatted).strip()
    else:
        # Append sources if citations were not already formatted in the LLM answer
        if sources and "[Source:" not in formatted:
            clean_source_names = set()
            for src in sources:
                name = None
                if isinstance(src, dict):
                    name = src.get("source") or src.get("kb_name")
                if name:
                    clean_source_names.add(name)

            if clean_source_names:
                sorted_names = sorted(list(clean_source_names))
                formatted += f"\n\n[Source: {', '.join(sorted_names)}]"

    # Convert standard markdown bold **text** to Slack bold *text*
    # (Be careful with already single *italics*)
    formatted = re.sub(r"\*\*(.*?)\*\*", r"*\1*", formatted)

    return formatted
