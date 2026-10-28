import os
from unittest.mock import MagicMock
from repoguide.cloud_bootstrap import hydrate_runtime_env
from repoguide.cloud_guard import claims
from repoguide.cloud_jobs import enabled


def test_cloud_mode_opt_in(monkeypatch):
    monkeypatch.delenv('REPOGUIDE_CLOUD_MODE',raising=False)
    assert not enabled()
    monkeypatch.setenv('REPOGUIDE_CLOUD_MODE','true')
    assert enabled()


def test_gateway_claims_only_from_signed_event():
    request=MagicMock()
    request.scope={'aws.event':{'requestContext':{'authorizer':{'jwt':{
      'claims':{'sub':'signed-user','cognito:groups':'[repoguide-admins]'}}}}}}
    assert claims(request)['sub']=='signed-user'


def test_bootstrap_is_noop_without_ssm(monkeypatch):
    monkeypatch.delenv('REPOGUIDE_SSM_PARAMETER',raising=False)
    hydrate_runtime_env()
