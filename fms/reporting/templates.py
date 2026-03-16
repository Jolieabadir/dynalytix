"""
Prompt templates for LLM-powered movement assessment report generation.

These templates structure the data from the rule engine into prompts
that produce clinical-quality reports suitable for PT documentation.
"""

SYSTEM_PROMPT = """You are a clinical documentation assistant for physical therapists.
You generate professional movement assessment reports based on functional movement assessment data.

Your reports should be:
- Written in clinical language appropriate for medical records
- Concise but thorough
- Objective and data-driven
- Include specific angle measurements where relevant
- Note any bilateral asymmetries
- Suggest areas for corrective focus based on findings
- Suitable for inclusion in patient charts and insurance documentation

You are NOT diagnosing conditions. You are documenting movement assessment findings.
The physical therapist will review and sign off on all reports.

IMPORTANT: Every report you generate must end with the following disclaimer on its own line:
"Generated with AI assistance. Movement data extracted via computer vision is subject to limitations including camera angle, lighting, and clothing. Clinical findings should be verified by the treating provider before inclusion in patient records. This tool is a clinical aid and does not replace professional clinical judgment.\""""


DEEP_SQUAT_REPORT_TEMPLATE = """Generate a clinical movement assessment report for the following Deep Squat evaluation.

## Patient Assessment Data

**Deep Squat Assessment Score: {score}/3**
**Pain Reported: {pain_reported}**
**Assessment Frame: {max_depth_frame}**

## Scoring Criteria Results

{criteria_text}

## Joint Angles at Maximum Squat Depth

{angles_text}

## Bilateral Differences

{bilateral_text}

---

Generate a professional clinical report with these sections:

1. **Assessment Summary** (2-3 sentences: what was performed, overall score, key finding)

2. **Movement Analysis** (detailed findings for each criterion - what passed, what failed, specific angle values, what compensations were observed)

3. **Bilateral Symmetry** (note any asymmetries >10° and their clinical significance)

4. **Clinical Implications** (what the findings suggest about mobility limitations, stability deficits, or injury risk)

5. **Corrective Recommendations** (specific exercise categories or mobility work targeting the identified deficits. Be specific: e.g. "ankle dorsiflexion mobilization" not just "work on mobility")

Keep the report under 400 words. Use clinical terminology but remain accessible."""


DEEP_SQUAT_BILLING_TEMPLATE = """Based on this Deep Squat movement assessment, suggest appropriate billing categories and service types.

**Score: {score}/3**
**Key Findings:**
{findings_text}

**Corrective Areas Identified:**
{corrective_areas}

Respond with ONLY a JSON array of objects, each with:
- "category": the billing category (e.g. "Physical Performance Testing", "Therapeutic Exercise", "Neuromuscular Re-education", "Manual Therapy", "Therapeutic Activities")
- "service_type": either "assessment" or "treatment"
- "justification": why this category applies to the findings
- "units": suggested units (for timed services, each unit is 15 minutes)

Do NOT include CPT codes. Include:
1. The assessment category (Physical Performance Testing if applicable)
2. Any treatment categories appropriate for the corrective work indicated by the findings

Respond with raw JSON only, no markdown backticks or preamble."""


# Pro tier only — requires AMA CPT license
DEEP_SQUAT_CPT_TEMPLATE_PRO = """Based on this Deep Squat movement assessment, suggest appropriate CPT billing codes.

**Score: {score}/3**
**Key Findings:**
{findings_text}

**Corrective Areas Identified:**
{corrective_areas}

Respond with ONLY a JSON array of objects, each with:
- "code": the CPT code string
- "description": brief description
- "justification": why this code applies to the findings
- "units": suggested units (for timed codes)

Include:
1. The assessment code (97750 if applicable)
2. Any treatment codes that would be appropriate for the corrective work indicated by the findings

Respond with raw JSON only, no markdown backticks or preamble."""


def format_criteria_for_prompt(criteria: list[dict]) -> str:
    """Format criteria results into readable text for the prompt."""
    lines = []
    for c in criteria:
        status = "PASS" if c["passed"] else "FAIL"
        line = f"- **{c['name']}**: {status}"
        if c.get("value") is not None and c.get("threshold") is not None:
            line += f" (measured: {c['value']:.1f}°, threshold: {c['threshold']:.1f}°)"
        if c.get("detail"):
            line += f"\n  Detail: {c['detail']}"
        lines.append(line)
    return "\n".join(lines)


