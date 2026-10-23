"""Measure bounded router decisions and latency with the exact same labeled set."""
import argparse
import json
import statistics
import time
from pathlib import Path

from repoguide.config import settings
from repoguide.router import decide
from repoguide.telemetry import setup_mlflow


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data',default='evals/mcp_route_cases.json')
    p.add_argument('--providers',nargs='+',default=['llm'])
    args=p.parse_args()
    import mlflow
    setup_mlflow()
    cases=json.loads(Path(args.data).read_text())
    with mlflow.start_run(run_name='RepoGuide-M6-routing-comparison'):
        mlflow.log_param('router_cases',len(cases));mlflow.log_param('router_dataset',args.data)
        rows=[]
        for provider in args.providers:
            if provider not in {'llm','jev'}: raise ValueError('Unknown router')
            settings.router_provider=provider
            for case in cases:
                start=time.perf_counter()
                result=decide(case['question'],case.get('sources',[]),case.get('dependencies',[]),case.get('docs_policy','auto'))
                ms=(time.perf_counter()-start)*1000
                record={'provider':provider,'question':case['question'],'expected':case['expected_tools'],'actual':result.tools,'correct':set(result.tools)==set(case['expected_tools']),'latency_ms':ms,'sufficient':result.sufficient}
                rows.append(record)
            selection=[r for r in rows if r['provider']==provider]
            mlflow.log_metric(f'{provider}_tool_accuracy',sum(r['correct'] for r in selection)/len(selection))
            mlflow.log_metric(f'{provider}_median_latency_ms',statistics.median(r['latency_ms'] for r in selection))
        mlflow.log_dict(rows,'router/decisions.json')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':main()
