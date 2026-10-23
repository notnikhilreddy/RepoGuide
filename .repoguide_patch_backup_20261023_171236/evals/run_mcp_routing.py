import json
from pathlib import Path
from repoguide.routing_v2 import plan

cases = json.loads(Path("evals/mcp_route_cases.json").read_text())
correct = 0
for case in cases:
    result = plan(case["question"],case["sources"],case["dependencies"],case["docs_policy"])
    passed = result.tools == case["expected_tools"]
    correct += passed
    print("PASS" if passed else "FAIL", repr(case["question"]), result.tools)
print(f"Routing accuracy on {len(cases)} hand-written cases: {correct}/{len(cases)}")
if correct != len(cases):
    raise SystemExit(1)
