#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# ============================================================================
# gemini_audit_loop.sh — Automated code audit loop using Google Gemini CLI
#
# Runs Gemini as an auditor against the current repo state (diffs, source).
# Produces structured artifacts for human review and Claude Code consumption.
#
# Prerequisites: gemini (on PATH, auth configured), jq, git
# Usage: ./scripts/gemini_audit_loop.sh [OPTIONS]
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ARTIFACTS="$REPO_ROOT/artifacts"

# -- Defaults ----------------------------------------------------------------
MAX_ROUNDS=2
DRY_RUN=false
AUTO_SAFE=false
ADVANCE=false
DIFF_BASE="HEAD~1"
SCHEMA_VERSION=1

# -- Colors ------------------------------------------------------------------
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# -- Usage -------------------------------------------------------------------
usage() {
    cat <<'EOF'
Usage: gemini_audit_loop.sh [OPTIONS]

Automated code audit loop using Google Gemini CLI.

Options:
  --max-rounds N    Max audit rounds (default: 2)
  --diff-base REF   Git ref for diff base (default: HEAD~1)
  --dry-run         Write stub artifacts, print commands, don't call gemini
  --auto-safe       Auto-continue between rounds if no critical findings
  --advance         Clear a previous stop condition and resume
  --help            Show this help

Artifact outputs (in artifacts/):
  state.json         Loop state (phase, iteration, schema version)
  audit_request.md   Human-readable scope for the current round
  diff.patch         Git diff for the review window
  gemini_raw.json    Raw Gemini CLI JSON output
  audit_report.json  Normalized findings (structured)
  audit_summary.md   Executive summary for humans
  checkpoints.log    Append-only checkpoint log

Environment:
  GEMINI_MODEL       Override Gemini model (optional)
  AUDIT_DIFF_BASE    Override diff base ref (alternative to --diff-base)

Prerequisites: gemini (authenticated), jq, git
EOF
    exit 0
}

# -- Arg parsing -------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --max-rounds)  MAX_ROUNDS="$2"; shift 2 ;;
        --diff-base)   DIFF_BASE="$2"; shift 2 ;;
        --dry-run)     DRY_RUN=true; shift ;;
        --auto-safe)   AUTO_SAFE=true; shift ;;
        --advance)     ADVANCE=true; shift ;;
        --help|-h)     usage ;;
        *) echo -e "${RED}Unknown option: $1${NC}" >&2; usage ;;
    esac
done

# Allow env override for diff base
DIFF_BASE="${AUDIT_DIFF_BASE:-$DIFF_BASE}"

# -- Preflight checks --------------------------------------------------------
preflight() {
    local missing=()
    for cmd in gemini jq git; do
        if ! command -v "$cmd" &>/dev/null; then
            missing+=("$cmd")
        fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo -e "${RED}Missing required commands: ${missing[*]}${NC}" >&2
        echo "Install them and ensure they are on PATH." >&2
        exit 1
    fi

    # Verify we're in a git repo
    if ! git -C "$REPO_ROOT" rev-parse --is-inside-work-tree &>/dev/null; then
        echo -e "${RED}Not a git repository: $REPO_ROOT${NC}" >&2
        exit 1
    fi

    # Verify artifacts dir exists
    mkdir -p "$ARTIFACTS"
}

# -- Logging -----------------------------------------------------------------
log()  { echo -e "${CYAN}[audit]${NC} $*"; }
warn() { echo -e "${YELLOW}[warn]${NC} $*" >&2; }
err()  { echo -e "${RED}[error]${NC} $*" >&2; }
ok()   { echo -e "${GREEN}[ok]${NC} $*"; }

# -- State management --------------------------------------------------------
init_state() {
    local last_commit
    last_commit="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
    cat > "$ARTIFACTS/state.json" <<EOF
{
  "schema_version": $SCHEMA_VERSION,
  "phase": "init",
  "iteration": 0,
  "max_rounds": $MAX_ROUNDS,
  "last_commit": "$last_commit",
  "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "stopped": false,
  "stop_reason": null
}
EOF
}

read_state() {
    jq -r "$1" "$ARTIFACTS/state.json" 2>/dev/null || echo "null"
}

