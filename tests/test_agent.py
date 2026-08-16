"""Exercises AsteriaCareAgent's tool-use loop against fake responses shaped
like real Anthropic SDK objects (attribute access, not dict access) — the
main thing unit tests on the schema/client alone can't catch is a mismatch
between how we read response.content and how the SDK actually returns it.
"""
from asteriacare.agent import TOOLS, AsteriaCareAgent
from asteriacare.config import Settings
from asteriacare.knowledge_base import KnowledgeBase


class _FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class _FakeToolBlock:
    type = "tool_use"

    def __init__(self, name, input, id):
        self.name = name
        self.input = input
        self.id = id


class _FakeResponse:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class _FakeMessages:
    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._script.pop(0)


class _FakeClient:
    def __init__(self, script):
        self.messages = _FakeMessages(script)


def _settings():
    return Settings(
        anthropic_api_key="test",
        anthropic_model="claude-sonnet-4-6",
        salesforce_client_id="",
        salesforce_client_secret="",
        salesforce_token_url="",
        salesforce_api_url="",
    )


def test_agent_resolves_multiple_tool_calls_before_replying():
    kb = KnowledgeBase("data/knowledge_base")
    script = [
        _FakeResponse(
            [_FakeToolBlock("knowledge_base_search", {"query": "pediatrics"}, "id1")],
            "tool_use",
        ),
        _FakeResponse(
            [_FakeToolBlock("record_patient_details", {"patient_name": "Jordan Ellis"}, "id2")],
            "tool_use",
        ),
        _FakeResponse([_FakeTextBlock("Got it, what else can I help with?")], "end_turn"),
    ]
    client = _FakeClient(script)
    agent = AsteriaCareAgent(_settings(), kb, is_new_patient=True, client=client)

    result = agent.send("Hi, I'm Jordan Ellis, need a pediatrics appointment")

    assert result.reply == "Got it, what else can I help with?"
    assert result.patient_details.patient_name == "Jordan Ellis"
    assert len(client.messages.calls) == 3


def test_agent_flags_lead_requested_without_calling_salesforce_itself():
    kb = KnowledgeBase("data/knowledge_base")
    script = [
        _FakeResponse([_FakeToolBlock("create_appointment_lead", {}, "id1")], "tool_use"),
        _FakeResponse([_FakeTextBlock("Submitting now.")], "end_turn"),
    ]
    client = _FakeClient(script)
    agent = AsteriaCareAgent(_settings(), kb, is_new_patient=True, client=client)

    result = agent.send("Yes, that's all correct, please submit it")

    assert result.lead_requested is True
    # The agent itself never talks to Salesforce — that's ConversationSession's job.


def test_existing_patient_agent_does_not_get_lead_creation_tool():
    kb = KnowledgeBase("data/knowledge_base")
    agent = AsteriaCareAgent(_settings(), kb, is_new_patient=False, client=_FakeClient([]))
    tool_names = {t["name"] for t in agent._available_tools()}
    assert "create_appointment_lead" not in tool_names
    assert "record_patient_details" not in tool_names
    assert "knowledge_base_search" in tool_names


def test_new_patient_agent_gets_all_tools():
    assert {t["name"] for t in TOOLS} == {
        "knowledge_base_search",
        "record_patient_details",
        "create_appointment_lead",
    }
