"""Freeze non-secret evaluated configuration before building immutable images."""

import hashlib
import json
from pathlib import Path

from update_runtime_settings import load_settings

root = Path(__file__).resolve().parents[1]
existing = (
    json.loads((root / "deployment/release-config.json").read_text())
    if (root / "deployment/release-config.json").exists()
    else {}
)
values = {
    **existing.get("runtime", {}),
    **(load_settings(root / ".env.deploy") if (root / ".env.deploy").exists() else {}),
}
from repoguide.config import Settings  # noqa: E402

keys = [
    "LLM_PROVIDER",
    "OPENAI_MODEL",
    "OPENAI_SERVICE_TIER",
    "OPENAI_REASONING_EFFORT",
    "OPENAI_MAX_OUTPUT_TOKENS",
    "OPENAI_MAX_INPUT_CHARS",
    "GEMINI_MODEL",
    "OPENCODE_MODEL",
    "OPENCODE_BASE_URL",
    "OLLAMA_MODEL",
    "OLLAMA_BASE_URL",
    "ROUTER_PROVIDER",
    "JEV_ENDPOINT",
    "JEV_MODEL",
    "ROUTER_SUFFICIENCY_THRESHOLD",
    "CONTEXT_CHAR_BUDGET",
]
frozen = {
    key: str(values.get(key) or Settings.model_fields[key.lower()].default)
    for key in keys
}
frozen.update(
    EMBEDDING_MODEL="/opt/models/embedding",
    RERANK_MODEL="/opt/models/reranker",
    EMBEDDING_DIM="384",
)

source = hashlib.sha256(
    b"".join(p.read_bytes() for p in sorted((root / "src/repoguide").glob("*.py")))
).hexdigest()
manifest = {
    "baseline_git_sha": "4aa70f5cbf345ab83ab7cc14257d79da6a8ee416",
    "runtime": frozen,
    "source_sha256": source,
    "models": json.loads((root / "deployment/models.json").read_text()),
}
(root / "deployment/release-config.json").write_text(
    json.dumps(manifest, indent=2) + "\n"
)
print("Frozen release source:", source)
