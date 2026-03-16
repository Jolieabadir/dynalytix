"""
MedStatix EHR Adapter — STUB.

MedStatix is Dynalytix's EHR integration partner. This adapter will handle:
- Pushing assessment results into patient charts
- Mapping Dynalytix billing categories to each practice's own codes
- Formatting clinical narratives in the practice's documentation style
- Receiving webhooks when patients are scheduled for assessments

This is a stub implementation. The real integration will be built once
MedStatix provides their API documentation and sandbox credentials.

Contact: MedStatix team (via Jolie's dad)
"""
import os
from .ehr_adapter import EHRAdapter, EHRPushResult, PatientRef, ProviderRef


class MedStatixAdapter(EHRAdapter):
    """
    MedStatix EHR integration.

    Config via environment variables:
    - MEDSTATIX_API_URL: Base URL for MedStatix API
    - MEDSTATIX_API_KEY: API key for authentication
    - MEDSTATIX_CLINIC_ID: Default clinic ID (can be overridden per-call)
    """

    def __init__(self):
        self.api_url = os.environ.get("MEDSTATIX_API_URL", "")
        self.api_key = os.environ.get("MEDSTATIX_API_KEY", "")
        self.default_clinic_id = os.environ.get("MEDSTATIX_CLINIC_ID", "")
        self._initialized = bool(self.api_url and self.api_key)

    @property
    def is_configured(self) -> bool:
        """Check if MedStatix credentials are set."""
        return self._initialized

    async def push_assessment(
        self,
        assessment_data: dict,
        patient: PatientRef,
        provider: ProviderRef,
    ) -> EHRPushResult:
        """
        Push assessment to MedStatix patient chart.

        STUB: Returns a mock success response.

        Real implementation will:
        1. POST to MedStatix API with assessment data
        2. MedStatix maps to practice's documentation format
        3. Assessment appears in patient's chart
        4. Return the EHR record ID for reference
        """
        if not self.is_configured:
            return EHRPushResult(
                success=False,
                error="MedStatix not configured. Set MEDSTATIX_API_URL and MEDSTATIX_API_KEY.",
            )

        # STUB — will be replaced with actual API call
        return EHRPushResult(
            success=False,
            error="MedStatix integration not yet implemented. Stub only.",
        )

    async def get_patient(self, patient_id: str) -> PatientRef | None:
        """
        Look up patient in MedStatix.

        STUB: Returns None.
        """
        if not self.is_configured:
            return None

        # STUB
        return None

    async def map_billing_codes(
        self,
        billing_descriptions: list[dict],
        clinic_id: str = "",
    ) -> list[dict]:
        """
        Map Dynalytix billing categories to the clinic's specific codes.

        STUB: Returns descriptions unchanged (no mapping applied).

        Real implementation will:
        1. Fetch clinic's code mapping from MedStatix
        2. Map each billing category to the practice's preferred codes
        3. Return enriched descriptions with mapped_code field
        """
        clinic_id = clinic_id or self.default_clinic_id

        # STUB — return descriptions with empty mapped_code
        for desc in billing_descriptions:
            desc["mapped_code"] = None
            desc["mapping_source"] = "unmapped"

        return billing_descriptions

    async def get_clinic_config(self, clinic_id: str = "") -> dict:
        """
        Get clinic configuration from MedStatix.

        STUB: Returns empty config.
        """
        return {
            "clinic_id": clinic_id or self.default_clinic_id,
            "configured": False,
            "documentation_template": None,
            "code_mapping": {},
            "providers": [],
        }

    async def webhook_register(self, clinic_id: str, webhook_url: str) -> bool:
        """
        Register webhook with MedStatix.

        STUB: Returns False.
        """
        return False
