"""
Movement Assessment Integration - Connects the scoring pipeline to the data collection backend.

This module:
1. Auto-runs the movement scoring pipeline when a labeled CSV is exported
2. Saves findings to a structured CSV alongside the labeled export
3. Provides API endpoints for retrieving assessment results and user-facing reports

Integration:
    In your api.py, add these lines:

    from fms.integration import register_fms_routes, run_fms_on_export

    # After app is created:
    register_fms_routes(app)

    # In the export endpoint, after exporter.export_video():
    fms_result = run_fms_on_export(export_path)
"""
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .pipeline import run_quick


# =============================================================================
# AUTO-RUN ON EXPORT
# =============================================================================

def run_fms_on_export(
    labeled_csv_path: str,
    pain_reported: bool = False,
) -> dict:
    """
    Automatically run movement scoring on an exported labeled CSV.

    Called after the exporter creates the labeled CSV.
    Saves findings to a companion CSV and JSON file.

    Args:
        labeled_csv_path: Path to the labeled CSV that was just exported.
        pain_reported: Whether pain was reported during the assessment.

    Returns:
        Dictionary with score, criteria, CPT suggestions, and output paths.
    """
    labeled_path = Path(labeled_csv_path)

    if not labeled_path.exists():
        return {"error": f"Labeled CSV not found: {labeled_csv_path}"}

    # Run the scoring pipeline
    result = run_quick(str(labeled_path), pain=pain_reported)

    # Determine output paths
    stem = labeled_path.stem  # e.g. "video_abc123_IMG_8524_labeled"
    findings_dir = labeled_path.parent / "fms_findings"
    findings_dir.mkdir(exist_ok=True)

    csv_output = findings_dir / f"{stem}_fms_findings.csv"
    json_output = findings_dir / f"{stem}_fms_report.json"

    # Save findings CSV
    _save_findings_csv(result, csv_output)

    # Save full JSON report
    report_data = {
        "assessment_date": datetime.now().isoformat(),
        "source_csv": str(labeled_path),
        "score": result["score"],
        "criteria": result["criteria"],
        "angles_at_depth": result.get("angles_at_depth", {}),
        "bilateral_differences": result.get("bilateral_differences", {}),
        "cpt_suggestions": result.get("cpt_suggestions", []),
    }
    with open(json_output, "w") as f:
        json.dump(report_data, f, indent=2)

    # Add output paths to result
    result["findings_csv_path"] = str(csv_output)
    result["report_json_path"] = str(json_output)

    print(f"Movement Assessment complete: Score {result['score']}/3")
    print(f"  Findings CSV: {csv_output}")
    print(f"  Report JSON:  {json_output}")

    return result


