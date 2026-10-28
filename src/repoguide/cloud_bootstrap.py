"""Load application secrets from SSM into the process environment BEFORE app imports.
The Terraform state only stores the SSM parameter name, never the value.
"""
from __future__ import annotations
import json
import os


def hydrate_runtime_env() -> None:
    name = os.getenv('REPOGUIDE_SSM_PARAMETER')
    if not name:
        return
    import boto3
    data = boto3.client('ssm').get_parameter(Name=name, WithDecryption=True)
    secret = json.loads(data['Parameter']['Value'])
    if not isinstance(secret, dict):
        raise ValueError('SSM parameter must be a JSON object')
    for key, value in secret.items():
        if not isinstance(value, str) or not key.isupper():
            raise ValueError('Invalid SSM configuration entry')
        if key not in {'DATABASE_URL', 'GEMINI_API_KEY', 'OPENCODE_API_KEY',
                       'CONTEXT7_API_KEY', 'GITHUB_PERSONAL_ACCESS_TOKEN',
                       'JEV_API_KEY', 'REDIS_URL', 'MLFLOW_TRACKING_URI'}:
            raise ValueError(f'Unexpected SSM setting: {key}')
        os.environ[key] = value
