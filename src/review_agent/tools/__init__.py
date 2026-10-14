"""
tools/ — stateless tool functions called by the LangGraph nodes.

Each function takes plain Python in, returns plain Python out.
No LangGraph state objects live here — that keeps tools unit-testable.

Functions:
  fetch_pr_data(pr_url)                      → PRData
  analyse_file(file, pass_name)              → list[Finding]
  build_review(findings, pr_data)            → (body, comments)
  post_or_print_review(pr_data, body, cmts)  → None
"""
