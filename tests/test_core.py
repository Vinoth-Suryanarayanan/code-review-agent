"""
tests/test_core.py — unit tests for the core reasoning layer.

These tests NEVER call the real Anthropic API.
Every LLM call is mocked with unittest.mock.patch.

What we test:
  - Rule-based security checks fire on the right patterns.
  - LLM pass deserialises the mocked JSON correctly.
  - Design pass caps severity at "medium".
  - Formatter produces a review body containing key sections.
  - Formatter inline comments have correct structure.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from review_agent.core.formatter import format_review
from review_agent.core.passes import Finding, run_design_pass, run_security_pass

# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_anthropic_response(json_text: str):
    """Return a mock Anthropic Messages response with one text content block."""
    content_block = MagicMock()
    content_block.text = json_text
    response = MagicMock()
    response.content = [content_block]
    return response


_PATCH_ANTHROPIC = "review_agent.core.passes.anthropic.Anthropic"


# ── Rule-based security tests ─────────────────────────────────────────────────

class TestSecurityRules:
    """Tests that don't need the LLM at all — rule matching only."""

    def _run_rules_only(self, patch_text: str) -> list[Finding]:
        """Run security pass with LLM mocked to return no findings."""
        with patch(_PATCH_ANTHROPIC) as MockClient:
            MockClient.return_value.messages.create.return_value = (
                _mock_anthropic_response("[]")
            )
            return run_security_pass("test.py", "modified", patch_text)

    def test_hardcoded_password_flagged(self):
        patch = '+password = "supersecret123"'
        findings = self._run_rules_only(patch)
        rule_hits = [f for f in findings if f.source == "rule"]
        assert len(rule_hits) >= 1
        assert rule_hits[0].severity == "critical"
        assert rule_hits[0].file == "test.py"

    def test_github_token_flagged(self):
        patch = "+token = 'ghp_" + "A" * 36 + "'"
        findings = self._run_rules_only(patch)
        rule_hits = [f for f in findings if f.source == "rule"]
        assert len(rule_hits) >= 1

    def test_clean_code_no_rule_hits(self):
        patch = "+result = db.execute('SELECT * FROM users WHERE id = ?', (user_id,))"
        findings = self._run_rules_only(patch)
        rule_hits = [f for f in findings if f.source == "rule"]
        assert len(rule_hits) == 0

    def test_only_added_lines_scanned(self):
        """Lines starting with '-' (removed) should not trigger rules."""
        patch = '-password = "removed_secret"'
        findings = self._run_rules_only(patch)
        assert len(findings) == 0


# ── LLM pass deserialisation ──────────────────────────────────────────────────

class TestLLMPassDeserialization:
    """Verify that the pass runner correctly parses LLM JSON output."""

    def test_valid_json_array_parsed(self):
        llm_json = """[
            {"severity": "high", "line": 10,
             "issue": "SQL injection", "suggestion": "use params"}
        ]"""
        with patch(_PATCH_ANTHROPIC) as MockClient:
            MockClient.return_value.messages.create.return_value = (
                _mock_anthropic_response(llm_json)
            )
            findings = run_security_pass("db.py", "modified", "+x = f'SELECT {val}'")

        llm_hits = [f for f in findings if f.source == "llm"]
        assert len(llm_hits) == 1
        assert llm_hits[0].severity == "high"
        assert llm_hits[0].line == 10

    def test_empty_array_returns_no_llm_findings(self):
        with patch(_PATCH_ANTHROPIC) as MockClient:
            MockClient.return_value.messages.create.return_value = (
                _mock_anthropic_response("[]")
            )
            findings = run_security_pass("ok.py", "modified", "+x = 1")

        llm_hits = [f for f in findings if f.source == "llm"]
        assert len(llm_hits) == 0

    def test_markdown_fenced_json_stripped(self):
        """Model sometimes wraps JSON in ```json ... ``` fences."""
        llm_json = '```json\n[{"severity":"low","line":null,"issue":"test","suggestion":"ok"}]\n```'
        with patch(_PATCH_ANTHROPIC) as MockClient:
            MockClient.return_value.messages.create.return_value = (
                _mock_anthropic_response(llm_json)
            )
            findings = run_security_pass("x.py", "added", "+pass")

        llm_hits = [f for f in findings if f.source == "llm"]
        assert len(llm_hits) == 1

    def test_unparseable_response_returns_empty(self):
        """If the LLM returns prose instead of JSON, we get no findings."""
        with patch(_PATCH_ANTHROPIC) as MockClient:
            MockClient.return_value.messages.create.return_value = (
                _mock_anthropic_response("I found no issues with this code.")
            )
            findings = run_security_pass("x.py", "added", "+pass")

        llm_hits = [f for f in findings if f.source == "llm"]
        assert len(llm_hits) == 0


