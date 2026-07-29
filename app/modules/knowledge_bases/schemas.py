"""Pydantic schemas for Knowledge Base request/response validation"""

from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime


class KBCreate(BaseModel):
    """
    Schema for creating a new knowledge base.

    REQUIRED:
    - name: KB name
    - agent_id: Agent this KB belongs to

    OPTIONAL:
    - description: Human description
    - source: Source type (default: "user_upload")
    """

    name: str = Field(..., min_length=1, max_length=255, description="KB name")
    description: Optional[str] = Field(
        None, max_length=1000, description="KB description"
    )
    agent_id: UUID = Field(..., description="Agent this KB belongs to")
    source: Optional[str] = Field(
        "user_upload",
        max_length=50,
        description="Source type (user_upload, api, database, etc.)",
    )
    document_type: Optional[str] = Field(
        None,
        max_length=50,
        description="Document type classification (e.g. PRICE_LIST, INVOICE)",
    )
    dataset_schema: Optional[dict] = Field(
        None,
        description="Schema definition of the tabular dataset",
    )
    s3_path: Optional[str] = Field(
        None,
        max_length=1024,
        description="S3 storage path of the file",
    )
    file_hash: Optional[str] = Field(
        None,
        max_length=64,
        description="SHA-256 hash of the uploaded document",
    )


    class Config:
        json_schema_extra = {
            "example": {
                "name": "Company Documentation",
                "description": "Internal company policies and procedures",
                "agent_id": "550e8400-e29b-41d4-a716-446655440000",
                "source": "user_upload",
            }
        }


class KBUpdate(BaseModel):
    """
    Schema for updating an existing knowledge base.

    All fields are optional (PATCH semantics).
    """

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=1000)
    is_active: Optional[bool] = Field(None)

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Updated KB Name",
                "description": "Updated description...",
            }
        }


class KBResponse(BaseModel):
    """
    Schema for knowledge base response (read-only).

    Returned by GET endpoints.
    """

    id: UUID
    tenant_id: UUID
    user_id: UUID
    agent_id: UUID
    name: str
    description: Optional[str]
    source: str
    total_chunks: int
    is_active: bool
    deleted_at: Optional[datetime] = Field(
        None, description="Soft delete timestamp (null = not deleted)"
    )
    created_at: datetime
    updated_at: datetime
    s3_path: Optional[str] = None
    parsed_path: Optional[str] = None


    connected_integration: Optional[str] = Field(None, description="The type of external integration connected to this KB (e.g., google_drive, sharepoint)")
    time_taken: Optional[str] = Field(None, description="The time taken for ingestion of this KB")
    time_metrics: Optional[dict] = Field(None, description="Detailed ingestion time metrics")

    class Config:
        from_attributes = True  # SQLAlchemy ORM mode
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
                "user_id": "550e8400-e29b-41d4-a716-446655440002",
                "agent_id": "550e8400-e29b-41d4-a716-446655440003",
                "name": "Company Documentation",
                "description": "Internal company policies and procedures",
                "source": "user_upload",
                "total_chunks": 45,
                "is_active": True,
                "deleted_at": None,
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
            }
        }


class KBListResponse(BaseModel):
    """
    Schema for listing knowledge bases.

    Includes pagination metadata.
    """

    kbs: list[KBResponse]
    count: int = Field(..., description="Number of KBs in this page")
    total: int = Field(..., description="Total KBs in database")

    class Config:
        json_schema_extra = {
            "example": {
                "kbs": [
                    {
                        "id": "550e8400-e29b-41d4-a716-446655440000",
                        "tenant_id": "550e8400-e29b-41d4-a716-446655440001",
                        "user_id": "550e8400-e29b-41d4-a716-446655440002",
                        "agent_id": "550e8400-e29b-41d4-a716-446655440003",
                        "name": "Company Documentation",
                        "description": "Internal company policies",
                        "source": "user_upload",
                        "total_chunks": 45,
                        "is_active": True,
                        "deleted_at": None,
                        "created_at": "2024-01-15T10:30:00Z",
                        "updated_at": "2024-01-15T10:30:00Z",
                    }
                ],
                "count": 1,
                "total": 1,
            }
        }


class KBDeleteResponse(BaseModel):
    """
    Schema for delete response.
    """

    id: UUID
    deleted_at: datetime

    class Config:
        json_schema_extra = {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "deleted_at": "2024-01-15T10:30:00Z",
            }
        }


class KBURLIngest(BaseModel):
    """
    Schema for URL ingestion request.
    """
    url: str = Field(..., description="Target URL to crawl")
    crawl_type: str = Field("all", pattern="^(single|all)$", description="Crawl depth: single or all (up to 10 pages)")

    class Config:
        json_schema_extra = {
            "example": {
                "url": "https://example.com",
                "crawl_type": "all"
            }
        }


class DatabaseConnectionRegister(BaseModel):
    """
    Schema to register/associate a database connection with an Agent KB.
    """
    db_type: str = Field(..., description="Database type: 'sqlite' or 'postgresql'")
    connection_params: dict = Field(..., description="JSON credentials/paths for the database connection")

    class Config:
        json_schema_extra = {
            "example": {
                "db_type": "sqlite",
                "connection_params": {
                    "filepath": "tester_zone/company.db"
                }
            }
        }


class DatabaseConnectionResponse(BaseModel):
    """
    Response schema for registered database connection details.
    """
    id: UUID
    tenant_id: UUID
    kb_id: UUID
    db_type: str
    connection_params: dict
    last_synced_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class DatabaseValidationResponse(BaseModel):
    """
    Schema returning the result of connection validation or schema discovery.
    """
    success: bool
    message: str
    tables: Optional[list[str]] = None
    schema_details: Optional[dict] = None


