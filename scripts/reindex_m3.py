"""Explicitly reindex the current HEAD of one repository with M3 chunking.

Warning: replaces stored chunks and graph for that repo/commit transactionally.
The existing repo ID stays the same but existing chunk IDs are replaced.
"""
import argparse

from repoguide.db import SessionLocal
from repoguide.indexer import index_repository


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Small public HTTPS GitHub repository URL")
    args = parser.parse_args()
    with SessionLocal() as session:
        repo = index_repository(args.url, session, force=True)
        print(f"Reindexed {repo.url} at {repo.commit_sha}: {repo.id}")


if __name__ == "__main__":
    main()
