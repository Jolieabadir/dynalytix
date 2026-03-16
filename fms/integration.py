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
from .disclaimer import CLINICAL_DISCLAIMER, BILLING_DISCLAIMER


# =============================================================================
# AUTO-RUN ON EXPORT
# =============================================================================

def run_fms_on_export(
    labeled_csv_path: str,
    pain_reported: bool = False,
    clinic_id: str = "",
) -> dict:
    """
    Automatically run movement scoring on an exported labeled CSV.

    Called after the exporter creates the labeled CSV.
    Saves findings to a companion CSV and JSON file.

    Args:
        labeled_csv_path: Path to the labeled CSV that was just exported.
        pain_reported: Whether pain was reported during the assessment.
        clinic_id: If provided, auto-maps billing codes using the clinic's cached mappings.

    Returns:
        Dictionary with score, criteria, billing descriptions, output paths, and approval status.
    """
    labeled_path = Path(labeled_csv_path)

    if not labeled_path.exists():
        return {"error": f"Labeled CSV not found: {labeled_csv_path}"}

    # Run the scoring pipeline (with auto-mapping if clinic_id provided)
    result = run_quick(str(labeled_path), pain=pain_reported, clinic_id=clinic_id)

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
        "billing_descriptions": result.get("billing_descriptions", []),
        "clinic_id": clinic_id if clinic_id else None,
        "disclaimer": CLINICAL_DISCLAIMER,
        "billing_disclaimer": BILLING_DISCLAIMER,
    }
    with open(json_output, "w") as f:
        json.dump(report_data, f, indent=2)

    # Create approval record (starts as draft — provider must review)
    assessment_stem = stem  # Use the same stem as the findings files
    try:
        from .ehr.approval import create_approval
        approval = create_approval(assessment_stem)
        result["approval_status"] = approval.status.value
        report_data["approval_status"] = approval.status.value
        # Re-save with approval status
        with open(json_output, "w") as f:
            json.dump(report_data, f, indent=2)
    except Exception as approval_err:
        print(f"  Approval tracking failed (non-blocking): {approval_err}")
        result["approval_status"] = "unknown"

    # Add output paths to result
    result["findings_csv_path"] = str(csv_output)
    result["report_json_path"] = str(json_output)

    print(f"Movement Assessment complete: Score {result['score']}/3")
    print(f"  Findings CSV: {csv_output}")
    print(f"  Report JSON:  {json_output}")
    if clinic_id:
        print(f"  Clinic ID:    {clinic_id} (auto-mapping applied)")
    print(f"  Approval:     {result.get('approval_status', 'unknown')}")

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

        # Add billing categories as additional rows
        for b in result.get("billing_descriptions", []):
            writer.writerow({
                "assessment_date": now,
                "fms_test": "deep_squat",
                "overall_score": result["score"],
                "criterion": f"Billing Category: {b['category']}",
                "passed": "",
                "measured_value": b.get("units", ""),
                "threshold": b.get("practice_code", "unmapped"),
                "detail": f"[{b['service_type']}] {b['justification']}",
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
        "disclaimer": CLINICAL_DISCLAIMER,
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
    async def get_fms_findings(video_id: int, cpt: bool = False):
        """
        Get the full assessment findings for a video (PT-facing).

        By default returns billing categories (descriptive language).
        Pass ?cpt=true to include CPT codes (Pro tier, requires AMA license).
        """
        from .ehr.approval import get_approval

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

        # Strip CPT codes unless explicitly requested (Pro tier)
        if not cpt:
            full_report.pop("cpt_suggestions", None)

        # Ensure disclaimers are present
        full_report["disclaimer"] = CLINICAL_DISCLAIMER
        full_report["billing_disclaimer"] = BILLING_DISCLAIMER

        # Include current approval status
        assessment_id = report_path.stem.replace("_fms_report", "")
        approval = get_approval(assessment_id)
        if approval:
            full_report["approval"] = {
                "status": approval.status.value,
                "reviewed_by": approval.reviewed_by_name or None,
                "reviewed_at": approval.reviewed_at or None,
                "provider_notes": approval.provider_notes or None,
                "pushed_at": approval.pushed_at or None,
            }
        else:
            full_report["approval"] = {"status": "unknown"}

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

    # =========================================================================
    # EHR INTEGRATION STUBS (MedStatix Gateway)
    # =========================================================================

    @app.post("/api/ehr/push/{video_id}")
    async def push_to_ehr(video_id: int, clinic_id: str = "", provider_id: str = "", patient_id: str = ""):
        """Push assessment to EHR via MedStatix. STUB — returns 501."""
        return JSONResponse(
            status_code=501,
            content={
                "status": "not_implemented",
                "message": "EHR integration not yet available. Use /api/fms/findings/{video_id} for assessment data.",
                "video_id": video_id, "clinic_id": clinic_id, "provider_id": provider_id, "patient_id": patient_id,
            }
        )

    @app.post("/api/ehr/map-codes/{video_id}")
    async def preview_code_mapping(video_id: int, clinic_id: str = ""):
        """Preview code mapping for a clinic without pushing. Returns billing descriptions with practice_code=null."""
        findings_dir = Path("data/exports/fms_findings")
        if not findings_dir.exists():
            raise HTTPException(status_code=404, detail="No assessment findings available")
        matches = [m for m in findings_dir.glob("*_fms_report.json") if f"video_{video_id}" in m.stem or str(video_id) in m.stem]
        if not matches:
            raise HTTPException(status_code=404, detail=f"No findings for video {video_id}")
        report_path = sorted(matches)[-1]
        with open(report_path) as f:
            full_report = json.load(f)
        billing = full_report.get("billing_descriptions", [])
        for item in billing:
            item.setdefault("practice_code", None)
            item.setdefault("practice_modifier", None)
            item.setdefault("mapping_status", "unmapped")
        return JSONResponse(content={
            "video_id": video_id, "clinic_id": clinic_id or "not_specified",
            "mapping_status": "unmapped",
            "message": "Code mapping requires MedStatix integration. Billing categories shown without practice codes.",
            "billing_items": billing,
        })

    @app.get("/api/ehr/clinic/{clinic_id}/config")
    async def get_clinic_ehr_config(clinic_id: str):
        """Get EHR config for a clinic. STUB — returns not_configured."""
        return JSONResponse(content={
            "clinic_id": clinic_id, "configured": False, "ehr_system": None, "code_mappings": {},
            "message": "MedStatix integration not yet configured for this clinic.",
        })

    @app.post("/api/ehr/webhook")
    async def ehr_webhook(request_body: dict = {}):
        """
        Webhook receiver for MedStatix events.

        Handles:
        - clinic.code_mapping_updated: Refresh clinic code cache
        - assessment.push_confirmed: Mark assessment as pushed
        - Other events: Log and acknowledge
        """
        from .ehr.approval import mark_pushed, get_approval
        from .ehr.clinic_codes import ClinicCodeMap, CodeEntry, save_clinic_codes

        event_type = request_body.get("event_type", "unknown")
        payload = request_body.get("payload", {})

        print(f"EHR webhook received: {event_type}")

        # Handle clinic code mapping updates
        if event_type == "clinic.code_mapping_updated":
            clinic_id = payload.get("clinic_id", "")
            if clinic_id:
                entries = []
                for e in payload.get("entries", []):
                    entries.append(CodeEntry(
                        billing_category=e.get("billing_category", ""),
                        practice_code=e.get("practice_code", ""),
                        practice_description=e.get("practice_description", ""),
                        modifier=e.get("modifier", ""),
                        unit_rate=e.get("unit_rate", 0.0),
                    ))

                code_map = ClinicCodeMap(
                    clinic_id=clinic_id,
                    clinic_name=payload.get("clinic_name", ""),
                    ehr_system=payload.get("ehr_system", ""),
                    entries=entries,
                    synced_at=datetime.now().isoformat(),
                    source="medstatix_webhook",
                )
                save_clinic_codes(code_map)
                print(f"  → Synced {len(entries)} code mappings for clinic {clinic_id}")

                return JSONResponse(content={
                    "received": True,
                    "event_type": event_type,
                    "processed": True,
                    "clinic_id": clinic_id,
                    "entries_synced": len(entries),
                })

        # Handle assessment push confirmations
        if event_type == "assessment.push_confirmed":
            assessment_id = payload.get("assessment_id", "")
            ehr_record_id = payload.get("ehr_record_id", "")
            gateway_request_id = payload.get("gateway_request_id", "")

            if assessment_id:
                approval = get_approval(assessment_id)
                if approval and approval.status.value == "approved":
                    try:
                        mark_pushed(assessment_id, ehr_record_id, gateway_request_id)
                        print(f"  → Marked assessment {assessment_id} as pushed")
                        return JSONResponse(content={
                            "received": True,
                            "event_type": event_type,
                            "processed": True,
                            "assessment_id": assessment_id,
                        })
                    except ValueError as e:
                        print(f"  → Failed to mark pushed: {e}")

        # Default: acknowledge but don't process
        print(f"  → Event not processed (no handler or missing data)")
        return JSONResponse(content={"received": True, "event_type": event_type, "processed": False})

    @app.get("/api/ehr/status/{gateway_request_id}")
    async def check_push_status(gateway_request_id: str):
        """Check EHR push status. STUB — returns 501."""
        return JSONResponse(status_code=501, content={
            "status": "not_implemented", "gateway_request_id": gateway_request_id,
        })

    # =========================================================================
    # PROVIDER APPROVAL WORKFLOW
    # =========================================================================

    @app.get("/api/fms/findings/{video_id}/approval")
    async def get_approval_status(video_id: int):
        """Get the approval status for an assessment."""
        from .ehr.approval import get_approval

        findings_dir = Path("data/exports/fms_findings")
        if not findings_dir.exists():
            raise HTTPException(status_code=404, detail="No assessment findings available")

        matches = [m for m in findings_dir.glob("*_fms_report.json")
                   if f"video_{video_id}" in m.stem or str(video_id) in m.stem]
        if not matches:
            raise HTTPException(status_code=404, detail=f"No findings for video {video_id}")

        report_path = sorted(matches)[-1]
        assessment_id = report_path.stem.replace("_fms_report", "")

        approval = get_approval(assessment_id)
        if not approval:
            return JSONResponse(content={
                "assessment_id": assessment_id,
                "status": "unknown",
                "message": "No approval record found for this assessment.",
            })

        return JSONResponse(content=approval.to_dict())

    @app.post("/api/fms/findings/{video_id}/approve")
    async def approve_assessment(
        video_id: int,
        provider_id: str = "",
        provider_name: str = "",
        notes: str = "",
        modified_score: bool = False,
        modified_billing: bool = False,
    ):
        """Provider approves the assessment. Ready for EHR push."""
        from .ehr.approval import approve, get_approval

        if not provider_id:
            raise HTTPException(status_code=400, detail="provider_id is required")

        findings_dir = Path("data/exports/fms_findings")
        if not findings_dir.exists():
            raise HTTPException(status_code=404, detail="No assessment findings available")

        matches = [m for m in findings_dir.glob("*_fms_report.json")
                   if f"video_{video_id}" in m.stem or str(video_id) in m.stem]
        if not matches:
            raise HTTPException(status_code=404, detail=f"No findings for video {video_id}")

        report_path = sorted(matches)[-1]
        assessment_id = report_path.stem.replace("_fms_report", "")

        record = approve(
            assessment_id=assessment_id,
            provider_id=provider_id,
            provider_name=provider_name,
            notes=notes,
            modified_score=modified_score,
            modified_billing=modified_billing,
        )

        return JSONResponse(content={
            "assessment_id": assessment_id,
            "status": record.status.value,
            "reviewed_by": record.reviewed_by_name,
            "reviewed_at": record.reviewed_at,
            "message": "Assessment approved. Ready for EHR push.",
        })

    @app.post("/api/fms/findings/{video_id}/reject")
    async def reject_assessment(
        video_id: int,
        provider_id: str = "",
        provider_name: str = "",
        notes: str = "",
    ):
        """Provider rejects the assessment."""
        from .ehr.approval import reject

        if not provider_id:
            raise HTTPException(status_code=400, detail="provider_id is required")

        findings_dir = Path("data/exports/fms_findings")
        if not findings_dir.exists():
            raise HTTPException(status_code=404, detail="No assessment findings available")

        matches = [m for m in findings_dir.glob("*_fms_report.json")
                   if f"video_{video_id}" in m.stem or str(video_id) in m.stem]
        if not matches:
            raise HTTPException(status_code=404, detail=f"No findings for video {video_id}")

        report_path = sorted(matches)[-1]
        assessment_id = report_path.stem.replace("_fms_report", "")

        record = reject(
            assessment_id=assessment_id,
            provider_id=provider_id,
            provider_name=provider_name,
            notes=notes,
        )

        return JSONResponse(content={
            "assessment_id": assessment_id,
            "status": record.status.value,
            "reviewed_by": record.reviewed_by_name,
            "reviewed_at": record.reviewed_at,
            "message": "Assessment rejected. Requires re-assessment or manual override.",
        })

    @app.post("/api/fms/findings/{video_id}/mark-reviewed")
    async def mark_provider_review_endpoint(video_id: int):
        """Mark that a provider has opened/viewed the assessment."""
        from .ehr.approval import mark_provider_review

        findings_dir = Path("data/exports/fms_findings")
        if not findings_dir.exists():
            raise HTTPException(status_code=404, detail="No assessment findings available")

        matches = [m for m in findings_dir.glob("*_fms_report.json")
                   if f"video_{video_id}" in m.stem or str(video_id) in m.stem]
        if not matches:
            raise HTTPException(status_code=404, detail=f"No findings for video {video_id}")

        report_path = sorted(matches)[-1]
        assessment_id = report_path.stem.replace("_fms_report", "")

        record = mark_provider_review(assessment_id)

        return JSONResponse(content={
            "assessment_id": assessment_id,
            "status": record.status.value,
            "message": "Assessment marked as under provider review.",
        })

    # =========================================================================
    # CLINIC CODE SYNC
    # =========================================================================

    @app.post("/api/ehr/clinic/{clinic_id}/sync-codes")
    async def sync_clinic_codes(clinic_id: str, code_mappings: dict = {}):
        """
        Sync billing code mappings for a clinic.

        This would typically be called by MedStatix when a clinic's code
        mappings are updated. For now, accepts a manual mapping payload.

        Expected format:
        {
            "clinic_name": "Example PT Clinic",
            "ehr_system": "webpt",
            "entries": [
                {
                    "billing_category": "Physical Performance Testing",
                    "practice_code": "97750",
                    "practice_description": "Physical performance test",
                    "modifier": "GP",
                    "unit_rate": 45.00
                },
                ...
            ]
        }
        """
        from .ehr.clinic_codes import ClinicCodeMap, CodeEntry, save_clinic_codes

        entries = []
        for e in code_mappings.get("entries", []):
            entries.append(CodeEntry(
                billing_category=e.get("billing_category", ""),
                practice_code=e.get("practice_code", ""),
                practice_description=e.get("practice_description", ""),
                modifier=e.get("modifier", ""),
                unit_rate=e.get("unit_rate", 0.0),
            ))

        code_map = ClinicCodeMap(
            clinic_id=clinic_id,
            clinic_name=code_mappings.get("clinic_name", ""),
            ehr_system=code_mappings.get("ehr_system", ""),
            entries=entries,
            synced_at=datetime.now().isoformat(),
            source="api",
        )

        path = save_clinic_codes(code_map)

        return JSONResponse(content={
            "clinic_id": clinic_id,
            "entries_synced": len(entries),
            "synced_at": code_map.synced_at,
            "cache_path": str(path),
            "message": f"Code mappings synced for clinic {clinic_id}.",
        })

    @app.get("/api/ehr/clinic/{clinic_id}/codes")
    async def get_clinic_codes(clinic_id: str):
        """Get cached billing code mappings for a clinic."""
        from .ehr.clinic_codes import load_clinic_codes

        code_map = load_clinic_codes(clinic_id)
        if not code_map:
            return JSONResponse(status_code=404, content={
                "clinic_id": clinic_id,
                "cached": False,
                "message": "No code mappings cached for this clinic. Sync codes first.",
            })

        return JSONResponse(content={
            "clinic_id": clinic_id,
            "cached": True,
            "clinic_name": code_map.clinic_name,
            "ehr_system": code_map.ehr_system,
            "synced_at": code_map.synced_at,
            "source": code_map.source,
            "entries": [
                {
                    "billing_category": e.billing_category,
                    "practice_code": e.practice_code,
                    "practice_description": e.practice_description,
                    "modifier": e.modifier,
                    "unit_rate": e.unit_rate,
                }
                for e in code_map.entries
            ],
        })

    @app.get("/api/ehr/clinics")
    async def list_clinics():
        """List all clinics with cached code mappings."""
        from .ehr.clinic_codes import list_cached_clinics, load_clinic_codes

        clinic_ids = list_cached_clinics()
        clinics = []
        for cid in clinic_ids:
            code_map = load_clinic_codes(cid)
            if code_map:
                clinics.append({
                    "clinic_id": cid,
                    "clinic_name": code_map.clinic_name,
                    "ehr_system": code_map.ehr_system,
                    "synced_at": code_map.synced_at,
                    "entry_count": len(code_map.entries),
                })

        return JSONResponse(content={
            "clinics": clinics,
            "total": len(clinics),
        })

    @app.delete("/api/ehr/clinic/{clinic_id}/codes")
    async def delete_clinic_codes(clinic_id: str):
        """Delete cached code mappings for a clinic."""
        from .ehr.clinic_codes import delete_clinic_codes as do_delete

        deleted = do_delete(clinic_id)
        if not deleted:
            return JSONResponse(status_code=404, content={
                "clinic_id": clinic_id,
                "deleted": False,
                "message": "No code mappings found for this clinic.",
            })

        return JSONResponse(content={
            "clinic_id": clinic_id,
            "deleted": True,
            "message": f"Code mappings deleted for clinic {clinic_id}.",
        })

    print("✓ Assessment routes: /api/fms/report/{id}, /api/fms/findings/{id}, /api/fms/findings/{id}/csv")
    print("✓ Approval routes: /api/fms/findings/{id}/approval, /api/fms/findings/{id}/approve, /api/fms/findings/{id}/reject")
    print("✓ Clinic codes: /api/ehr/clinic/{id}/sync-codes, /api/ehr/clinic/{id}/codes, /api/ehr/clinics")
    print("✓ EHR stubs: /api/ehr/push/{id}, /api/ehr/map-codes/{id}, /api/ehr/webhook, /api/ehr/status/{id}")
