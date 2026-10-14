"""
review_agent — agentic PR reviewer.

Layer order (each layer imports ONLY from the layer below it):

  github/   ← raw GitHub API calls (fetch PR diff, post comments)
  core/     ← pure reasoning passes (no I/O, easy to unit-test)
  tools/    ← stateless tool functions wiring github + core together
  agents/   ← LangGraph graph, nodes, human-in-the-loop logic
"""

__version__ = "0.1.0"
