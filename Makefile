.PHONY: setup install test lint doctor review help

# ── Setup ─────────────────────────────────────────────────────────────────────

setup: install
	@if [ ! -f .env ]; then cp .env.example .env; echo "✓ .env created — fill in GITHUB_TOKEN and ANTHROPIC_API_KEY"; fi

install:
	uv sync --extra dev

# ── Quality ───────────────────────────────────────────────────────────────────

test:
	uv run pytest tests/ -v --tb=short

lint:
	uv run ruff check src tests

# ── Run ───────────────────────────────────────────────────────────────────────

# Usage: make review PR=https://github.com/owner/repo/pull/42
review:
	@test -n "$(PR)" || (echo "Usage: make review PR=<github-pr-url>" && exit 1)
	uv run python -m review_agent.agents.run --pr-url "$(PR)"

# ── Health check ──────────────────────────────────────────────────────────────

doctor:
	@echo "=== code-review-agent doctor ==="
	@command -v uv  >/dev/null 2>&1 && echo "✓ uv found"      || echo "✗ uv missing  →  brew install uv"
	@command -v git >/dev/null 2>&1 && echo "✓ git found"     || echo "✗ git missing"
	@test -f .env              && echo "✓ .env found"          || echo "✗ .env missing  →  cp .env.example .env"
	@grep -q "ghp_your_token" .env 2>/dev/null && echo "✗ GITHUB_TOKEN not set" || echo "✓ GITHUB_TOKEN set"
	@grep -q "sk-ant-your_key" .env 2>/dev/null && echo "✗ ANTHROPIC_API_KEY not set" || echo "✓ ANTHROPIC_API_KEY set"
	@echo "================================"

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  make setup          Install deps + create .env"
	@echo "  make test           Run all tests (no API keys needed)"
	@echo "  make lint           Ruff linter"
	@echo "  make doctor         Check prerequisites"
	@echo "  make review PR=URL  Review a GitHub PR"
	@echo ""
