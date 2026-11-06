"""Validate a protected approved-baseline pointer and archive its exact source."""

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("manifest")
a = p.parse_args()
manifest = json.loads(Path(a.manifest).read_text())
sha = manifest.get("git_sha", "")
if not re.fullmatch("[0-9a-f]{40}", sha):
    raise SystemExit("Protected baseline has no valid immutable Git SHA")
if not re.fullmatch(
    r"\d+\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[\w/-]+@sha256:[0-9a-f]{64}",
    manifest.get("images", {}).get("answer", ""),
):
    raise SystemExit("Protected baseline has no immutable Answer image")
subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], check=True)
path = Path("/tmp/repoguide-baseline")
if path.exists():
    shutil.rmtree(path)
path.mkdir()
archive = subprocess.Popen(["git", "archive", sha], stdout=subprocess.PIPE)
subprocess.run(["tar", "-x", "-C", str(path)], stdin=archive.stdout, check=True)
archive.stdout.close()
if archive.wait():
    raise SystemExit("Could not archive approved baseline")
print("Approved baseline source prepared:", sha)
