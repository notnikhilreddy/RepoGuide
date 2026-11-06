"""Build reproducible Python 3.12 Linux ZIPs; never include application secrets."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = (
    "torch",
    "sentence_transformers",
    "mlflow",
    "langgraph",
    "tree_sitter",
    "fastapi",
)


def package(kind, modules):
    with tempfile.TemporaryDirectory(prefix="repoguide-zip-") as temp:
        stage = Path(temp)
        if kind == "api":
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python-version",
                    "3.12",
                    "--python-platform",
                    "x86_64-manylinux_2_17",
                    "--only-binary",
                    ":all:",
                    "--require-hashes",
                    "--no-compile-bytecode",
                    "--target",
                    str(stage),
                    "-r",
                    str(ROOT / "deployment/requirements-api.txt"),
                ],
                check=True,
            )
        package_dir = stage / "repoguide"
        package_dir.mkdir(exist_ok=True)
        (package_dir / "__init__.py").write_text("")
        for name in modules:
            shutil.copy2(ROOT / "src/repoguide" / (name + ".py"), package_dir)
        output = ROOT / "deployment" / (kind + ".zip")
        with zipfile.ZipFile(
            output, "w", zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for file in sorted(stage.rglob("*")):
                if not file.is_file() or "__pycache__" in file.parts:
                    continue
                relative = file.relative_to(stage).as_posix()
                if (
                    any(relative.startswith(prefix + "/") for prefix in FORBIDDEN)
                    or ".env" in relative
                ):
                    raise ValueError("Forbidden file in ZIP")
                info = zipfile.ZipInfo(relative, (2026, 1, 1, 0, 0, 0))
                info.external_attr = 0o100644 << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, file.read_bytes())
        return {
            "path": str(output.relative_to(ROOT)),
            "bytes": output.stat().st_size,
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }


if __name__ == "__main__":
    (ROOT / ".artifacts").mkdir(exist_ok=True)
    results = [
        package(
            "api",
            [
                "cloud_api",
                "cloud_reads",
                "cloud_state",
                "cloud_cache",
                "cloud_product",
                "cloud_features",
                "github_api",
                "repository_views",
                "git_utils",
                "telemetry",
            ],
        ),
        package("controller", ["cloud_scaler", "cloud_state", "cloud_product"]),
    ]
    (ROOT / ".artifacts/package-inventory.json").write_text(
        json.dumps(results, indent=2)
    )
    print(json.dumps(results, indent=2))
