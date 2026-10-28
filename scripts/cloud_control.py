"""Use AWS SSO credentials; pause/resume background ECS compute without destroying data.
Defaults read from Terraform outputs via flags or environment variables.
"""
from __future__ import annotations
import argparse
import os
import boto3


def main():
    a=argparse.ArgumentParser()
    a.add_argument('action',choices=['status','wake','sleep'])
    a.add_argument('--cluster',default=os.getenv('REPOGUIDE_ECS_CLUSTER'))
    a.add_argument('--service',default=os.getenv('REPOGUIDE_ECS_SERVICE'))
    a.add_argument('--queue-url',default=os.getenv('REPOGUIDE_QUEUE_URL'))
    a.add_argument('--job-table',default=os.getenv('REPOGUIDE_JOB_TABLE'))
    args=a.parse_args()
    missing=[k for k,v in {'cluster':args.cluster,'service':args.service,
                           'queue-url':args.queue_url,'job-table':args.job_table}.items() if not v]
    if missing:a.error('Set these CLI flags or environment variables: '+', '.join(missing))
    ddb=boto3.client('dynamodb');sqs=boto3.client('sqs');ecs=boto3.client('ecs')
    attr=sqs.get_queue_attributes(QueueUrl=args.queue_url,AttributeNames=[
        'ApproximateNumberOfMessages','ApproximateNumberOfMessagesNotVisible'])['Attributes']
    visible=int(attr['ApproximateNumberOfMessages'])
    inflight=int(attr['ApproximateNumberOfMessagesNotVisible'])
    service=ecs.describe_services(cluster=args.cluster,services=[args.service])['services'][0]
    ctl={'pk':{'S':'control#worker'}}
    if args.action=='sleep':
        if visible or inflight:
            a.error(f'Refusing to stop while jobs exist: visible={visible}, inflight={inflight}')
        ddb.update_item(TableName=args.job_table,Key=ctl,
            UpdateExpression='SET paused=:p, idle_checks=:z',
            ExpressionAttributeValues={':p':{'BOOL':True},':z':{'N':'0'}})
        ecs.update_service(cluster=args.cluster,service=args.service,desiredCount=0)
    elif args.action=='wake':
        ddb.update_item(TableName=args.job_table,Key=ctl,
            UpdateExpression='SET paused=:p, idle_checks=:z',
            ExpressionAttributeValues={':p':{'BOOL':False},':z':{'N':'0'}})
        ecs.update_service(cluster=args.cluster,service=args.service,desiredCount=1)
    print(f'Action={args.action}; desired={service["desiredCount"]}; visible={visible}; in-flight={inflight}')
    print('Refresh status in ECS console; desired count changes asynchronously.')

if __name__=='__main__':main()
