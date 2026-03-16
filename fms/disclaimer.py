"""
Clinical disclaimer text for all Dynalytix reports.

This disclaimer MUST appear on every generated report — patient-facing and provider-facing.
"""

CLINICAL_DISCLAIMER = (
    "Generated with AI assistance. Movement data extracted via computer vision "
    "is subject to limitations including camera angle, lighting, and clothing. "
    "Clinical findings should be verified by the treating provider before "
    "inclusion in patient records. This tool is a clinical aid and does not "
    "replace professional clinical judgment."
)

BILLING_DISCLAIMER = (
    "Billing categories are suggestions based on assessment findings. "
    "The treating provider is responsible for selecting appropriate billing codes "
    "based on their clinical judgment and the services actually rendered. "
    "This tool does not provide billing advice."
)
