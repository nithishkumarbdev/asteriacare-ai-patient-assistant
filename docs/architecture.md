# Architecture

## Request flow

```
CLI / caller
      │
      ▼
ConversationSession
  ├─ route(patient_type)          ── picks system prompt + available tools
  └─ send(message)
        │
        ▼
   AsteriaCareAgent.send()
        │  Anthropic tool-use loop (max 6 iterations per turn)
        │
        ├─ tool: knowledge_base_search ──▶ KnowledgeBase.retrieve()
        ├─ tool: record_patient_details ──▶ PatientDetails.merge()
        └─ tool: create_appointment_lead ──▶ flagged on AgentTurnResult
        │
        ▼
   back in ConversationSession
        │  if lead_requested AND details.is_complete():
        ▼
   SalesforceClient.create_lead()
        │
   success ──▶ ConversationOutcome(lead_created=True, lead_id=...)
   failure ──▶ ConversationOutcome(lead_error=...)
```

## Components

### `agent.py` — the conversational core

A single class, `AsteriaCareAgent`, wrapping an Anthropic `messages.create`
tool-use loop. Two system prompts (new patient / existing patient) and two
tool sets are selected based on `is_new_patient`, so the existing-patient
branch literally cannot call `create_appointment_lead` — it isn't offered to
the model as a tool, rather than being blocked by a prompt instruction alone.

Each `send()` call runs up to 6 tool-resolution iterations before returning,
which bounds a pathological loop (e.g. the model repeatedly calling
`knowledge_base_search`) without needing a timeout.

### `schemas.py` — the extraction contract

`PatientDetails` is a plain dataclass with a `REQUIRED` tuple and two methods
that do the actual work: `merge()` (apply partial updates without ever
overwriting an already-captured field with an empty one) and
`missing_fields()` / `is_complete()` (drive the "keep asking" vs.
"summarize and confirm" behavior). Because this logic lives in code rather
than a platform's extraction config, it's directly unit tested
(`tests/test_schemas.py`).

### `knowledge_base.py` — grounding

`KnowledgeBase.retrieve(query, k)` is the only interface the agent depends
on. The shipped implementation splits markdown files on `## ` headings and
scores chunks by token overlap — no embedding model or external service
required to run the project end-to-end. Swapping in a real vector store
means implementing the same `retrieve()` signature against pgvector,
Pinecone, or whatever else, and changing one import in `agent.py`.

### `salesforce_client.py` — the CRM write

A real client, not a config block:

- `_authenticate()` performs the OAuth **client-credentials** exchange and
  caches the token (`_CachedToken`) with a conservative TTL so most turns
  don't re-authenticate.
- `create_lead()` retries exactly once on a `401` (token revoked
  server-side) before giving up — no infinite retry loop.
- `build_lead_payload()` is a static method, independently testable, that
  maps `PatientDetails` onto Salesforce Lead fields — see
  [`salesforce-integration.md`](salesforce-integration.md) for the mapping
  itself.

### `conversation.py` — the safety boundary

`ConversationSession._create_lead()` re-checks `details.is_complete()`
**before** calling Salesforce, regardless of what the model believed when it
called the `create_appointment_lead` tool. This means a model turn that
prematurely decides intake is done can't actually create an incomplete Lead
— the orchestrator, not the prompt, is the enforcement point.

## Design choices worth calling out

- **Tool availability, not just instructions, enforces scope.** The
  existing-patient agent is structurally unable to create a Lead because the
  tool isn't in its tool list — a stronger guarantee than "the prompt tells
  it not to."
- **Confirm-before-write is enforced twice**: once by the agent's system
  prompt (asks the model not to call the tool before confirmation), and
  again by the orchestrator (re-validates completeness before the actual
  Salesforce call). Belt and suspenders, because prompt instructions alone
  are not a reliable safety boundary.
- **Bounded tool loop.** A hard iteration cap on `agent.send()` avoids a
  hung conversation if the model gets stuck calling tools without ever
  producing a text reply.
- **No hidden network calls in tests.** The Salesforce test suite scripts a
  fake `requests.Session`-compatible object rather than hitting a sandbox,
  so `pytest` runs offline and deterministically.
