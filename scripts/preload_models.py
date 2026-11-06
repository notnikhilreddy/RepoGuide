"""Materialize only pinned inference files, without duplicated HF cache layers."""

import json
import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import snapshot_download

models = json.loads(Path("/build/models.json").read_text())
for key in ["embedding"] + (["reranker"] if sys.argv[1] == "answer" else []):
    model = models[key]
    with tempfile.TemporaryDirectory() as temp:
        snapshot = snapshot_download(
            model["id"],
            revision=model["revision"],
            cache_dir=temp,
            allow_patterns=[
                "*.json",
                "*.safetensors",
                "*.txt",
                "*.model",
                "1_Pooling/*",
            ],
            ignore_patterns=["onnx/*", "openvino/*"],
        )
        shutil.copytree(
            snapshot,
            "/opt/models/" + key,
            symlinks=False,
            ignore=shutil.ignore_patterns("*.lock"),
        )
        # HF cache downloads can be mode 0600 under the build user's umask.
        # Final images run as UID 10001 and need read-only access to every weight.
        for path in Path("/opt/models/" + key).rglob("*"):
            path.chmod(0o755 if path.is_dir() else 0o644)
