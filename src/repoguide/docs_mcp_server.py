"""An MCP v2 server with a single read-only, catalog-restricted documentation tool.

Run in the project's uv environment:
    uv run python -m repoguide.docs_mcp_server

Do not print to stdout: stdout carries MCP protocol messages.
"""
from __future__ import annotations

from html.parser import HTMLParser
import httpx
from mcp.server import MCPServer
from repoguide.docs_catalog import DOCUMENTS, get_doc

mcp = MCPServer("RepoGuide official documentation")

MAX_RESPONSE_BYTES = 1_500_000
MAX_TEXT_CHARS = 6_000


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self.skip_depth += 1
        elif tag in {"p", "h1", "h2", "h3", "li", "pre", "code"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg", "nav", "footer"}:
            self.skip_depth = max(0, self.skip_depth - 1)

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        return " ".join("".join(self.parts).split())[:MAX_TEXT_CHARS]


def fetch_document(library: str, topic: str) -> dict:
    """Fetch one fixed URL; no arbitrary URL, redirects, or proxy use."""
    spec = get_doc(library, topic)
    with httpx.Client(timeout=7.0, follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", spec.url, headers={"User-Agent": "RepoGuide-docs/0.4"}) as response:
            response.raise_for_status()  # 3xx treated as an error below
            if response.status_code != 200:
                raise ValueError("Official documentation returned non-200 status")
            content_type = response.headers.get("content-type", "").lower()
            if not ("text/html" in content_type or "text/plain" in content_type):
                raise ValueError("Unexpected documentation content type")
            raw = bytearray()
            for block in response.iter_bytes(8192):
                raw.extend(block)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("Documentation page exceeded response budget")
    html = raw.decode("utf-8", errors="replace")
    if "text/html" in content_type:
        parser = TextExtractor()
        parser.feed(html)
        excerpt = parser.text()
    else:
        excerpt = " ".join(html.split())[:MAX_TEXT_CHARS]
    if not excerpt:
        raise ValueError("Official documentation returned no readable text")
    return {"library": library, "topic": topic, "title": spec.title,
            "url": spec.url, "excerpt": excerpt}


@mcp.tool()
def list_official_topics() -> list[dict]:
    """Return the fixed list of approved documentation subjects."""
    return [{"library": d.library, "topic": d.topic, "title": d.title}
            for d in DOCUMENTS]


@mcp.tool()
def read_official_doc(library: str, topic: str) -> dict:
    """Read an approved official documentation page by library and topic."""
    return fetch_document(library, topic)


if __name__ == "__main__":
    mcp.run(transport="stdio")
