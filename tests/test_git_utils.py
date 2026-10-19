import pytest

from repoguide.git_utils import parse_github_url


def test_valid_github_url():
    assert parse_github_url(
        "https://github.com/psf/requests"
    ) == ("psf", "requests")


def test_rejects_non_github_url():
    with pytest.raises(ValueError):
        parse_github_url(
            "https://example.com/owner/repo"
        )


def test_rejects_nested_path():
    with pytest.raises(ValueError):
        parse_github_url(
            "https://github.com/owner/repo/tree/main"
        )


def test_rejects_embedded_credentials():
    with pytest.raises(ValueError):
        parse_github_url(
            "https://token@github.com/owner/repo"
        )