import json
from unittest.mock import MagicMock

import pytest

from repoguide import cache
from repoguide.cloud_cache import RestCache


def test_tenant_depth_commit_model_and_prompt_change_keys(monkeypatch):
    state = {"question": "how|tenant=alice", "repo_id": "r", "commit_sha": "one"}
    key = cache.result_key(state, "gemini", "model1")
    assert key != cache.result_key(
        {**state, "question": "how|tenant=bob"}, "gemini", "model1"
    )
    assert key != cache.result_key({**state, "commit_sha": "two"}, "gemini", "model1")
    assert key != cache.result_key(state, "gemini", "model2")
    monkeypatch.setattr(cache, "quality_fingerprint", lambda: "new-prompt")
    assert key != cache.result_key(state, "gemini", "model1")
    assert "alice" not in key and "how" not in key


def test_evaluation_bypasses_read_and_write(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(cache, "cache_client", lambda: client)
    monkeypatch.setenv("REPOGUIDE_EVALUATION", "true")
    assert cache.load_result("key") is None
    cache.save_result("key", {"answer": "cached"})
    client.get.assert_not_called()
    client.setex.assert_not_called()


@pytest.mark.parametrize("error", [TimeoutError, RuntimeError, OSError])
def test_quota_timeout_and_cache_outage_are_misses(monkeypatch, error):
    client = MagicMock()
    client.get.side_effect = error
    client.setex.side_effect = error
    monkeypatch.setattr(cache, "cache_client", lambda: client)
    assert cache.load_result("key") is None
    cache.save_result("key", {"answer": "valid"})


def test_rest_uses_https_authorization_timeout_and_ttl(monkeypatch):
    request = MagicMock()
    request.__enter__.return_value.read.return_value = b'{"result":"OK"}'
    transport = MagicMock(return_value=request)
    monkeypatch.setattr("repoguide.cloud_cache.urlopen", transport)
    client = RestCache("https://cache.example", "private-token")
    client.setex("hashed-key", 30, "{}")
    arg = transport.call_args.args[0]
    assert arg.headers["Authorization"] == "Bearer private-token"
    assert json.loads(arg.data) == ["SET", "hashed-key", "{}", "EX", 30]
    assert transport.call_args.kwargs["timeout"] == 1
    assert "private-token" not in arg.full_url
    with pytest.raises(ValueError):
        RestCache("http://cache.example", "token")
