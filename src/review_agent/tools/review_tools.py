"""
tools/review_tools.py — thin wiring between github/ and core/ layers.

These are the functions the LangGraph nodes call.  Keeping them small
means each node does one thing, and the logic lives in the layer below.
"""

from __future__ import annotations

from review_agent.core.formatter import format_review
from review_agent.core.passes import (
    Finding,
    run_correctness_pass,
    run_design_pass,
    run_security_pass,
)
from review_agent.github.client import ChangedFile, PRData, fetch_pr, post_review


# ── Tool: fetch PR ────────────────────────────────────────────────────────────

def fetch_pr_data(pr_url: str) -> PRData:
    """Fetch the PR diff from GitHub and return a PRData."""
    return fetch_pr(pr_url)


# ── Tool: analyse one file ─────────────────────────────────────────────────────

def analyse_file(
    changed_file: ChangedFile,
    pass_name: str,
) -> list[Finding]:
    """
    Run a single reasoning pass on one changed file.

    pass_name must be "security", "correctness", or "design".
    Returns an empty list if the file has no patch (e.g. a binary file).
    """
    if not changed_file.patch:
        return []

    if pass_name == "security":
        return run_security_pass(
            changed_file.filename, changed_file.status, changed_file.patch
        )
    elif pass_name == "correctness":
        return run_correctness_pass(
            changed_file.filename, changed_file.status, changed_file.patch
        )
    elif pass_name == "design":
        return run_design_pass(
            changed_file.filename, changed_file.status, changed_file.patch
        )
    else:
        raise ValueError(f"Unknown pass: {pass_name!r}")


# ── Tool: format review ───────────────────────────────────────────────────────

def build_review(
    findings: list[Finding],
    pr_data: PRData,
) -> tuple[str, list[dict]]:
    """Format findings into (review_body_markdown, inline_comments)."""
    return format_review(findings, pr_data.title, pr_data.author)


# ── Tool: post review ─────────────────────────────────────────────────────────

def post_or_print_review(
    pr_data: PRData,
    review_body: str,
    inline_comments: list[dict],
) -> None:
    """Post the review to GitHub (or dry-run print if POST_TO_GITHUB=false)."""
    post_review(pr_data, review_body, inline_comments)
