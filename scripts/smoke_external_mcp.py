"""Live smoke test: optional. Requires Node/npm, Docker, keys, network."""
import asyncio
import sys

from repoguide.external_tools_v2 import Context7Lookup, GitHubLookup, context7_docs, github_readme


async def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: uv run python scripts/test_external_mcp.py context7|github [args...]")
    if sys.argv[1] == "context7":
        dep = sys.argv[2] if len(sys.argv) > 2 else "fastapi"
        result = await context7_docs(Context7Lookup(library_name=dep, question="How do lifespan events work?"))
    elif sys.argv[1] == "github":
        if len(sys.argv) < 5:
            raise SystemExit("github owner repo commit_sha")
        result = await github_readme(GitHubLookup(owner=sys.argv[2], repo=sys.argv[3], commit_sha=sys.argv[4]))
    else:
        raise SystemExit("unknown mode")
    print(result.title, result.url, result.excerpt[:700])


if __name__ == "__main__":
    asyncio.run(main())
