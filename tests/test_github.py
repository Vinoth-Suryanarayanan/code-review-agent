"""
tests/test_github.py — unit tests for the github/ layer.

No real GitHub API calls.  PyGitHub is fully mocked.

What we test:
  - fetch_pr correctly parses a PR URL and maps the response.
  - fetch_pr truncates long patches.
  - fetch_pr raises ValueError on a bad URL.
  - post_review dry-run prints instead of calling GitHub (POST_TO_GITHUB=false).
  - post_review calls create_review when POST_TO_GITHUB=true.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from review_agent.github.client import PRData, fetch_pr, post_review

# Patch target: the Github class used inside client.py
_PATCH_GITHUB = "review_agent.github.client.Github"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_file(filename="foo.py", status="modified", additions=5, deletions=2, patch="+ x = 1"):
    f = MagicMock()
    f.filename  = filename
    f.status    = status
    f.additions = additions
    f.deletions = deletions
    f.patch     = patch
    return f


def _mock_pr(title="Fix bug", body="Fixes #1", base_ref="main", head_ref="feature/x",
             author="alice", files=None):
    pr = MagicMock()
    pr.title        = title
    pr.body         = body
    pr.base.ref     = base_ref
    pr.head.ref     = head_ref
    pr.user.login   = author
    pr.get_files.return_value = files or [_mock_file()]
    return pr


def _mock_github(pr):
    """Return a patched Github() that returns our mock PR."""
    gh = MagicMock()
    gh.get_repo.return_value.get_pull.return_value = pr
    return gh


# ── fetch_pr tests ────────────────────────────────────────────────────────────

class TestFetchPR:
    def test_parses_url_correctly(self):
        pr = _mock_pr()
        with patch(_PATCH_GITHUB, return_value=_mock_github(pr)):
            data = fetch_pr("https://github.com/alice/myrepo/pull/42")

        assert data.repo_full_name == "alice/myrepo"
        assert data.pr_number == 42
        assert data.title == "Fix bug"
        assert data.author == "alice"

    def test_files_mapped(self):
        files = [_mock_file("a.py"), _mock_file("b.py")]
        pr = _mock_pr(files=files)
        with patch(_PATCH_GITHUB, return_value=_mock_github(pr)):
            data = fetch_pr("https://github.com/o/r/pull/1")

        assert len(data.files) == 2
        assert data.files[0].filename == "a.py"

    def test_patch_truncated_when_too_long(self):
        long_patch = "+" + "x" * 10_000
        pr = _mock_pr(files=[_mock_file(patch=long_patch)])
        with patch(_PATCH_GITHUB, return_value=_mock_github(pr)):
            data = fetch_pr("https://github.com/o/r/pull/1")

        assert data.files[0].truncated is True
        assert len(data.files[0].patch) <= 8_000

    def test_short_patch_not_truncated(self):
        pr = _mock_pr(files=[_mock_file(patch="+short")])
        with patch(_PATCH_GITHUB, return_value=_mock_github(pr)):
            data = fetch_pr("https://github.com/o/r/pull/1")

        assert data.files[0].truncated is False

    def test_bad_url_raises_value_error(self):
        with pytest.raises(ValueError, match="Cannot parse GitHub PR URL"):
            fetch_pr("https://notgithub.com/foo/bar")

    def test_none_patch_becomes_empty_string(self):
        f = _mock_file(patch=None)
        pr = _mock_pr(files=[f])
        with patch(_PATCH_GITHUB, return_value=_mock_github(pr)):
            data = fetch_pr("https://github.com/o/r/pull/1")

        assert data.files[0].patch == ""


# ── post_review tests ─────────────────────────────────────────────────────────

def _sample_pr_data():
    return PRData(
        repo_full_name="alice/myrepo",
        pr_number=42,
        title="Fix bug",
        body="",
        base_branch="main",
        head_branch="feature/x",
        author="alice",
        files=[],
    )


class TestPostReview:
    def test_dry_run_prints_not_posts(self, capsys):
        pr_data = _sample_pr_data()
        with patch("review_agent.github.client.settings") as mock_settings:
            mock_settings.post_to_github = False
            post_review(pr_data, "## Review", [])

        captured = capsys.readouterr()
        assert "DRY RUN" in captured.out

    def test_live_calls_create_review(self):
        pr_data = _sample_pr_data()
        mock_pr = MagicMock()
        mock_pr.head.sha = "abc123"

        with patch(_PATCH_GITHUB) as MockGH, \
             patch("review_agent.github.client.settings") as mock_settings:
            mock_settings.post_to_github = True
            mock_settings.github_token = "fake"
            MockGH.return_value.get_repo.return_value.get_pull.return_value = mock_pr

            post_review(pr_data, "## Review body", [])

        mock_pr.create_review.assert_called_once_with(
            body="## Review body",
            event="COMMENT",
        )

    def test_inline_comments_without_line_skipped(self):
        """Comments with no line number should not call create_review_comment."""
        pr_data = _sample_pr_data()
        mock_pr = MagicMock()
        mock_pr.head.sha = "abc123"
        comment_no_line = {"path": "foo.py", "line": None, "body": "issue"}

        with patch(_PATCH_GITHUB) as MockGH, \
             patch("review_agent.github.client.settings") as mock_settings:
            mock_settings.post_to_github = True
            mock_settings.github_token = "fake"
            MockGH.return_value.get_repo.return_value.get_pull.return_value = mock_pr

            post_review(pr_data, "body", [comment_no_line])

        mock_pr.create_review_comment.assert_not_called()
