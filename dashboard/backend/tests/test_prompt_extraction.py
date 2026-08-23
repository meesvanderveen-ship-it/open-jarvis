from dashboard.backend.services.prompts import get_prompts


def test_extracts_known_prompt_templates():
    result = get_prompts()
    names = {p["name"] for p in result["prompts"]}
    assert "CLAUDE_JUDGE_PROMPT" in names
    assert "GPT_NANO_GATE_PROMPT" in names
    for p in result["prompts"]:
        assert p["length"] > 0
        assert isinstance(p["text"], str)
