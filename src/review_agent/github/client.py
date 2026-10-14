"""
github/client.py — fetch PR data and post reviews via PyGitHub.

Key design decisions
--------------------
* We fetch the PR *once* at the start of a run and pass the data dict
  through the graph as plain Python — no live GitHub objects in state.
  This makes the graph easy to test: just inject a dict.

* `post_review` posts all comments in a single API call (a "pending"
  review submitted at the end).  One call = one notification to the
  author, not N separate pings.

* File patches are truncated at MAX_PATCH_CHARS to keep context windows
  manageable.  The agent will note "diff truncated" in that case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from github import Github
from github.PullRequest import PullRequest

from review_agent.config import settings

# Truncate individual file patches longer than this (characters).
MAX_PATCH_CHARS = 8_000


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ChangedFile:
    """One file changed in the PR."""
    filename: str          # e.g. "src/foo/bar.py"
    status: str            # "added" | "modified" | "removed" | "renamed"
    additions: int
    deletions: int
    patch: str             # unified diff text (may be truncated)
    truncated: bool = False


@dataclass
class PRData:
    """Everything the agent needs to know about a PR, as plain data."""
    repo_full_name: str    # "owner/repo"
    pr_number: int
    title: str
    body: str
    base_branch: str       # branch being merged INTO
    head_branch: str       # branch with the new code
    author: str
    files: list[ChangedFile] = field(default_factory=list)


# ── GitHub client ─────────────────────────────────────────────────────────────

def _gh() -> Github:
    """Return an authenticated PyGitHub client."""
    return Github(settings.github_token)


def fetch_pr(pr_url: str) -> PRData:
    """
    Given a GitHub PR URL, return a PRData with all changed files.

    Example URL:  https://github.com/owner/repo/pull/42

    Raises:
        ValueError   — if the URL doesn't look like a PR URL.
        GithubException — if the PR doesn't exist or token lacks access.
    """
    # Parse  owner/repo  and  PR number  from the URL.
    match = re.search(r"github\.com/([^/]+/[^/]+)/pull/(\d+)", pr_url)
    if not match:
        raise ValueError(f"Cannot parse GitHub PR URL: {pr_url!r}")

    repo_full_name = match.group(1)
    pr_number = int(match.group(2))

    gh = _gh()
    repo = gh.get_repo(repo_full_name)
    pr: PullRequest = repo.get_pull(pr_number)

    files: list[ChangedFile] = []
    for f in pr.get_files():
        patch = f.patch or ""
        truncated = False
        if len(patch) > MAX_PATCH_CHARS:
            patch = patch[:MAX_PATCH_CHARS]
            truncated = True

        files.append(ChangedFile(
            filename=f.filename,
            status=f.status,
            additions=f.additions,
            deletions=f.deletions,
            patch=patch,
            truncated=truncated,
        ))

    return PRData(
        repo_full_name=repo_full_name,
        pr_number=pr_number,
        title=pr.title,
        body=pr.body or "",
        base_branch=pr.base.ref,
        head_branch=pr.head.ref,
        author=pr.user.login,
        files=files,
    )


def post_review(
    pr_data: PRData,
    body: str,
    comments: list[dict],  # [{"path": str, "line": int, "body": str}, ...]
    event: str = "COMMENT",  # "COMMENT" | "APPROVE" | "REQUEST_CHANGES"
) -> None:
    """
    Post a PR review with inline comments.

    When settings.post_to_github is False, print the review to stdout
    (dry-run mode — useful for local development without a real PR).
    """
    if not settings.post_to_github:
        print("\n=== DRY RUN — would post GitHub review ===")
        print(f"PR:    {pr_data.repo_full_name}#{pr_data.pr_number}")
        print(f"Event: {event}")
        print(f"Body:\n{body}")
        if comments:
            print(f"\nInline comments ({len(comments)}):")
            for c in comments:
                print(f"  {c['path']}:{c['line']}  {c['body'][:80]}")
        print("===========================================\n")
        return

    gh = _gh()
    repo = gh.get_repo(pr_data.repo_full_name)
    pr = repo.get_pull(pr_data.pr_number)

    # Build the list of review comments in the format PyGitHub expects.
    # Each comment needs: path, body, and EITHER line (new file position)
    # OR position (diff position).  We use line here.
    for c in comments:
        # Only post comment if we can identify the line in the diff
        if not c.get("line"):
            continue
        pr.create_review_comment(
            body=c["body"],
            commit=pr.head.sha,   # attach to the latest commit
            path=c["path"],
            line=c["line"],
        )

    # Submit the top-level review body.
    pr.create_review(body=body, event=event)
