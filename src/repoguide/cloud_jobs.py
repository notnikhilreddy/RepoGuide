"""Compatibility adapters for the local monolith and operator script.

The deployed ZIP uses cloud_api directly. These adapters never auto-start ECS.
"""

from __future__ import annotations

import os
import uuid

from repoguide import cloud_state as state


def enabled():
    return os.getenv("REPOGUIDE_CLOUD_MODE", "").lower() == "true"


clients = state.clients


def enqueue_index(url, force=False, owner_sub=""):
    from repoguide.cloud_api import validate_index

    return state.submit(
        "index",
        owner_sub,
        validate_index({"url": url, "force": force}),
        str(uuid.uuid4()),
    )


def get_job(job_id, owner_sub=None):
    return state.public_job(job_id, owner_sub)


def worker_paused():
    return state.control("index").get("desired_state") != "on"


def worker_status():
    current = state.status("index")
    return {
        **current,
        "paused": current.get("desired_state") != "on",
        "desired": int(current.get("desired_state") == "on"),
        "running": int(current.get("observed_state") == "ready"),
    }


def control_worker(action):
    if action == "wake":
        return state.start_service("index", "operator")
    if action == "sleep":
        return state.stop_service("index", "operator")
    raise ValueError("Unknown control action")