update_state() {
    # Usage: update_state '.phase = "auditing"' '.iteration = 1'
    local tmp="$ARTIFACTS/state.json.tmp"
    local expr=""
    for arg in "$@"; do
        if [[ -z "$expr" ]]; then
            expr="$arg"
        else
            expr="$expr | $arg"
        fi
    done
    expr="$expr | .updated_at = \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\""
    jq "$expr" "$ARTIFACTS/state.json" > "$tmp" && mv "$tmp" "$ARTIFACTS/state.json"
}

# -- Checkpoint logging ------------------------------------------------------
checkpoint() {
    local phase="$1" commit="$2" counts="$3"
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) | phase=$phase | commit=$commit | $counts" \
        >> "$ARTIFACTS/checkpoints.log"
}

# -- Build diff.patch --------------------------------------------------------
build_diff() {
    log "Building diff.patch (base: $DIFF_BASE)..."
    # Try the requested diff; fall back to full staged+unstaged if ref doesn't exist
    if git -C "$REPO_ROOT" rev-parse "$DIFF_BASE" &>/dev/null; then
        git -C "$REPO_ROOT" diff "$DIFF_BASE" \
            -- ':!data/tracker.db' ':!data/raw/' ':!.env' ':!artifacts/' \
            > "$ARTIFACTS/diff.patch" 2>/dev/null || true
    else
        warn "Ref '$DIFF_BASE' not found; using full working tree diff"
        git -C "$REPO_ROOT" diff HEAD \
            -- ':!data/tracker.db' ':!data/raw/' ':!.env' ':!artifacts/' \
            > "$ARTIFACTS/diff.patch" 2>/dev/null || true
    fi

    # If diff is empty, include a summary of recent commits instead
    if [[ ! -s "$ARTIFACTS/diff.patch" ]]; then
        log "No diff found; including recent commit log as context"
        {
            echo "# No diff from $DIFF_BASE — including recent commits for context"
            echo ""
            git -C "$REPO_ROOT" log --oneline -20
        } > "$ARTIFACTS/diff.patch"
    fi

    local lines
    lines="$(wc -l < "$ARTIFACTS/diff.patch" | tr -d ' ')"
    log "diff.patch: $lines lines"
}

# -- Build audit_request.md --------------------------------------------------
build_audit_request() {
    local iteration="$1"
    local last_commit
    last_commit="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"

    cat > "$ARTIFACTS/audit_request.md" <<EOF
# Audit Request — Round $iteration

## Repository
- **Project:** Rent Comp Tracker (daily multifamily rental comp scraper)
- **Commit:** $last_commit
- **Diff base:** $DIFF_BASE
- **Date:** $(date -u +%Y-%m-%dT%H:%M:%SZ)

## What changed
$(if [[ -s "$ARTIFACTS/diff.patch" ]] && ! head -1 "$ARTIFACTS/diff.patch" | grep -q '^# No diff'; then
    echo "See diff.patch for full changes. Summary of files touched:"
    echo '```'
    git -C "$REPO_ROOT" diff --stat "$DIFF_BASE" -- ':!data/tracker.db' ':!data/raw/' ':!.env' ':!artifacts/' 2>/dev/null || echo "(stat unavailable)"
    echo '```'
else
    echo "No code diff in this window. Auditing current repo state."
fi)

## Review priorities
1. **Security:** Secrets exposure (.env, API keys, tokens in prompts/logs), command injection, XSS in dashboard HTML, SQL injection in storage.py
2. **CI/CD:** GitHub Actions workflow (daily.yml) — permissions, secret handling, commit-and-push safety
3. **Scraping:** Parser regex fragility, HTTP error handling, Cloudflare/WAF bypass headers, rate limiting
4. **SQLite:** Schema integrity, migration safety, concurrent write risk, append-only contract
5. **Email/Resend:** API key handling, recipient validation, HTML injection in digest
6. **Dependencies:** Supply chain (requirements.txt), pinning, known CVEs
7. **Operational:** DB growth, raw HTML storage, gitignored secrets, file permission

## Stress-test questions
- What happens if a property website changes its HTML structure?
- What happens if the GitHub Actions workflow fails mid-commit?
- Could a malicious property website inject content into the dashboard or email?
- Are there any race conditions with the SQLite DB in git?
- What tests would catch regressions in each area?
EOF

    log "audit_request.md written for round $iteration"
}

