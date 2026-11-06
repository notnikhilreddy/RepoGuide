"""Create a disposable local PostgreSQL 18 fixture database, never production."""

import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
name = "repoguide-validation"
exists = (
    subprocess.run(
        ["docker", "inspect", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode
    == 0
)
if exists:
    print("Existing disposable validation container preserved")
    raise SystemExit(0)
image = "pgvector/pgvector:pg18@sha256:c29f30688a9ad961691bdf0ec1650717cc132a5814619d80f80463d6e4c42e47"
subprocess.run(
    [
        "docker",
        "run",
        "--name",
        name,
        "--rm",
        "-d",
        "-e",
        "POSTGRES_USER=repoguide",
        "-e",
        "POSTGRES_PASSWORD=repoguide",
        "-e",
        "POSTGRES_DB=repoguide",
        "-p",
        "127.0.0.1:55432:5432",
        image,
    ],
    check=True,
)

for attempt in range(30):
    if (
        subprocess.run(
            ["docker", "exec", name, "pg_isready", "-U", "repoguide"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    ):
        break
    time.sleep(1)
else:
    raise SystemExit("Disposable database failed to start")
env = {
    **os.environ,
    "DATABASE_URL": "postgresql+psycopg://repoguide:repoguide@127.0.0.1:55432/repoguide",
    "MLFLOW_ENABLED": "false",
}
subprocess.run(
    ["uv", "run", "--frozen", "alembic", "upgrade", "head"],
    cwd=ROOT,
    env=env,
    check=True,
)
subprocess.run(
    [
        "docker",
        "exec",
        "-u",
        "root",
        name,
        "sh",
        "-c",
        "cp /etc/ssl/certs/ssl-cert-snakeoil.pem /tmp/server.crt && cp /etc/ssl/private/ssl-cert-snakeoil.key /tmp/server.key && chown postgres:postgres /tmp/server.* && chmod 600 /tmp/server.key",
    ],
    check=True,
)
subprocess.run(
    [
        "docker",
        "exec",
        name,
        "psql",
        "-U",
        "repoguide",
        "-d",
        "repoguide",
        "-c",
        "ALTER SYSTEM SET ssl_cert_file='/tmp/server.crt'",
        "-c",
        "ALTER SYSTEM SET ssl_key_file='/tmp/server.key'",
        "-c",
        "ALTER SYSTEM SET ssl='on'",
        "-c",
        "SELECT pg_reload_conf()",
    ],
    check=True,
)
print("Disposable TLS validation database ready on port 55432")
