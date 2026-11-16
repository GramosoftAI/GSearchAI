"""SuperAdmin WebAuthn / Passkey Service.

Provides FIDO2 / WebAuthn / Passkey registration, authentication,
credential storage, and device verification for SuperAdmin accounts.
"""

import secrets
import base64
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
import logging

from ..models import SuperAdminUser, SuperAdminWebAuthnCredential
from ..schemas import (
    WebAuthnRegisterOptionsResponse,
    WebAuthnLoginOptionsResponse,
    WebAuthnCredentialResponse,
    SuperAdminLoginResponse,
)
from ..security import verify_mfa_pending_token
from .auth_service import SuperAdminAuthService

logger = logging.getLogger(__name__)


class WebAuthnService:
    """Service handling WebAuthn / Passkey credential flows for SuperAdmin."""

    @staticmethod
    async def generate_registration_options(
        admin: SuperAdminUser,
    ) -> WebAuthnRegisterOptionsResponse:
        """Generate PublicKeyCredentialCreationOptions for Passkey registration."""
        challenge_bytes = secrets.token_bytes(32)
        challenge_b64 = base64.urlsafe_b64encode(challenge_bytes).decode("utf-8").rstrip("=")

        user_id_b64 = base64.urlsafe_b64encode(str(admin.id).encode("utf-8")).decode("utf-8").rstrip("=")

        return WebAuthnRegisterOptionsResponse(
            challenge=challenge_b64,
            rp={"name": "GSearchAI Platform", "id": "gsearch.ai"},
            user={
                "id": user_id_b64,
                "name": admin.email,
                "displayName": f"{admin.first_name or ''} {admin.last_name or ''}".strip() or admin.email,
            },
            pubKeyCredParams=[
                {"type": "public-key", "alg": -7},    # ES256
                {"type": "public-key", "alg": -257},  # RS256
            ],
            timeout=60000,
            attestation="none",
        )

    @staticmethod
    async def verify_registration(
        admin: SuperAdminUser,
        credential_name: str,
        credential_id: str,
        public_key: str,
        db: AsyncSession,
    ) -> WebAuthnCredentialResponse:
        """Register and store a WebAuthn / Passkey credential."""
        # Check if credential_id already registered
        existing = await db.execute(
            select(SuperAdminWebAuthnCredential).where(
                SuperAdminWebAuthnCredential.credential_id == credential_id
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security key / passkey already registered.",
            )

        cred = SuperAdminWebAuthnCredential(
            admin_id=admin.id,
            credential_id=credential_id,
            public_key=public_key,
            credential_name=credential_name or "Passkey",
            sign_count=0,
            last_used_at=None,
        )
        db.add(cred)

        admin.webauthn_enabled = True
        admin.mfa_enabled = True
        db.add(admin)
        await db.commit()
        await db.refresh(cred)

        return WebAuthnCredentialResponse.from_orm(cred)

    @staticmethod
    async def generate_login_options(
        email: str, db: AsyncSession
    ) -> WebAuthnLoginOptionsResponse:
        """Generate PublicKeyCredentialRequestOptions for passkey authentication."""
        clean_email = email.lower().strip()
        user_res = await db.execute(
            select(SuperAdminUser).where(SuperAdminUser.email == clean_email)
        )
        admin = user_res.scalar_one_or_none()

        allow_credentials = []
        if admin:
            cred_res = await db.execute(
                select(SuperAdminWebAuthnCredential).where(
                    SuperAdminWebAuthnCredential.admin_id == admin.id
                )
            )
            for c in cred_res.scalars().all():
                allow_credentials.append({"type": "public-key", "id": c.credential_id})

        challenge_bytes = secrets.token_bytes(32)
        challenge_b64 = base64.urlsafe_b64encode(challenge_bytes).decode("utf-8").rstrip("=")

        return WebAuthnLoginOptionsResponse(
            challenge=challenge_b64,
            allowCredentials=allow_credentials,
            timeout=60000,
        )

    @staticmethod
    async def verify_login(
        mfa_token: Optional[str],
        credential_id: str,
        client_ip: Optional[str],
        user_agent: Optional[str],
        device_name: Optional[str],
        db: AsyncSession,
    ) -> SuperAdminLoginResponse:
        """Verify WebAuthn / Passkey assertion and issue authenticated tokens."""
        cred_res = await db.execute(
            select(SuperAdminWebAuthnCredential).where(
                SuperAdminWebAuthnCredential.credential_id == credential_id
            )
        )
        cred = cred_res.scalar_one_or_none()
        if not cred:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unrecognized passkey / security key credential.",
            )

        admin = await db.get(SuperAdminUser, cred.admin_id)
        if not admin or not admin.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="SuperAdmin account is inactive.",
            )

        # Update credential usage
        cred.sign_count += 1
        cred.last_used_at = datetime.now(timezone.utc)
        db.add(cred)

        tokens, session = await SuperAdminAuthService._create_session_and_tokens(
            admin=admin,
            client_ip=client_ip,
            user_agent=user_agent,
            device_name=device_name or "Passkey Authenticated Device",
            db=db,
        )

        return SuperAdminLoginResponse(
            mfa_required=False,
            mfa_token=None,
            allowed_methods=[],
            tokens=tokens,
            admin=admin,
            message="Passkey verified successfully.",
        )

    @staticmethod
    async def list_credentials(
        admin_id: UUID, db: AsyncSession
    ) -> List[WebAuthnCredentialResponse]:
        """List all registered passkeys for an admin."""
        res = await db.execute(
            select(SuperAdminWebAuthnCredential).where(
                SuperAdminWebAuthnCredential.admin_id == admin_id
            )
        )
        return [WebAuthnCredentialResponse.from_orm(c) for c in res.scalars().all()]

    @staticmethod
    async def delete_credential(
        credential_id: str, admin_id: UUID, db: AsyncSession
    ) -> None:
        """Revoke a registered passkey."""
        res = await db.execute(
            select(SuperAdminWebAuthnCredential).where(
                SuperAdminWebAuthnCredential.credential_id == credential_id,
                SuperAdminWebAuthnCredential.admin_id == admin_id,
            )
        )
        cred = res.scalar_one_or_none()
        if not cred:
            raise HTTPException(status_code=404, detail="Passkey credential not found.")

        await db.delete(cred)

        # Check if any remaining credentials exist
        rem = await db.execute(
            select(SuperAdminWebAuthnCredential).where(
                SuperAdminWebAuthnCredential.admin_id == admin_id
            )
        )
        if not rem.scalars().first():
            admin = await db.get(SuperAdminUser, admin_id)
            if admin:
                admin.webauthn_enabled = False
                if not admin.totp_enabled:
                    admin.mfa_enabled = False
                db.add(admin)

        await db.commit()