# -- JSON schema for Gemini response -----------------------------------------
# This schema is embedded in the prompt to instruct Gemini to return structured JSON.
FINDINGS_SCHEMA='{
  "findings": [
    {
      "id": "string (e.g. SEC-001)",
      "severity": "critical | high | medium | low | info",
      "category": "security | ci_cd | scraping | sqlite | email | dependency | operational | testing",
      "title": "string — one-line summary",
      "file": "string — file path or null",
      "line": "number or null",
      "description": "string — detailed explanation",
      "recommendation": "string — specific fix",
      "test_suggestion": "string — what test would catch this"
    }
  ],
  "summary": {
    "total": "number",
    "critical": "number",
    "high": "number",
    "medium": "number",
    "low": "number",
    "info": "number",
    "top_risk": "string — single sentence"
  }
}'

# -- Build Gemini prompt -----------------------------------------------------
build_gemini_prompt() {
    local diff_content
    # Truncate diff to ~12K chars to stay within reasonable prompt size
    diff_content="$(head -c 12000 "$ARTIFACTS/diff.patch")"
    local truncated=""
    if [[ "$(wc -c < "$ARTIFACTS/diff.patch" | tr -d ' ')" -gt 12000 ]]; then
        truncated=" (truncated to 12KB; full diff in artifacts/diff.patch)"
    fi

    cat <<PROMPT
You are a senior security and reliability auditor reviewing a Python + Bash codebase.

PROJECT: Rent Comp Tracker — a daily scraper that fetches apartment listing data from property websites (RentCafe/Yardi, SecureCafe, AppFolio), stores it in SQLite, renders a static HTML dashboard with Chart.js, and sends email digests via Resend HTTP API. Runs as a GitHub Actions cron job that commits the DB back to the repo.

REVIEW PRIORITIES (in order):
1. Security: secrets exposure, injection (SQL, XSS, command), unsafe deserialization
2. CI/CD: GitHub Actions permissions, secret handling, push safety
3. Scraping: regex fragility, error handling, anti-bot detection
4. SQLite: migration safety, data integrity, append-only contract
5. Email: API key handling, HTML injection in digest content
6. Dependencies: supply chain, pinning, known issues
7. Operational: failure modes, monitoring gaps, growth risks

DIFF${truncated}:
\`\`\`
${diff_content}
\`\`\`

AUDIT REQUEST:
$(cat "$ARTIFACTS/audit_request.md")

INSTRUCTIONS:
- Analyze the diff and the audit request above.
- Return ONLY a valid JSON object matching this exact schema (no markdown fences, no explanation outside JSON):

${FINDINGS_SCHEMA}

- Use severity levels precisely: critical = exploitable now or data loss risk, high = should fix before deploy, medium = fix soon, low = minor improvement, info = observation.
- If you find no issues, return {"findings": [], "summary": {"total": 0, "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "top_risk": "No significant risks identified."}}.
- Be specific: include file paths and line numbers when possible.
- Focus on real, actionable findings. Do not pad with generic advice.
PROMPT
}

# -- Run Gemini --------------------------------------------------------------
run_gemini() {
    local iteration="$1"
    local prompt
    prompt="$(build_gemini_prompt)"

    local gemini_args=(-p "$prompt" -o json)

    # Optional model override
    if [[ -n "${GEMINI_MODEL:-}" ]]; then
        gemini_args+=(-m "$GEMINI_MODEL")
    fi

    if [[ "$DRY_RUN" == true ]]; then
        log "[DRY RUN] Would execute:"
        echo "  gemini -p <prompt> -o json ${GEMINI_MODEL:+-m $GEMINI_MODEL}"
        echo "  Prompt length: $(echo "$prompt" | wc -c | tr -d ' ') chars"

        # Write stub artifacts
        cat > "$ARTIFACTS/gemini_raw.json" <<'STUB'
{"response": "{\"findings\": [], \"summary\": {\"total\": 0, \"critical\": 0, \"high\": 0, \"medium\": 0, \"low\": 0, \"info\": 0, \"top_risk\": \"DRY RUN — no audit performed.\"}}"}
STUB
        return 0
    fi

    log "Calling Gemini CLI (round $iteration)..."
    update_state ".phase = \"auditing\"" ".iteration = $iteration"

    # Run gemini; capture exit code
    local exit_code=0
    gemini "${gemini_args[@]}" > "$ARTIFACTS/gemini_raw.json" 2>"$ARTIFACTS/gemini_stderr.tmp" || exit_code=$?

    if [[ $exit_code -ne 0 ]]; then
        err "Gemini CLI exited with code $exit_code"
        if [[ -s "$ARTIFACTS/gemini_stderr.tmp" ]]; then
            err "stderr: $(cat "$ARTIFACTS/gemini_stderr.tmp")"
        fi
        rm -f "$ARTIFACTS/gemini_stderr.tmp"
        return 1
    fi
    rm -f "$ARTIFACTS/gemini_stderr.tmp"

    # Check for .error in JSON output
    local has_error
    has_error="$(jq -r 'if .error then "yes" else "no" end' "$ARTIFACTS/gemini_raw.json" 2>/dev/null || echo "parse_fail")"
    if [[ "$has_error" == "yes" ]]; then
        err "Gemini returned an error:"
        jq -r '.error' "$ARTIFACTS/gemini_raw.json" >&2
        return 1
    fi

    ok "Gemini response received"
}

# -- Extract and normalize findings ------------------------------------------
extract_findings() {
    log "Extracting findings from Gemini response..."

    # The Gemini JSON output wraps the model's text in .response
    # We instructed the model to return only JSON, so .response should be valid JSON
    local response_text
    response_text="$(jq -r '.response // empty' "$ARTIFACTS/gemini_raw.json" 2>/dev/null || true)"

    if [[ -z "$response_text" ]]; then
        # Try alternate structures: some gemini versions use different keys
        response_text="$(jq -r '
            .candidates[0].content.parts[0].text //
            .parts[0].text //
            .text //
            .message //
            empty
        ' "$ARTIFACTS/gemini_raw.json" 2>/dev/null || true)"
    fi

    if [[ -z "$response_text" ]]; then
        warn "Could not extract response text from Gemini output"
        warn "Raw output structure: $(jq 'keys' "$ARTIFACTS/gemini_raw.json" 2>/dev/null || echo 'not JSON')"
        # Write empty report
        echo '{"findings":[],"summary":{"total":0,"critical":0,"high":0,"medium":0,"low":0,"info":0,"top_risk":"Failed to parse Gemini response."}}' \
            | jq '.' > "$ARTIFACTS/audit_report.json"
        return 1
    fi

    # Strip markdown code fences if Gemini wrapped the JSON
    response_text="$(echo "$response_text" | sed 's/^```json//; s/^```//; s/```$//' | sed '/^$/d')"

    # Validate JSON
    if echo "$response_text" | jq empty 2>/dev/null; then
        echo "$response_text" | jq '.' > "$ARTIFACTS/audit_report.json"
        ok "audit_report.json written (valid JSON)"
    else
        warn "Gemini response is not valid JSON; attempting to extract JSON block..."
        # Try to find JSON object in the response
        local extracted
        extracted="$(echo "$response_text" | grep -Pzo '\{[\s\S]*\}' | head -1 || true)"
        if [[ -n "$extracted" ]] && echo "$extracted" | jq empty 2>/dev/null; then
            echo "$extracted" | jq '.' > "$ARTIFACTS/audit_report.json"
            ok "audit_report.json written (extracted from mixed output)"
        else
            err "Could not extract valid JSON from Gemini response"
            echo '{"findings":[],"summary":{"total":0,"critical":0,"high":0,"medium":0,"low":0,"info":0,"top_risk":"Gemini response was not valid JSON. Manual review of gemini_raw.json required."}}' \
                | jq '.' > "$ARTIFACTS/audit_report.json"
            # Also save the raw text for debugging
            echo "$response_text" > "$ARTIFACTS/gemini_response_raw.txt"
            return 1
        fi
    fi
}

