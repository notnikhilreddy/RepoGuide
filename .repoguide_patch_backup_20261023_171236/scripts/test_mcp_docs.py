"""Run locally: uv run python scripts/test_mcp_docs.py fastapi lifespan"""
import asyncio
import sys
from repoguide.docs_catalog import get_doc
from repoguide.docs_mcp_client import fetch_official_docs


async def main():
    spec = get_doc(sys.argv[1], sys.argv[2])
    docs, errors = await fetch_official_docs([spec])
    print("Errors:", errors)
    for d in docs:
        print("Title:", d["title"])
        print("URL:", d["url"])
        print("Excerpt:", d["excerpt"][:600])


if __name__ == "__main__":
    asyncio.run(main())
