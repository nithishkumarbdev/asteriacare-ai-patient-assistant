# AsteriaCare AI Patient Assistant

I built this for a healthcare clinic scenario: a patient lands on the site,
the assistant figures out if they're new or returning, answers whatever
they ask using the clinic's actual knowledge base instead of guessing, and
if they're booking an appointment, it pulls their details out of the
conversation naturally and creates a Salesforce Lead once they confirm
everything's right. No forms. No "click here to book."

```
patient message
      │
      ▼
ConversationSession.route()         ── new / existing patient
      │
      ▼
AsteriaCareAgent (Anthropic tool-use loop)
  ├─ knowledge_base_search   → grounded Q&A, no hallucinated clinic facts
  ├─ record_patient_details  → incremental structured extraction
  └─ create_appointment_lead → fires only after patient confirmation
      │
      ▼
SalesforceClient
  ├─ OAuth client-credentials token (cached, auto re-auth on 401)
  └─ POST /sobjects/Lead        → 201 Created
```

## How I approached it

The extraction schema (`schemas.PatientDetails`) is a plain dataclass.
`missing_fields()` and `is_complete()` are what actually decide whether the
agent keeps asking questions or moves to confirmation, and I could write
tests against that logic directly instead of trusting a prompt to behave.

Confirm-before-write was something I was strict about. The model can call
`create_appointment_lead`, but `ConversationSession._create_lead` re-checks
`is_complete()` itself before anything touches Salesforce. I didn't want a
model mistake to be the only thing standing between a patient and an
incomplete Lead landing in the CRM, so the orchestrator checks again
regardless of what the model thinks it knows.

The Salesforce client is a real HTTP client: it caches the OAuth token,
retries once on a 401, and has a payload builder I tested against the exact
field mapping AsteriaCare uses (see
[`docs/salesforce-integration.md`](docs/salesforce-integration.md)). I
split `patient_name` into first and last name explicitly in the payload
builder rather than assuming the model would hand back separate fields, and
wrote a test around that split so it can't quietly regress.

For the knowledge base, I kept it dependency-light on purpose: it's a
keyword-scored retriever over markdown files, no embedding model or vector
DB required to run the whole thing on one API key. The agent only knows
about `retrieve(query, k)` though, so if I ever want to swap in pgvector or
Pinecone, that's a one-file change.

Everything above is covered by `tests/`, 17 tests, all offline, no real
credentials needed to run them, including one that runs the agent's full
tool-use loop against fake responses shaped exactly like the real Anthropic
SDK returns them (attribute access, multi-turn tool resolution, the whole
thing), so I know the loop itself works before a real key ever touches it.

## Project layout

```
asteriacare-ai-patient-assistant/
├── src/asteriacare/
│   ├── agent.py              # tool-use loop, system prompts, tool schemas
│   ├── conversation.py       # routing + confirm-before-write orchestration
│   ├── salesforce_client.py  # OAuth + Lead creation, real HTTP client
│   ├── knowledge_base.py     # pluggable retriever (keyword impl included)
│   ├── schemas.py            # PatientDetails extraction contract
│   ├── config.py             # env-driven settings, no secrets in code
│   └── cli.py                # `python -m asteriacare.cli` — talk to it locally
├── data/knowledge_base/      # sample clinic content (locations, depts, policies)
├── tests/                    # pytest suite, no network calls
├── docs/
│   ├── architecture.md
│   └── salesforce-integration.md
├── examples/
│   └── lead-payload.json     # sanitized example Salesforce payload
├── requirements.txt
├── pyproject.toml
└── .env.example
```

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY at minimum
python -m asteriacare.cli
```

If you don't set Salesforce credentials, the conversation still runs fine.
Lead creation just fails with a clear error instead of pretending it
worked. That was deliberate on my part: the agent should never tell a
patient "submitted" when it wasn't.

## Testing

```bash
pip install -r requirements.txt
pytest -q
```

13 of the 17 tests cover extraction-schema edge cases, knowledge base
retrieval, and the Salesforce client's behavior (success, a 400, the
401-retry path, auth failure) against a fake HTTP session I scripted
myself, so nothing here needs a live sandbox to verify.

The other 4 exercise the agent's tool-use loop, scripted against fake
objects with the same attribute shape the real Anthropic SDK returns
(`response.content`, `.type`, `.text`, `.name`, `.input`), so the multi-turn
tool resolution logic is actually exercised, not just assumed to work
because the schema tests pass.

CI runs the whole suite on every push, see
[`.github/workflows/tests.yml`](.github/workflows/tests.yml).

**What's still unverified:** I haven't run this against a live Anthropic
key or a real Salesforce org. The tests prove the code is internally
consistent and matches the real SDK's response shape; they can't catch a
prompt that doesn't work well in practice, a real API quirk, or an actual
Salesforce sandbox rejecting a field. That's the honest gap left, and it's
one API key away from closing.

## What I kept out of this repo

No credentials anywhere, `.env` is gitignored and `.env.example` only shows
the shape. No real patient data either, the knowledge base content and the
example Lead payload are both made up.

## What's next

I'm planning to swap the keyword-based knowledge base for a real vector
store, port the same `ConversationSession` to WhatsApp, log the full
conversation as a Salesforce Task attached to the Lead, and add a lead
temperature signal (hot/warm/cold) so the sales team knows who to call
first.
