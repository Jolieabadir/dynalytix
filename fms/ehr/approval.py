"""
Assessment Approval Workflow.

Every assessment follows this lifecycle:
  draft → provider_review → approved (or rejected)

The provider MUST review and approve before results can be pushed to the
patient's chart. This is required for FDA CDS exemption (Criterion 4:
the HCP independently reviews the basis for the recommendation).

Status meanings:
- draft: Scoring pipeline ran, results generated. Not yet reviewed by provider.
- provider_review: Provider has opened/viewed the assessment. Clock is ticking.
- approved: Provider reviewed and approved. Ready to push to EHR / patient chart.
- rejected: Provider reviewed and rejected. Needs re-assessment or manual override.
- pushed: Approved and successfully pushed to the patient's EHR chart.

Storage: JSON sidecar files next to the assessment findings.
  data/exports/fms_findings/{stem}_approval.json
Future: migrate to database table when chart DB (PostgreSQL) is built.
"""
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional


class ApprovalStatus(str, Enum):
    DRAFT = "draft"
    PROVIDER_REVIEW = "provider_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUSHED = "pushed"


@dataclass
class ApprovalRecord:
    """Tracks the approval state of a single assessment."""
    assessment_id: str             # Matches the video_id or assessment filename stem

    status: ApprovalStatus = ApprovalStatus.DRAFT

    # Provider who reviewed (filled on approval/rejection)
    reviewed_by_provider_id: str = ""
    reviewed_by_name: str = ""
    reviewed_at: str = ""          # ISO datetime

    # Provider can add notes when approving/rejecting
    provider_notes: str = ""

    # If provider modified any scores or billing codes during review
    provider_modified_score: bool = False
    provider_modified_billing: bool = False

    # EHR push tracking
    pushed_at: str = ""
    ehr_record_id: str = ""
    push_gateway_request_id: str = ""

    # Timestamps
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ApprovalRecord":
        d = d.copy()
        d["status"] = ApprovalStatus(d.get("status", "draft"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


FINDINGS_DIR = Path("data/exports/fms_findings")


def _approval_path(assessment_id: str) -> Path:
    """Get the path to an assessment's approval sidecar file."""
    return FINDINGS_DIR / f"{assessment_id}_approval.json"


def create_approval(assessment_id: str) -> ApprovalRecord:
    """Create a new approval record when an assessment is first generated."""
    FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    record = ApprovalRecord(
        assessment_id=assessment_id,
        status=ApprovalStatus.DRAFT,
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
    )
    _save(record)
    return record


def get_approval(assessment_id: str) -> Optional[ApprovalRecord]:
    """Load an assessment's approval record."""
    path = _approval_path(assessment_id)
    if not path.exists():
        return None
    with open(path) as f:
        return ApprovalRecord.from_dict(json.load(f))


def approve(
    assessment_id: str,
    provider_id: str,
    provider_name: str = "",
    notes: str = "",
    modified_score: bool = False,
    modified_billing: bool = False,
) -> ApprovalRecord:
    """
    Provider approves the assessment. Results are now ready for EHR push.

    Args:
        assessment_id: The assessment to approve
        provider_id: ID of the approving provider
        provider_name: Name of the approving provider
        notes: Optional provider notes
        modified_score: Whether the provider changed the AI-generated score
        modified_billing: Whether the provider changed any billing codes
    """
    record = get_approval(assessment_id)
    if record is None:
        record = create_approval(assessment_id)

    record.status = ApprovalStatus.APPROVED
    record.reviewed_by_provider_id = provider_id
    record.reviewed_by_name = provider_name
    record.reviewed_at = datetime.now().isoformat()
    record.provider_notes = notes
    record.provider_modified_score = modified_score
    record.provider_modified_billing = modified_billing
    record.updated_at = datetime.now().isoformat()

    _save(record)
    return record


def reject(
    assessment_id: str,
    provider_id: str,
    provider_name: str = "",
    notes: str = "",
) -> ApprovalRecord:
    """Provider rejects the assessment."""
    record = get_approval(assessment_id)
    if record is None:
        record = create_approval(assessment_id)

    record.status = ApprovalStatus.REJECTED
    record.reviewed_by_provider_id = provider_id
    record.reviewed_by_name = provider_name
    record.reviewed_at = datetime.now().isoformat()
    record.provider_notes = notes
    record.updated_at = datetime.now().isoformat()

    _save(record)
    return record


def mark_pushed(
    assessment_id: str,
    ehr_record_id: str = "",
    gateway_request_id: str = "",
) -> ApprovalRecord:
    """Mark an approved assessment as successfully pushed to EHR."""
    record = get_approval(assessment_id)
    if record is None:
        raise ValueError(f"No approval record for assessment {assessment_id}")
    if record.status != ApprovalStatus.APPROVED:
        raise ValueError(f"Cannot push assessment in status '{record.status.value}'. Must be 'approved'.")

    record.status = ApprovalStatus.PUSHED
    record.pushed_at = datetime.now().isoformat()
    record.ehr_record_id = ehr_record_id
    record.push_gateway_request_id = gateway_request_id
    record.updated_at = datetime.now().isoformat()

    _save(record)
    return record


def mark_provider_review(assessment_id: str) -> ApprovalRecord:
    """Mark that a provider has opened/viewed the assessment."""
    record = get_approval(assessment_id)
    if record is None:
        record = create_approval(assessment_id)
    if record.status == ApprovalStatus.DRAFT:
        record.status = ApprovalStatus.PROVIDER_REVIEW
        record.updated_at = datetime.now().isoformat()
        _save(record)
    return record


def _save(record: ApprovalRecord):
    """Save an approval record to disk."""
    FINDINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = _approval_path(record.assessment_id)
    with open(path, "w") as f:
        json.dump(record.to_dict(), f, indent=2)
