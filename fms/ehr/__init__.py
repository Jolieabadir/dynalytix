"""
EHR Integration Module.

Architecture: Dynalytix → MedStatix Gateway → EHR
Dynalytix never talks to EHR systems directly. We push a standardized
assessment payload to MedStatix, and they handle per-EHR translation.

Modules:
- payload: Standardized assessment payload schema (the interface contract)
- adapter: Abstract gateway interface (swap partners without code changes)
- medstatix: MedStatix-specific gateway implementation (stub)
- events: Webhook event types that MedStatix can send us
"""
from .payload import AssessmentPayload, PatientRef, ProviderRef, ClinicRef
from .adapter import EHRGateway, PushResult, PushStatus
from .medstatix import MedStatixGateway

__all__ = [
    "AssessmentPayload", "PatientRef", "ProviderRef", "ClinicRef",
    "EHRGateway", "PushResult", "PushStatus", "MedStatixGateway",
]
