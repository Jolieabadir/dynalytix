"""
Webhook event types for inbound events from MedStatix.

MedStatix POSTs to /api/ehr/webhook when things happen on their side.
"""
from dataclasses import dataclass
from enum import Enum


class EventType(str, Enum):
    # Assessment lifecycle
    PUSH_CONFIRMED = "assessment.push_confirmed"
    PUSH_FAILED = "assessment.push_failed"
    PUSH_UPDATED = "assessment.push_updated"

    # Patient events
    PATIENT_SCHEDULED = "patient.scheduled"
    PATIENT_ASSESSMENT_REQUESTED = "patient.assessment_requested"

    # Clinic config events
    CLINIC_CODE_MAPPING_UPDATED = "clinic.code_mapping_updated"
    CLINIC_PROVIDER_ADDED = "clinic.provider_added"
    CLINIC_PROVIDER_REMOVED = "clinic.provider_removed"

    # Connection events
    CLINIC_CONNECTED = "clinic.connected"
    CLINIC_DISCONNECTED = "clinic.disconnected"


@dataclass
class WebhookEvent:
    """Inbound webhook event from MedStatix."""
    event_type: EventType
    clinic_id: str = ""
    patient_id: str = ""
    provider_id: str = ""
    assessment_id: str = ""
    ehr_record_id: str = ""
    data: dict | None = None
    timestamp: str = ""
    gateway_request_id: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "WebhookEvent":
        return cls(
            event_type=EventType(d.get("event_type", "")),
            clinic_id=d.get("clinic_id", ""),
            patient_id=d.get("patient_id", ""),
            provider_id=d.get("provider_id", ""),
            assessment_id=d.get("assessment_id", ""),
            ehr_record_id=d.get("ehr_record_id", ""),
            data=d.get("data"),
            timestamp=d.get("timestamp", ""),
            gateway_request_id=d.get("gateway_request_id", ""),
        )
