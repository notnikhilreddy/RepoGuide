"""Cost-bounded CloudWatch Embedded Metric Format for deployed HTTP requests."""
from __future__ import annotations
import json
import logging
import os
import time

logger=logging.getLogger('repoguide.cloud')

def emit_request(method:str, path:str, status:int, latency_ms:float):
    if os.getenv('REPOGUIDE_CLOUD_MODE','').lower() != 'true': return
    # Avoid query parameters, source-code snippets, usernames, user IDs.
    family = 'ask' if '/ask' in path else ('index' if 'index' in path else ('health' if path=='/health' else 'other'))
    print(json.dumps({
        '_aws':{'Timestamp':int(time.time()*1000),'CloudWatchMetrics':[{'Namespace':'RepoGuide/Http',
            'Dimensions':[['RouteFamily']], 'Metrics':[
                {'Name':'Requests','Unit':'Count'}, {'Name':'LatencyMs','Unit':'Milliseconds'},
                {'Name':'ServerErrors','Unit':'Count'}]}]},
        'RouteFamily':family, 'Requests':1,'LatencyMs':round(latency_ms,2),
        'ServerErrors':int(status>=500),'status':status,'method':method
    },separators=(',',':')))
