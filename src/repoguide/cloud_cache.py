"""Optional Upstash HTTPS cache with bounded operations; standard library only."""

from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen


class RestCache:
    def __init__(self, url, token):
        if not url.startswith("https://"):
            raise ValueError("Cache requires HTTPS")
        self.url, self.token = url.rstrip("/"), token

    def command(self, *args):
        request = Request(
            self.url,
            data=json.dumps(args).encode(),
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=1) as response:
            result = json.loads(response.read(400000))
        if result.get("error"):
            raise RuntimeError("Cache command unavailable")
        return result.get("result")

    def get(self, key):
        return self.command("GET", key)

    def setex(self, key, ttl, value):
        if len(value.encode()) > 250000:
            return
        self.command("SET", key, value, "EX", min(int(ttl), 3600))


def rest_cache():
    url, token = (
        os.getenv("UPSTASH_REDIS_REST_URL"),
        os.getenv("UPSTASH_REDIS_REST_TOKEN"),
    )
    return RestCache(url, token) if url and token else None
