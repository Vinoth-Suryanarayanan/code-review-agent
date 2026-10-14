"""
core/passes.py — the three reasoning passes.

Why three passes?
-----------------
A single "review this diff" prompt gives vague, scattered output.
Three focused passes each have a narrow brief:

  Pass 1 — SECURITY
    Look only for vulnerabilities: injection, exposed secrets, auth bypass,
    unsafe deserialization, path traversal, etc.

  Pass 2 — CORRECTNESS
    Logic errors, off-by-one, unhandled exceptions, wrong types,
    broken edge cases — things that will cause bugs at runtime.

  Pass 3 — DESIGN
    Code smell, readability, maintainability, API surface, naming.
    Low-severity by default; raised to medium only with clear rationale.

Each pass returns a list of Finding objects.
The agents layer assembles all three lists and hands them to formatter.py.

Design note — rules first
--------------------------
Before calling the LLM, each pass runs a fast rule-based pre-screen
(e.g. regex for "SECRET=", "password =", hardcoded IPs).  Only findings
not caught by rules go to the LLM.  This mirrors the TutionFee
reconciler pattern: ~90 % rules, ~10 % LLM.

This makes the agent:
  - Cheaper  (fewer tokens)
  - Faster   (rules run in microseconds)
  - Auditable (rule hits are deterministic)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

import anthropic

from review_agent.config import settings

# ── Finding data class ────────────────────────────────────────────────────────

Severity = Literal["critical", "high", "medium", "low", "info"]
PassName = Literal["security", "correctness", "design"]


@dataclass
class Finding:
    """One issue found in the diff."""
    severity: Severity
    pass_name: PassName
    file: str
    line: int | None      # None = file-level, not line-level
    issue: str            # short description ("SQL injection risk")
    suggestion: str       # what to do about it
    source: str           # "rule" | "llm"  — for transparency / debugging


# ── Rule-based pre-screens ────────────────────────────────────────────────────

# Patterns that flag a security issue without needing the LLM.
_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'(?i)(secret|password|api_?key|token)\s*=\s*["\'][^"\']{8,}["\']'),
     "Hardcoded secret — move to environment variable or secrets manager"),
    (re.compile(r'(?i)ghp_[0-9a-zA-Z]{36}'),
     "GitHub personal access token exposed in source"),
    (re.compile(r'(?i)sk-ant-[0-9a-zA-Z\-]{20,}'),
     "Anthropic API key exposed in source"),
    (re.compile(r'(?i)AKIA[0-9A-Z]{16}'),
     "AWS access key ID exposed in source"),
]

_SQL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'(?i)f["\'].*SELECT.*WHERE.*\{'),
     "Possible SQL injection — use parameterised queries"),
    (re.compile(r'(?i)execute\(["\'].*%s.*["\'] %'),
     "String-formatting in SQL execute — use parameterised queries"),
]


def _rule_security(filename: str, patch: str) -> list[Finding]:
    """Run deterministic security rules on one file's patch."""
    findings: list[Finding] = []
    for i, line in enumerate(patch.splitlines(), start=1):
        if not line.startswith("+"):   # only check added/changed lines
            continue
        for pattern, suggestion in _SECRET_PATTERNS + _SQL_PATTERNS:
            if pattern.search(line):
                findings.append(Finding(
                    severity="critical",
                    pass_name="security",
                    file=filename,
                    line=i,
                    issue=f"Rule match: {pattern.pattern[:60]}",
                    suggestion=suggestion,
                    source="rule",
                ))
    return findings


# ── LLM prompt templates ──────────────────────────────────────────────────────

_SYSTEM_SECURITY = """\
You are a security-focused code reviewer.
Review ONLY the unified diff provided.
Look for: SQL/command injection, exposed credentials, path traversal, \
broken auth, unsafe deserialization, missing input validation, \
insecure cryptography, SSRF, XSS.
Ignore style and design issues — those are handled in a separate pass.
"""

_SYSTEM_CORRECTNESS = """\
You are a correctness-focused code reviewer.
Review ONLY the unified diff provided.
Look for: logic errors, off-by-one errors, unhandled exceptions, \
type mismatches, race conditions, broken edge cases, incorrect algorithms.
Ignore security and style issues — those are handled in separate passes.
"""

_SYSTEM_DESIGN = """\
You are a design-focused code reviewer.
Review ONLY the unified diff provided.
Look for: code duplication, overly complex logic, poor naming, \
missing documentation on public APIs, large functions that should be split,
abstraction leaks, unclear responsibility boundaries.
Flag only clear design problems — not personal style preferences.
"""

_USER_TEMPLATE = """\
File: {filename}
Status: {status}

Diff:
```diff
{patch}
```

Return your findings as a JSON array.  Each element must be:
{{
  "severity": "critical"|"high"|"medium"|"low"|"info",
  "line": <integer or null>,
  "issue": "<one sentence>",
  "suggestion": "<one sentence>"
}}

Return [] if there are no findings.  Return JSON only — no prose.
"""


# ── LLM pass runner ───────────────────────────────────────────────────────────

def _llm_pass(
    system: str,
    pass_name: PassName,
    filename: str,
    status: str,
    patch: str,
) -> list[Finding]:
    """Call the LLM for one (file, pass) combination."""
    import json

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model=settings.review_model,
        max_tokens=1024,
        system=system,
        messages=[{
            "role": "user",
            "content": _USER_TEMPLATE.format(
                filename=filename,
                status=status,
                patch=patch,
            ),
        }],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if the model wrapped the JSON.
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        # Model returned something unparseable — treat as no findings.
        return []

    findings: list[Finding] = []
    for item in items:
        findings.append(Finding(
            severity=item.get("severity", "info"),
            pass_name=pass_name,
            file=filename,
            line=item.get("line"),
            issue=item.get("issue", ""),
            suggestion=item.get("suggestion", ""),
            source="llm",
        ))
    return findings


# ── Public API — one function per pass ───────────────────────────────────────

def run_security_pass(filename: str, status: str, patch: str) -> list[Finding]:
    """
    Security pass: rules first, then LLM for anything the rules missed.

    Rules are deterministic and free.  The LLM catches subtler issues
    that rules can't express as simple regex patterns (e.g. auth bypass
    spread across multiple lines).
    """
    rule_findings = _rule_security(filename, patch)

    # Still run the LLM even if rules fired — it may catch different issues.
    llm_findings = _llm_pass(_SYSTEM_SECURITY, "security", filename, status, patch)

    return rule_findings + llm_findings


def run_correctness_pass(filename: str, status: str, patch: str) -> list[Finding]:
    """Correctness pass: LLM only (correctness issues are hard to express as rules)."""
    return _llm_pass(_SYSTEM_CORRECTNESS, "correctness", filename, status, patch)


def run_design_pass(filename: str, status: str, patch: str) -> list[Finding]:
    """Design pass: LLM only, capped at medium severity."""
    findings = _llm_pass(_SYSTEM_DESIGN, "design", filename, status, patch)
    # Design pass can flag at most "medium" — never critical/high.
    for f in findings:
        if f.severity in ("critical", "high"):
            f.severity = "medium"
    return findings
