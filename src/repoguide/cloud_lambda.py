"""FastAPI on AWS Lambda via Mangum; imports happen after SSM hydration."""
from repoguide.cloud_bootstrap import hydrate_runtime_env
hydrate_runtime_env()
from mangum import Mangum  # noqa: E402
from repoguide.main import app  # noqa: E402
handler = Mangum(app, lifespan='auto')
