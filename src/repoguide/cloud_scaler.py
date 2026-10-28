"""Scheduled scale-to-zero controller for SQS polling ECS service.
Avoids scaling down with visible or in-flight messages; requires two idle checks.
"""
from __future__ import annotations
import os
import time
import boto3


def handler(event, context):
    ddb, sqs, ecs = (boto3.client(x) for x in ('dynamodb', 'sqs', 'ecs'))
    table = os.environ['REPOGUIDE_JOB_TABLE']
    ctl = ddb.get_item(TableName=table, Key={'pk': {'S': 'control#worker'}}, ConsistentRead=True).get('Item', {})
    paused = ctl.get('paused', {}).get('BOOL', False)
    attrs = sqs.get_queue_attributes(QueueUrl=os.environ['REPOGUIDE_QUEUE_URL'],
        AttributeNames=['ApproximateNumberOfMessages','ApproximateNumberOfMessagesNotVisible'])['Attributes']
    pending = int(attrs.get('ApproximateNumberOfMessages', 0)) + int(attrs.get('ApproximateNumberOfMessagesNotVisible', 0))
    services = ecs.describe_services(cluster=os.environ['REPOGUIDE_ECS_CLUSTER'],
                                      services=[os.environ['REPOGUIDE_ECS_SERVICE']]).get('services', [])
    if not services:
        raise RuntimeError('Worker ECS service not found')
    desired = services[0]['desiredCount']
    prev = int(ctl.get('idle_checks', {}).get('N', '0'))
    idle = 0 if pending else prev + 1
    # Never turn off workers midway through an in-flight task based on a single approximate queue sample.
    target = 0 if paused or (pending == 0 and idle >= 2) else (1 if pending else desired)
    if desired != target:
        ecs.update_service(cluster=os.environ['REPOGUIDE_ECS_CLUSTER'],
                           service=os.environ['REPOGUIDE_ECS_SERVICE'], desiredCount=target)
    ddb.update_item(TableName=table, Key={'pk': {'S': 'control#worker'}},
                    UpdateExpression='SET idle_checks=:i, last_check=:t',
                    ExpressionAttributeValues={':i': {'N': str(idle)}, ':t': {'N': str(int(time.time()))}})
    print({'pending':pending,'desired_before':desired,'desired_after':target,'paused':paused})
    return {'pending':pending,'desired':target}
