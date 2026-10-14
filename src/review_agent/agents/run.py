"""
agents/run.py — CLI entry point.

Usage:
    uv run python -m review_agent.agents.run --pr-url https://github.com/owner/repo/pull/42

Or via Makefile:
    make review PR=https://github.com/owner/repo/pull/42

Flow
----
1.  Invoke the graph on the given PR URL.
2.  Graph pauses at the human_approval interrupt.
3.  We print the review body so the user can read it.
4.  Ask Y/N: post to GitHub or abort.
5.  Resume the graph with approved=True/False.
6.  Graph posts the review (or skips) and reaches END.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from review_agent.agents.graph import AgentState, graph


def main() -> None:
    parser = argparse.ArgumentParser(description="Review a GitHub PR.")
    parser.add_argument("--pr-url", required=True, help="Full GitHub PR URL")
    args = parser.parse_args()

    # Each run gets a unique thread_id so the MemorySaver keeps them separate.
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = AgentState(pr_url=args.pr_url)

    print(f"\n🔍  Fetching and analysing PR: {args.pr_url}\n")

    # ── First invocation — runs fetch_pr → analyse, then INTERRUPTS ──────────
    result = graph.invoke(initial_state, config=config)

    # If the graph short-circuited (e.g. PR too large), show the message.
    if result.get("message") and not result.get("review_body"):
        print(f"⚠️  {result['message']}")
        sys.exit(0)

    # Show the review the agent drafted.
    review_body: str = result.get("review_body", "")
    findings = result.get("findings", [])

    print("=" * 72)
    print(review_body)
    print("=" * 72)
    print(f"\n{len(findings)} finding(s) total.\n")

    # ── Human approval ────────────────────────────────────────────────────────
    while True:
        answer = input("Post this review to GitHub? [y/n]: ").strip().lower()
        if answer in ("y", "yes"):
            approved = True
            break
        elif answer in ("n", "no"):
            approved = False
            break
        print("Please enter y or n.")

    # ── Second invocation — resume with approved flag ─────────────────────────
    # Write the decision into the checkpointed state, then resume with None.
    # (Passing a new input to invoke() would restart the graph from fetch_pr.)
    graph.update_state(config, {"approved": approved})
    final = graph.invoke(None, config=config)

    if approved:
        print(f"\n✅  {final.get('message', 'Review posted.')}")
    else:
        print("\n🚫  Review aborted — nothing was posted to GitHub.")


if __name__ == "__main__":
    main()
