"""Minimal MCP v2 client: communicate with the local documentation server over stdio."""
from __future__ import annotations

import asyncio
import json
import sys

from mcp import Client, StdioServerParameters
from mcp.types import TextContent
from repoguide.docs_catalog import DocSpec


async def fetch_official_docs(specs: list[DocSpec]) -> tuple[list[dict], list[str]]:
    if not specs:
        return [], []
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "repoguide.docs_mcp_server"],
    )
    documents: list[dict] = []
    errors: list[str] = []
    async with Client(params) as client:
        # Discovery verifies that the expected tool is actually available.
        listing = await client.list_tools()
        if "read_official_doc" not in {t.name for t in listing.tools}:
            raise RuntimeError("Documentation MCP server does not expose read_official_doc")
        for doc in specs[:2]:
            try:
                result = await asyncio.wait_for(
                    client.call_tool("read_official_doc", {
                        "library": doc.library, "topic": doc.topic,
                    }, read_timeout_seconds=10),
                    timeout=13,
                )
                if result.is_error:
                    errors.append(f"{doc.library}/{doc.topic}: MCP tool error")
                    continue
                payload = result.structured_content
                if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
                    payload = payload["result"]
                if not isinstance(payload, dict) or "excerpt" not in payload:
                    # Some servers return a JSON text block rather than structured content.
                    text_blocks = [x.text for x in result.content if isinstance(x, TextContent)]
                    payload = json.loads(text_blocks[0]) if text_blocks else {}
                if not isinstance(payload, dict) or not isinstance(payload.get("excerpt"), str):
                    errors.append(f"{doc.library}/{doc.topic}: invalid result")
                    continue
                # Never trust links or title metadata returned by a tool: use catalog.
                documents.append({"library": doc.library, "topic": doc.topic,
                                  "title": doc.title, "url": doc.url,
                                  "excerpt": payload["excerpt"][:9000]})
            except (TimeoutError, ValueError, json.JSONDecodeError):
                errors.append(f"{doc.library}/{doc.topic}: retrieval unavailable")
    return documents, errors
