"""Interactive terminal runner: `python -m asteriacare.cli`.

Lets you talk to the agent locally against a real Anthropic API key and
(optionally) a real Salesforce sandbox.
"""
from __future__ import annotations

from pathlib import Path

from .config import Settings
from .conversation import ConversationSession
from .knowledge_base import KnowledgeBase

KB_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "knowledge_base"


def main() -> None:
    settings = Settings.from_env()
    if not settings.anthropic_api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill it in."
        )

    kb = KnowledgeBase(KB_DIR)
    session = ConversationSession(settings, kb)

    print("AsteriaCare AI Patient Assistant (local CLI)")
    patient_type = input("Are you a new or existing patient? [new/existing]: ").strip().lower()
    patient_type = "existing" if patient_type.startswith("e") else "new"

    print(session.route(patient_type))  # type: ignore[arg-type]

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nEnding session.")
            break
        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit"}:
            break

        outcome = session.send(user_input)
        print(f"assistant> {outcome.reply}")
        if outcome.lead_created:
            print(f"[Lead created: {outcome.lead_id}]")
        elif outcome.lead_error:
            print(f"[Lead not created: {outcome.lead_error}]")


if __name__ == "__main__":
    main()
