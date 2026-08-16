import pytest

from asteriacare.config import Settings
from asteriacare.salesforce_client import (
    SalesforceAuthError,
    SalesforceClient,
    SalesforceRequestError,
)
from asteriacare.schemas import PatientDetails


class FakeResponse:
    def __init__(self, status_code: int, json_body: dict, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text or str(json_body)

    def json(self):
        return self._json_body


class FakeSession:
    """Minimal stand-in for requests.Session, scripted per test."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._responses.pop(0)


def _settings():
    return Settings(
        anthropic_api_key="test",
        anthropic_model="claude-sonnet-4-6",
        salesforce_client_id="id",
        salesforce_client_secret="secret",
        salesforce_token_url="https://example.com/token",
        salesforce_api_url="https://example.com",
    )


def _details():
    return PatientDetails(
        patient_name="Jordan Ellis",
        patient_phone="+1-555-0100",
        patient_email="jordan@example.com",
        reason_for_visit="Follow-up",
        department="Cardiology",
        doctor="Dr. Aisha Kapoor",
        patient_location="Riverside Campus",
        appointment_datetime="2026-09-01 10:00",
    )


def test_build_lead_payload_splits_name_correctly():
    payload = SalesforceClient.build_lead_payload(_details())
    assert payload["FirstName"] == "Jordan"
    assert payload["LastName"] == "Ellis"
    assert payload["CustomFields__c"]["Department__c"] == "Cardiology"


def test_build_lead_payload_handles_single_word_name():
    details = _details()
    details.patient_name = "Madonna"
    payload = SalesforceClient.build_lead_payload(details)
    assert payload["FirstName"] == "Madonna"
    assert payload["LastName"] == "Madonna"


def test_create_lead_success_path():
    session = FakeSession(
        [
            FakeResponse(200, {"access_token": "tok", "instance_url": "https://inst.example.com"}),
            FakeResponse(201, {"id": "00Q123", "success": True}),
        ]
    )
    client = SalesforceClient(_settings(), session=session)
    result = client.create_lead(_details())
    assert result["id"] == "00Q123"
    assert len(session.calls) == 2


def test_create_lead_retries_once_on_401():
    session = FakeSession(
        [
            FakeResponse(200, {"access_token": "tok1", "instance_url": "https://inst.example.com"}),
            FakeResponse(401, {}, text="expired"),
            FakeResponse(200, {"access_token": "tok2", "instance_url": "https://inst.example.com"}),
            FakeResponse(201, {"id": "00Q456"}),
        ]
    )
    client = SalesforceClient(_settings(), session=session)
    result = client.create_lead(_details())
    assert result["id"] == "00Q456"
    assert len(session.calls) == 4


def test_create_lead_raises_on_persistent_failure():
    session = FakeSession(
        [
            FakeResponse(200, {"access_token": "tok", "instance_url": "https://inst.example.com"}),
            FakeResponse(400, {"error": "bad request"}, text="bad request"),
        ]
    )
    client = SalesforceClient(_settings(), session=session)
    with pytest.raises(SalesforceRequestError):
        client.create_lead(_details())


def test_authenticate_raises_on_bad_credentials():
    session = FakeSession([FakeResponse(401, {}, text="invalid_client")])
    client = SalesforceClient(_settings(), session=session)
    with pytest.raises(SalesforceAuthError):
        client.create_lead(_details())
