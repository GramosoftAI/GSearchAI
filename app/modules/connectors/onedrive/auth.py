import logging
import time
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger(__name__)

ONEDRIVE_OAUTH_SCOPES = [
    "openid",
    "profile",
    "email",
    "offline_access",
    "Files.Read",
    "Files.Read.All",
    "User.Read",
]

class OneDriveAuthManager:
    def __init__(self):
        self.client_id = None
        self.client_secret = None
        self.tenant_id = "common"
        self._access_token = None
        self._refresh_token = None
        self._token_expires_at = 0

    def load_credentials(self, credentials: dict) -> dict:
        self.client_id = credentials.get("client_id")
        self.client_secret = credentials.get("client_secret")
        self.tenant_id = credentials.get("tenant_id") or "common"
        self._access_token = credentials.get("access_token")
        self._refresh_token = credentials.get("refresh_token")
        return credentials

    async def get_valid_token(self) -> str:
        # If we have an access token and it hasn't expired yet
        if self._access_token:
            if not self._token_expires_at or time.time() < self._token_expires_at - 60:
                return self._access_token

        if not self._refresh_token:
            if self._access_token:
                return self._access_token
            raise ValueError("OneDrive credentials do not contain a valid access or refresh token")

        import os
        from dotenv import load_dotenv
        load_dotenv()

        client_id = (
            self.client_id
            or os.getenv("MS_CLIENT_ID")
            or os.getenv("AZURE_CLIENT_ID")
            or ""
        )
        client_secret = (
            self.client_secret
            or os.getenv("MS_CLIENT_SECRET")
            or os.getenv("AZURE_CLIENT_SECRET")
            or ""
        )
        tenant_id = (
            self.tenant_id
            or os.getenv("MS_TENANT_ID")
            or os.getenv("AZURE_TENANT_ID")
            or "common"
        )

        if not client_id or not client_secret:
            if self._access_token:
                return self._access_token
            raise ValueError("Microsoft Client ID or Client Secret missing for OneDrive token refresh")

        token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": self._refresh_token,
            "grant_type": "refresh_token",
            "scope": " ".join(ONEDRIVE_OAUTH_SCOPES),
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            if response.status_code != 200:
                logger.error(f"Failed to refresh OneDrive token: {response.text}")
                raise RuntimeError("OneDrive authentication refresh failed with Microsoft Entra ID")

            result = response.json()
            self._access_token = result.get("access_token")
            if "refresh_token" in result:
                self._refresh_token = result["refresh_token"]
            self._token_expires_at = time.time() + result.get("expires_in", 3600)
            return self._access_token


async def execute_graph_request(auth_manager: OneDriveAuthManager, method: str, endpoint: str, **kwargs) -> dict:
    try:
        token = await auth_manager.get_valid_token()
    except Exception as token_err:
        logger.error(f"Failed to obtain valid OneDrive token: {token_err}")
        token = auth_manager._access_token

    headers = kwargs.get("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    headers["Accept"] = "application/json"
    kwargs["headers"] = headers

    base_url = "https://graph.microsoft.com/v1.0"
    url = f"{base_url}{endpoint}" if endpoint.startswith("/") else f"{base_url}/{endpoint}"

    async with httpx.AsyncClient() as client:
        response = await client.request(method, url, **kwargs)
        if response.status_code == 401 and auth_manager._refresh_token:
            logger.info("401 received, attempting token refresh...")
            auth_manager._token_expires_at = 0
            new_token = await auth_manager.get_valid_token()
            headers["Authorization"] = f"Bearer {new_token}"
            kwargs["headers"] = headers
            response = await client.request(method, url, **kwargs)

        if response.status_code >= 400:
            logger.error(f"OneDrive MS Graph Request Failed ({response.status_code}): {response.text}")
            response.raise_for_status()

        if response.status_code == 204:
            return {}

        return response.json()

