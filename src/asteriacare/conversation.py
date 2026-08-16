"""Top-level orchestrator: patient-type routing + agent turns + Salesforce
Lead creation on confirmed intake.

The routing decision and the confirm-before-write safeguard are enforced
here rather than left to the model's own judgment.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

from .agent import AsteriaCareAgent
from .config import Settings
from .knowledge_base import KnowledgeBase
from .salesforce_client import SalesforceClient, SalesforceRequestError

PatientType = Literal["new", "existing"]


@dataclass
class ConversationOutcome:
    reply: str
    lead_created: bool = False
    lead_id: Optional[str] = None
    lead_error: Optional[str] = None


class ConversationSession:
    """One end-to-end patient conversation, from routing through Lead creation."""

    def __init__(self, settings: Settings, knowledge_base: KnowledgeBase):
        self._settings = settings
        self._kb = knowledge_base
        self._salesforce = SalesforceClient(settings)
        self._agent: Optional[AsteriaCareAgent] = None
        self._patient_type: Optional[PatientType] = None
        self._lead_created = False

    @property
    def patient_type(self) -> Optional[PatientType]:
        return self._patient_type

    def route(self, patient_type: PatientType) -> str:
        """Equivalent of the 'Patient Type' button step in the original flow."""
        self._patient_type = patient_type
        self._agent = AsteriaCareAgent(
            self._settings, self._kb, is_new_patient=(patient_type == "new")
        )
        if patient_type == "new":
            return (
                "Hi! Welcome to AsteriaCare Hospitals. I can help you with our "
                "locations, departments, doctors, services, insurance, and "
                "appointment requests. What brings you in today?"
            )
        return (
            "Welcome back! What can I help you with — questions about your "
            "care, or something about an existing appointment?"
        )

    def send(self, message: str) -> ConversationOutcome:
        if self._agent is None:
            raise RuntimeError("Call route() before send() to set the patient type.")

        turn = self._agent.send(message)
        outcome = ConversationOutcome(reply=turn.reply)

        if turn.lead_requested and not self._lead_created:
            outcome = self._create_lead(turn)

        return outcome

    def _create_lead(self, turn) -> ConversationOutcome:
        details = turn.patient_details
        if not details.is_complete():
            return ConversationOutcome(
                reply=(
                    turn.reply
                    + "\n\n(Note: intake isn't fully complete yet, so I haven't "
                    "submitted this — let's fill in the rest first.)"
                ),
                lead_error="incomplete_intake",
            )
        try:
            result = self._salesforce.create_lead(details)
            self._lead_created = True
            return ConversationOutcome(
                reply=(
                    "Thanks! Your appointment request has been submitted to "
                    "AsteriaCare Hospitals. Our team will review it and "
                    "contact you to finalize the appointment."
                ),
                lead_created=True,
                lead_id=result.get("id"),
            )
        except SalesforceRequestError as exc:
            return ConversationOutcome(
                reply=(
                    "I wasn't able to submit that just now — let's double-check "
                    "your details and try again in a moment."
                ),
                lead_error=str(exc),
            )
