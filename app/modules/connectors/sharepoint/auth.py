"""Microsoft Graph authentication and HTTP helper for SharePoint and Outlook."""

import asyncio
import logging
import os
import time
from typing import Any, Callable, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"


class SharePointAuthManager:
    """Manages Microsoft Entra ID (OAuth2 / App-Only) tokens for Microsoft Graph."""

    def __init__(
        self,
        on_token_refresh: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self.client_id: Optional[str] = None
        self.client_secret: Optional[str] = None
        self.tenant_id: Optional[str] = None
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._on_token_refresh = on_token_refresh

    def load_credentials(self, credentials: Dict[str, Any]) -> Dict[str, Any]:
        """Load OAuth / app credentials, unwrapping nested `credentials` if present."""
        raw = credentials or {}
        if "credentials" in raw and isinstance(raw["credentials"], dict) and not raw.get("access_token"):
            creds = raw["credentials"]
        else:
            creds = raw

        self.client_id = creds.get("client_id") or os.getenv("MS_CLIENT_ID")
        self.client_secret = creds.get("client_secret") or os.getenv("MS_CLIENT_SECRET")
        self.tenant_id = creds.get("tenant_id") or os.getenv("MS_TENANT_ID") or "common"
        self._access_token = creds.get("access_token") or raw.get("access_token")
        self._refresh_token = creds.get("refresh_token") or raw.get("refresh_token")

        expires_at = creds.get("expires_at") or raw.get("expires_at")
        if expires_at is not None:
            try:
                self._token_expires_at = float(expires_at)
            except (TypeError, ValueError):
                self._token_expires_at = 0.0
        elif self._access_token:
            # Loaded token without explicit expiry: trust until expired/401 rather than forcing immediate refresh
            self._token_expires_at = time.time() + 300.0
        else:
            self._token_expires_at = 0.0

        return creds

    def export_credentials(self) -> Dict[str, Any]:
        """Return current credential state for persistence."""
        return {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "tenant_id": self.tenant_id,
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_at": self._token_expires_at,
        }

    async def get_valid_token(self, force_refresh: bool = False) -> str:
        """Return a valid Microsoft Graph access token, refreshing when needed."""
        if (
            not force_refresh
            and self._access_token
            and time.time() < self._token_expires_at - 60
        ):
            return self._access_token

        if not self.client_id or not self.client_secret:
            raise ValueError("SharePoint/Outlook client_id or client_secret is not configured")

        effective_tenant = self.tenant_id or os.getenv("MS_TENANT_ID") or "common"

        if self._refresh_token:
            # 3-legged OAuth refresh token flow
            token_url = f"https://login.microsoftonline.com/{effective_tenant}/oauth2/v2.0/token"
            data = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            }
        else:
            # 2-legged App-only flow cannot use 'common'
            if effective_tenant == "common":
                env_tenant = os.getenv("MS_TENANT_ID")
                if env_tenant and env_tenant != "common":
                    effective_tenant = env_tenant
                else:
                    raise ValueError(
                        "Cannot use tenant_id='common' for client_credentials without a refresh_token. "
                        "Configure MS_TENANT_ID or authenticate via OAuth login."
                    )
            token_url = f"https://login.microsoftonline.com/{effective_tenant}/oauth2/v2.0/token"
            data = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(token_url, data=data)
            if response.status_code != 200:
                logger.error("Failed to acquire MS Graph token: %s", response.text)
                raise RuntimeError(f"Authentication failed with Microsoft Entra ID: {response.status_code}")

            result = response.json()
            self._access_token = result["access_token"]
            if "refresh_token" in result:
                self._refresh_token = result["refresh_token"]
            self._token_expires_at = time.time() + float(result.get("expires_in", 3600))

            if self._on_token_refresh:
                try:
                    self._on_token_refresh(self.export_credentials())
                except Exception as cb_err:
                    logger.warning("Token refresh callback failed: %s", cb_err)

            return self._access_token


async def execute_graph_request(
    auth_manager: SharePointAuthManager,
    method: str,
    endpoint: str,
    max_retries: int = 3,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Execute a Microsoft Graph request supporting relative paths, full @odata.nextLink URLs, 401 refresh, and 429/5xx retries."""
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        url = endpoint
    elif endpoint.startswith("/"):
        url = f"{GRAPH_API_BASE}{endpoint}"
    else:
        url = f"{GRAPH_API_BASE}/{endpoint}"

    force_refresh = False
    refreshed_on_401 = False

    for attempt in range(max_retries + 1):
        token = await auth_manager.get_valid_token(force_refresh=force_refresh)
        force_refresh = False

        headers = dict(kwargs.get("headers") or {})
        headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("Accept", "application/json")
        req_kwargs = {**kwargs, "headers": headers}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.request(method, url, **req_kwargs)

        if response.status_code == 401 and not refreshed_on_401:
            logger.info("MS Graph returned 401; forcing token refresh and retrying once.")
            refreshed_on_401 = True
            force_refresh = True
            continue

        if response.status_code in (429, 502, 503, 504) and attempt < max_retries:
            retry_after_raw = response.headers.get("Retry-After")
            try:
                delay = float(retry_after_raw) if retry_after_raw else float(2 ** attempt)
            except ValueError:
                delay = float(2 ** attempt)
            delay = min(max(delay, 0.5), 30.0)
            logger.warning(
                "MS Graph transient status %s on %s; retrying in %.1fs",
                response.status_code,
                url,
                delay,
            )
            await asyncio.sleep(delay)
            continue

        if response.status_code >= 400:
            logger.error("MS Graph Request Failed: %s - %s", response.status_code, response.text)
            response.raise_for_status()

        if response.status_code == 204 or not response.content:
            return {}

        return response.json()

    raise RuntimeError(f"MS Graph request exhausted retries: {method} {url}")
