"""
CPT Code Reference and Rule-Based Suggestions.

This module provides CPT code suggestions WITHOUT requiring an LLM call.
Useful as a fallback when no API key is available, or for instant results.

The LLM report generator produces more nuanced suggestions, but this
rule-based approach covers the common cases accurately.

DISCLAIMER: These are suggestions only. The treating physical therapist
must review and approve all billing codes. This system does not provide
billing advice.
"""
from dataclasses import dataclass


# =============================================================================
# CPT CODE REFERENCE
# =============================================================================

CPT_CODES = {
    # Assessment codes
    "97161": {
        "description": "PT Evaluation - Low Complexity",
        "category": "evaluation",
        "timed": False,
        "notes": "Single body system, limited clinical decision making",
    },
    "97162": {
        "description": "PT Evaluation - Moderate Complexity",
        "category": "evaluation",
        "timed": False,
        "notes": "Multiple body systems, moderate clinical decision making",
    },
    "97163": {
        "description": "PT Evaluation - High Complexity",
        "category": "evaluation",
        "timed": False,
        "notes": "Multiple body systems, high clinical decision making",
    },
    "97164": {
        "description": "PT Re-evaluation",
        "category": "evaluation",
        "timed": False,
        "notes": "Reassessment of established plan of care",
    },
    "97750": {
        "description": "Physical Performance Test or Measurement",
        "category": "assessment",
        "timed": True,
        "unit_minutes": 15,
        "notes": "Functional testing with written report required. "
                 "FMS assessment falls under this code.",
    },

    # Treatment codes
    "97110": {
        "description": "Therapeutic Exercise",
        "category": "treatment",
        "timed": True,
        "unit_minutes": 15,
        "notes": "Exercises for strength, endurance, ROM, flexibility",
    },
    "97112": {
        "description": "Neuromuscular Re-education",
        "category": "treatment",
        "timed": True,
        "unit_minutes": 15,
        "notes": "Movement, balance, coordination, posture training",
    },
    "97116": {
        "description": "Gait Training",
        "category": "treatment",
        "timed": True,
        "unit_minutes": 15,
        "notes": "Walking training, mobility improvement",
    },
    "97140": {
        "description": "Manual Therapy",
        "category": "treatment",
        "timed": True,
        "unit_minutes": 15,
        "notes": "Joint mobilization, soft tissue mobilization, manipulation",
    },
    "97530": {
        "description": "Therapeutic Activities",
        "category": "treatment",
        "timed": True,
        "unit_minutes": 15,
        "notes": "Functional activities (lifting, reaching, bending)",
    },
}


# =============================================================================
# RULE-BASED CPT SUGGESTIONS
# =============================================================================

@dataclass
class CPTSuggestion:
    """A suggested CPT billing code."""
    code: str
    description: str
    justification: str
    units: int | None = None


def suggest_assessment_codes(score: int, test_duration_minutes: int = 15) -> list[CPTSuggestion]:
    """
    Suggest assessment CPT codes for the FMS screen itself.

    Args:
        score: FMS score (0-3)
        test_duration_minutes: Time spent on assessment
    """
    suggestions = []

    # 97750 - Physical Performance Test
    units = max(1, test_duration_minutes // 15)
    suggestions.append(
        CPTSuggestion(
            code="97750",
            description="Physical Performance Test or Measurement",
            justification="FMS Deep Squat assessment with computer vision-assisted "
                          "movement analysis and written report",
            units=units,
        )
    )

    return suggestions


def suggest_treatment_codes(criteria_results: list[dict]) -> list[CPTSuggestion]:
    """
    Suggest treatment CPT codes based on identified deficits.

    Maps specific FMS criterion failures to appropriate treatment codes.
    """
    suggestions = []
    seen_codes = set()

    for criterion in criteria_results:
        if criterion["passed"]:
            continue

        name = criterion["name"].lower()

        # Ankle / heel rise issues → manual therapy + therapeutic exercise
        if "heel" in name or "ankle" in name:
            if "97140" not in seen_codes:
                suggestions.append(
                    CPTSuggestion(
                        code="97140",
                        description="Manual Therapy",
                        justification="Joint mobilization for ankle dorsiflexion "
                                      "deficit identified during FMS deep squat",
                        units=1,
                    )
                )
                seen_codes.add("97140")

            if "97110" not in seen_codes:
                suggestions.append(
                    CPTSuggestion(
                        code="97110",
                        description="Therapeutic Exercise",
                        justification="Ankle dorsiflexion and calf flexibility "
                                      "exercises to address heel rise compensation",
                        units=2,
                    )
                )
                seen_codes.add("97110")

        # Torso alignment / core issues → neuromuscular re-ed + therapeutic exercise
        if "torso" in name or "lumbar" in name:
            if "97112" not in seen_codes:
                suggestions.append(
                    CPTSuggestion(
                        code="97112",
                        description="Neuromuscular Re-education",
                        justification="Core stability and trunk control retraining "
                                      "to address torso alignment deficit during squat",
                        units=1,
                    )
                )
                seen_codes.add("97112")

            if "97110" not in seen_codes:
                suggestions.append(
                    CPTSuggestion(
                        code="97110",
                        description="Therapeutic Exercise",
                        justification="Core strengthening and thoracic mobility "
                                      "exercises to improve squat mechanics",
                        units=2,
                    )
                )
                seen_codes.add("97110")

        # Knee alignment issues → neuromuscular re-ed
        if "knee" in name and "97112" not in seen_codes:
            suggestions.append(
                CPTSuggestion(
                    code="97112",
                    description="Neuromuscular Re-education",
                    justification="Hip and knee neuromuscular control training "
                                  "to address knee valgus/varus during squat",
                    units=1,
                )
            )
            seen_codes.add("97112")

        # Depth issues → therapeutic exercise + activities
        if "depth" in name:
            if "97110" not in seen_codes:
                suggestions.append(
                    CPTSuggestion(
                        code="97110",
                        description="Therapeutic Exercise",
                        justification="Hip flexion mobility and lower extremity "
                                      "strengthening to improve squat depth",
                        units=2,
                    )
                )
                seen_codes.add("97110")

            if "97530" not in seen_codes:
                suggestions.append(
                    CPTSuggestion(
                        code="97530",
                        description="Therapeutic Activities",
                        justification="Functional squat progression activities "
                                      "to improve movement pattern",
                        units=1,
                    )
                )
                seen_codes.add("97530")

    return suggestions


def suggest_all_codes(
    score: int,
    criteria_results: list[dict],
    test_duration_minutes: int = 15,
) -> list[CPTSuggestion]:
    """
    Generate complete CPT code suggestions for an FMS assessment.

    Combines assessment codes (for the screen itself) with treatment
    codes (for the corrective work indicated by findings).

    Args:
        score: FMS score (0-3)
        criteria_results: List of criterion result dicts from the scoring engine
        test_duration_minutes: Time spent on the assessment

    Returns:
        List of CPTSuggestion objects, assessment codes first, then treatment.
    """
    assessment = suggest_assessment_codes(score, test_duration_minutes)
    treatment = suggest_treatment_codes(criteria_results)

    return assessment + treatment
