"""Structured data contracts for the assistant.

Kept dependency-light (stdlib dataclasses) rather than pulling in a validation
framework for a handful of fields — but every field the agent can extract is
declared here in one place, and `PatientDetails.missing_fields()` is what
drives the "keep asking" vs. "ready to confirm" branch in the conversation
loop, so this file is the single source of truth for what a complete intake
looks like.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Optional


@dataclass
class PatientDetails:
    """Fields the New Patient agent must collect before a Lead can be created.

    `missing_fields()` drives the "keep asking" vs. "ready to confirm"
    branch in the conversation loop.
    """

    patient_name: Optional[str] = None
    patient_phone: Optional[str] = None
    patient_email: Optional[str] = None
    reason_for_visit: Optional[str] = None
    department: Optional[str] = None
    doctor: Optional[str] = None
    patient_location: Optional[str] = None
    appointment_datetime: Optional[str] = None

    REQUIRED = (
        "patient_name",
        "patient_phone",
        "patient_email",
        "reason_for_visit",
        "department",
        "patient_location",
        "appointment_datetime",
    )
    # `doctor` is intentionally optional — not every visit is doctor-specific
    # (e.g. diagnostics, general enquiries).

    def merge(self, updates: dict) -> "PatientDetails":
        """Return a new PatientDetails with non-empty updates applied.

        The agent may extract a subset of fields on any given turn; this
        never lets a later `None`/empty value erase something already
        captured.
        """
        current = {f.name: getattr(self, f.name) for f in fields(self)}
        for key, value in updates.items():
            if key in current and value:
                current[key] = value
        return PatientDetails(**current)

    def missing_fields(self) -> list[str]:
        return [f for f in self.REQUIRED if not getattr(self, f)]

    def is_complete(self) -> bool:
        return not self.missing_fields()

    def as_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}
