"""Local test entrypoint only; never packaged into a deployed worker image.

Actual model/retrieval/DB/citation validation run normally. Generation is a
reviewed fixture, so paused Google evaluation requests remain paused.
"""

import json
import os
from pathlib import Path

from repoguide.cloud_bootstrap import hydrate_runtime_env

hydrate_runtime_env()
os.environ.update(
    json.loads(Path("/opt/repoguide/release-config.json").read_text())["runtime"]
)
from repoguide import provider  # noqa: E402
from repoguide.cloud_worker import run  # noqa: E402


def fixture_complete(prompt):
    evidence = prompt.split("<repository_evidence>\n", 1)[1].split(
        "</repository_evidence>", 1
    )[0]
    import re

    label = re.search(r"\[(S\d+)\]", evidence)
    if not label:
        raise ValueError("Fixture requires real indexed repository evidence")
    text = evidence[label.end() :].split("\n", 1)[-1][:300]
    citation = label.group(1)
    return json.dumps(
        {
            "status": "answered",
            "answer": "This excerpt is present in the indexed repository evidence:\n\n"
            + text
            + " ["
            + citation
            + "]",
            "claims": [
                {
                    "text": "The excerpt is part of the supplied repository evidence.",
                    "citations": [citation],
                }
            ],
            "limitations": [
                "Generation is a local test fixture. No live LLM quality is asserted."
            ],
        }
    )


provider.complete = fixture_complete
run()
