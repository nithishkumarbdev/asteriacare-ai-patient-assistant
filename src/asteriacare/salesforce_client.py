"""Salesforce integration: OAuth client-credentials token exchange + Lead creation.

A real, testable HTTP client. Token caching avoids re-authenticating on
every Lead creation; a 401 triggers exactly one re-auth-and-retry rather than
looping.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import requests

from .config import Settings
from .schemas import PatientDetails


class SalesforceAuthError(RuntimeError):
    pass


class SalesforceRequestError(RuntimeError):
    def __init__(self, status_code: int, body: str):
        super().__init__(f"Salesforce request failed ({status_code}): {body}")
        self.status_code = status_code
        self.body = body


@dataclass
class _CachedToken:
    access_token: str
    instance_url: str
    obtained_at: float
    ttl_seconds: int = 3300  # refresh a bit before Salesforce's own expiry

    @property
    def expired(self) -> bool:
        return (time.time() - self.obtained_at) > self.ttl_seconds


class SalesforceClient:
    def __init__(self, settings: Settings, session: Optional[requests.Session] = None):
        self._settings = settings
        self._session = session or requests.Session()
        self._token: Optional[_CachedToken] = None

    # -- auth -----------------------------------------------------------
    def _authenticate(self) -> _CachedToken:
        resp = self._session.post(
            self._settings.salesforce_token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._settings.salesforce_client_id,
                "client_secret": self._settings.salesforce_client_secret,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            raise SalesforceAuthError(
                f"Salesforce OAuth failed ({resp.status_code}): {resp.text}"
            )
        payload = resp.json()
        token = _CachedToken(
            access_token=payload["access_token"],
            instance_url=payload.get("instance_url", self._settings.salesforce_api_url),
            obtained_at=time.time(),
        )
        self._token = token
        return token

    def _get_token(self) -> _CachedToken:
        if self._token is None or self._token.expired:
            return self._authenticate()
        return self._token

    # -- Lead creation ----------------------------------------------------
    @staticmethod
    def build_lead_payload(details: PatientDetails) -> dict:
        """Map collected patient details onto Salesforce Lead fields.

        Mirrors the field mapping documented in
        docs/salesforce-integration.md, implemented as real, testable code
        with explicit first/last name splitting.
        """
        name_parts = (details.patient_name or "").strip().split(" ", 1)
        first_name = name_parts[0] if name_parts and name_parts[0] else None
        last_name = name_parts[1] if len(name_parts) > 1 else (first_name or "Unknown")

        payload = {
            "FirstName": first_name,
            "LastName": last_name,
            "Company": "AsteriaCare Hospitals",
            "Phone": details.patient_phone,
            "Email": details.patient_email,
            "City": details.patient_location,
            "LeadSource": "AsteriaCare AI",
            "CustomFields__c": {
                "Department__c": details.department,
                "Doctor__c": details.doctor,
                "Hospital__c": details.patient_location,
                "Reason__c": details.reason_for_visit,
                "AppointmentDateTime__c": details.appointment_datetime,
            },
        }
        # Drop empty values rather than sending nulls Salesforce would reject.
        return {k: v for k, v in payload.items() if v not in (None, "")}

    def create_lead(self, details: PatientDetails, *, allow_duplicates: bool = False) -> dict:
        payload = self.build_lead_payload(details)
        payload["allow_duplicates"] = allow_duplicates

        token = self._get_token()
        url = f"{token.instance_url}/services/data/v60.0/sobjects/Lead"
        resp = self._session.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token.access_token}"},
            timeout=10,
        )

        if resp.status_code == 401:
            # Token may have been revoked server-side; re-auth once and retry.
            token = self._authenticate()
            resp = self._session.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token.access_token}"},
                timeout=10,
            )

        if resp.status_code not in (200, 201):
            raise SalesforceRequestError(resp.status_code, resp.text)

        return resp.json()
