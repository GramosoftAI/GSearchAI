"""Google Drive Crawler and native export engine"""

import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlparse

import httpx

from app.core.connectors import (
    CheckpointedConnector,
    ConnectorCheckpoint,
    HierarchyNode,
    SlimDocument,
    StageCompletion,
)
from .auth import (
    DRIVE_SCOPES,
    GoogleAPIError,
    GoogleAuthManager,
    execute_google_download,
    execute_google_request,
)

logger = logging.getLogger(__name__)

# Native Google MIME types and their corresponding target export formats
NATIVE_GOOGLE_EXPORT_MAP = {
    "application/vnd.google-apps.document": {
        "mime_type": "text/plain",
        "extension": ".txt",
    },
    "application/vnd.google-apps.spreadsheet": {
        "mime_type": "text/csv",
        "extension": ".csv",
    },
    "application/vnd.google-apps.presentation": {
        "mime_type": "application/pdf",
        "extension": ".pdf",
    },
}

FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
SHORTCUT_MIME_TYPE = "application/vnd.google-apps.shortcut"

# Native Google formats that cannot be exported to text/binary streams
UNEXPORTABLE_GOOGLE_MIMES = {
    "application/vnd.google-apps.form",
    "application/vnd.google-apps.drawing",
    "application/vnd.google-apps.site",
    "application/vnd.google-apps.script",
    "application/vnd.google-apps.jam",
    "application/vnd.google-apps.map",
}


def _chunk_list(lst: List[str], chunk_size: int = 25) -> List[List[str]]:
    """Partition a list into chunks of at most chunk_size items."""
    return [lst[i : i + chunk_size] for i in range(0, len(lst), chunk_size)]