# ── Design pass severity cap ──────────────────────────────────────────────────

class TestDesignPassSeverityCap:
    """Design pass must not produce critical or high severity findings."""

    def test_severity_capped_at_medium(self):
        llm_json = '[{"severity":"critical","line":5,"issue":"too complex","suggestion":"split"}]'
        with patch(_PATCH_ANTHROPIC) as MockClient:
            MockClient.return_value.messages.create.return_value = (
                _mock_anthropic_response(llm_json)
            )
            findings = run_design_pass("complex.py", "modified", "+def do_all(): ...")

        assert len(findings) == 1
        assert findings[0].severity == "medium"   # capped from critical

    def test_medium_severity_unchanged(self):
        llm_json = '[{"severity":"medium","line":3,"issue":"naming","suggestion":"rename"}]'
        with patch(_PATCH_ANTHROPIC) as MockClient:
            MockClient.return_value.messages.create.return_value = (
                _mock_anthropic_response(llm_json)
            )
            findings = run_design_pass("x.py", "modified", "+x=1")

        assert findings[0].severity == "medium"   # unchanged


# ── Formatter tests ───────────────────────────────────────────────────────────

class TestFormatter:
    def _sample_findings(self) -> list[Finding]:
        return [
            Finding(
                severity="critical",
                pass_name="security",
                file="auth.py",
                line=42,
                issue="Hardcoded admin password",
                suggestion="Use env var",
                source="rule",
            ),
            Finding(
                severity="medium",
                pass_name="correctness",
                file="parser.py",
                line=None,
                issue="Off-by-one in loop",
                suggestion="Use range(len(x))",
                source="llm",
            ),
        ]

    def test_review_body_contains_pr_title(self):
        body, _ = format_review(self._sample_findings(), "Fix login bug", "alice")
        assert "Fix login bug" in body

    def test_review_body_contains_author(self):
        body, _ = format_review(self._sample_findings(), "PR title", "alice")
        assert "@alice" in body

    def test_review_body_contains_severity_summary(self):
        body, _ = format_review(self._sample_findings(), "PR title", "alice")
        assert "Critical" in body or "critical" in body

    def test_inline_comments_only_for_line_findings(self):
        _, comments = format_review(self._sample_findings(), "title", "alice")
        # Only auth.py finding has a line (42); parser.py has line=None.
        assert len(comments) == 1
        assert comments[0]["path"] == "auth.py"
        assert comments[0]["line"] == 42

    def test_empty_findings_no_table(self):
        body, comments = format_review([], "All good", "bob")
        assert "No issues found" in body
        assert comments == []

    def test_findings_sorted_critical_first(self):
        findings = [
            Finding("low", "design", "a.py", 1, "style", "fix", "llm"),
            Finding("critical", "security", "b.py", 2, "secret", "remove", "rule"),
        ]
        body, _ = format_review(findings, "title", "alice")
        # Critical emoji (🔴) should appear before low emoji (🔵) in the body.
        assert body.index("🔴") < body.index("🔵")
