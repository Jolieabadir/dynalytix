"""
Auth-related API routes.

Handles: provider signup/login flow, patient token generation,
clinic creation, provider management.

Note: Actual auth (signup, login, session) is handled by Supabase client-side.
These routes handle the Dynalytix-specific parts (linking auth users to
clinics/providers, generating patient tokens, etc.).
"""
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from .middleware import (
    CurrentUser, require_provider, require_clinic_admin,
    generate_patient_token,
)
from .supabase_client import get_admin, is_supabase_configured


router = APIRouter(prefix="/api/auth", tags=["auth"])


# ==================== SCHEMAS ====================

class ClinicCreate(BaseModel):
    name: str
    ehr_system: str = ""
    timezone: str = "America/New_York"


class ProviderSetup(BaseModel):
    """Called after Supabase signup to link auth user to a clinic."""
    clinic_id: str
    name: str
    npi: str = ""
    role: str = "provider"  # "provider" or "clinic_admin"


class PatientCreate(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    dob: str = ""  # ISO date


class PatientTokenRequest(BaseModel):
    patient_id: str
    assessment_type: str = "deep_squat"
    expires_in_days: int = 7


# ==================== ROUTES ====================

@router.get("/me")
async def get_me(user: CurrentUser = Depends(require_provider)):
    """Get the current authenticated user's profile."""
    return {
        "auth_user_id": user.auth_user_id,
        "provider_id": user.provider_id,
        "clinic_id": user.clinic_id,
        "role": user.role,
        "email": user.email,
        "name": user.name,
    }


@router.post("/clinics")
async def create_clinic(clinic: ClinicCreate, user: Optional[CurrentUser] = Depends(require_clinic_admin)):
    """Create a new clinic. The creating user becomes the clinic admin."""
    admin = get_admin()
    if not admin:
        return {"error": "Database not configured", "clinic_id": "dev"}

    result = admin.table("clinics").insert({
        "name": clinic.name,
        "ehr_system": clinic.ehr_system,
        "timezone": clinic.timezone,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create clinic")

    return result.data[0]


@router.post("/providers/setup")
async def setup_provider(setup: ProviderSetup, user: CurrentUser = Depends(require_provider)):
    """
    Link an authenticated Supabase user to a clinic as a provider.
    Called after signup to complete the provider profile.
    """
    admin = get_admin()
    if not admin:
        return {"provider_id": "dev", "clinic_id": setup.clinic_id}

    # Check if provider already exists for this auth user
    existing = admin.table("providers").select("*").eq("auth_user_id", user.auth_user_id).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail="Provider already set up for this account")

    result = admin.table("providers").insert({
        "auth_user_id": user.auth_user_id,
        "clinic_id": setup.clinic_id,
        "name": setup.name,
        "email": user.email,
        "npi": setup.npi,
        "role": setup.role,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create provider")

    return result.data[0]


@router.post("/patients")
async def create_patient(patient: PatientCreate, user: CurrentUser = Depends(require_provider)):
    """Create a new patient in the provider's clinic."""
    admin = get_admin()
    if not admin:
        return {"patient_id": "dev", "clinic_id": user.clinic_id}

    result = admin.table("patients").insert({
        "clinic_id": user.clinic_id,
        "first_name": patient.first_name,
        "last_name": patient.last_name,
        "email": patient.email,
        "phone": patient.phone,
        "dob": patient.dob or None,
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create patient")

    return result.data[0]


@router.get("/patients")
async def list_patients(user: CurrentUser = Depends(require_provider)):
    """List all patients in the provider's clinic."""
    admin = get_admin()
    if not admin:
        return {"patients": [], "clinic_id": user.clinic_id}

    result = admin.table("patients").select("*").eq("clinic_id", user.clinic_id).order("last_name").execute()
    return {"patients": result.data, "clinic_id": user.clinic_id}


@router.post("/patient-tokens")
async def create_patient_token(req: PatientTokenRequest, user: CurrentUser = Depends(require_provider)):
    """
    Generate a secure assessment link for a patient.

    The link contains a token that identifies:
    - Which patient
    - Which clinic
    - Which provider requested it
    - What assessment type
    - When it expires

    The patient clicks this link, films their assessment, and submits.
    No account creation required.
    """
    admin = get_admin()
    if not admin:
        token = generate_patient_token()
        return {"token": token, "url": f"/assess?token={token}", "expires_in_days": req.expires_in_days}

    token = generate_patient_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=req.expires_in_days)

    result = admin.table("patient_tokens").insert({
        "patient_id": req.patient_id,
        "clinic_id": user.clinic_id,
        "provider_id": user.provider_id,
        "token": token,
        "assessment_type": req.assessment_type,
        "expires_at": expires_at.isoformat(),
    }).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create patient token")

    # Build the assessment URL
    # In production this would be https://dynalytix.net/assess?token=...
    base_url = "https://dynalytix.net"
    assessment_url = f"{base_url}/assess?token={token}"

    return {
        "token": token,
        "url": assessment_url,
        "patient_id": req.patient_id,
        "assessment_type": req.assessment_type,
        "expires_at": expires_at.isoformat(),
        "expires_in_days": req.expires_in_days,
    }


@router.get("/clinic/providers")
async def list_clinic_providers(user: CurrentUser = Depends(require_clinic_admin)):
    """List all providers in the admin's clinic."""
    admin = get_admin()
    if not admin:
        return {"providers": [], "clinic_id": user.clinic_id}

    result = admin.table("providers").select("*").eq("clinic_id", user.clinic_id).order("name").execute()
    return {"providers": result.data, "clinic_id": user.clinic_id}