class GoogleDriveConnector(CheckpointedConnector[ConnectorCheckpoint]):
    """
    Checkpointed crawler for Google Drive with recursive folder scoping,
    exponential backoff retry for downloads, and least-privilege boundary enforcement.
    """

    def __init__(
        self,
        folder_urls: Optional[List[str]] = None,
        include_shared_drives: bool = False,
        include_my_drive: bool = True,
        exclude_mime_types: Optional[List[str]] = None,
    ) -> None:
        self.auth_manager = GoogleAuthManager()
        self.include_shared_drives = include_shared_drives
        self.include_my_drive = include_my_drive
        self.exclude_mime_types = exclude_mime_types or []
        self.target_folder_ids = self._extract_folder_ids(folder_urls or [])

    def _extract_folder_ids(self, urls: List[str]) -> List[str]:
        """Extract folder IDs from raw Google Drive URLs or bare folder ID strings."""
        ids: List[str] = []
        for url in urls:
            if not url:
                continue
            u = url.strip()
            # Handle raw folder ID passed directly
            if "/" not in u and len(u) >= 10:
                ids.append(u)
                continue

            parsed = urlparse(u)
            # Handle ?id=FOLDER_ID (e.g. drive.google.com/open?id=...)
            if parsed.query:
                qs = parse_qs(parsed.query)
                if "id" in qs and qs["id"]:
                    ids.append(qs["id"][0])
                    continue

            # Handle /folders/FOLDER_ID path
            path_parts = parsed.path.rstrip("/").split("/")
            if path_parts and path_parts[-1]:
                ids.append(path_parts[-1])
        return ids

    def load_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any] | None:
        return self.auth_manager.load_credentials(credentials, scopes=DRIVE_SCOPES)

    def build_dummy_checkpoint(self) -> ConnectorCheckpoint:
        return ConnectorCheckpoint(
            has_more=True,
            completion_stage="start",
        )

    def validate_checkpoint_json(self, checkpoint_json: str) -> ConnectorCheckpoint:
        try:
            return ConnectorCheckpoint.model_validate_json(checkpoint_json)
        except Exception as e:
            logger.warning(f"Failed to validate checkpoint JSON: {e}, falling back to dummy")
            return self.build_dummy_checkpoint()

    async def download_file_bytes(
        self,
        file_id: str,
        mime_type: str,
        impersonate_email: Optional[str] = None,
    ) -> bytes:
        """
        Download binary file content or export native Google formats with retry backoff.
        Handles export ceilings and unexportable native types gracefully.
        """
        # Skip unexportable native Google file types
        if mime_type in UNEXPORTABLE_GOOGLE_MIMES:
            logger.info(f"Skipping unexportable Google Workspace file {file_id} (mimeType: {mime_type})")
            return b""

        async with self.auth_manager.get_client(impersonate_email) as client:
            # 1. Native Google Doc / Sheet / Slide Exporter
            if mime_type in NATIVE_GOOGLE_EXPORT_MAP:
                export_format = NATIVE_GOOGLE_EXPORT_MAP[mime_type]
                logger.info(f"Exporting native Google file {file_id} as {export_format['mime_type']}")
                url = f"/drive/v3/files/{file_id}/export"
                params = {"mimeType": export_format["mime_type"]}

                try:
                    return await execute_google_download(client, url, params=params)
                except GoogleAPIError as e:
                    # Google Docs / Sheets have a 10MB export ceiling
                    if "exportSizeLimitExceeded" in str(e).lower() or "export size limit" in str(e).lower():
                        logger.warning(f"Google Workspace export ceiling (10MB) exceeded for {file_id}. Skipping body.")
                        return b""
                    raise

            # 2. Standard Binary Downloader
            else:
                logger.info(f"Downloading standard binary file {file_id}")
                url = f"/drive/v3/files/{file_id}"
                params: Dict[str, Any] = {"alt": "media"}
                if self.include_shared_drives:
                    params["supportsAllDrives"] = "true"

                return await execute_google_download(client, url, params=params)

    def _build_search_query(
        self,
        parent_ids: Optional[List[str]] = None,
        start_time: Optional[float] = None,
    ) -> str:
        """Construct Google Drive file search query filters constrained to parent folders."""
        queries = ["trashed = false", f"mimeType != '{FOLDER_MIME_TYPE}'"]

        if parent_ids:
            if len(parent_ids) == 1:
                queries.append(f"'{parent_ids[0]}' in parents")
            else:
                or_clause = " or ".join(f"'{pid}' in parents" for pid in parent_ids)
                queries.append(f"({or_clause})")

        if start_time and start_time > 0:
            iso_time = datetime.fromtimestamp(start_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            queries.append(f"modifiedTime > '{iso_time}'")

        # Exclude specific MIME types
        for mime in self.exclude_mime_types:
            queries.append(f"mimeType != '{mime}'")

        for mime in UNEXPORTABLE_GOOGLE_MIMES:
            queries.append(f"mimeType != '{mime}'")

        return " and ".join(queries)

    async def _discover_folder_subtree(
        self,
        client: httpx.AsyncClient,
        root_folder_ids: List[str],
    ) -> Tuple[Set[str], List[HierarchyNode]]:
        """
        Recursively discover all descendant folders from root_folder_ids using BFS.
        Returns:
          - discovered_ids: Complete set of folder IDs within the subtree (including roots).
          - hierarchy_nodes: Deduped HierarchyNodes with correct parent-child relationships.
        """
        discovered_ids: Set[str] = set(root_folder_ids)
        queue: List[str] = list(root_folder_ids)
        hierarchy_nodes: List[HierarchyNode] = []
        visited: Set[str] = set()

        while queue:
            current_id = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)

            # 1. Fetch metadata for the current folder
            try:
                folder_params: Dict[str, Any] = {
                    "fields": "id, name, parents",
                    "supportsAllDrives": self.include_shared_drives,
                }
                f_meta = await execute_google_request(
                    client,
                    "GET",
                    f"/drive/v3/files/{current_id}",
                    params=folder_params,
                )
                parent_id = (f_meta.get("parents") or [None])[0]
                hierarchy_nodes.append(
                    HierarchyNode(
                        raw_node_id=current_id,
                        raw_parent_id=parent_id,
                        display_name=f_meta.get("name", "Target Folder"),
                        node_type="folder",
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to fetch metadata for folder {current_id}: {e}")

            # 2. Query direct child folders
            page_token: Optional[str] = None
            has_more = True
            while has_more:
                q = f"'{current_id}' in parents and mimeType = '{FOLDER_MIME_TYPE}' and trashed = false"
                params: Dict[str, Any] = {
                    "q": q,
                    "pageSize": 100,
                    "fields": "nextPageToken, files(id, name, parents)",
                    "supportsAllDrives": self.include_shared_drives,
                    "includeItemsFromAllDrives": self.include_shared_drives,
                }
                if self.include_shared_drives:
                    params["corpora"] = "allDrives"
                if page_token:
                    params["pageToken"] = page_token

                try:
                    res = await execute_google_request(client, "GET", "/drive/v3/files", params=params)
                except Exception as e:
                    logger.error(f"Failed to list child folders of {current_id}: {e}")
                    break

                for cf in res.get("files", []):
                    cf_id = cf.get("id")
                    if cf_id and cf_id not in discovered_ids:
                        discovered_ids.add(cf_id)
                        queue.append(cf_id)

                page_token = res.get("nextPageToken")
                has_more = bool(page_token)

        return discovered_ids, hierarchy_nodes

    async def list_directory(
        self,
        parent_id: Optional[str] = None,
        impersonate_email: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List files and folders directly within a specific parent (or root)."""
        email = impersonate_email or self.auth_manager.primary_admin_email
        async with self.auth_manager.get_client(email) as client:
            queries = ["trashed = false"]
            if parent_id:
                queries.append(f"'{parent_id}' in parents")
            else:
                queries.append("'root' in parents")

            params: Dict[str, Any] = {
                "q": " and ".join(queries),
                "pageSize": 1000,
                "fields": "files(id, name, mimeType, size, modifiedTime)",
                "supportsAllDrives": self.include_shared_drives,
                "includeItemsFromAllDrives": self.include_shared_drives,
            }
            if self.include_shared_drives:
                params["corpora"] = "allDrives"

            try:
                res = await execute_google_request(client, "GET", "/drive/v3/files", params=params)
                return res.get("files", [])
            except Exception as e:
                logger.error(f"Failed to list directory for {email}: {e}")
                return []

    async def get_files_metadata(
        self,
        file_ids: List[str],
        impersonate_email: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch metadata for specific file IDs."""
        if not file_ids:
            return []
        email = impersonate_email or self.auth_manager.primary_admin_email
        async with self.auth_manager.get_client(email) as client:
            files_meta: List[Dict[str, Any]] = []
            for fid in file_ids:
                params = {
                    "fields": "id, name, mimeType, parents, size, webViewLink, trashed, owners, permissions",
                    "supportsAllDrives": self.include_shared_drives,
                }
                try:
                    res = await execute_google_request(client, "GET", f"/drive/v3/files/{fid}", params=params)
                    if res and not res.get("trashed"):
                        files_meta.append(res)
                except Exception as e:
                    logger.error(f"Failed to get file metadata for {fid} ({email}): {e}")
            return files_meta

    async def load_from_checkpoint(
        self,
        start: float,
        end: float,
        checkpoint: ConnectorCheckpoint,
    ) -> AsyncGenerator[SlimDocument | HierarchyNode, None]:
        """
        Main crawling loop yielding slim documents and folder hierarchy nodes.
        Strictly scopes file enumeration to target_folder_ids (and its descendants)
        when specified, adhering to the Principle of Least Privilege.
        """
        emails_to_crawl = [self.auth_manager.primary_admin_email]
        if self.auth_manager.is_service_account and checkpoint.user_emails:
            emails_to_crawl = checkpoint.user_emails

        for email in emails_to_crawl:
            if email not in checkpoint.completion_map:
                checkpoint.completion_map[email] = StageCompletion(stage="crawling", completed_until=start)

            completion = checkpoint.completion_map[email]
            if completion.stage == "done":
                continue

            logger.info(f"Starting scoped crawl stage for user: {email}")

            async with self.auth_manager.get_client(email) as client:
                # 1. RECURSIVE FOLDER SUBTREE DISCOVERY
                scoped_folder_ids: Set[str] = set()
                if self.target_folder_ids:
                    scoped_folder_ids, hierarchy_nodes = await self._discover_folder_subtree(
                        client, self.target_folder_ids
                    )
                    # Yield deduped hierarchy nodes for the discovered folder tree
                    for node in hierarchy_nodes:
                        yield node

                # 2. SCOPED FILE ENUMERATION STAGE
                # Batch target folder IDs into chunks of ~25 to avoid Google Drive 'q' length limits
                folder_batches: List[Optional[List[str]]]
                if scoped_folder_ids:
                    folder_batches = _chunk_list(list(scoped_folder_ids), chunk_size=25)
                elif self.target_folder_ids:
                    folder_batches = _chunk_list(self.target_folder_ids, chunk_size=25)
                else:
                    # Unscoped crawl (user selected root / entire account)
                    folder_batches = [None]

                for idx, folder_chunk in enumerate(folder_batches):
                    has_more_pages = True
                    page_token = completion.next_page_token if idx == 0 else None

                    while has_more_pages:
                        q_query = self._build_search_query(
                            parent_ids=folder_chunk,
                            start_time=completion.completed_until,
                        )
                        params: Dict[str, Any] = {
                            "q": q_query,
                            "pageSize": 50,
                            "fields": "nextPageToken, files(id, name, mimeType, parents, modifiedTime, size, webViewLink, owners, permissions, shortcutDetails)",
                            "supportsAllDrives": self.include_shared_drives,
                            "includeItemsFromAllDrives": self.include_shared_drives,
                        }
                        if self.include_shared_drives:
                            params["corpora"] = "allDrives"
                        if page_token:
                            params["pageToken"] = page_token

                        try:
                            logger.debug(f"Listing files with query: {q_query}")
                            res = await execute_google_request(client, "GET", "/drive/v3/files", params=params)
                        except Exception as e:
                            logger.error(f"Failed to list Google Drive files for {email}: {e}")
                            completion.next_page_token = page_token
                            checkpoint.has_more = True
                            return

                        files = res.get("files", [])
                        for file in files:
                            file_id = file.get("id")
                            if not file_id or file_id in checkpoint.all_retrieved_file_ids:
                                continue

                            mime_type = file.get("mimeType", "application/octet-stream")

                            # Resolve shortcuts to their target file ID if present
                            if mime_type == SHORTCUT_MIME_TYPE:
                                shortcut_details = file.get("shortcutDetails", {})
                                target_id = shortcut_details.get("targetId")
                                target_mime = shortcut_details.get("targetMimeType", mime_type)
                                if target_id:
                                    file_id = target_id
                                    mime_type = target_mime

                            # Skip unexportable Google Workspace types
                            if mime_type in UNEXPORTABLE_GOOGLE_MIMES:
                                continue

                            parents = file.get("parents", [])

                            # Build metadata footprint including permissions & owners for RAG ACLs
                            meta = {
                                "file_id": file_id,
                                "filename": file.get("name", "unnamed"),
                                "mime_type": mime_type,
                                "webViewLink": file.get("webViewLink"),
                                "size_bytes": int(file.get("size") or 0),
                                "parents": parents,
                                "user_email": email,
                                "owners": [
                                    o.get("emailAddress")
                                    for o in file.get("owners", [])
                                    if o.get("emailAddress")
                                ],
                                "permissions": [
                                    {
                                        "id": p.get("id"),
                                        "type": p.get("type"),
                                        "role": p.get("role"),
                                        "emailAddress": p.get("emailAddress"),
                                    }
                                    for p in file.get("permissions", [])
                                ],
                            }

                            yield SlimDocument(
                                id=file_id,
                                source="google_drive",
                                metadata=meta,
                            )

                            checkpoint.all_retrieved_file_ids.add(file_id)

                        page_token = res.get("nextPageToken")
                        completion.next_page_token = page_token
                        has_more_pages = bool(page_token)

                # Advance completed_until to current sync window end for incremental syncs
                completion.completed_until = end
                completion.stage = "done"

        all_done = all(comp.stage == "done" for comp in checkpoint.completion_map.values())
        checkpoint.has_more = not all_done
        return
