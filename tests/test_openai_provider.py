from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from repoguide import llm, provider


@pytest.fixture
def openai(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "openai")
    monkeypatch.setattr(llm.settings, "openai_model", "gpt-6-luna")
    monkeypatch.setattr(llm.settings, "openai_service_tier", "default")
    monkeypatch.setattr(llm.settings, "openai_max_input_chars", 32000)
    client = MagicMock()
    monkeypatch.setattr(llm, "get_openai_client", lambda: client)
    return client


def test_openai_completion_uses_standard_tier_bounded_output_and_no_storage(openai):
    openai.responses.create.return_value = SimpleNamespace(
        status="completed", output_text="Cited answer [S1]", usage=None
    )
    assert llm.generate_answer("Evidence [S1]") == "Cited answer [S1]"
    request = openai.responses.create.call_args.kwargs
    assert request["model"] == "gpt-6-luna"
    assert request["service_tier"] == "default"
    assert request["max_output_tokens"] <= 3500
    assert request["store"] is False
    assert provider.identity().provider == "openai"


def test_oversize_input_fails_before_any_provider_request(openai):
    with pytest.raises(ValueError, match="short-context"):
        llm.generate_answer("x" * 32000)
    openai.responses.create.assert_not_called()


@pytest.mark.parametrize("status,text", [("incomplete", "partial"), ("completed", "")])
def test_incomplete_answers_are_rejected(openai, status, text):
    openai.responses.create.return_value = SimpleNamespace(
        status=status, output_text=text, usage=None
    )
    with pytest.raises(ValueError, match="complete answer"):
        llm.generate_answer("evidence")


def test_stream_does_not_spend_on_a_second_request_after_failure(openai):
    openai.responses.create.return_value = iter(
        [SimpleNamespace(type="response.failed")]
    )
    with pytest.raises(ValueError, match="did not complete"):
        list(provider.stream("evidence"))
    assert openai.responses.create.call_count == 1


def test_router_uses_small_json_response_on_standard_tier(openai):
    openai.responses.create.return_value = SimpleNamespace(
        status="completed", output_text='{"intent":"code"}', usage=None
    )
    assert llm.generate_router_json("Classify this as JSON") == {"intent": "code"}
    request = openai.responses.create.call_args.kwargs
    assert request["max_output_tokens"] == 600
    assert request["service_tier"] == "default"
    assert request["reasoning"] == {"effort": "none"}


def test_completion_and_router_use_final_phase_without_concatenating_commentary(openai):
    def message(phase, text):
        return SimpleNamespace(
            type="message",
            phase=phase,
            content=[SimpleNamespace(type="output_text", text=text)],
        )

    response = SimpleNamespace(
        status="completed",
        output_text='preamble\n{"intent":"code"}',
        output=[
            message("commentary", "preamble"),
            message("final_answer", '{"intent":"code"}'),
        ],
        usage=None,
    )
    openai.responses.create.return_value = response
    assert llm.generate_answer("evidence") == '{"intent":"code"}'
    assert llm.generate_router_json("Classify as JSON") == {"intent": "code"}
    response.output = [message("commentary", "An incomplete preamble")]
    with pytest.raises(ValueError, match="complete answer"):
        llm.generate_answer("evidence")


def test_stream_ignores_commentary_even_when_phase_arrives_at_item_done(openai):
    events = []
    for index, phase, text in [
        (0, "commentary", "Checking the code"),
        (1, "final_answer", "Final cited answer [S1]"),
    ]:
        events.extend(
            [
                SimpleNamespace(
                    type="response.output_item.added",
                    output_index=index,
                    item=SimpleNamespace(type="message", phase=None),
                ),
                SimpleNamespace(
                    type="response.output_text.delta", output_index=index, delta=text
                ),
                SimpleNamespace(
                    type="response.output_item.done",
                    output_index=index,
                    item=SimpleNamespace(type="message", phase=phase),
                ),
            ]
        )
    openai.responses.create.return_value = iter(events)
    assert "".join(provider.stream("Evidence")) == "Final cited answer [S1]"
