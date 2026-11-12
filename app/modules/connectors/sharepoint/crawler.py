"""SharePoint & OneDrive Crawler using Microsoft Graph API."""

import logging
import urllib.parse
from collections.abc import AsyncGenerator
from typing import Any, Callable, Dict, List, Optional, Set

import httpx

from app.core.connectors import (
    CheckpointedConnector,
    ConnectorCheckpoint,
    HierarchyNode,
    SlimDocument,
)
from .auth import GRAPH_API_BASE, SharePointAuthManager, execute_graph_request

logger = logging.getLogger(__name__)

FOLDER_MIME_TYPE = "application/vnd.microsoft.graph.folder"


class SharePointConnector(CheckpointedConnector[ConnectorCheckpoint]):
    """
    Checkpointed crawler for Microsoft SharePoint / OneDrive.
    Traverses folder structures and downloads binary files for ingestion.
    """

    def __init__(
        self,
        site_urls: Optional[List[str]] = None,
        on_token_refresh: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.auth_manager = SharePointAuthManager(on_token_refresh=on_token_refresh)
        self.site_urls = site_urls or []
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None

    def load_credentials(self, credentials: dict) -> Optional[dict]:
        """Load OAuth or app credentials from database connection parameters."""
        loaded = self.auth_manager.load_credentials(credentials or {})
        self.access_token = self.auth_manager._access_token
        self.refresh_token = self.auth_manager._refresh_token

        if not self.access_token and not (
            self.auth_manager.client_id
            and self.auth_manager.client_secret
            and self.auth_manager.tenant_id
            and self.auth_manager.tenant_id != "common"
        ):
            logger.error("Missing SharePoint OAuth access token or app credentials")
            return None

        return loaded

    def export_credentials(self) -> Dict[str, Any]:
        """Expose latest credentials (including refreshed tokens) for DB persistence."""
        return self.auth_manager.export_credentials()

    def get_headers(self) -> dict:
        """Return authorization headers using the current access token."""
        token = self.auth_manager._access_token or self.access_token
        if not token:
            raise ValueError("Access token is missing. User must authenticate via OAuth.")
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def build_dummy_checkpoint(self) -> ConnectorCheckpoint:
        return ConnectorCheckpoint(
            has_more=True,
            completion_stage="start",
        )

    def validate_checkpoint_json(self, checkpoint_json: str) -> ConnectorCheckpoint:
        try:
            return ConnectorCheckpoint.model_validate_json(checkpoint_json)
        except Exception as e:
            logger.warning("Failed to validate checkpoint JSON: %s, falling back to dummy", e)
            return self.build_dummy_checkpoint()

    async def get_site_id_from_url(self, url: str) -> Optional[str]:
        """Resolve a SharePoint web URL or Graph site URL to a Microsoft Graph Site ID."""
        try:
            if not url:
                return None
            if url == "root":
                return "root"

            parsed = urllib.parse.urlparse(url)
            hostname = parsed.hostname
            if not hostname:
                return None

            path = (parsed.path or "").rstrip("/")

            # Handle direct Microsoft Graph site URLs (e.g., https://graph.microsoft.com/v1.0/sites/root)
            if hostname == "graph.microsoft.com":
                if "/sites/" in path:
                    endpoint = "/sites/" + path.split("/sites/", 1)[1]
                else:
                    endpoint = "/sites/root"
                res = await execute_graph_request(self.auth_manager, "GET", endpoint)
                return res.get("id") or "root"

            parts = [p for p in path.split("/") if p]
            if len(parts) >= 2 and parts[0] in ("sites", "teams"):
                site_path = f"/{parts[0]}/{parts[1]}"
                endpoint = f"/sites/{hostname}:{site_path}"
            else:
                endpoint = f"/sites/{hostname}"

            res = await execute_graph_request(self.auth_manager, "GET", endpoint)
            return res.get("id")
        except Exception as e:
            logger.error("Failed to resolve site ID for %s: %s", url, e)
            return None

    async def list_directory(self, parent_id: str) -> List[Dict[str, Any]]:
        """List files and folders directly within a SharePoint folder, drive, or site root (paginated)."""
        try:
            if ":" in parent_id:
                drive_id, item_id = parent_id.split(":", 1)
                endpoint = f"/drives/{drive_id}/items/{item_id}/children"
            elif parent_id == "onedrive":
                endpoint = "/me/drive/root/children"
            else:
                endpoint = f"/sites/{parent_id}/drive/root/children"

            formatted_items: List[Dict[str, Any]] = []
            next_url: Optional[str] = endpoint

            while next_url:
                try:
                    res = await execute_graph_request(self.auth_manager, "GET", next_url)
                except httpx.HTTPStatusError as http_err:
                    # Fallback to user's personal OneDrive root if /sites/root is unavailable
                    if (
                        parent_id == "root"
                        and next_url == endpoint
                        and http_err.response is not None
                        and http_err.response.status_code in (400, 403, 404)
                    ):
                        logger.info("Falling back to /me/drive/root/children for root listing")
                        res = await execute_graph_request(
                            self.auth_manager, "GET", "/me/drive/root/children"
                        )
                    else:
                        raise

                for item in res.get("value", []):
                    is_folder = "folder" in item
                    mime_type = (
                        FOLDER_MIME_TYPE
                        if is_folder
                        else item.get("file", {}).get("mimeType", "application/octet-stream")
                    )
                    drive_id = item.get("parentReference", {}).get("driveId")
                    item_id = item.get("id")
                    formatted_id = f"{drive_id}:{item_id}" if drive_id else str(item_id)

                    formatted_items.append({
                        "id": formatted_id,
                        "name": item.get("name"),
                        "mimeType": mime_type,
                        "is_folder": is_folder,
                        "webUrl": item.get("webUrl"),
                        "parents": [parent_id],
                    })

                next_url = res.get("@odata.nextLink")

            return formatted_items
        except Exception as e:
            logger.error("Failed to list directory for %s: %s", parent_id, e)
            return []

    async def get_files_metadata(self, item_ids: List[str]) -> List[Dict[str, Any]]:
        """Fetch metadata for specific `driveId:itemId` or `siteId` items."""
        files_meta: List[Dict[str, Any]] = []
        for raw_id in item_ids:
            try:
                if ":" in raw_id:
                    drive_id_part, item_id = raw_id.split(":", 1)
                    endpoint = f"/drives/{drive_id_part}/items/{item_id}"
                else:
                    drive_id_part = None
                    endpoint = f"/sites/{raw_id}/drive/root"

                item = await execute_graph_request(self.auth_manager, "GET", endpoint)
                if item:
                    is_folder = "folder" in item
                    mime_type = (
                        FOLDER_MIME_TYPE
                        if is_folder
                        else item.get("file", {}).get("mimeType", "application/octet-stream")
                    )
                    parent_ref = item.get("parentReference", {}) or {}
                    resolved_drive_id = parent_ref.get("driveId") or drive_id_part
                    parent_item_id = parent_ref.get("id")

                    parent_id = (
                        f"{resolved_drive_id}:{parent_item_id}"
                        if (resolved_drive_id and parent_item_id)
                        else None
                    )

                    files_meta.append({
                        "id": raw_id,
                        "name": item.get("name"),
                        "mimeType": mime_type,
                        "is_folder": is_folder,
                        "parents": [parent_id] if parent_id else [],
                        "webViewLink": item.get("webUrl"),
                        "size": item.get("size", 0),
                    })
            except Exception as e:
                logger.error("Failed to get file metadata for %s: %s", raw_id, e)
        return files_meta

    async def download_file_bytes(self, file_id: str) -> bytes:
        """Download binary file content from SharePoint/OneDrive with automatic 401 token refresh."""
        if ":" not in file_id:
            raise ValueError("Invalid SharePoint file ID format. Expected driveId:itemId")

        drive_id, item_id = file_id.split(":", 1)
        url = f"{GRAPH_API_BASE}/drives/{drive_id}/items/{item_id}/content"

        for attempt in range(2):
            token = await self.auth_manager.get_valid_token(force_refresh=(attempt == 1))
            headers = {"Authorization": f"Bearer {token}"}
            async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
                response = await client.get(url, headers=headers)

            if response.status_code == 401 and attempt == 0:
                logger.info("SharePoint download got 401; refreshing token and retrying")
                continue

            if response.status_code >= 400:
                logger.error("SharePoint binary download failed: %s", response.text)
                response.raise_for_status()

            return response.content

        raise RuntimeError(f"Failed to download SharePoint file {file_id}")

    async def load_from_checkpoint(
        self,
        start: float,
        end: float,
        checkpoint: ConnectorCheckpoint,
    ) -> AsyncGenerator[SlimDocument | HierarchyNode, None]:
        """Full BFS crawl across configured SharePoint sites (or root site)."""
        root_targets: List[str] = []
        if self.site_urls:
            for url in self.site_urls:
                site_id = await self.get_site_id_from_url(url)
                if site_id and site_id not in root_targets:
                    root_targets.append(site_id)
        if not root_targets:
            root_targets = ["root"]

        queue: List[tuple[str, Optional[str], str]] = [
            (target, None, f"SharePoint ({target})") for target in root_targets
        ]
        visited_folders: Set[str] = set()

        while queue:
            folder_id, parent_id, display_name = queue.pop(0)
            if folder_id in visited_folders:
                continue
            visited_folders.add(folder_id)

            yield HierarchyNode(
                raw_node_id=folder_id,
                raw_parent_id=parent_id,
                display_name=display_name,
                node_type="folder",
            )

            children = await self.list_directory(folder_id)
            for child in children:
                child_id = child.get("id")
                if not child_id:
                    continue
                if child.get("is_folder") or child.get("mimeType") == FOLDER_MIME_TYPE:
                    queue.append((child_id, folder_id, child.get("name") or "Folder"))
                elif child_id not in checkpoint.all_retrieved_file_ids:
                    checkpoint.all_retrieved_file_ids.add(child_id)
                    yield SlimDocument(
                        id=child_id,
                        source="sharepoint",
                        metadata={
                            "file_id": child_id,
                            "filename": child.get("name", "unnamed"),
                            "mime_type": child.get("mimeType", ""),
                            "webViewLink": child.get("webUrl"),
                            "parents": child.get("parents", [folder_id]),
                        },
                    )

        checkpoint.has_more = False
        checkpoint.completion_stage = "done"
