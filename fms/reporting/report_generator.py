"""
LLM-powered report generator.

Calls the Anthropic API to generate clinical reports and CPT code suggestions
from FMS scoring data.
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
    """Complete FMS report with clinical narrative and billing suggestions."""
    clinical_report: str
    cpt_suggestions: list[CPTSuggestion]
    score: int
    raw_data: dict

    def to_dict(self) -> dict:
        return {
            "clinical_report": self.clinical_report,
            "cpt_suggestions": [c.to_dict() for c in self.cpt_suggestions],
            "score": self.score,
        }

    def print_report(self):
        """Print the full formatted report."""
        print("=" * 70)
        print("FMS DEEP SQUAT ASSESSMENT REPORT")
        print("=" * 70)
        print()
        print(self.clinical_report)
        print()
        print("-" * 70)
        print("SUGGESTED CPT CODES")
        print("-" * 70)
        for cpt in self.cpt_suggestions:
            units_str = f" ({cpt.units} units)" if cpt.units else ""
            print(f"\n  {cpt.code}{units_str} - {cpt.description}")
            print(f"    Justification: {cpt.justification}")
        print()
        print("=" * 70)
        print("NOTE: CPT codes are SUGGESTIONS only. The treating physical")
        print("therapist must review and approve all billing codes.")
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


def generate_full_report(result_dict: dict) -> FMSReport:
    """
    Generate the complete report: clinical narrative + CPT suggestions.

    Args:
        result_dict: Output from DeepSquatResult.to_dict()

    Returns:
        FMSReport with all components.
    """
    clinical = generate_clinical_report(result_dict)
    cpt_codes = generate_cpt_suggestions(result_dict)

    return FMSReport(
        clinical_report=clinical,
        cpt_suggestions=cpt_codes,
        score=result_dict["score"],
        raw_data=result_dict,
    )
