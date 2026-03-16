"""
Movement Assessment Pipeline.

Ties together scoring, reporting, and billing into a single workflow:
  CSV → Score → Report → CPT Codes

Usage:
    # Quick mode (no LLM, instant results):
    python -m fms.pipeline path/to/video_labeled.csv

    # Full mode (with LLM-generated clinical report):
    python -m fms.pipeline path/to/video_labeled.csv --full-report

    # With pain flag:
    python -m fms.pipeline path/to/video_labeled.csv --pain
"""
import argparse
import json
import sys
from pathlib import Path

from .scoring.deep_squat import score_deep_squat
from .billing.cpt_codes import suggest_all_codes


def run_quick(csv_path: str, pain: bool = False, include_cpt_codes: bool = False) -> dict:
    """
    Run the quick pipeline: scoring + rule-based billing categories.

    No LLM call required. Instant results.

    Args:
        csv_path: Path to the pose CSV file.
        pain: Whether pain was reported.
        include_cpt_codes: If True, include CPT codes (Pro tier / EHR integration).

    Returns:
        Dictionary with score, criteria, and billing descriptions (+ CPT if requested).
    """
    # Score
    result = score_deep_squat(csv_path, pain_reported=pain)
    result_dict = result.to_dict()

    # CPT suggestions (rule-based) - used for both billing descriptions and CPT output
    cpt_suggestions = suggest_all_codes(
        score=result.score,
        criteria_results=result_dict["criteria"],
    )

    # Billing descriptions (always included — base tier)
    from .billing.cpt_codes import suggest_all_billing_descriptions
    billing_descriptions = suggest_all_billing_descriptions(
        score=result.score,
        criteria_results=result_dict["criteria"],
    )

    output = {
        "mode": "quick",
        "score": result.score,
        "summary": result.summary(),
        "criteria": result_dict["criteria"],
        "angles_at_depth": result_dict["angles_at_depth"],
        "bilateral_differences": result_dict["left_right_differences"],
        "billing_descriptions": [
            {
                "category": b.category,
                "service_type": b.service_type,
                "justification": b.justification,
                "units": b.units,
            }
            for b in billing_descriptions
        ],
    }

    # CPT codes only included when explicitly requested (Pro tier / EHR integration)
    if include_cpt_codes:
        output["cpt_suggestions"] = [
            {
                "code": s.code,
                "description": s.description,
                "justification": s.justification,
                "units": s.units,
            }
            for s in cpt_suggestions
        ]

    return output


def run_full(csv_path: str, pain: bool = False, include_cpt_codes: bool = False) -> dict:
    """
    Run the full pipeline: scoring + LLM report + billing categories.

    Requires ANTHROPIC_API_KEY environment variable.

    Args:
        csv_path: Path to the pose CSV file.
        pain: Whether pain was reported.
        include_cpt_codes: If True, include CPT codes (Pro tier / EHR integration).

    Returns:
        Dictionary with score, clinical report, billing descriptions (+ CPT if requested).
    """
    from .reporting.report_generator import generate_full_report
    from .billing.cpt_codes import suggest_all_billing_descriptions, suggest_all_codes

    # Score
    result = score_deep_squat(csv_path, pain_reported=pain)
    result_dict = result.to_dict()

    # Generate full LLM report (may include CPT codes internally)
    report = generate_full_report(result_dict, include_cpt_codes=include_cpt_codes)

    # Billing descriptions (always included — base tier)
    billing_descriptions = suggest_all_billing_descriptions(
        score=result.score,
        criteria_results=result_dict["criteria"],
    )

    output = {
        "mode": "full",
        "score": result.score,
        "summary": result.summary(),
        "clinical_report": report.clinical_report,
        "billing_descriptions": [
            {
                "category": b.category,
                "service_type": b.service_type,
                "justification": b.justification,
                "units": b.units,
            }
            for b in billing_descriptions
        ],
        "criteria": result_dict["criteria"],
        "angles_at_depth": result_dict["angles_at_depth"],
        "bilateral_differences": result_dict["left_right_differences"],
    }

    # CPT codes only included when explicitly requested (Pro tier / EHR integration)
    if include_cpt_codes:
        # Also get rule-based CPT as a comparison/fallback
        rule_based_cpt = suggest_all_codes(
            score=result.score,
            criteria_results=result_dict["criteria"],
        )
        output["cpt_suggestions_llm"] = [c.to_dict() for c in report.cpt_suggestions]
        output["cpt_suggestions_rules"] = [
            {
                "code": s.code,
                "description": s.description,
                "justification": s.justification,
                "units": s.units,
            }
            for s in rule_based_cpt
        ]

    return output


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Deep Squat Assessment Pipeline"
    )
    parser.add_argument(
        "csv_path",
        help="Path to the exported pose CSV from Dynalytix",
    )
    parser.add_argument(
        "--full-report",
        action="store_true",
        help="Generate LLM-powered clinical report (requires ANTHROPIC_API_KEY)",
    )
    parser.add_argument(
        "--pain",
        action="store_true",
        help="Flag that patient reported pain (auto-scores 0)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted text",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Save output to file",
    )
    parser.add_argument(
        "--cpt",
        action="store_true",
        help="Include CPT codes in output (requires AMA license for production use)",
    )

    args = parser.parse_args()

    # Validate input
    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"Error: File not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    # Run pipeline
    if args.full_report:
        mode_desc = "scoring + LLM report"
        if args.cpt:
            mode_desc += " + CPT codes"
        print(f"Running full pipeline ({mode_desc})...")
        print()
        try:
            output = run_full(str(csv_path), pain=args.pain, include_cpt_codes=args.cpt)
        except ImportError as e:
            print(f"Error: {e}", file=sys.stderr)
            print("Install with: pip install anthropic", file=sys.stderr)
            sys.exit(1)
        except EnvironmentError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        mode_desc = "scoring + rule-based billing categories"
        if args.cpt:
            mode_desc += " + CPT codes"
        print(f"Running quick pipeline ({mode_desc})...")
        print("(Use --full-report for LLM-generated clinical narrative)")
        print()
        output = run_quick(str(csv_path), pain=args.pain, include_cpt_codes=args.cpt)

    # Display results
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        # Formatted output
        print(output["summary"])
        print()

        if "clinical_report" in output:
            print("=" * 70)
            print("CLINICAL REPORT")
            print("=" * 70)
            print(output["clinical_report"])
            print()

        print("-" * 70)
        print("BILLING CATEGORIES")
        print("-" * 70)

        if "cpt_suggestions" in output or "cpt_suggestions_llm" in output:
            cpt_key = "cpt_suggestions_llm" if "cpt_suggestions_llm" in output else "cpt_suggestions"
            for cpt in output[cpt_key]:
                units = f" ({cpt['units']} units)" if cpt.get("units") else ""
                print(f"\n  {cpt['code']}{units} - {cpt['description']}")
                print(f"    {cpt['justification']}")
            print()
            print("⚠ CPT codes are SUGGESTIONS only. The treating physical")
            print("  therapist must review and approve all billing codes.")
        else:
            for b in output["billing_descriptions"]:
                units = f" ({b['units']} units)" if b.get("units") else ""
                print(f"\n  {b['category']}{units} [{b['service_type']}]")
                print(f"    {b['justification']}")
            print()
            print("Findings support the billing categories listed above.")
            print("Consult your practice's billing guidelines for specific codes.")

    # Save to file if requested
    if args.output:
        output_path = Path(args.output)
        with open(output_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
