"""
Clinic Code Mapping Cache.

When a clinic connects via MedStatix, their billing code mappings are synced
to Dynalytix and cached locally. Every assessment auto-maps against this cache
so billing codes are pre-filled BEFORE the provider ever sees the results.

The provider should never manually select codes. The flow is:
  Patient films → pipeline scores → codes auto-mapped → provider clicks approve → done.

Cache is refreshed when MedStatix sends a clinic.code_mapping_updated webhook event,
or when manually triggered via the /api/ehr/clinic/{id}/sync endpoint.

Storage: JSON files in data/clinic_codes/{clinic_id}.json
Future: migrate to database table when chart DB (PostgreSQL) is built.
"""
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# Storage location for clinic code caches
CLINIC_CODES_DIR = Path("data/clinic_codes")


@dataclass
class CodeEntry:
    """A single code mapping entry for a clinic.

    Maps a Dynalytix billing category to the clinic's own code.
    Example: "Physical Performance Testing" → "97750" with modifier "GP"
    """
    billing_category: str       # Dynalytix category e.g. "Physical Performance Testing"
    practice_code: str          # Clinic's code e.g. "97750" or custom internal code
    practice_description: str   # How the clinic labels it in their system
    modifier: str = ""          # e.g. "GP", "59", "KX"
    unit_rate: float = 0.0     # Reimbursement rate per unit (for ROI tracking, optional)


@dataclass
class ClinicCodeMap:
    """Complete code mapping table for a clinic.

    Pulled from MedStatix and cached locally. Each clinic has their own
    code preferences depending on their EHR, payer mix, and billing workflow.
    """
    clinic_id: str
    clinic_name: str = ""
    ehr_system: str = ""                                # e.g. "webpt", "clinicient"
    entries: list[CodeEntry] = field(default_factory=list)
    synced_at: str = ""                                 # ISO datetime of last sync
    source: str = "medstatix"                           # where the mapping came from

    def get_entry(self, billing_category: str) -> Optional[CodeEntry]:
        """Look up the clinic's code for a Dynalytix billing category."""
        for entry in self.entries:
            if entry.billing_category == billing_category:
                return entry
        return None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ClinicCodeMap":
        entries = [CodeEntry(**e) for e in d.get("entries", [])]
        return cls(
            clinic_id=d.get("clinic_id", ""),
            clinic_name=d.get("clinic_name", ""),
            ehr_system=d.get("ehr_system", ""),
            entries=entries,
            synced_at=d.get("synced_at", ""),
            source=d.get("source", "medstatix"),
        )


def save_clinic_codes(code_map: ClinicCodeMap) -> Path:
    """Save a clinic's code mappings to the local cache."""
    CLINIC_CODES_DIR.mkdir(parents=True, exist_ok=True)
    path = CLINIC_CODES_DIR / f"{code_map.clinic_id}.json"
    with open(path, "w") as f:
        json.dump(code_map.to_dict(), f, indent=2)
    return path


def load_clinic_codes(clinic_id: str) -> Optional[ClinicCodeMap]:
    """Load a clinic's cached code mappings. Returns None if not cached."""
    path = CLINIC_CODES_DIR / f"{clinic_id}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return ClinicCodeMap.from_dict(json.load(f))


def list_cached_clinics() -> list[str]:
    """List all clinic IDs that have cached code mappings."""
    if not CLINIC_CODES_DIR.exists():
        return []
    return [p.stem for p in CLINIC_CODES_DIR.glob("*.json")]


def delete_clinic_codes(clinic_id: str) -> bool:
    """Delete a clinic's cached code mappings."""
    path = CLINIC_CODES_DIR / f"{clinic_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def apply_clinic_codes(billing_descriptions: list[dict], clinic_id: str) -> list[dict]:
    """
    Auto-map billing descriptions using a clinic's cached code mappings.

    This is the function that makes the magic happen. Called automatically
    after every scoring run when a clinic_id is provided. Fills in the
    practice_code, practice_modifier, and mapping_status fields so the
    provider sees pre-mapped codes when they open the assessment.

    Args:
        billing_descriptions: List of billing description dicts from the pipeline
        clinic_id: The clinic whose code mappings to apply

    Returns:
        The same list with practice_code/practice_modifier/mapping_status filled in.
        If no cached codes exist for this clinic, returns descriptions unchanged.
    """
    code_map = load_clinic_codes(clinic_id)
    if code_map is None:
        # No cached codes for this clinic — leave unmapped
        return billing_descriptions

    for desc in billing_descriptions:
        category = desc.get("category", "")
        entry = code_map.get_entry(category)
        if entry:
            desc["practice_code"] = entry.practice_code
            desc["practice_modifier"] = entry.modifier
            desc["mapping_status"] = "clinic_mapped"
        else:
            # Category exists in Dynalytix but clinic has no mapping for it
            desc["mapping_status"] = "unmapped"

    return billing_descriptions