def _save_findings_csv(result: dict, output_path: Path):
    """
    Save assessment findings as a structured CSV.

    One row per criterion, easy to read in a spreadsheet.
    """
    fieldnames = [
        "assessment_date",
        "fms_test",
        "overall_score",
        "criterion",
        "passed",
        "measured_value",
        "threshold",
        "detail",
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        now = datetime.now().isoformat()

        for criterion in result.get("criteria", []):
            writer.writerow({
                "assessment_date": now,
                "fms_test": "deep_squat",
                "overall_score": result["score"],
                "criterion": criterion["name"],
                "passed": criterion["passed"],
                "measured_value": criterion.get("value", ""),
                "threshold": criterion.get("threshold", ""),
                "detail": criterion.get("detail", ""),
            })

        # Add bilateral differences as additional rows
        for joint, diff in result.get("bilateral_differences", {}).items():
            writer.writerow({
                "assessment_date": now,
                "fms_test": "deep_squat",
                "overall_score": result["score"],
                "criterion": f"Bilateral Difference: {joint}",
                "passed": abs(diff) <= 10,
                "measured_value": f"{diff:+.1f}",
                "threshold": "±10.0",
                "detail": "Asymmetry detected" if abs(diff) > 10 else "Within normal range",
            })

        # Add CPT suggestions as additional rows
        for cpt in result.get("cpt_suggestions", []):
            writer.writerow({
                "assessment_date": now,
                "fms_test": "deep_squat",
                "overall_score": result["score"],
                "criterion": f"CPT Suggestion: {cpt['code']}",
                "passed": "",
                "measured_value": cpt.get("units", ""),
                "threshold": "",
                "detail": f"{cpt['description']} — {cpt['justification']}",
            })


# =============================================================================
# USER-FACING REPORT (no billing codes)
# =============================================================================

def generate_user_report(result: dict) -> dict:
    """
    Generate a user-facing assessment report (NO billing codes).

    This is what gets shown on the website to the patient/athlete.
    Billing codes are stripped — those are PT-only.

    Args:
        result: Output from run_quick() or run_fms_on_export()

    Returns:
        Dictionary with user-safe report data.
    """
    # Build criteria summary for the user
    criteria_summary = []
    for c in result.get("criteria", []):
        criteria_summary.append({
            "name": c["name"],
            "status": "Pass" if c["passed"] else "Needs Improvement",
            "detail": c.get("detail", ""),
        })

    # Build asymmetry notes
    asymmetries = []
    for joint, diff in result.get("bilateral_differences", {}).items():
        if abs(diff) > 10:
            side = "left" if diff > 0 else "right"
            asymmetries.append({
                "joint": joint,
                "difference_degrees": round(abs(diff), 1),
                "note": f"{joint} shows {abs(diff):.1f}° difference — "
                        f"{side} side is more restricted",
            })

    # Score interpretation
    score = result.get("score", 0)
    if score == 3:
        interpretation = (
            "Excellent movement quality. You demonstrated full squat depth "
            "with good trunk alignment and no compensations."
        )
    elif score == 2:
        interpretation = (
            "Good movement quality with minor limitations. You achieved "
            "adequate depth but required heel elevation, suggesting some "
            "ankle mobility restriction."
        )
    elif score == 1:
        interpretation = (
            "Movement limitations detected. Some criteria were not met, "
            "indicating areas where mobility or stability could be improved."
        )
    else:
        interpretation = (
            "Pain was reported during this movement. Please consult with "
            "a healthcare professional for evaluation."
        )

    # Corrective focus areas (derived from failed criteria, no CPT codes)
    focus_areas = []
    for c in result.get("criteria", []):
        if not c["passed"]:
            name = c["name"].lower()
            if "depth" in name:
                focus_areas.append("Hip and ankle mobility exercises")
            if "torso" in name or "trunk" in name:
                focus_areas.append("Core stability and thoracic spine mobility")
            if "knee" in name:
                focus_areas.append("Hip strengthening and knee alignment drills")
            if "heel" in name or "ankle" in name:
                focus_areas.append("Ankle dorsiflexion and calf flexibility")
            if "lumbar" in name:
                focus_areas.append("Lumbopelvic control and anti-flexion exercises")

    return {
        "test": "Deep Squat",
        "score": score,
        "max_score": 3,
        "interpretation": interpretation,
        "criteria": criteria_summary,
        "asymmetries": asymmetries,
        "focus_areas": list(set(focus_areas)),  # deduplicate
    }


# =============================================================================
# FASTAPI ROUTE REGISTRATION
# =============================================================================

def register_fms_routes(app):
    """
    Register assessment-related API routes on the FastAPI app.

    Call this in your api.py after creating the app:
        from fms.integration import register_fms_routes
        register_fms_routes(app)
    """
    from fastapi import HTTPException
    from fastapi.responses import FileResponse, JSONResponse

    @app.get("/api/fms/report/{video_id}")
    async def get_fms_report(video_id: int):
        """
        Get the user-facing assessment report for a video.

        Returns the assessment results WITHOUT billing codes.
        Suitable for displaying to patients/athletes on the website.
        """
        # Find the findings JSON
        findings_dir = Path("data/exports/fms_findings")

        if not findings_dir.exists():
            raise HTTPException(status_code=404, detail="No assessment findings available")

        # Search for a report matching this video ID
        # Filenames include video_id in the path
        matches = list(findings_dir.glob(f"*video_{video_id}*_fms_report.json"))

        # Also try matching by any report with this video_id pattern
        if not matches:
            matches = list(findings_dir.glob(f"*_fms_report.json"))
            # Filter to those that might match (broad search)
            matches = [m for m in matches if f"video_{video_id}" in m.stem
                        or str(video_id) in m.stem]

        if not matches:
            raise HTTPException(
                status_code=404,
                detail=f"No assessment report found for video {video_id}. "
                       "Export the video first to generate a report."
            )

        # Load the most recent report
        report_path = sorted(matches)[-1]
        with open(report_path) as f:
            full_report = json.load(f)

        # Generate user-facing version (no billing codes)
        user_report = generate_user_report(full_report)

        return JSONResponse(content=user_report)

    @app.get("/api/fms/findings/{video_id}")
    async def get_fms_findings(video_id: int):
        """
        Get the full assessment findings for a video (PT-facing, includes CPT codes).

        This is the complete assessment data for clinical use.
        """
        findings_dir = Path("data/exports/fms_findings")

        if not findings_dir.exists():
            raise HTTPException(status_code=404, detail="No assessment findings available")

        matches = list(findings_dir.glob(f"*_fms_report.json"))
        matches = [m for m in matches if f"video_{video_id}" in m.stem
                    or str(video_id) in m.stem]

        if not matches:
            raise HTTPException(
                status_code=404,
                detail=f"No assessment findings found for video {video_id}"
            )

        report_path = sorted(matches)[-1]
        with open(report_path) as f:
            full_report = json.load(f)

        return JSONResponse(content=full_report)

    @app.get("/api/fms/findings/{video_id}/csv")
    async def download_fms_csv(video_id: int):
        """Download the assessment findings CSV for a video."""
        findings_dir = Path("data/exports/fms_findings")

        if not findings_dir.exists():
            raise HTTPException(status_code=404, detail="No assessment findings available")

        matches = list(findings_dir.glob(f"*_fms_findings.csv"))
        matches = [m for m in matches if f"video_{video_id}" in m.stem
                    or str(video_id) in m.stem]

        if not matches:
            raise HTTPException(
                status_code=404,
                detail=f"No assessment CSV found for video {video_id}"
            )

        csv_path = sorted(matches)[-1]
        return FileResponse(
            csv_path,
            media_type="text/csv",
            filename=csv_path.name,
        )

    print("✓ Assessment routes registered: /api/fms/report/{id}, /api/fms/findings/{id}, /api/fms/findings/{id}/csv")
