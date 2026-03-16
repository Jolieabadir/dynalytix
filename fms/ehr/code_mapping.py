"""
Billing code mapping utilities.

Maps Dynalytix's generic billing categories to practice-specific codes.
Each clinic may use different code sets depending on their EHR, payer mix,
and documentation preferences.

This module provides the mapping logic. The actual mappings per clinic
are stored in and retrieved from the EHR adapter (e.g. MedStatix).
"""
from dataclasses import dataclass


@dataclass
class CodeMapping:
    """A mapping from a Dynalytix billing category to a practice-specific code."""
    dynalytix_category: str       # e.g. "Physical Performance Testing"
    practice_code: str            # e.g. "97750" or practice-specific identifier
    practice_description: str     # How the practice labels this service
    modifier: str = ""            # e.g. "GP", "59" — practice-specific modifiers
    notes: str = ""


# Default mapping — used when no clinic-specific mapping exists.
# These are the most common code associations but each clinic can override.
DEFAULT_CATEGORY_TO_CODE = {
    "Physical Performance Testing": "97750",
    "Physical Therapy Evaluation — Low Complexity": "97161",
    "Physical Therapy Evaluation — Moderate Complexity": "97162",
    "Physical Therapy Evaluation — High Complexity": "97163",
    "Physical Therapy Re-evaluation": "97164",
    "Therapeutic Exercise": "97110",
    "Neuromuscular Re-education": "97112",
    "Gait Training": "97116",
    "Manual Therapy": "97140",
    "Therapeutic Activities": "97530",
}


def apply_clinic_mapping(
    billing_descriptions: list[dict],
    clinic_mapping: dict[str, CodeMapping] | None = None,
) -> list[dict]:
    """
    Apply a clinic-specific code mapping to billing descriptions.

    If no clinic mapping is provided, uses the default mapping.

    Args:
        billing_descriptions: Output from suggest_all_billing_descriptions()
        clinic_mapping: Dict of category -> CodeMapping from the EHR adapter

    Returns:
        Enriched billing descriptions with mapped_code, mapped_description,
        and modifier fields added.
    """
    for desc in billing_descriptions:
        category = desc.get("category", "")

        if clinic_mapping and category in clinic_mapping:
            mapping = clinic_mapping[category]
            desc["mapped_code"] = mapping.practice_code
            desc["mapped_description"] = mapping.practice_description
            desc["modifier"] = mapping.modifier
            desc["mapping_source"] = "clinic"
        elif category in DEFAULT_CATEGORY_TO_CODE:
            desc["mapped_code"] = DEFAULT_CATEGORY_TO_CODE[category]
            desc["mapped_description"] = category
            desc["modifier"] = ""
            desc["mapping_source"] = "default"
        else:
            desc["mapped_code"] = None
            desc["mapped_description"] = category
            desc["modifier"] = ""
            desc["mapping_source"] = "unmapped"

    return billing_descriptions
