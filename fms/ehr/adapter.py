"""
Abstract EHR Gateway interface.

Any EHR integration partner (MedStatix, or a future replacement) implements
this interface. The rest of Dynalytix only depends on the abstract interface.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from .payload import AssessmentPayload, ClinicRef


class PushStatus(str, Enum):
    SUCCESS = "success"
    PENDING = "pending"
    FAILED = "failed"
    NOT_CONFIGURED = "not_configured"
    NOT_IMPLEMENTED = "not_implemented"


@dataclass
class PushResult:
    status: PushStatus
    ehr_record_id: str | None = None
    gateway_request_id: str | None = None
    error: str | None = None
    raw_response: dict = field(default_factory=dict)


class EHRGateway(ABC):
    """
    Abstract interface for EHR integration gateways.

    Dynalytix calls these methods. The gateway handles auth, code mapping,
    formatting, and pushing to the EHR.
    """

    @abstractmethod
    async def push_assessment(self, payload: AssessmentPayload) -> PushResult:
        """Push a completed assessment to the EHR."""
        ...

    @abstractmethod
    async def map_codes(self, payload: AssessmentPayload) -> AssessmentPayload:
        """Map billing categories to clinic-specific codes (fills practice_code fields)."""
        ...

    @abstractmethod
    async def get_clinic_config(self, clinic: ClinicRef) -> dict:
        """Get clinic-specific config (code mappings, EHR system, template)."""
        ...

    @abstractmethod
    async def lookup_patient(self, clinic: ClinicRef, first_name: str = "", last_name: str = "", dob: str = "", email: str = "") -> dict | None:
        """Look up a patient in the clinic's EHR."""
        ...

    @abstractmethod
    async def check_status(self, gateway_request_id: str) -> PushResult:
        """Check the status of a previously submitted push request."""
        ...

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Whether the gateway has valid credentials."""
        ...
