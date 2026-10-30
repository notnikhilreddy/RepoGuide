import pytest
from pydantic import ValidationError

# MCP is optional in this environment; test imports when installed.
mcp = pytest.importorskip("mcp")
from repoguide.external_tools_v2 import Context7Lookup, GitHubLookup  # noqa: E402


def test_prevent_path_traversal():
    req = GitHubLookup(
        owner="psf", repo="requests", path="../secret.md", commit_sha="a" * 40
    )
    with pytest.raises(ValueError):
        req.check_path()


def test_valid_readme():
    GitHubLookup(
        owner="psf", repo="requests", path="README.md", commit_sha="a" * 40
    ).check_path()


def test_reject_malformed_package():
    with pytest.raises(ValidationError):
        Context7Lookup(library_name="../../etc/passwd", question="what is this API?")