def format_angles_for_prompt(angles: dict[str, float]) -> str:
    """Format angle measurements into readable text."""
    lines = []
    for key, value in sorted(angles.items()):
        clean_name = key.replace("angle_", "").replace("_", " ").title()
        lines.append(f"- {clean_name}: {value:.1f}°")
    return "\n".join(lines) if lines else "No angle data available"


def format_bilateral_for_prompt(diffs: dict[str, float]) -> str:
    """Format bilateral differences into readable text."""
    lines = []
    for name, diff in diffs.items():
        flag = " ⚠ ASYMMETRY" if abs(diff) > 10 else ""
        lines.append(f"- {name}: Left-Right difference = {diff:+.1f}°{flag}")
    return "\n".join(lines) if lines else "No bilateral data available"


def build_report_prompt(result_dict: dict) -> tuple[str, str]:
    """
    Build the full prompt for report generation.

    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    criteria_text = format_criteria_for_prompt(result_dict["criteria"])
    angles_text = format_angles_for_prompt(result_dict["angles_at_depth"])
    bilateral_text = format_bilateral_for_prompt(result_dict["left_right_differences"])

    user_prompt = DEEP_SQUAT_REPORT_TEMPLATE.format(
        score=result_dict["score"],
        pain_reported=result_dict["pain_reported"],
        max_depth_frame=result_dict["max_depth_frame"],
        criteria_text=criteria_text,
        angles_text=angles_text,
        bilateral_text=bilateral_text,
    )

    return SYSTEM_PROMPT, user_prompt


def build_cpt_prompt(result_dict: dict) -> tuple[str, str]:
    """
    Build the prompt for CPT code suggestion.

    Returns:
        Tuple of (system_prompt, user_prompt)
    """
    # Extract key findings
    findings = []
    corrective_areas = []

    for c in result_dict["criteria"]:
        if not c["passed"]:
            findings.append(f"- {c['name']}: {c['detail']}")
            # Map failures to corrective areas
            name = c["name"].lower()
            if "heel" in name or "ankle" in name:
                corrective_areas.append("Ankle dorsiflexion mobility")
            if "torso" in name or "alignment" in name:
                corrective_areas.append("Thoracic spine mobility and core stability")
            if "knee" in name:
                corrective_areas.append("Hip and knee neuromuscular control")
            if "lumbar" in name:
                corrective_areas.append("Lumbopelvic stability and motor control")
            if "depth" in name:
                corrective_areas.append("Hip flexion mobility and lower extremity strength")

    if not findings:
        findings.append("- All criteria passed (score 3)")

    if not corrective_areas:
        corrective_areas.append("Maintenance and injury prevention programming")

    findings_text = "\n".join(findings)
    corrective_text = "\n".join(f"- {area}" for area in set(corrective_areas))

    user_prompt = DEEP_SQUAT_CPT_TEMPLATE_PRO.format(
        score=result_dict["score"],
        findings_text=findings_text,
        corrective_areas=corrective_text,
    )

    return SYSTEM_PROMPT, user_prompt


def build_billing_prompt(result_dict: dict) -> tuple[str, str]:
    """Build the prompt for billing category suggestions (no CPT codes)."""
    # Same logic as build_cpt_prompt but uses DEEP_SQUAT_BILLING_TEMPLATE
    findings = []
    corrective_areas = []
    for c in result_dict["criteria"]:
        if not c["passed"]:
            findings.append(f"- {c['name']}: {c['detail']}")
            name = c["name"].lower()
            if "heel" in name or "ankle" in name:
                corrective_areas.append("Ankle dorsiflexion mobility")
            if "torso" in name or "alignment" in name:
                corrective_areas.append("Thoracic spine mobility and core stability")
            if "knee" in name:
                corrective_areas.append("Hip and knee neuromuscular control")
            if "lumbar" in name:
                corrective_areas.append("Lumbopelvic stability and motor control")
            if "depth" in name:
                corrective_areas.append("Hip flexion mobility and lower extremity strength")
    if not findings:
        findings.append("- All criteria passed (score 3)")
    if not corrective_areas:
        corrective_areas.append("Maintenance and injury prevention programming")

    findings_text = "\n".join(findings)
    corrective_text = "\n".join(f"- {area}" for area in set(corrective_areas))

    user_prompt = DEEP_SQUAT_BILLING_TEMPLATE.format(
        score=result_dict["score"],
        findings_text=findings_text,
        corrective_areas=corrective_text,
    )
    return SYSTEM_PROMPT, user_prompt
