# Salesforce Integration

## Authentication

`SalesforceClient._authenticate()` performs an OAuth 2.0 **client-credentials**
token exchange against `SALESFORCE_TOKEN_URL`:

```
POST {SALESFORCE_TOKEN_URL}
  grant_type=client_credentials
  client_id={SALESFORCE_CLIENT_ID}
  client_secret={SALESFORCE_CLIENT_SECRET}
```

The resulting `access_token` and `instance_url` are cached in-process
(`_CachedToken`) with a ~55-minute soft TTL, so most conversation turns don't
re-authenticate. If a request comes back `401` (token revoked or expired
early), the client re-authenticates exactly once and retries — no
unbounded retry loop.

No credentials are ever hardcoded or committed. See
[`../.env.example`](../.env.example) for the four required environment
variables.

## Field mapping

`SalesforceClient.build_lead_payload()` maps a `PatientDetails` instance onto
a Salesforce Lead:

| Salesforce field | Source |
|---|---|
| `FirstName` | First token of `patient_name` |
| `LastName` | Remainder of `patient_name` (or repeats the first token if it's a single word) |
| `Company` *(required)* | Fixed: `"AsteriaCare Hospitals"` |
| `Phone` | `patient_phone` |
| `Email` | `patient_email` |
| `City` | `patient_location` |
| `LeadSource` | Fixed: `"AsteriaCare AI"` |
| `CustomFields__c.Department__c` | `department` |
| `CustomFields__c.Doctor__c` | `doctor` (omitted if not collected — visit doesn't require a specific doctor) |
| `CustomFields__c.Hospital__c` | `patient_location` |
| `CustomFields__c.Reason__c` | `reason_for_visit` |
| `CustomFields__c.AppointmentDateTime__c` | `appointment_datetime` |

Empty/`None` values are dropped before the request is sent rather than
submitted as nulls.

Name splitting happens explicitly in `build_lead_payload()` rather than
assuming the model will hand back separate first/last name fields, and is
covered by
`tests/test_salesforce_client.py::test_build_lead_payload_splits_name_correctly`.

## Request

```
POST {instance_url}/services/data/v60.0/sobjects/Lead
Authorization: Bearer {access_token}
Content-Type: application/json

{ ...mapped fields..., "allow_duplicates": false }
```

A `200`/`201` response is treated as success; anything else raises
`SalesforceRequestError` with the status code and response body attached, so
the orchestrator can surface a clear failure rather than assuming success.

## Duplicate handling

`allow_duplicates` defaults to `False` on every Lead creation call, so a
repeat enquiry from the same patient doesn't silently create a duplicate Lead
without that being an explicit decision.

## Example payload

See [`../examples/lead-payload.json`](../examples/lead-payload.json) for a
sanitized example of the JSON body sent to Salesforce for a single completed
intake.
