"""
Standardized Assessment Payload — the interface contract between
Dynalytix and the EHR integration partner (MedStatix).

VERSIONED: Breaking changes must increment PAYLOAD_VERSION.
MedStatix's gateway should check the version and handle accordingly.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any


PAYLOAD_VERSION = "1.0.0"


@dataclass
class PatientRef:
    """Patient identification."""
    dynalytix_patient_id: str          # Our internal ID
    first_name: str = ""
    last_name: str = ""
    dob: str = ""                      # ISO date: "1990-05-15"
    email: str = ""
    phone: str = ""
    ehr_patient_id: str | None = None  # Populated by MedStatix after patient lookup


@dataclass
class ProviderRef:
    """Provider identification."""
    dynalytix_provider_id: str         # Our internal ID
    name: str = ""
    npi: str = ""                      # National Provider Identifier
    ehr_provider_id: str | None = None


@dataclass
class ClinicRef:
    """Clinic identification."""
    dynalytix_clinic_id: str           # Our internal ID
    name: str = ""
    medstatix_clinic_id: str = ""
    ehr_system: str = ""               # e.g. "webpt", "clinicient", "theraoffice", "nethealth"
    timezone: str = "America/New_York"


@dataclass
class CriterionResult:
    """Single scoring criterion from the assessment."""
    name: str
    passed: bool
    measured_value: float | None = None
    threshold: float | None = None
    detail: str = ""


@dataclass
class BillingItem:
    """Single billing line item in the payload.

    category + justification are always populated by Dynalytix.
    practice_code is populated by MedStatix after applying the clinic's code mapping.
    """
    category: str
    service_type: str
    justification: str
    units: int | None = None
    practice_code: str | None = None
    practice_modifier: str | None = None


@dataclass
class AssessmentPayload:
    """
    The complete payload Dynalytix sends to MedStatix for EHR integration.

    This is the single object that crosses the Dynalytix→MedStatix boundary.
    MedStatix receives this, maps it to the clinic's EHR format, and pushes it.
    """
    payload_version: str = PAYLOAD_VERSION

    # Who
    patient: PatientRef | None = None
    provider: ProviderRef | None = None
    clinic: ClinicRef | None = None

    # What was assessed
    assessment_type: str = "deep_squat"
    assessment_date: str = ""

    # Results
    score: int = 0
    score_label: str = ""        # "perfect", "compensation", "cannot_complete", "pain"
    pain_reported: bool = False
    criteria: list[CriterionResult] = field(default_factory=list)

    # Raw measurements (provider can review)
    angles_at_depth: dict[str, float] = field(default_factory=dict)
    bilateral_differences: dict[str, float] = field(default_factory=dict)

    # Clinical narrative (AI-generated draft, provider must review)
    clinical_narrative: str | None = None

    # Billing (categories with placeholder slots for practice codes)
    billing_items: list[BillingItem] = field(default_factory=list)

    # Disclaimers
    disclaimer: str = ""

    # Dual-angle scoring
    dual_angle: bool = False
    view_sources: dict[str, str] = field(default_factory=dict)
    front_score: int | None = None
    side_score: int | None = None

    # Metadata
    dynalytix_assessment_id: str = ""
    source_video_hash: str = ""
    processing_mode: str = "quick"

    def to_dict(self) -> dict:
        """Serialize to dict for JSON transmission to MedStatix."""
        return asdict(self)

    @classmethod
    def from_pipeline_result(
        cls,
        result: dict,
        patient: PatientRef | None = None,
        provider: ProviderRef | None = None,
        clinic: ClinicRef | None = None,
        assessment_id: str = "",
    ) -> "AssessmentPayload":
        """
        Build a payload from the output of pipeline.run_quick() or run_full().

        This is the bridge between our internal pipeline output and the
        standardized payload that MedStatix consumes.
        """
        score = result.get("score", 0)
        score_labels = {3: "perfect", 2: "compensation", 1: "cannot_complete", 0: "pain"}

        billing_items = []
        for b in result.get("billing_descriptions", []):
            billing_items.append(BillingItem(
                category=b["category"],
                service_type=b["service_type"],
                justification=b["justification"],
                units=b.get("units"),
                practice_code=b.get("practice_code"),
                practice_modifier=b.get("practice_modifier"),
            ))

        criteria = []
        for c in result.get("criteria", []):
            criteria.append(CriterionResult(
                name=c["name"],
                passed=c["passed"],
                measured_value=c.get("value"),
                threshold=c.get("threshold"),
                detail=c.get("detail", ""),
            ))

        return cls(
            patient=patient,
            provider=provider,
            clinic=clinic,
            assessment_type="deep_squat",
            assessment_date=datetime.now().isoformat(),
            score=score,
            score_label=score_labels.get(score, "unknown"),
            pain_reported=result.get("pain_reported", score == 0),
            criteria=criteria,
            angles_at_depth=result.get("angles_at_depth", {}),
            bilateral_differences=result.get("bilateral_differences", {}),
            clinical_narrative=result.get("clinical_report"),
            billing_items=billing_items,
            disclaimer=result.get("disclaimer", ""),
            dual_angle=result.get("dual_angle", False),
            view_sources=result.get("view_sources", {}),
            front_score=result.get("front_score"),
            side_score=result.get("side_score"),
            dynalytix_assessment_id=assessment_id,
            processing_mode=result.get("mode", "quick"),
        )
