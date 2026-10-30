"""Two bounded read-only MCP client integrations for M4. No free-form tool args.

MCP SDK 2.x via stdio: Context7 npm package and GitHub's official Docker image.
Always cap returned text; do not trust result content as instructions.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass

from mcp import Client, StdioServerParameters
from pydantic import BaseModel, Field

from repoguide.config import settings


@dataclass(frozen=True)
class ExternalEvidence:
    provider: str
    title: str
    url: str
    excerpt: str
    library: str
    topic: str


class Context7Lookup(BaseModel):
    library_name: str = Field(min_length=2, max_length=80, pattern=r"^[\w.-]+$")
    question: str = Field(min_length=5, max_length=400)


class GitHubLookup(BaseModel):
    owner: str = Field(pattern=r"^[A-Za-z0-9-]{1,39}$")
    repo: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    path: str = Field(default="README.md", min_length=1, max_length=300)
    commit_sha: str = Field(pattern=r"^[a-fA-F0-9]{40}$")

    def check_path(self) -> None:
        # Only read specific, non-hidden plain text files from the indexed repo.
        if (
            self.path.startswith(("/", "."))
            or ".." in self.path.split("/")
            or "\\" in self.path
        ):
            raise ValueError("GitHub path is not allowed")
        if not self.path.lower().endswith((".md", ".rst", ".txt")):
            raise ValueError("Only known documentation file types are allowed")


def extract_tool_text(result, limit: int = 8000) -> str:
    if getattr(result, "is_error", False):
        raise RuntimeError("MCP tool reported an error")
    parts = []
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        parts.append(json.dumps(structured, ensure_ascii=False, default=str))
    else:
        for block in getattr(result, "content", []):
            if hasattr(block, "text"):
                parts.append(block.text)
    return "\n".join(parts)[:limit]


async def context7_docs(query: Context7Lookup) -> ExternalEvidence:
    # npm package reads CONTEXT7_API_KEY environment variable, avoids putting
    # token on a process command line. npx is a trusted, preinstalled dependency.
    env = dict(os.environ)
    if settings.context7_api_key:
        env["CONTEXT7_API_KEY"] = settings.context7_api_key
    params = StdioServerParameters(
        command="npx",
        args=["-y", "@upstash/context7-mcp"],
        env=env,
    )
    async with asyncio.timeout(35):
        async with Client(params) as client:
            listing = await client.list_tools()
            allowed = {t.name for t in listing.tools}
            if not {"resolve-library-id", "query-docs"}.issubset(allowed):
                raise RuntimeError("Unexpected Context7 MCP tools")
            resolved = await client.call_tool(
                "resolve-library-id",
                {
                    "libraryName": query.library_name,
                    "query": query.question,
                },
            )
            text = extract_tool_text(resolved)
            # Context7 currently returns human-readable library listings. A
            # conservative resolver requires exact /org/name ID reference in the
            # returned data, not an arbitrary LLM-fabricated string.
            ids = re.findall(
                r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?", text
            )
            if not ids:
                raise RuntimeError("Context7 did not return a resolvable library ID")

            # The first result is ranked by Context7; validate against the
            # requested library name to avoid choosing a wrong similarly-named lib.
            def normalize(value: str) -> str:
                return value.lower().replace("_", "-")

            wanted = normalize(query.library_name)

            matches = [
                library_id
                for library_id in ids
                if any(
                    wanted in normalize(part)
                    for part in library_id.strip("/").split("/")
                )
            ]

            if not matches:
                raise RuntimeError(
                    f"Context7 could not resolve dependency: {query.library_name}"
                )

            library_id = matches[0]
            result = await client.call_tool(
                "query-docs",
                {
                    "libraryId": library_id,
                    "query": query.question[:400],
                },
            )
            excerpt = extract_tool_text(result)
            if not excerpt.strip():
                raise RuntimeError("Context7 returned empty documentation")
            return ExternalEvidence(
                provider="context7",
                title=f"Context7 indexed docs: {query.library_name}",
                url="https://context7.com" + library_id,
                excerpt=excerpt,
                library=query.library_name,
                topic="documentation",
            )


async def github_readme(query: GitHubLookup) -> ExternalEvidence:
    query.check_path()
    token = settings.github_personal_access_token
    if not token:
        raise RuntimeError("GITHUB_PERSONAL_ACCESS_TOKEN must be configured")
    # GitHub's official server; only allow get_file_contents and no writes.
    env = dict(os.environ)
    env.update(
        {
            "GITHUB_READ_ONLY": "1",
            "GITHUB_TOOLS": "get_file_contents",
            "GITHUB_PERSONAL_ACCESS_TOKEN": token,
        }
    )
    params = StdioServerParameters(
        command="docker",
        args=[
            "run",
            "--rm",
            "-i",
            "-e",
            "GITHUB_PERSONAL_ACCESS_TOKEN",
            "-e",
            "GITHUB_READ_ONLY=1",
            "-e",
            "GITHUB_TOOLS=get_file_contents",
            "ghcr.io/github/github-mcp-server",
        ],
        env=env,
    )
    async with asyncio.timeout(40):
        async with Client(params) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            if "get_file_contents" not in names:
                raise RuntimeError("GitHub read-only tool is missing")
            result = await client.call_tool(
                "get_file_contents",
                {
                    "owner": query.owner,
                    "repo": query.repo,
                    "path": query.path,
                    "sha": query.commit_sha,
                },
            )
            excerpt = extract_tool_text(result)
            if not excerpt.strip():
                raise RuntimeError("GitHub returned empty file contents")
            return ExternalEvidence(
                provider="github",
                title=f"GitHub {query.owner}/{query.repo}: {query.path}",
                url=f"https://github.com/{query.owner}/{query.repo}/blob/{query.commit_sha}/{query.path}",
                excerpt=excerpt,
                library="github",
                topic=query.path,
            )


class GitHubIssueLookup(BaseModel):
    owner: str = Field(pattern=r"^[A-Za-z0-9-]{1,39}$")
    repo: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    issue_number: int = Field(ge=1, le=100000000)


async def github_issue(query: GitHubIssueLookup) -> ExternalEvidence:
    token = settings.github_personal_access_token
    if not token:
        raise RuntimeError("GITHUB_PERSONAL_ACCESS_TOKEN must be configured")
    env = dict(os.environ)
    env.update(
        {
            "GITHUB_READ_ONLY": "1",
            "GITHUB_TOOLS": "issue_read",
            "GITHUB_PERSONAL_ACCESS_TOKEN": token,
        }
    )
    params = StdioServerParameters(
        command="docker",
        args=[
            "run",
            "--rm",
            "-i",
            "-e",
            "GITHUB_PERSONAL_ACCESS_TOKEN",
            "-e",
            "GITHUB_READ_ONLY=1",
            "-e",
            "GITHUB_TOOLS=issue_read",
            "ghcr.io/github/github-mcp-server",
        ],
        env=env,
    )
    async with asyncio.timeout(40):
        async with Client(params) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            if "issue_read" not in tools:
                raise RuntimeError("GitHub issue_read tool is missing")
            result = await client.call_tool(
                "issue_read",
                {
                    "owner": query.owner,
                    "repo": query.repo,
                    "issue_number": query.issue_number,
                    "method": "get",
                },
            )
            excerpt = extract_tool_text(result)
            if not excerpt.strip():
                raise RuntimeError("GitHub returned empty issue")
            return ExternalEvidence(
                provider="github",
                title=f"GitHub issue #{query.issue_number}",
                url=f"https://github.com/{query.owner}/{query.repo}/issues/{query.issue_number}",
                excerpt=excerpt,
                library="github",
                topic="issue",
            )
