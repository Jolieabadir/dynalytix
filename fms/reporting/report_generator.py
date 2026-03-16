"""
LLM-powered report generator.

Calls the Anthropic API to generate clinical reports and CPT code suggestions
from movement scoring data.
"""
import json
import os
from dataclasses import dataclass

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

from .templates import build_report_prompt, build_cpt_prompt


@dataclass
class CPTSuggestion:
    """A suggested CPT billing code."""
    code: str
    description: str
    justification: str
    units: int | None = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "description": self.description,
            "justification": self.justification,
            "units": self.units,
        }


@dataclass
class FMSReport:
    """Complete movement assessment report with clinical narrative and billing suggestions."""
    clinical_report: str
    cpt_suggestions: list[CPTSuggestion]
    score: int
    raw_data: dict
    billing_descriptions: list[dict] | None = None

    def to_dict(self) -> dict:
        return {
            "clinical_report": self.clinical_report,
            "cpt_suggestions": [c.to_dict() for c in self.cpt_suggestions],
            "billing_descriptions": self.billing_descriptions or [],
            "score": self.score,
        }

    def print_report(self):
        """Print the full formatted report."""
        print("=" * 70)
        print("MOVEMENT ASSESSMENT REPORT")
        print("=" * 70)
        print()
        print(self.clinical_report)
        print()
        print("-" * 70)
        print("BILLING CATEGORIES")
        print("-" * 70)
        if self.billing_descriptions:
            for b in self.billing_descriptions:
                units_str = f" ({b.get('units', '')} units)" if b.get("units") else ""
                print(f"\n  {b['category']}{units_str} [{b['service_type']}]")
                print(f"    Justification: {b['justification']}")
        if self.cpt_suggestions:
            print()
            print("CPT CODE SUGGESTIONS (Pro tier)")
            print("-" * 70)
            for cpt in self.cpt_suggestions:
                units_str = f" ({cpt.units} units)" if cpt.units else ""
                print(f"\n  {cpt.code}{units_str} - {cpt.description}")
                print(f"    Justification: {cpt.justification}")
            print()
            print("⚠ CPT codes are SUGGESTIONS only. The treating physical")
            print("  therapist must review and approve all billing codes.")
        from ..disclaimer import CLINICAL_DISCLAIMER
        print()
        print("DISCLAIMER")
        print("-" * 70)
        print(CLINICAL_DISCLAIMER)
        print()
        print("=" * 70)


def _call_anthropic(system: str, user: str, model: str = "claude-sonnet-4-20250514") -> str:
    """Make an API call to Anthropic."""
    if not HAS_ANTHROPIC:
        raise ImportError(
            "anthropic package not installed. Run: pip install anthropic"
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY environment variable not set. "
            "Get your key at https://console.anthropic.com/"
        )

    client = anthropic.Anthropic(api_key=api_key)

    message = client.messages.create(
        model=model,
        max_tokens=1500,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    return message.content[0].text


def generate_clinical_report(result_dict: dict) -> str:
    """
    Generate a clinical narrative report from scoring results.

    Args:
        result_dict: Output from DeepSquatResult.to_dict()

    Returns:
        Clinical report text.
    """
    system, user = build_report_prompt(result_dict)
    return _call_anthropic(system, user)


def generate_cpt_suggestions(result_dict: dict) -> list[CPTSuggestion]:
    """
    Generate CPT code suggestions from scoring results.

    Args:
        result_dict: Output from DeepSquatResult.to_dict()

    Returns:
        List of CPTSuggestion objects.
    """
    system, user = build_cpt_prompt(result_dict)
    raw = _call_anthropic(system, user)

    # Parse JSON response
    try:
        # Strip any markdown fencing the LLM might add
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]

        codes = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        # Fallback: return the raw text as a single suggestion
        return [
            CPTSuggestion(
                code="PARSE_ERROR",
                description="Could not parse LLM response",
                justification=raw,
            )
        ]

    suggestions = []
    for item in codes:
        suggestions.append(
            CPTSuggestion(
                code=item.get("code", ""),
                description=item.get("description", ""),
                justification=item.get("justification", ""),
                units=item.get("units"),
            )
        )

    return suggestions


def generate_full_report(result_dict: dict, include_cpt_codes: bool = False) -> FMSReport:
    """
    Generate the complete report: clinical narrative + billing descriptions.

    Args:
        result_dict: Output from DeepSquatResult.to_dict()
        include_cpt_codes: If True, include CPT codes (Pro tier / EHR integration).

    Returns:
        FMSReport with all components.
    """
    from ..billing.cpt_codes import suggest_all_billing_descriptions

    clinical = generate_clinical_report(result_dict)

    # Billing descriptions (always generated — base tier)
    billing_descs = suggest_all_billing_descriptions(
        score=result_dict["score"],
        criteria_results=result_dict["criteria"],
    )

    # CPT codes only if explicitly requested (Pro tier)
    cpt_codes = None
    if include_cpt_codes:
        cpt_codes = generate_cpt_suggestions(result_dict)

    return FMSReport(
        clinical_report=clinical,
        cpt_suggestions=cpt_codes or [],
        score=result_dict["score"],
        raw_data=result_dict,
        billing_descriptions=[
            {
                "category": b.category,
                "service_type": b.service_type,
                "justification": b.justification,
                "units": b.units,
                "practice_code": b.practice_code,        # None until EHR integration
                "practice_modifier": b.practice_modifier,  # None until EHR integration
                "mapping_status": b.mapping_status,        # "unmapped" until EHR integration
            }
            for b in billing_descs
        ],
    )
