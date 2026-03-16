"""
Abstract base class for EHR integrations.

All EHR adapters implement this interface so the rest of the codebase
doesn't need to know which EHR system is being used.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EHRPushResult:
    """Result of pushing an assessment to an EHR."""
    success: bool
    ehr_record_id: str | None = None
    error: str | None = None
    raw_response: dict = field(default_factory=dict)


@dataclass
class PatientRef:
    """Minimal patient reference for EHR lookups."""
    patient_id: str
    first_name: str = ""
    last_name: str = ""
    dob: str = ""  # ISO date
    ehr_patient_id: str | None = None  # The patient's ID in the EHR system


@dataclass
class ProviderRef:
    """Minimal provider reference."""
    provider_id: str
    name: str = ""
    npi: str = ""  # National Provider Identifier
    clinic_id: str = ""


class EHRAdapter(ABC):
    """
    Abstract interface for EHR integrations.

    Concrete implementations (e.g. MedStatixAdapter) handle the specifics
    of each EHR system's API, authentication, and data format.
    """

    @abstractmethod
    async def push_assessment(
        self,
        assessment_data: dict,
        patient: PatientRef,
        provider: ProviderRef,
    ) -> EHRPushResult:
        """
        Push a completed assessment to the EHR.

        The assessment_data dict is the output of run_quick() or run_full()
        from fms/pipeline.py, including billing_descriptions and optionally
        cpt_suggestions.

        The adapter is responsible for:
        1. Mapping billing_descriptions to the practice's own codes
        2. Formatting the clinical narrative for the EHR's documentation format
        3. Attaching the report to the correct patient chart
        """
        ...

    @abstractmethod
    async def get_patient(self, patient_id: str) -> PatientRef | None:
        """Look up a patient in the EHR by their Dynalytix patient ID."""
        ...

    @abstractmethod
    async def map_billing_codes(
        self,
        billing_descriptions: list[dict],
        clinic_id: str,
    ) -> list[dict]:
        """
        Map Dynalytix billing descriptions to a clinic's specific billing codes.

        Each clinic may use different code sets or have their own templates.
        The EHR adapter handles this mapping so Dynalytix doesn't need to
        know the specifics of each practice's billing setup.

        Returns the billing_descriptions list with an added "mapped_code" field
        containing the practice-specific code for each category.
        """
        ...

    @abstractmethod
    async def get_clinic_config(self, clinic_id: str) -> dict:
        """
        Get clinic-specific configuration from the EHR.

        Returns things like:
        - Preferred documentation template
        - Code mapping overrides
        - Report format preferences
        - Provider list for the clinic
        """
        ...

    @abstractmethod
    async def webhook_register(self, clinic_id: str, webhook_url: str) -> bool:
        """
        Register a webhook URL for the EHR to call when events occur
        (e.g. patient scheduled, assessment requested).
        """
        ...
