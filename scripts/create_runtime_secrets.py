"""Write a JSON SSM SecureString without printing credential values.
Usage: python scripts/create_runtime_secrets.py --env-file .env.deploy --name /repoguide/demo/runtime
"""
from __future__ import annotations
import argparse
import json
import stat
from pathlib import Path

KEYS={'DATABASE_URL','GEMINI_API_KEY','OPENCODE_API_KEY','CONTEXT7_API_KEY',
      'GITHUB_PERSONAL_ACCESS_TOKEN','JEV_API_KEY','REDIS_URL','MLFLOW_TRACKING_URI'}


def parse(path: Path) -> dict[str,str]:
    if not path.is_file():raise ValueError('Create the local secrets file first')
    mode=path.stat().st_mode
    if mode & (stat.S_IRGRP | stat.S_IROTH):
        raise PermissionError('Secrets file is group/world-readable; run chmod 600')
    out={}
    for line in path.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#'):continue
        key,sep,value=line.partition('=')
        if not sep:raise ValueError('Expected KEY=value')
        if key not in KEYS:raise ValueError(f'Unexpected key {key}')
        if value.startswith('"') and value.endswith('"'):value=value[1:-1]
        out[key]=value
    if not out.get('DATABASE_URL'):raise ValueError('DATABASE_URL required')
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--env-file',default='.env.deploy')
    ap.add_argument('--name',default='/repoguide/demo/runtime')
    a=ap.parse_args()
    import boto3
    data=json.dumps(parse(Path(a.env_file)))
    boto3.client('ssm').put_parameter(Name=a.name,Value=data,Type='SecureString',Overwrite=True)
    print('Updated SSM SecureString:',a.name,'(values not displayed)')

if __name__=='__main__':main()
