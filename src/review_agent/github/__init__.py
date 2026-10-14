"""
github/ — thin wrapper around PyGitHub.

Responsibilities:
  - Authenticate with GitHub using the token from config.
  - Fetch the diff for a PR (list of changed files + patch text).
  - Post a review (batch of inline comments) back to the PR.

Nothing in this layer calls the LLM.  Nothing here imports from core/,
tools/, or agents/.
"""