# -- Generate summary --------------------------------------------------------
generate_summary() {
    local iteration="$1"
    local report="$ARTIFACTS/audit_report.json"

    local total critical high medium low info top_risk
    total="$(jq -r '.summary.total // 0' "$report")"
    critical="$(jq -r '.summary.critical // 0' "$report")"
    high="$(jq -r '.summary.high // 0' "$report")"
    medium="$(jq -r '.summary.medium // 0' "$report")"
    low="$(jq -r '.summary.low // 0' "$report")"
    info="$(jq -r '.summary.info // 0' "$report")"
    top_risk="$(jq -r '.summary.top_risk // "N/A"' "$report")"

    cat > "$ARTIFACTS/audit_summary.md" <<EOF
# Audit Summary — Round $iteration
**Date:** $(date -u +%Y-%m-%dT%H:%M:%SZ)
**Commit:** $(git -C "$REPO_ROOT" rev-parse --short HEAD)
**Diff base:** $DIFF_BASE

## Findings

| Severity | Count |
|----------|-------|
| Critical | $critical |
| High     | $high |
| Medium   | $medium |
| Low      | $low |
| Info     | $info |
| **Total**| **$total** |

## Top Risk
$top_risk

## Findings Detail
$(jq -r '
    .findings[] |
    "### \(.id) [\(.severity)] — \(.title)\n" +
    "**Category:** \(.category)  \n" +
    (if .file then "**File:** `\(.file)`" + (if .line then ":\(.line)" else "" end) + "  \n" else "" end) +
    "\(.description)\n\n" +
    "**Recommendation:** \(.recommendation)\n\n" +
    "**Test suggestion:** \(.test_suggestion)\n\n---\n"
' "$report" 2>/dev/null || echo "_(no findings to display)_")

## Next Steps
$(if [[ "$critical" -gt 0 ]]; then
    echo "**STOP:** Critical findings detected. Address before continuing. Re-run with \`--advance\` after fixes."
elif [[ "$high" -gt 0 ]]; then
    echo "**Review:** High-severity findings should be addressed before deploy."
else
    echo "No blocking findings. Safe to continue."
fi)
EOF

    ok "audit_summary.md written"
    echo ""
    echo -e "${BOLD}=== Round $iteration Results ===${NC}"
    echo -e "  Critical: ${RED}$critical${NC}  High: ${YELLOW}$high${NC}  Medium: $medium  Low: $low  Info: $info"
    echo -e "  Top risk: $top_risk"
    echo ""
}

# -- Stop condition check ----------------------------------------------------
check_stop_conditions() {
    local report="$ARTIFACTS/audit_report.json"

    # Check schema version
    local current_schema
    current_schema="$(read_state '.schema_version')"
    if [[ "$current_schema" != "$SCHEMA_VERSION" ]]; then
        warn "Schema version mismatch (state: $current_schema, expected: $SCHEMA_VERSION)"
        update_state '.stopped = true' ".stop_reason = \"schema_version_mismatch\""
        return 1
    fi

    # Check for critical findings
    local critical
    critical="$(jq -r '.summary.critical // 0' "$report" 2>/dev/null)"
    if [[ "$critical" -gt 0 ]]; then
        warn "Critical findings detected ($critical). Stopping."
        warn "Address critical issues, then re-run with --advance to continue."
        update_state '.stopped = true' ".stop_reason = \"critical_findings: $critical\""
        return 1
    fi

    # Check for Gemini errors
    if jq -e '.error' "$ARTIFACTS/gemini_raw.json" &>/dev/null; then
        warn "Gemini returned errors. Stopping."
        update_state '.stopped = true' '.stop_reason = "gemini_error"'
        return 1
    fi

    return 0
}

# -- Main loop ---------------------------------------------------------------
main() {
    echo -e "${BOLD}Rent Comp Tracker — Gemini Audit Loop${NC}"
    echo "============================================"
    echo ""

    preflight

    # Handle --advance: clear stop condition
    if [[ "$ADVANCE" == true ]]; then
        if [[ -f "$ARTIFACTS/state.json" ]]; then
            local was_stopped
            was_stopped="$(read_state '.stopped')"
            if [[ "$was_stopped" == "true" ]]; then
                local reason
                reason="$(read_state '.stop_reason')"
                log "Clearing stop condition: $reason"
                update_state '.stopped = false' '.stop_reason = null'
                ok "Stop condition cleared. Resuming."
            else
                log "No stop condition to clear."
            fi
        else
            log "No previous state found. Starting fresh."
        fi
    fi

    # Check if previously stopped (and --advance not given)
    if [[ -f "$ARTIFACTS/state.json" ]] && [[ "$ADVANCE" != true ]]; then
        local stopped
        stopped="$(read_state '.stopped')"
        if [[ "$stopped" == "true" ]]; then
            local reason
            reason="$(read_state '.stop_reason')"
            err "Audit loop was stopped: $reason"
            err "Fix the issues, then re-run with --advance to continue."
            exit 1
        fi
    fi

    # Initialize state
    init_state
    log "Max rounds: $MAX_ROUNDS"
    log "Diff base: $DIFF_BASE"
    log "Dry run: $DRY_RUN"
    log "Auto-safe: $AUTO_SAFE"
    echo ""

    local round=1
    while [[ $round -le $MAX_ROUNDS ]]; do
        echo -e "${BOLD}--- Round $round of $MAX_ROUNDS ---${NC}"

        # Step 1: Builder snapshot
        build_diff
        build_audit_request "$round"

        # Step 2: Run auditor
        if ! run_gemini "$round"; then
            err "Gemini call failed in round $round"
            update_state ".phase = \"failed\"" '.stopped = true' '.stop_reason = "gemini_call_failed"'
            checkpoint "failed" "$(git -C "$REPO_ROOT" rev-parse --short HEAD)" "error=gemini_call_failed"
            exit 1
        fi

        # Step 3: Extract findings
        extract_findings || true

        # Step 4: Generate summary
        generate_summary "$round"

        # Step 5: Checkpoint
        local counts
        counts="$(jq -r '"critical=\(.summary.critical // 0) high=\(.summary.high // 0) medium=\(.summary.medium // 0) low=\(.summary.low // 0) info=\(.summary.info // 0)"' "$ARTIFACTS/audit_report.json" 2>/dev/null || echo "counts=unknown")"
        checkpoint "round_$round" "$(git -C "$REPO_ROOT" rev-parse --short HEAD)" "$counts"

        update_state ".phase = \"round_${round}_complete\"" ".iteration = $round"

        # Step 6: Check stop conditions
        if ! check_stop_conditions; then
            if [[ "$round" -lt "$MAX_ROUNDS" ]]; then
                err "Stopping after round $round. Use --advance to resume after fixing issues."
            fi
            exit 1
        fi

        # Between-round gate
        if [[ $round -lt $MAX_ROUNDS ]]; then
            if [[ "$AUTO_SAFE" == true ]]; then
                log "Auto-safe: no critical findings, continuing to round $((round + 1))..."
            else
                log "Round $round complete. Run again with --advance to continue, or --auto-safe for auto-continue."
                update_state ".phase = \"awaiting_advance\""
                break
            fi
        fi

        round=$((round + 1))
    done

    if [[ $round -gt $MAX_ROUNDS ]]; then
        update_state ".phase = \"complete\""
        ok "All $MAX_ROUNDS rounds complete."
    fi

    echo ""
    echo -e "${BOLD}Artifacts written to:${NC} $ARTIFACTS/"
    echo "  state.json        — loop state"
    echo "  audit_request.md  — scope for this round"
    echo "  diff.patch        — reviewed diff"
    echo "  gemini_raw.json   — raw Gemini output"
    echo "  audit_report.json — structured findings (for Claude Code)"
    echo "  audit_summary.md  — human-readable summary"
    echo "  checkpoints.log   — append-only log"
    echo ""
    echo -e "${CYAN}Claude Code consumption:${NC}"
    echo "  Read artifacts/audit_report.json for structured findings."
    echo "  Each finding has: id, severity, category, file, line, description, recommendation, test_suggestion"
    echo "  Filter by severity: jq '.findings[] | select(.severity == \"critical\" or .severity == \"high\")' artifacts/audit_report.json"
}

main
