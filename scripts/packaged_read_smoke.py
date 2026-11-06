"""Exercise the extracted deployment ZIP against the isolated TLS PostgreSQL DB."""

import hashlib
import json
import os
import sys
import time
import uuid
import zipfile
from pathlib import Path

zipfile.ZipFile("/deployment/api.zip").extractall("/tmp/api-package")
sys.path.insert(0, "/tmp/api-package")
from repoguide import cloud_api as api  # noqa: E402
from repoguide import cloud_product as product  # noqa: E402
from repoguide import cloud_reads as reads  # noqa: E402
from repoguide import cloud_state as state  # noqa: E402

os.environ["READ_DATABASE_URL"] = (
    "postgresql://repoguide:repoguide@host.docker.internal:55432/repoguide"
)
os.environ["REPOGUIDE_COGNITO_ISSUER"] = "test-issuer"
os.environ["REPOGUIDE_COGNITO_CLIENT_ID"] = "test-client"
api.configure = lambda: None  # SSM transport is separately checked in AWS.
os.environ.update(
    AWS_ACCESS_KEY_ID="testing",
    AWS_SECRET_ACCESS_KEY="testing",
    AWS_DEFAULT_REGION="us-east-2",
    AWS_ENDPOINT_URL="http://host.docker.internal:5500",
    REPOGUIDE_JOB_TABLE="packaged-read-" + uuid.uuid4().hex[:10],
)
db = state.clients()[0]
db.create_table(
    TableName=state.table(),
    BillingMode="PAY_PER_REQUEST",
    KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
    AttributeDefinitions=[
        {"AttributeName": k, "AttributeType": "S"}
        for k in ["pk", "catalog_pk", "catalog_sk"]
    ],
    GlobalSecondaryIndexes=[
        {
            "IndexName": "catalog",
            "KeySchema": [
                {"AttributeName": "catalog_pk", "KeyType": "HASH"},
                {"AttributeName": "catalog_sk", "KeyType": "RANGE"},
            ],
            "Projection": {"ProjectionType": "ALL"},
        }
    ],
)
with reads.database() as connection:
    for row in connection.execute("SELECT id FROM repositories").fetchall():
        product.grant_repository(str(row["id"]), "test")


def request(path, query=None):
    event = {
        "rawPath": path,
        "queryStringParameters": query or {},
        "requestContext": {
            "http": {"method": "GET"},
            "authorizer": {
                "jwt": {
                    "claims": {
                        "sub": "test",
                        "iss": "test-issuer",
                        "client_id": "test-client",
                        "token_use": "access",
                    }
                }
            },
        },
    }
    begin = time.monotonic()
    response = api.handler(event, None)
    if response["statusCode"] != 200:
        raise AssertionError((path, response["statusCode"], response["body"]))
    return json.loads(response["body"]), time.monotonic() - begin


health, health_seconds = request("/health")
ready, ready_seconds = request("/ready")
repos, cold_seconds = request("/api/ui/repositories")
repo = next(
    r for r in repos if r["commit_sha"] == "4aa70f5cbf345ab83ab7cc14257d79da6a8ee416"
)
prefix = "/api/ui/repositories/" + repo["id"]
results = []
for path in [
    prefix + "/overview",
    prefix + "/files",
    "/repositories/" + repo["id"] + "/graph",
    "/repositories/" + repo["id"] + "/dependencies",
    "/repositories/" + repo["id"] + "/architecture",
    "/repositories/" + repo["id"] + "/health",
]:
    data, elapsed = request(path)
    results.append(
        {"path": path.rsplit("/", 1)[-1], "seconds": elapsed, "nonempty": bool(data)}
    )
file, _ = request(prefix + "/file", {"path": "src/repoguide/indexer.py"})
assert not file["partial"] and "def index_repository" in file["content"]
symbols, _ = request(prefix + "/symbols-in-file", {"path": "src/repoguide/indexer.py"})
assert any(s["name"] == "index_repository" for s in symbols)
try:
    with reads.database() as db:
        db.execute("DELETE FROM repositories")
except Exception as exc:
    readonly = type(exc).__name__ == "ReadOnlySqlTransaction"
else:
    readonly = False
assert readonly
latencies = [request("/api/ui/repositories")[1] for _ in range(10)]
report = {
    "packaged": True,
    "zip_sha256": hashlib.sha256(Path("/deployment/api.zip").read_bytes()).hexdigest(),
    "ssm_mocked": True,
    "authorization_transport": "Moto DynamoDB with real owner grants; production PostgreSQL transport is not mocked",
    "database": "live disposable TLS PostgreSQL",
    "workers": "absent",
    "health_seconds": health_seconds,
    "ready_seconds": ready_seconds,
    "first_list_seconds": cold_seconds,
    "warm_list_p95_seconds": sorted(latencies)[-1],
    "readonly_enforced": readonly,
    "routes": results,
}
Path("/evidence/packaged-api-smoke.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report))
state.clients()[0].delete_table(TableName=state.table())
