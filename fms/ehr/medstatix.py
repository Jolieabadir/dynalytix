"""
MedStatix EHR Gateway — STUB.

MedStatix handles: EHR connections (WebPT, Clinicient, TheraOffice, Net Health),
billing code mapping per clinic, documentation formatting, patient chart operations.

Stub until MedStatix provides API docs and sandbox credentials.

Environment variables (set when MedStatix provides them):
- MEDSTATIX_API_URL
- MEDSTATIX_API_KEY
- MEDSTATIX_WEBHOOK_SECRET
"""
import os
from .adapter import EHRGateway, PushResult, PushStatus
from .payload import AssessmentPayload, ClinicRef


class MedStatixGateway(EHRGateway):

    def __init__(self):
        self.api_url = os.environ.get("MEDSTATIX_API_URL", "")
        self.api_key = os.environ.get("MEDSTATIX_API_KEY", "")
        self.webhook_secret = os.environ.get("MEDSTATIX_WEBHOOK_SECRET", "")

    @property
    def is_configured(self) -> bool:
        return bool(self.api_url and self.api_key)

    async def push_assessment(self, payload: AssessmentPayload) -> PushResult:
        """STUB: Returns not_implemented."""
        if not self.is_configured:
            return PushResult(status=PushStatus.NOT_CONFIGURED, error="Set MEDSTATIX_API_URL and MEDSTATIX_API_KEY.")
        return PushResult(status=PushStatus.NOT_IMPLEMENTED, error="Awaiting MedStatix API docs.")

    async def map_codes(self, payload: AssessmentPayload) -> AssessmentPayload:
        """STUB: Returns payload unchanged (codes remain unmapped)."""
        return payload

    async def get_clinic_config(self, clinic: ClinicRef) -> dict:
        """STUB: Returns empty config."""
        return {"clinic_id": clinic.dynalytix_clinic_id, "configured": False, "code_mappings": {}, "providers": []}

    async def lookup_patient(self, clinic: ClinicRef, first_name: str = "", last_name: str = "", dob: str = "", email: str = "") -> dict | None:
        """STUB: Returns None."""
        return None

    async def check_status(self, gateway_request_id: str) -> PushResult:
        """STUB: Returns not_implemented."""
        return PushResult(status=PushStatus.NOT_IMPLEMENTED, error="Status checking not yet implemented.")
