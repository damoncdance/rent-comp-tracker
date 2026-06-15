#!/usr/bin/env bash
# ask_codex.sh — run Codex CLI as a READ-ONLY advisor on a prompt file.
#
# Codex never writes code here: it reads the repo + the briefing and returns
# analysis only. Claude (or you) remains the sole writer/committer. This keeps
# the single-writer discipline from the Claude<->Codex collaboration loop.
#
# Usage:
#   scripts/ask_codex.sh <prompt_file> [output_file]
#
# Example:
#   scripts/ask_codex.sh docs/agent_collab/iwt_bug/codex_brief.md \
#                         docs/agent_collab/iwt_bug/codex_review.md
set -euo pipefail

PROMPT_FILE="${1:?usage: ask_codex.sh <prompt_file> [output_file]}"
OUT_FILE="${2:-}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v codex >/dev/null 2>&1; then
  echo "codex CLI not found on PATH" >&2
  exit 1
fi

# -s read-only: Codex may read the repo but cannot modify files or run writes.
# --skip-git-repo-check: harmless if run from a worktree/subdir.
run() {
  codex exec \
    -C "$REPO_ROOT" \
    -s read-only \
    --skip-git-repo-check \
    - < "$PROMPT_FILE"
}

if [[ -n "$OUT_FILE" ]]; then
  run | tee "$OUT_FILE"
else
  run
fi