class GoogleDriveRegister(BaseModel):
    """
    Schema to register/associate a Google Drive connection with an Agent KB.
    """
    credentials: dict = Field(..., description="Service Account JSON payload or OAuth token data")
    folder_urls: Optional[list[str]] = Field(None, description="Optional Google Drive or Folder URLs to isolate indexing")

    class Config:
        json_schema_extra = {
            "example": {
                "credentials": {
                    "type": "service_account",
                    "project_id": "graphmind-prod",
                    "private_key_id": "abcdef123456",
                    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEv...",
                    "client_email": "crawler@graphmind.iam.gserviceaccount.com",
                    "primary_admin_email": "admin@yourdomain.com"
                },
                "folder_urls": [
                    "https://drive.google.com/drive/folders/1A2B3C4D5E6F7G8H9I"
                ]
            }
        }


class GoogleDriveItem(BaseModel):
    """Schema representing a single file or folder from Google Drive."""
    id: str
    name: str
    mime_type: str
    is_folder: bool


class GoogleDriveListResponse(BaseModel):
    """Schema for returning a directory listing from Google Drive."""
    items: list[GoogleDriveItem] = []


class GoogleDriveSyncRequest(BaseModel):
    """
    Schema for selectively syncing files or folders from Google Drive.
    """
    file_ids: Optional[list[str]] = Field(default_factory=list, description="Specific file IDs to ingest")
    folder_ids: Optional[list[str]] = Field(default_factory=list, description="Specific folder IDs to ingest (recursive)")
    user_email: Optional[str] = Field(None, description="Email of the user syncing the drive")

    class Config:
        json_schema_extra = {
            "example": {
                "file_ids": ["1A2B3C4D5E6F7G8H9I", "9Z8Y7X6W5V4U3T2S1R"],
                "folder_ids": ["folder1_id", "folder2_id"]
            }
        }


class SharePointRegister(BaseModel):
    """
    Schema to register/associate a SharePoint connection with an Agent KB.
    """
    credentials: dict = Field(..., description="Credentials for Microsoft Graph (client_id, client_secret, tenant_id)")
    site_urls: Optional[list[str]] = Field(None, description="Optional SharePoint Site URLs to isolate indexing")

    class Config:
        json_schema_extra = {
            "example": {
                "credentials": {
                    "client_id": "00000000-0000-0000-0000-000000000000",
                    "client_secret": "supersecret",
                    "tenant_id": "11111111-1111-1111-1111-111111111111"
                },
                "site_urls": [
                    "https://graph.microsoft.com/v1.0/sites/root"
                ]
            }
        }


class SharePointItem(BaseModel):
    """Schema representing a single file or folder from SharePoint."""
    id: str
    name: str
    mime_type: str
    is_folder: bool


class SharePointListResponse(BaseModel):
    """Schema for returning a directory listing from SharePoint."""
    items: list[SharePointItem] = []


class SharePointSyncRequest(BaseModel):
    """
    Schema for selectively syncing files or folders from SharePoint.
    """
    file_ids: Optional[list[str]] = Field(default_factory=list, description="Specific file IDs to ingest")
    folder_ids: Optional[list[str]] = Field(default_factory=list, description="Specific folder IDs to ingest (recursive)")

    class Config:
        json_schema_extra = {
            "example": {
                "file_ids": ["driveId:itemId"],
                "folder_ids": ["driveId:folderId"]
            }
        }


class GmailRegister(BaseModel):
    """Schema to register Gmail connection."""
    credentials: dict = Field(..., description="Service Account JSON payload or OAuth token data")
    
    class Config:
        json_schema_extra = {
            "example": {
                "credentials": {
                    "type": "service_account",
                    "client_email": "crawler@example.com"
                }
            }
        }


class GmailSyncRequest(BaseModel):
    """Schema for syncing Gmail messages."""
    user_email: Optional[str] = Field(None, description="Email of the user to sync from")
    email: Optional[str] = Field(None, description="Alias for user_email")
    folder_ids: Optional[list[str]] = Field(default_factory=list, description="Specific folder/labels to sync")
    max_results: Optional[int] = Field(100, description="Maximum number of emails to fetch")
    query: Optional[str] = Field(None, description="Optional Gmail search query (e.g. 'in:inbox')")

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "folder_ids": ["INBOX"]
            }
        }


class OutlookRegister(BaseModel):
    """Schema to register Outlook connection."""
    credentials: dict = Field(..., description="Credentials for Microsoft Graph")
    
    class Config:
        json_schema_extra = {
            "example": {
                "credentials": {
                    "client_id": "00000000-0000-0000-0000-000000000000",
                    "client_secret": "secret",
                    "tenant_id": "common"
                }
            }
        }


class OutlookSyncRequest(BaseModel):
    """Schema for syncing Outlook messages."""
    user_email: Optional[str] = Field(None, description="Email of the user to sync from")
    email: Optional[str] = Field(None, description="Alias for user_email")
    folder_ids: Optional[list[str]] = Field(default_factory=list, description="Specific folder to sync")
    max_results: Optional[int] = Field(100, description="Maximum number of emails to fetch")
    folder_id: Optional[str] = Field(None, description="Specific folder to sync (default Inbox)")

    class Config:
        json_schema_extra = {
            "example": {
                "email": "user@example.com",
                "folder_ids": ["inbox"]
            }
        }
