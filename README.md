# code-review-agent

An agentic GitHub PR reviewer built with **LangGraph**, **Anthropic Claude**, and **PyGitHub**.

The agent runs three focused reasoning passes — security → correctness → design — then pauses for human approval before posting anything to GitHub.

---

## What it does

```
You:  make review PR=https://github.com/your-org/your-repo/pull/42

Agent:
  1. Fetches the PR diff from GitHub
  2. Runs three Claude passes on every changed file
     - 🔒 Security  (injection, exposed secrets, auth bypass …)
     - ✅ Correctness (logic errors, type mismatches, edge cases …)
     - 🎨 Design    (naming, complexity, abstraction …)
  3. Shows you the draft review (Markdown + inline comments)
  4. Asks: "Post to GitHub? [y/n]"
  5. Posts (or aborts) based on your answer
```

---

## Architecture

```
src/review_agent/
├── github/       ← raw GitHub API  (PyGitHub, no LLM)
│   └── client.py
├── core/         ← pure reasoning  (no I/O, easy to test)
│   ├── passes.py     # three LLM reasoning passes
│   └── formatter.py  # findings → GitHub review body
├── tools/        ← wiring between github/ and core/
│   └── review_tools.py
├── agents/       ← LangGraph graph + CLI entry point
│   ├── graph.py      # StateGraph, nodes, human-in-the-loop
│   └── run.py        # CLI: python -m review_agent.agents.run
└── config.py     ← pydantic-settings (env vars / .env)
```

**Layer rule:** each layer imports only from the layer below it.
`agents/` → `tools/` → `core/` and `github/` → nothing agent-specific.

---

## Key design decisions

### Rules first, LLM second
The security pass runs fast regex rules before calling the LLM.
~90 % of obvious issues (hardcoded secrets, SQL string-formatting) are caught
by rules — deterministically and for free.  The LLM handles the nuanced 10 %.

### Human-in-the-loop via LangGraph interrupt
The graph pauses with `interrupt_before=["human_approval"]` before posting.
You read the review, decide to post or abort, and the graph resumes.
This means the agent can never post to GitHub without your explicit Y.

### Three focused passes, not one big prompt
A single "review this diff" prompt gives vague, scattered output.
Each pass has a narrow brief and its own system prompt — findings from
different passes are easier to reason about and easier to tune.

---

## Quick start

```bash
# 1. Clone
git clone https://github.com/Vinoth-Suryanarayanan/code-review-agent
cd code-review-agent

# 2. Install deps (requires uv — brew install uv)
make setup

# 3. Fill in .env
#    GITHUB_TOKEN — needs repo + pull_requests scope
#    ANTHROPIC_API_KEY — from console.anthropic.com

# 4. Check everything is wired up
make doctor

# 5. Review a PR
make review PR=https://github.com/your-org/your-repo/pull/42
```

---

## Running tests (no API keys needed)

```bash
make test
```

All tests mock the GitHub API and the Anthropic API.
The full suite runs offline.

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `GITHUB_TOKEN` | *(required)* | PAT with `repo` scope |
| `ANTHROPIC_API_KEY` | *(required)* | Claude API key |
| `REVIEW_MODEL` | `claude-3-5-haiku-20241022` | Model for the three passes |
| `POST_TO_GITHUB` | `true` | Set to `false` for local dry-run |
| `MAX_FILES_PER_PR` | `50` | Skip PRs larger than this |

---

## Safety

- `.env` is git-ignored — credentials never committed.
- `POST_TO_GITHUB=false` lets you test locally with no risk of posting.
- The human-approval interrupt means the agent cannot post without your explicit Y.
