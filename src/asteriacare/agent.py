"""The conversational agent: an Anthropic tool-use loop grounded in the
clinic knowledge base, with a structured-extraction tool that accumulates
patient details across turns.

Two system prompts and two tool sets are selected based on patient type, so
the questions asked, the grounding rules, and even which tools are offered
to the model differ between a first-time visitor and a returning patient.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import anthropic

from .config import Settings
from .knowledge_base import KnowledgeBase
from .schemas import PatientDetails

NEW_PATIENT_SYSTEM_PROMPT = """\
You are the New Patient Assistant for AsteriaCare Hospitals, a multi-location \
healthcare clinic. You are warm, clear, and efficient.

GROUNDING
- Answer questions about departments, doctors, services, locations, and \
insurance ONLY using the knowledge_base_search tool results. If the \
knowledge base doesn't cover something, say so plainly. Never invent \
clinic-specific facts (hours, doctor names, insurance policies).

YOUR JOB
- Help the visitor get their questions answered.
- Naturally collect, over the course of the conversation, everything needed \
to request an appointment: full name, phone number, email, reason for \
visit, department, preferred/relevant doctor (if any), which hospital \
location, and a requested appointment date/time.
- Do NOT interrogate the visitor with a rigid list of questions. Let the \
conversation flow, and ask for whatever's still missing when it's natural \
to do so.
- After every user turn, call record_patient_details with any new fields \
you learned, even partial ones. Only include fields you actually learned \
this turn.
- Once record_patient_details reports the intake is complete, summarize \
the collected details back to the visitor and ask them to confirm before \
anything is submitted. Do not call create_appointment_lead until the \
visitor has explicitly confirmed the summary is correct.
"""

EXISTING_PATIENT_SYSTEM_PROMPT = """\
You are the Existing Patient Assistant for AsteriaCare Hospitals. You are \
speaking with someone who has already told us they're an existing patient \
— be warm and efficient, don't re-introduce the hospital.

GROUNDING
- Answer questions about departments, doctors, services, locations, \
insurance, and general policies ONLY using the knowledge_base_search tool. \
If something isn't in the knowledge base, say you don't have that \
information rather than guessing.

WHAT YOU CAN HELP WITH
- Explaining, from the knowledge base, how to reschedule, cancel, or follow \
up on an existing appointment. Describe the process — do NOT claim to have \
made a change yourself; you don't have a tool that performs that action.
- Pointing the patient to the right department or contact for \
account-specific requests (billing, medical records, prescriptions).

You do not have access to record_patient_details or create_appointment_lead \
— this branch never creates a new Lead.
"""


TOOLS = [
    {
        "name": "knowledge_base_search",
        "description": (
            "Search the AsteriaCare clinic knowledge base for information "
            "about departments, doctors, services, hospital locations, "
            "insurance, and policies. Always use this before answering any "
            "clinic-specific question rather than answering from memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "record_patient_details",
        "description": (
            "Record any patient/appointment fields learned during this turn "
            "of the conversation. Only pass fields you actually learned — "
            "omit anything not mentioned. Safe to call every turn."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string"},
                "patient_phone": {"type": "string"},
                "patient_email": {"type": "string"},
                "reason_for_visit": {"type": "string"},
                "department": {"type": "string"},
                "doctor": {"type": "string"},
                "patient_location": {"type": "string"},
                "appointment_datetime": {"type": "string"},
            },
        },
    },
    {
        "name": "create_appointment_lead",
        "description": (
            "Submit the confirmed appointment request to Salesforce as a "
            "new Lead. Only call this AFTER the visitor has explicitly "
            "confirmed the summarized details are correct."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


@dataclass
class AgentTurnResult:
    reply: str
    patient_details: PatientDetails
    lead_requested: bool = False


class AsteriaCareAgent:
    """Stateful per-conversation agent wrapping the Anthropic tool-use loop."""

    def __init__(
        self,
        settings: Settings,
        knowledge_base: KnowledgeBase,
        *,
        is_new_patient: bool = True,
        client: Optional[anthropic.Anthropic] = None,
    ):
        self._settings = settings
        self._kb = knowledge_base
        self._client = client or anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._is_new_patient = is_new_patient
        self._history: list[dict] = []
        self._details = PatientDetails()

    @property
    def patient_details(self) -> PatientDetails:
        return self._details

    def _system_prompt(self) -> str:
        return NEW_PATIENT_SYSTEM_PROMPT if self._is_new_patient else EXISTING_PATIENT_SYSTEM_PROMPT

    def _available_tools(self) -> list[dict]:
        if self._is_new_patient:
            return TOOLS
        return [t for t in TOOLS if t["name"] == "knowledge_base_search"]

    def send(self, user_message: str) -> AgentTurnResult:
        self._history.append({"role": "user", "content": user_message})
        lead_requested = False

        # Tool-use loop: keep resolving tool calls until the model produces
        # a plain text turn (or we hit a hard iteration cap as a safety net).
        for _ in range(6):
            response = self._client.messages.create(
                model=self._settings.anthropic_model,
                max_tokens=1024,
                system=self._system_prompt(),
                tools=self._available_tools(),
                messages=self._history,
            )
            self._history.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                text = "".join(
                    block.text for block in response.content if block.type == "text"
                )
                return AgentTurnResult(
                    reply=text,
                    patient_details=self._details,
                    lead_requested=lead_requested,
                )

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if block.name == "knowledge_base_search":
                    chunks = self._kb.retrieve(block.input.get("query", ""))
                    result_text = self._kb.format_for_prompt(chunks)
                elif block.name == "record_patient_details":
                    self._details = self._details.merge(block.input)
                    missing = self._details.missing_fields()
                    result_text = (
                        "Recorded. Still missing: " + ", ".join(missing)
                        if missing
                        else "Recorded. Intake is complete — summarize and ask the visitor to confirm."
                    )
                elif block.name == "create_appointment_lead":
                    lead_requested = True
                    result_text = (
                        "Lead submission requested; the calling application "
                        "will handle the actual Salesforce call."
                    )
                else:
                    result_text = f"Unknown tool: {block.name}"

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    }
                )

            self._history.append({"role": "user", "content": tool_results})

        return AgentTurnResult(
            reply="I'm having trouble completing that — could you rephrase?",
            patient_details=self._details,
            lead_requested=lead_requested,
        )
