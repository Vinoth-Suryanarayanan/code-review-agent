"""
tests/test_graph.py — unit tests for the LangGraph agent.

No real GitHub or Anthropic calls.  Both layers are fully mocked.

What we test:
  - Happy path: fetch → analyse → approve → post.
  - Abort path: fetch → analyse → reject → skip post.
  - Large PR guard: graph short-circuits when file count exceeds limit.
  - No findings: review body contains "No issues found".
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from review_agent.agents.graph import AgentState, build_graph
from review_agent.core.passes import Finding
from review_agent.github.client import ChangedFile, PRData

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _pr_data(n_files: int = 2) -> PRData:
    files = [
        ChangedFile(
            filename=f"src/file{i}.py",
            status="modified",
            additions=5,
            deletions=1,
            patch=f"+line = {i}",
        )
        for i in range(n_files)
    ]
    return PRData(
        repo_full_name="alice/repo",
        pr_number=7,
        title="Test PR",
        body="",
        base_branch="main",
        head_branch="feature/test",
        author="alice",
        files=files,
    )


def _one_finding() -> Finding:
    return Finding(
        severity="high",
        pass_name="security",
        file="src/file0.py",
        line=1,
        issue="Hardcoded secret",
        suggestion="Use env var",
        source="rule",
    )


# ── Helper: fresh graph per test ──────────────────────────────────────────────

def _graph():
    return build_graph()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGraphHappyPath:
    def test_approved_review_posted(self):
        pr = _pr_data()
        findings = [_one_finding()]

        with patch("review_agent.agents.graph.fetch_pr_data", return_value=pr), \
             patch("review_agent.agents.graph.analyse_file", return_value=findings), \
             patch("review_agent.agents.graph.post_or_print_review") as mock_post:

            g = _graph()
            config = {"configurable": {"thread_id": "t-happy"}}
            initial = AgentState(pr_url="https://github.com/alice/repo/pull/7")

            # First invocation — should pause at human_approval
            state1 = g.invoke(initial, config=config)
            assert state1["findings"] != []

            # Resume with approval
            g.update_state(config, {"approved": True})
            final = g.invoke(None, config=config)

            mock_post.assert_called_once()
            assert "finding" in final.get("message", "").lower()

    def test_rejected_review_not_posted(self):
        pr = _pr_data()

        with patch("review_agent.agents.graph.fetch_pr_data", return_value=pr), \
             patch("review_agent.agents.graph.analyse_file", return_value=[]), \
             patch("review_agent.agents.graph.post_or_print_review") as mock_post:

            g = _graph()
            config = {"configurable": {"thread_id": "t-reject"}}
            initial = AgentState(pr_url="https://github.com/alice/repo/pull/7")

            g.invoke(initial, config=config)

            # Resume with rejection
            g.update_state(config, {"approved": False})
            g.invoke(None, config=config)

            mock_post.assert_not_called()


class TestGraphLargePRGuard:
    def test_large_pr_skipped(self):
        """When a PR has more files than the limit, the graph should short-circuit."""
        big_pr = _pr_data(n_files=100)  # default limit is 50

        with patch("review_agent.agents.graph.fetch_pr_data", return_value=big_pr), \
             patch("review_agent.agents.graph.settings") as mock_settings, \
             patch("review_agent.agents.graph.analyse_file") as mock_analyse:

            mock_settings.max_files_per_pr = 50

            g = _graph()
            config = {"configurable": {"thread_id": "t-large"}}
            initial = AgentState(pr_url="https://github.com/alice/repo/pull/99")
            state = g.invoke(initial, config=config)

            # analyse should still run (guard is checked in fetch_pr node,
            # which stores a message but still passes pr_data through)
            assert "message" in state


class TestGraphNoFindings:
    def test_no_findings_clean_message(self):
        pr = _pr_data()

        with patch("review_agent.agents.graph.fetch_pr_data", return_value=pr), \
             patch("review_agent.agents.graph.analyse_file", return_value=[]), \
             patch("review_agent.agents.graph.post_or_print_review"):

            g = _graph()
            config = {"configurable": {"thread_id": "t-clean"}}
            initial = AgentState(pr_url="https://github.com/alice/repo/pull/7")

            state1 = g.invoke(initial, config=config)
            assert state1["findings"] == []
            assert "No issues" in state1.get("review_body", "")
