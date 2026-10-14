"""
agents/graph.py — the LangGraph state machine.

State
-----
AgentState holds everything the graph needs across nodes.
LangGraph passes the full state dict into every node function.

Nodes (in order)
-----------------
  fetch_pr       → calls tools.fetch_pr_data, stores PRData in state
  analyse        → runs all three passes on every changed file
  human_approval → INTERRUPT: show findings summary, ask to post or abort
  post_review    → calls tools.post_or_print_review
  done           → terminal node

Graph flow
----------

  fetch_pr  →  analyse  →  human_approval  →  post_review  →  done
                                         ↘  abort  →  done

The human_approval node uses LangGraph's interrupt_before mechanism:
  - The graph pauses BEFORE entering human_approval.
  - The caller (run.py) prints the summary and asks the user Y/N.
  - If Y: resume by injecting {"approved": True} into state.
  - If N: resume by injecting {"approved": False}; graph routes to done.

MemorySaver checkpointer
------------------------
We use MemorySaver (in-process dict) as the checkpointer.
Every graph step is saved so the resume after human approval works
even if the process restarts (as long as the thread_id is the same).
For production you'd swap in SqliteSaver or a Redis checkpointer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from review_agent.config import settings
from review_agent.core.passes import Finding
from review_agent.github.client import PRData
from review_agent.tools.review_tools import (
    analyse_file,
    build_review,
    fetch_pr_data,
    post_or_print_review,
)

# ── State ─────────────────────────────────────────────────────────────────────

@dataclass
class AgentState:
    """
    Mutable state passed through the graph.

    LangGraph requires the state to be a TypedDict or dataclass.
    We use a dataclass because the field defaults are cleaner to read.
    """
    # Input
    pr_url: str = ""

    # Populated by fetch_pr node
    pr_data: PRData | None = None

    # Populated by analyse node
    findings: list[Finding] = field(default_factory=list)

    # Populated by build_review inside the analyse node
    review_body: str = ""
    inline_comments: list[dict] = field(default_factory=list)

    # Set by the caller after the human_approval interrupt
    approved: bool | None = None

    # Terminal message for run.py to display
    message: str = ""


# ── Node functions ────────────────────────────────────────────────────────────

def node_fetch_pr(state: AgentState) -> dict[str, Any]:
    """
    Node 1 — fetch PR diff from GitHub.

    Input  state: pr_url
    Output state: pr_data
    """
    pr_data = fetch_pr_data(state.pr_url)

    # Guard: skip PRs that are too large.
    if len(pr_data.files) > settings.max_files_per_pr:
        return {
            "pr_data": pr_data,
            "message": (
                f"PR has {len(pr_data.files)} changed files "
                f"(limit {settings.max_files_per_pr}).  Skipping review."
            ),
        }

    return {"pr_data": pr_data}


def node_analyse(state: AgentState) -> dict[str, Any]:
    """
    Node 2 — run all three reasoning passes on all changed files.

    Input  state: pr_data
    Output state: findings, review_body, inline_comments
    """
    if state.pr_data is None:
        return {"message": "No PR data to analyse."}

    all_findings: list[Finding] = []
    passes = ["security", "correctness", "design"]

    for changed_file in state.pr_data.files:
        for pass_name in passes:
            findings = analyse_file(changed_file, pass_name)
            all_findings.extend(findings)

    review_body, inline_comments = build_review(all_findings, state.pr_data)

    return {
        "findings": all_findings,
        "review_body": review_body,
        "inline_comments": inline_comments,
    }


def node_human_approval(state: AgentState) -> dict[str, Any]:
    """
    Node 3 — human-in-the-loop checkpoint.

    This node is declared in interrupt_before so LangGraph PAUSES
    before running it.  run.py prints the summary, asks Y/N, then
    resumes the graph with state["approved"] set.

    When the graph resumes and actually enters this node, we just
    pass through — the routing edge does the real decision.
    """
    # Nothing to do here — the interrupt already happened.
    return {}


def _route_after_approval(state: AgentState) -> str:
    """Routing function: post if approved, skip to done if not."""
    if state.approved:
        return "post_review"
    return "done"


def node_post_review(state: AgentState) -> dict[str, Any]:
    """
    Node 4 — post the review to GitHub (or dry-run print).

    Input  state: pr_data, review_body, inline_comments
    Output state: message
    """
    if state.pr_data is None:
        return {"message": "Nothing to post."}

    post_or_print_review(
        state.pr_data,
        state.review_body,
        state.inline_comments,
    )

    n = len(state.findings)
    return {"message": f"Review posted — {n} finding(s) reported."}


def node_done(state: AgentState) -> dict[str, Any]:
    """Terminal node — nothing to do; graph ends here."""
    return {}


# ── Graph wiring ──────────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """
    Assemble the LangGraph state machine.

    Returns a compiled graph with MemorySaver checkpointer so the
    human-approval interrupt/resume works across calls.
    """
    builder = StateGraph(AgentState)

    # Register nodes.
    builder.add_node("fetch_pr",        node_fetch_pr)
    builder.add_node("analyse",         node_analyse)
    builder.add_node("human_approval",  node_human_approval)
    builder.add_node("post_review",     node_post_review)
    builder.add_node("done",            node_done)

    # Entry point.
    builder.set_entry_point("fetch_pr")

    # Edges.
    builder.add_edge("fetch_pr",       "analyse")
    builder.add_edge("analyse",        "human_approval")

    # Conditional edge after human_approval: post or skip.
    builder.add_conditional_edges(
        "human_approval",
        _route_after_approval,
        {"post_review": "post_review", "done": "done"},
    )

    builder.add_edge("post_review", "done")
    builder.add_edge("done",        END)

    checkpointer = MemorySaver()
    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_approval"],   # pause here for human input
    )


# Singleton graph — import this from run.py and from tests.
graph = build_graph()
