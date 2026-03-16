"""
EHR Integration Module.

Architecture: Dynalytix → MedStatix Gateway → EHR
Dynalytix never talks to EHR systems directly.

Modules:
- payload: Standardized assessment payload schema (the interface contract)
- adapter: Abstract gateway interface (swap partners without code changes)
- medstatix: MedStatix-specific gateway implementation (stub)
- events: Webhook event types that MedStatix can send us
- clinic_codes: Local cache of clinic billing code mappings (auto-mapping)
- approval: Provider approval workflow (draft → approved → pushed)

Full flow:
1. Patient films assessment at home, submits via link
2. Scoring pipeline runs automatically
3. Billing categories auto-mapped to clinic's own codes (from cached code mappings)
4. Assessment lands in provider dashboard as "draft"
5. Provider reviews pre-mapped results, clicks approve
6. Approved assessment pushed to patient chart via MedStatix → EHR
"""
from .payload import AssessmentPayload, PatientRef, ProviderRef, ClinicRef
from .adapter import EHRGateway, PushResult, PushStatus
from .medstatix import MedStatixGateway
from .clinic_codes import (
    ClinicCodeMap, CodeEntry,
    save_clinic_codes, load_clinic_codes, apply_clinic_codes,
    list_cached_clinics,
)
from .approval import (
    ApprovalStatus, ApprovalRecord,
    create_approval, get_approval, approve, reject,
    mark_pushed, mark_provider_review,
)

__all__ = [
    "AssessmentPayload", "PatientRef", "ProviderRef", "ClinicRef",
    "EHRGateway", "PushResult", "PushStatus", "MedStatixGateway",
    "ClinicCodeMap", "CodeEntry",
    "save_clinic_codes", "load_clinic_codes", "apply_clinic_codes",
    "list_cached_clinics",
    "ApprovalStatus", "ApprovalRecord",
    "create_approval", "get_approval", "approve", "reject",
    "mark_pushed", "mark_provider_review",
]
