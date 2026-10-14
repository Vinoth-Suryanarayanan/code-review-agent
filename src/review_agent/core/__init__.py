"""
core/ — pure reasoning logic.  No I/O, no GitHub, no LangGraph.

This layer is the easiest to unit-test: give it text in, get findings out.

Modules:
  passes.py    — the three analysis passes (security / correctness / design)
  formatter.py — turn raw findings into a GitHub review body + comments
"""
