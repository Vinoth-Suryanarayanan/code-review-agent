"""
Shared pytest setup.

review_agent.config builds Settings() at import time, and Settings requires
GITHUB_TOKEN and ANTHROPIC_API_KEY.  Tests mock every GitHub and Anthropic
call, so dummy values are enough — this lets `make test` (and CI) run
without a .env file.  Real values from the environment or .env still win.
"""

import os

os.environ.setdefault("GITHUB_TOKEN", "test-github-token")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("POST_TO_GITHUB", "false")
