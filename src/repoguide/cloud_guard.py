"""Demo authorization and per-identity request budgets, enforced server-side.
Gateway JWT is the actual signature verifier; this module never trusts browser headers.
"""
from __future__ import annotations
import os
import time
from fastapi import Request, HTTPException


def claims(request: Request) -> dict:
    event = request.scope.get('aws.event', {})
    return (event.get('requestContext', {}).get('authorizer', {})
            .get('jwt', {}).get('claims', {}))


def require_admin(request: Request):
    if os.getenv('REPOGUIDE_CLOUD_MODE','').lower() != 'true':
        return
    raw = claims(request).get('cognito:groups', '')
    if isinstance(raw, str):
        groups = set(raw.replace('[','').replace(']','').replace('"','').split(','))
    elif isinstance(raw, list):
        groups = set(raw)
    else:
        groups = set()
    if 'repoguide-admins' not in {g.strip() for g in groups}:
        raise HTTPException(403,'Admin permissions required')


def enforce_request_budget(request: Request):
    if os.getenv('REPOGUIDE_CLOUD_MODE','').lower() != 'true': return
    subject = claims(request).get('sub')
    if not subject:
        raise HTTPException(401,'Authenticated user required')
    limit = int(os.getenv('REPOGUIDE_USER_REQUESTS_PER_MINUTE','5'))
    bucket = int(time.time() // 60)
    import boto3
    from botocore.exceptions import ClientError
    db = boto3.client('dynamodb')
    try:
        db.update_item(TableName=os.environ['REPOGUIDE_JOB_TABLE'],
            Key={'pk': {'S': f'limit#{subject}#{bucket}'}},
            UpdateExpression='SET #count = if_not_exists(#count, :zero) + :one, expires_at = :ttl',
            ConditionExpression='attribute_not_exists(#count) OR #count < :limit',
            ExpressionAttributeNames={'#count': 'count'},
            ExpressionAttributeValues={':zero': {'N':'0'}, ':one': {'N':'1'},
                                       ':limit': {'N':str(limit)}, ':ttl': {'N':str((bucket+2)*60)}})
    except ClientError as exc:
        if exc.response['Error']['Code'] == 'ConditionalCheckFailedException':
            raise HTTPException(429,'Per-user request limit reached') from exc
        raise HTTPException(503,'Rate limiter temporarily unavailable') from exc
