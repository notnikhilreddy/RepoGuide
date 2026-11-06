"""Offline report-protocol tests. These use no live provider or database."""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from repoguide.answers import AnswerResult


def setup_evaluator(monkeypatch, tmp_path, *, generate=True):
    monkeypatch.setenv("REPOGUIDE_EVALUATION", "true")
    monkeypatch.setenv("MLFLOW_ENABLED", "false")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://fixture@host.docker.internal:55432/fixture",
    )
    monkeypatch.setenv("EVALUATED_IMAGE_ID", "sha256:" + "b" * 64)
    module = importlib.import_module("evals.release_eval")
    root = Path(__file__).resolve().parents[1]
    original_path = Path

    def paths(value):
        if str(value) == "/evals":
            return root / "evals"
        if str(value) == "/opt/repoguide/release-config.json":
            return root / "deployment/release-config.json"
        return original_path(value)

    monkeypatch.setattr(module, "Path", paths)
    corpus = json.loads((root / "evals/release_cases.json").read_text())
    all_paths = {p for c in corpus["cases"] for p in c["expected_paths"]}

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def scalar(self, _):
            return SimpleNamespace(id="fixture")

        def scalars(self, _):
            return list(all_paths)

        def get(self, *_):
            return SimpleNamespace(content="fixture source evidence\n")

    monkeypatch.setattr(module, "SessionLocal", Session)
    monkeypatch.setattr(
        module,
        "get_embedding_service",
        lambda: SimpleNamespace(encode_query=lambda _: [0.0] * 384),
    )
    monkeypatch.setattr(
        module, "get_reranker", lambda: SimpleNamespace(predict=lambda _: [1])
    )
    monkeypatch.setattr(
        module,
        "search",
        lambda **_: [
            SimpleNamespace(chunk=SimpleNamespace(file_path=next(iter(all_paths))))
        ],
    )
    scores = {k: 4 for k in module.JUDGE_KEYS} | {
        "unsupported_claims": False,
        "injection_resistant": True,
        "rationale": "Offline test fixture",
    }

    class Responses:
        def create(self, **_):
            return SimpleNamespace(
                status="completed",
                output_text=json.dumps(scores),
                usage=SimpleNamespace(input_tokens=2, output_tokens=1, total_tokens=3),
            )

    monkeypatch.setattr(
        module, "OpenAI", lambda **_: SimpleNamespace(responses=Responses())
    )
    monkeypatch.setattr(module.settings, "openai_api_key", "offline-test-key")
    monkeypatch.setattr(module.settings, "context7_api_key", "offline-context-key")
    monkeypatch.setattr(module.llm, "get_openai_client", module.llm.get_openai_client)
    monkeypatch.setenv("REPOGUIDE_EVAL_BUDGET_FILE", str(tmp_path / "spend.json"))
    monkeypatch.setattr(module.llm, "generate_answer", lambda _: "fixture generation")

    def answer(**args):
        if generate:
            module.llm.generate_answer("offline fixture")
        return AnswerResult(
            answer="fixture answer",
            status="answered",
            claims=[],
            limitations=[],
            verified_labels=["S1"],
            rejected_labels=[],
            sources=[
                {
                    "label": "S1",
                    "file_path": next(iter(all_paths)),
                    "start_line": 1,
                    "end_line": 1,
                }
            ],
            docs_sources=[],
            trace=[],
        )

    monkeypatch.setattr(module, "answer", answer)
    monkeypatch.setattr(
        module,
        "decide",
        lambda *args: SimpleNamespace(intent="code", tools=[], router="policy"),
    )
    external = importlib.import_module("repoguide.external_tools_v2")

    async def context(_):
        return SimpleNamespace(excerpt="offline fixture documentation")

    monkeypatch.setattr(external, "context7_docs", context)
    for key in ["CALLS", "TOKENS", "GEN_TOKENS", "GEN_CALLS"]:
        monkeypatch.setattr(module, key, 0)
    return module


def test_evaluator_produces_complete_typed_report_with_mocked_transports(
    monkeypatch, tmp_path
):
    evaluator = setup_evaluator(monkeypatch, tmp_path)
    path = tmp_path / "mock-report.json"
    evaluator.evaluate(path)
    report = json.loads(path.read_text())
    assert report["complete"] and report["repeats"] == 2
    assert report["generation_requests"] == 2 * len(report["case_ids"])
    assert len(report["cases"]) == 2 * len(report["case_ids"])
    from evals.release_gate import compare

    assert compare(report, report)["passed"]
    # This fixture identity cannot match a real evaluated Docker image and the
    # report lives only in pytest's temporary directory, never release artifacts.
    assert report["image_id"] == "sha256:" + "b" * 64


def test_judging_abstentions_does_not_count_as_live_generation(monkeypatch, tmp_path):
    evaluator = setup_evaluator(monkeypatch, tmp_path, generate=False)
    path = tmp_path / "mock-report.json"
    with pytest.raises(RuntimeError, match="No successful live answer generation"):
        evaluator.evaluate(path)
    report = json.loads(path.read_text())
    assert report["complete"] is False and report["live_generation"] is False


def test_judge_retries_invalid_json_once_but_never_retries_valid_low_scores(
    monkeypatch, tmp_path
):
    evaluator = setup_evaluator(monkeypatch, tmp_path)
    valid = {k: 0 for k in evaluator.JUDGE_KEYS} | {
        "unsupported_claims": True,
        "injection_resistant": False,
        "rationale": "Low score is final",
    }
    texts = iter(['{"invalid":', json.dumps(valid)])
    calls = []

    def respond(**request):
        calls.append(request)
        return SimpleNamespace(output_text=next(texts))

    result = SimpleNamespace(answer="Untrusted text", claims=[])
    client = SimpleNamespace(responses=SimpleNamespace(create=respond))
    assert (
        evaluator.judge(
            client,
            {
                "id": "format-test",
                "question": "Question",
                "required_facts": [],
                "answerable": True,
            },
            result,
            [],
        )
        == valid
    )
    assert len(calls) == 2 and calls[0] == calls[1]
    calls.clear()
    client.responses.create = lambda **request: (
        calls.append(request) or SimpleNamespace(output_text=json.dumps(valid))
    )
    evaluator.judge(
        client,
        {
            "id": "low-score",
            "question": "Question",
            "required_facts": [],
            "answerable": True,
        },
        result,
        [],
    )
    assert len(calls) == 1


def test_raw_retrieval_reuse_requires_matching_source_image_and_corpus(
    monkeypatch, tmp_path
):
    evaluator = setup_evaluator(monkeypatch, tmp_path)
    first = tmp_path / "first.json"
    evaluator.evaluate(first)

    def forbidden(**_):
        raise AssertionError(
            "Raw retrieval must reuse its identical recorded measurements"
        )

    monkeypatch.setattr(evaluator, "search", forbidden)
    second = tmp_path / "second.json"
    evaluator.evaluate(second, str(first))
    report = json.loads(second.read_text())
    assert report["raw_retrieval_reused"]["sha256"]
    cached = json.loads(first.read_text())
    cached["image_id"] = "sha256:" + "c" * 64
    first.write_text(json.dumps(cached))
    with pytest.raises(ValueError, match="identity mismatch"):
        evaluator.evaluate(tmp_path / "third.json", str(first))
