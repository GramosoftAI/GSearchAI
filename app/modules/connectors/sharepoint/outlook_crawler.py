"""Outlook Crawler and message export engine via Microsoft Graph API."""

import html as html_lib
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any, Callable, Dict, List, Optional

import httpx

from app.core.connectors import (
    CheckpointedConnector,
    ConnectorCheckpoint,
    HierarchyNode,
    SlimDocument,
    StageCompletion,
)
from .auth import SharePointAuthManager, execute_graph_request

logger = logging.getLogger(__name__)

WELL_KNOWN_FOLDER_MAP = {
    "inbox": "inbox",
    "sent": "sentitems",
    "sent items": "sentitems",
    "sentitems": "sentitems",
    "drafts": "drafts",
    "deleted": "deleteditems",
    "deleted items": "deleteditems",
    "deleteditems": "deleteditems",
    "junk": "junkemail",
    "junk email": "junkemail",
    "junkemail": "junkemail",
    "archive": "archive",
}


def normalize_outlook_folder_id(folder_id: Optional[str]) -> Optional[str]:
    """Map display folder names like 'Sent Items' or 'Inbox' to Graph well-known IDs."""
    if not folder_id:
        return None
    cleaned = folder_id.strip()
    return WELL_KNOWN_FOLDER_MAP.get(cleaned.lower(), cleaned)


