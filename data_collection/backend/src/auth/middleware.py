"""
FastAPI auth middleware and dependency injection.

Provides:
- get_current_user: Extracts and validates the JWT from the Authorization header
- require_provider: Ensures the user is a provider (not a patient)
- require_clinic_admin: Ensures the user is a clinic admin
- verify_patient_token: Validates a patient assessment token

Falls back gracefully if Supabase is not configured (dev mode — no auth required).
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Header, Query, status

try:
    from jose import jwt, JWTError
    HAS_JOSE = True
except ImportError:
    HAS_JOSE = False

from .supabase_client import get_admin, is_supabase_configured


@dataclass
class CurrentUser:
    """The authenticated user for the current request."""
    auth_user_id: str          # Supabase auth.users.id
    provider_id: str = ""      # providers.id (empty if patient)
    clinic_id: str = ""        # The user's clinic
    role: str = ""             # "provider" | "clinic_admin" | "patient"
    email: str = ""
    name: str = ""


async def get_current_user(
    authorization: Optional[str] = Header(None),
) -> Optional[CurrentUser]:
    """
    Extract and validate the user from the Authorization header.

    In dev mode (Supabase not configured), returns None (no auth enforced).
    In production, validates the JWT and looks up the provider record.
    """
    if not is_supabase_configured():
        # Dev mode — no auth required
        return None

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1]

    try:
        # Supabase JWTs are signed with the JWT secret from project settings
        jwt_secret = os.environ.get("SUPABASE_JWT_SECRET", "")
        if not jwt_secret:
            raise HTTPException(status_code=500, detail="SUPABASE_JWT_SECRET not configured")

        payload = jwt.decode(token, jwt_secret, algorithms=["HS256"], audience="authenticated")
        auth_user_id = payload.get("sub", "")
        email = payload.get("email", "")

        if not auth_user_id:
            raise HTTPException(status_code=401, detail="Invalid token: no subject")

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
        )

    # Look up the provider record for this auth user
    admin = get_admin()
    if admin:
        result = admin.table("providers").select("*").eq("auth_user_id", auth_user_id).execute()
        if result.data:
            provider = result.data[0]
            return CurrentUser(
                auth_user_id=auth_user_id,
                provider_id=provider["id"],
                clinic_id=provider["clinic_id"],
                role=provider["role"],
                email=provider["email"],
                name=provider["name"],
            )

    # Auth user exists but no provider record — might be new signup
    return CurrentUser(
        auth_user_id=auth_user_id,
        email=email,
        role="unlinked",
    )


async def require_provider(
    user: Optional[CurrentUser] = Depends(get_current_user),
) -> CurrentUser:
    """Require that the current user is a provider or clinic admin."""
    if user is None:
        # Dev mode — return a dummy provider
        return CurrentUser(auth_user_id="dev", provider_id="dev", clinic_id="dev", role="provider")
    if user.role not in ("provider", "clinic_admin"):
        raise HTTPException(status_code=403, detail="Provider access required")
    return user


async def require_clinic_admin(
    user: Optional[CurrentUser] = Depends(get_current_user),
) -> CurrentUser:
    """Require that the current user is a clinic admin."""
    if user is None:
        return CurrentUser(auth_user_id="dev", provider_id="dev", clinic_id="dev", role="clinic_admin")
    if user.role != "clinic_admin":
        raise HTTPException(status_code=403, detail="Clinic admin access required")
    return user


def generate_patient_token() -> str:
    """Generate a cryptographically secure patient assessment token."""
    return secrets.token_urlsafe(32)


async def verify_patient_token(
    token: str = Query(..., description="Patient assessment token from the URL"),
) -> dict:
    """
    Validate a patient assessment token.

    Returns the token record if valid and not expired/used.
    """
    if not is_supabase_configured():
        # Dev mode
        return {"patient_id": "dev", "clinic_id": "dev", "provider_id": "dev", "assessment_type": "deep_squat"}

    admin = get_admin()
    if not admin:
        raise HTTPException(status_code=500, detail="Database not configured")

    result = admin.table("patient_tokens").select("*").eq("token", token).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Invalid assessment token")

    token_record = result.data[0]

    # Check expiration
    expires_at = datetime.fromisoformat(token_record["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=410, detail="Assessment token has expired")

    # Check if already used
    if token_record["is_used"]:
        raise HTTPException(status_code=410, detail="Assessment token has already been used")

    return token_record
