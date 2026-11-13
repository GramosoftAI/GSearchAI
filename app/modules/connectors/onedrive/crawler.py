import logging
from typing import Any, Dict, List, Optional
import httpx

from app.core.connectors import (
    CheckpointedConnector,
    ConnectorCheckpoint,
    HierarchyNode,
    SlimDocument,
    StageCompletion,
)
from .auth import OneDriveAuthManager, execute_graph_request

logger = logging.getLogger(__name__)

FOLDER_MIME_TYPE = "application/vnd.microsoft.graph.folder"

class OneDriveConnector(CheckpointedConnector[ConnectorCheckpoint]):
    """
    Checkpointed crawler for Microsoft OneDrive.
    Traverses personal/business OneDrive items via Microsoft Graph API and downloads content.
    """

    def __init__(self, folder_ids: Optional[List[str]] = None) -> None:
        self.auth_manager = OneDriveAuthManager()
        self.folder_ids = folder_ids or []
        self.access_token = None
        self.refresh_token = None

    def load_credentials(self, credentials: dict) -> dict:
        self.access_token = credentials.get("access_token")
        self.refresh_token = credentials.get("refresh_token")
        self.auth_manager.load_credentials(credentials)

        if not self.access_token and not self.refresh_token:
            logger.error("Missing OneDrive OAuth tokens")
            return None

        return credentials

    def build_dummy_checkpoint(self) -> ConnectorCheckpoint:
        return ConnectorCheckpoint(
            has_more=True,
            completion_stage="start",
        )

    def validate_checkpoint_json(self, checkpoint_json: str) -> ConnectorCheckpoint:
        try:
            return ConnectorCheckpoint.model_validate_json(checkpoint_json)
        except Exception as e:
            logger.warning(f"Failed to validate OneDrive checkpoint JSON: {e}, falling back to dummy")
            return self.build_dummy_checkpoint()

    async def list_directory(self, parent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List files and folders directly within a specific OneDrive folder or drive root.
        If parent_id is empty or 'root', lists /me/drive/root/children.
        Otherwise lists /me/drive/items/{parent_id}/children.
        """
        try:
            if not parent_id or parent_id == "root":
                endpoint = "/me/drive/root/children"
            else:
                endpoint = f"/me/drive/items/{parent_id}/children"

            res = await execute_graph_request(self.auth_manager, "GET", endpoint)
            items = res.get("value", [])

            formatted_items = []
            for item in items:
                is_folder = "folder" in item
                mime_type = (
                    FOLDER_MIME_TYPE
                    if is_folder
                    else item.get("file", {}).get("mimeType", "application/octet-stream")
                )
                item_id = item.get("id")

                formatted_items.append({
                    "id": item_id,
                    "name": item.get("name"),
                    "mimeType": mime_type,
                    "is_folder": is_folder,
                    "webUrl": item.get("webUrl"),
                    "size": item.get("size", 0),
                    "parents": [parent_id or "root"],
                })

            return formatted_items
        except Exception as e:
            logger.error(f"Failed to list OneDrive directory for parent {parent_id}: {e}")
            return []

    async def get_files_metadata(self, item_ids: List[str]) -> List[Dict[str, Any]]:
        """Fetch metadata for specific OneDrive item IDs."""
        files_meta = []
        for item_id in item_ids:
            try:
                endpoint = f"/me/drive/items/{item_id}"
                item = await execute_graph_request(self.auth_manager, "GET", endpoint)
                if item:
                    is_folder = "folder" in item
                    mime_type = (
                        FOLDER_MIME_TYPE
                        if is_folder
                        else item.get("file", {}).get("mimeType", "application/octet-stream")
                    )
                    parent_ref = item.get("parentReference", {}).get("id")

                    files_meta.append({
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "mimeType": mime_type,
                        "parents": [parent_ref] if parent_ref else [],
                        "webViewLink": item.get("webUrl"),
                        "size": item.get("size", 0),
                    })
            except Exception as e:
                logger.error(f"Failed to get OneDrive file metadata for {item_id}: {e}")
        return files_meta

    async def download_file_bytes(self, file_id: str) -> bytes:
        """Download binary file content from OneDrive."""
        endpoint = f"/me/drive/items/{file_id}/content"
        token = await self.auth_manager.get_valid_token()
        headers = {"Authorization": f"Bearer {token}"}
        base_url = "https://graph.microsoft.com/v1.0"

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(f"{base_url}{endpoint}", headers=headers)
            if response.status_code >= 400:
                logger.error(f"OneDrive binary download failed for {file_id}: {response.text}")
                response.raise_for_status()

            return response.content

    async def load_from_checkpoint(self, checkpoint: ConnectorCheckpoint):
        raise NotImplementedError("Batch checkpointing traversal can be invoked on demand")

