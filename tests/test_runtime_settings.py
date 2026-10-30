"""Full SSM replacement behavior without AWS credentials or network calls."""

import json
from unittest.mock import MagicMock, call

import pytest

from scripts.update_runtime_settings import load_settings, sync_settings

NAME = "/repoguide/demo/runtime"


def test_env_keeps_empty_values_and_literal_strings(tmp_path):
    path = tmp_path / ".env.deploy"
    path.write_text(
        '# comment\nGEMINI_API_KEY="a=b$HOME#literal"\nREDIS_URL=\nJEV_API_KEY=""\nMLFLOW_ENABLED=false\n'
    )
    assert load_settings(path) == {
        "GEMINI_API_KEY": "a=b$HOME#literal",
        "REDIS_URL": "",
        "JEV_API_KEY": "",
        "MLFLOW_ENABLED": "false",
    }


def test_replacement_uses_only_local_keys_including_blanks_without_remote_reads(capsys):
    ssm = MagicMock()
    ssm.put_parameter.return_value = {"Version": 8}
    local = {
        "DATABASE_URL": "private-value",
        "GEMINI_API_KEY": "",
        "CUSTOM_SETTING": "",
    }
    assert sync_settings(ssm, NAME, local)
    assert ssm.mock_calls == [
        # One overwrite replaces the whole JSON object, without a remote merge.
        call.put_parameter(
            Name=NAME,
            Value=json.dumps(local, separators=(",", ":")),
            Type="SecureString",
            Overwrite=True,
        )
    ]
    assert "private-value" not in capsys.readouterr().out


def test_repeated_runs_still_write_the_local_payload():
    ssm = MagicMock()
    ssm.put_parameter.return_value = {"Version": 2}
    for _ in range(2):
        assert sync_settings(ssm, NAME, {"GEMINI_MODEL": ""})
    assert ssm.put_parameter.call_count == 2
    ssm.get_parameter.assert_not_called()


def test_dry_run_needs_no_aws_client():
    assert not sync_settings(None, NAME, {"GEMINI_API_KEY": ""}, dry_run=True)


def test_explicit_kms_key_is_passed_to_aws():
    ssm = MagicMock()
    ssm.put_parameter.return_value = {"Version": 1}
    sync_settings(ssm, NAME, {}, kms_key_id="alias/my-key")
    assert ssm.put_parameter.call_args.kwargs["KeyId"] == "alias/my-key"


@pytest.mark.parametrize(
    "content",
    ["private-value-without-equals", "BAD KEY=private-value", 'KEY="private-value'],
)
def test_invalid_file_syntax_does_not_disclose_values(tmp_path, content):
    path = tmp_path / ".env.deploy"
    path.write_text(content)
    with pytest.raises(ValueError) as exc:
        load_settings(path)
    assert "private-value" not in str(exc.value)