def strip_html_to_text(raw_body: str) -> str:
    """Convert HTML email bodies to clean readable plain text."""
    if not raw_body:
        return ""
    if "<" not in raw_body and ">" not in raw_body:
        return raw_body.strip()

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(raw_body, "html.parser")
        for tag in soup(["script", "style", "head"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
    except Exception:
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw_body, flags=re.I | re.S)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = re.sub(r"</(p|div|li|tr|h[1-6])>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html_lib.unescape(text)

    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


class OutlookConnector(CheckpointedConnector[ConnectorCheckpoint]):
    """
    Checkpointed crawler for Outlook via Microsoft Graph API.
    Fetches messages from a user's mailbox.
    """

    def __init__(
        self,
        folder_id: Optional[str] = None,
        max_results: int = 100,
        on_token_refresh: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.auth_manager = SharePointAuthManager(on_token_refresh=on_token_refresh)
        self.folder_id = normalize_outlook_folder_id(folder_id)
        self.max_results = max_results

    def load_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any] | None:
        return self.auth_manager.load_credentials(credentials)

    def export_credentials(self) -> Dict[str, Any]:
        return self.auth_manager.export_credentials()

    def build_dummy_checkpoint(self) -> ConnectorCheckpoint:
        return ConnectorCheckpoint(has_more=True, completion_stage="start")

    def validate_checkpoint_json(self, checkpoint_json: str) -> ConnectorCheckpoint:
        try:
            return ConnectorCheckpoint.model_validate_json(checkpoint_json)
        except Exception as e:
            logger.warning("Failed to validate checkpoint JSON: %s, falling back to dummy", e)
            return self.build_dummy_checkpoint()

    async def _graph_get_with_me_fallback(
        self,
        user_email: Optional[str],
        path_suffix: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a Graph GET request on `/users/{email}/...` and fall back to `/me/...` for delegated auth."""
        if not user_email or user_email.lower() == "me":
            return await execute_graph_request(
                self.auth_manager, "GET", f"/me{path_suffix}", params=params
            )

        try:
            return await execute_graph_request(
                self.auth_manager,
                "GET",
                f"/users/{urllib.parse.quote(user_email)}{path_suffix}",
                params=params,
            )
        except httpx.HTTPStatusError as http_err:
            if http_err.response is not None and http_err.response.status_code in (400, 403, 404):
                logger.info(
                    "Falling back from /users/%s%s to /me%s (status %s)",
                    user_email,
                    path_suffix,
                    path_suffix,
                    http_err.response.status_code,
                )
                return await execute_graph_request(
                    self.auth_manager, "GET", f"/me{path_suffix}", params=params
                )
            raise

    async def list_mail_folders(self, user_email: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch real mail folders from Microsoft Graph."""
        folders: List[Dict[str, Any]] = []
        next_url: Optional[str] = None

        while True:
            if next_url:
                res = await execute_graph_request(self.auth_manager, "GET", next_url)
            else:
                res = await self._graph_get_with_me_fallback(
                    user_email, "/mailFolders", params={"$top": 100}
                )

            for folder in res.get("value", []):
                folders.append({
                    "id": folder.get("id"),
                    "name": folder.get("displayName"),
                    "is_folder": True,
                    "total_item_count": folder.get("totalItemCount", 0),
                    "unread_item_count": folder.get("unreadItemCount", 0),
                })

            next_url = res.get("@odata.nextLink")
            if not next_url:
                break

        return folders

    async def get_message_content(self, user_email: str, message_id: str) -> Dict[str, Any]:
        """Fetch full message payload from Microsoft Graph and normalize HTML body to text."""
        try:
            res = await self._graph_get_with_me_fallback(
                user_email, f"/messages/{message_id}"
            )

            raw_body = res.get("body", {}).get("content", "") or ""
            content_type = (res.get("body", {}).get("contentType") or "").lower()
            body_text = strip_html_to_text(raw_body) if content_type == "html" or "<" in raw_body else raw_body.strip()

            subject = res.get("subject", "No Subject")
            sender_dict = res.get("from", {}).get("emailAddress", {})
            sender = sender_dict.get("address", "Unknown Sender")
            date_str = res.get("receivedDateTime", "")

            return {
                "id": message_id,
                "subject": subject,
                "sender": sender,
                "date": date_str,
                "snippet": res.get("bodyPreview", ""),
                "body": body_text or res.get("bodyPreview", ""),
            }
        except Exception as e:
            logger.error("Failed to fetch Outlook message %s: %s", message_id, e)
            return {}

    async def load_from_checkpoint(
        self,
        start: float,
        end: float,
        checkpoint: ConnectorCheckpoint,
    ) -> AsyncGenerator[SlimDocument | HierarchyNode, None]:
        emails_to_crawl = checkpoint.user_emails or ["me"]

        for email in emails_to_crawl:
            if email not in checkpoint.completion_map:
                checkpoint.completion_map[email] = StageCompletion(
                    stage="crawling", completed_until=start
                )

            completion = checkpoint.completion_map[email]
            if completion.stage == "done":
                continue

            logger.info("Starting Outlook crawl for user: %s (folder=%s)", email, self.folder_id)

            has_more_pages = True
            next_link = completion.next_page_token
            messages_fetched = 0

            path_suffix = (
                f"/mailFolders/{self.folder_id}/messages"
                if self.folder_id
                else "/messages"
            )

            while has_more_pages and messages_fetched < self.max_results:
                try:
                    if next_link:
                        res = await execute_graph_request(self.auth_manager, "GET", next_link)
                    else:
                        params = {"$top": min(50, self.max_results - messages_fetched)}
                        res = await self._graph_get_with_me_fallback(
                            email, path_suffix, params=params
                        )
                except Exception as e:
                    logger.error("Failed to list Outlook messages for %s: %s", email, e)
                    completion.next_page_token = next_link
                    checkpoint.has_more = True
                    return

                messages = res.get("value", [])
                for msg in messages:
                    if messages_fetched >= self.max_results:
                        break
                    msg_id = msg.get("id")
                    if not msg_id or msg_id in checkpoint.all_retrieved_file_ids:
                        continue

                    messages_fetched += 1
                    meta = {
                        "message_id": msg_id,
                        "user_email": email,
                        "source_type": "outlook_message",
                        "folder_id": self.folder_id,
                    }

                    yield SlimDocument(
                        id=msg_id,
                        source="outlook",
                        metadata=meta,
                    )

                    checkpoint.all_retrieved_file_ids.add(msg_id)

                next_link = res.get("@odata.nextLink")
                completion.next_page_token = next_link
                has_more_pages = bool(next_link)

            completion.stage = "done"

        all_done = all(comp.stage == "done" for comp in checkpoint.completion_map.values())
        checkpoint.has_more = not all_done
        return
