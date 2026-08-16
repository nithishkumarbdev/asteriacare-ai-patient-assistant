from pathlib import Path

from asteriacare.knowledge_base import KnowledgeBase

KB_DIR = Path(__file__).resolve().parent.parent / "data" / "knowledge_base"


def test_retrieve_finds_relevant_chunk_for_pediatrics():
    kb = KnowledgeBase(KB_DIR)
    results = kb.retrieve("pediatrics vaccinations for my kid")
    assert results, "expected at least one matching chunk"
    assert any("Pediatrics" in c.heading for c in results)


def test_retrieve_returns_empty_for_empty_query():
    kb = KnowledgeBase(KB_DIR)
    assert kb.retrieve("") == []

    assert kb.retrieve("   ") == []


def test_format_for_prompt_handles_no_results():
    kb = KnowledgeBase(KB_DIR)
    formatted = kb.format_for_prompt([])
    assert "no matching" in formatted.lower()
