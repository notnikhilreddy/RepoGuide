from unittest.mock import MagicMock

from repoguide.cloud_bootstrap import hydrate_runtime_env
from repoguide.cloud_guard import claims
from repoguide.cloud_jobs import enabled


def test_cloud_mode_opt_in(monkeypatch):
    monkeypatch.delenv("REPOGUIDE_CLOUD_MODE", raising=False)
    assert not enabled()
    monkeypatch.setenv("REPOGUIDE_CLOUD_MODE", "true")
    assert enabled()


def test_gateway_claims_only_from_signed_event():
    request = MagicMock()
    request.scope = {
        "aws.event": {
            "requestContext": {
                "authorizer": {
                    "jwt": {
                        "claims": {
                            "sub": "signed-user",
                            "cognito:groups": "[repoguide-admins]",
                        }
                    }
                }
            }
        }
    }
    assert claims(request)["sub"] == "signed-user"


def test_bootstrap_is_noop_without_ssm(monkeypatch):
    monkeypatch.delenv("REPOGUIDE_SSM_PARAMETER", raising=False)
    hydrate_runtime_env()


def test_bootstrap_rejects_whole_invalid_payload_before_setting_environment(
    monkeypatch,
):
    import json

    import boto3
    import pytest

    monkeypatch.setenv("REPOGUIDE_SSM_PARAMETER", "/repoguide/test/runtime")
    monkeypatch.setenv("GEMINI_MODEL", "original")
    ssm = MagicMock()
    ssm.get_parameter.return_value = {
        "Parameter": {
            "Value": json.dumps(
                {
                    "GEMINI_MODEL": "replacement",
                    "UNSUPPORTED_SETTING": "private-value",
                }
            )
        }
    }
    monkeypatch.setattr(boto3, "client", lambda *_: ssm)
    with pytest.raises(ValueError, match="unsupported"):
        hydrate_runtime_env()
    import os

    assert os.environ["GEMINI_MODEL"] == "original"
