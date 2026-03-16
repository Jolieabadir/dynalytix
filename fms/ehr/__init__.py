"""
EHR Integration Module.

Provides abstract interfaces and concrete adapters for pushing
Dynalytix assessment results to Electronic Health Record systems.

Current integrations:
- MedStatix (stub — in development)
"""
from .ehr_adapter import EHRAdapter, EHRPushResult
from .medstatix import MedStatixAdapter

__all__ = ["EHRAdapter", "EHRPushResult", "MedStatixAdapter"]
