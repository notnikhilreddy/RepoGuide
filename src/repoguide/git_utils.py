import re
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from repoguide.telemetry import span


@dataclass
class ClonedRepository:
    path: Path
    commit_sha: str
    owner: str
    name: str


def parse_github_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)

    if parsed.scheme != "https" or parsed.hostname != "github.com":
        raise ValueError("Only HTTPS github.com URLs are supported")

    if parsed.username or parsed.password or parsed.port:
        raise ValueError("GitHub credentials and custom ports are not allowed")

    if parsed.query or parsed.fragment:
        raise ValueError("Query parameters and fragments are not supported")

    parts = parsed.path.strip("/").split("/")

    if len(parts) != 2:
        raise ValueError("Expected https://github.com/owner/repository")

    owner, repo = parts
    repo = repo.removesuffix(".git")

    if not re.fullmatch(r"[A-Za-z0-9-]+", owner):
        raise ValueError("Invalid GitHub owner")

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        raise ValueError("Invalid GitHub repository name")

    return owner, repo


@contextmanager
def clone_repository(url: str):
    owner, repo = parse_github_url(url)

    # Build a canonical URL rather than forwarding raw input to Git.
    safe_url = f"https://github.com/{owner}/{repo}.git"

    with tempfile.TemporaryDirectory(prefix="repoguide-") as temp_dir:
        destination = Path(temp_dir) / repo

        command = [
            "git",
            "-c",
            "protocol.file.allow=never",
            "-c",
            "protocol.ext.allow=never",
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--no-recurse-submodules",
            "--filter=blob:none",
            safe_url,
            str(destination),
        ]

        try:
            with span("git.clone", "TOOL", {"owner": owner, "repo": repo, "depth": 1}):
                subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    env={
                        "PATH": __import__("os").environ.get("PATH", ""),
                        "HOME": temp_dir,
                        "GIT_CONFIG_NOSYSTEM": "1",
                        "GIT_CONFIG_GLOBAL": "/dev/null",
                        "GIT_TERMINAL_PROMPT": "0",
                        "GIT_LFS_SKIP_SMUDGE": "1",
                    },
                )

            result = subprocess.run(
                ["git", "-C", str(destination), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )

        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"Could not clone repository: {exc.stderr.strip()[:500]}"
            ) from exc

        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Git operation timed out") from exc

        yield ClonedRepository(
            path=destination,
            commit_sha=result.stdout.strip(),
            owner=owner,
            name=repo,
        )
