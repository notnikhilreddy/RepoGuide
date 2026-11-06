"""Seed only the disposable evaluation DB from the approved pinned source archive."""

import json
import os
import resource
import time
from contextlib import contextmanager
from pathlib import Path

from repoguide import indexer
from repoguide.db import SessionLocal
from repoguide.git_utils import ClonedRepository

if "host.docker.internal" not in os.environ.get("DATABASE_URL", ""):
    raise SystemExit("Fixture seeding is restricted to the disposable local database")
fixture = json.loads(Path("/evals/release_cases.json").read_text())["fixture"]


@contextmanager
def clone(_url):
    yield ClonedRepository(
        Path("/fixture-source"), fixture["commit"], "notnikhilreddy", "RepoGuide"
    )


indexer.clone_repository = clone
begin = time.monotonic()
with SessionLocal() as db:
    repo = indexer.index_repository(fixture["repository"], db)
    result = {
        "repo_id": repo.id,
        "commit": repo.commit_sha,
        "seconds": time.monotonic() - begin,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
    }
Path("/evidence/fixture.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result))
