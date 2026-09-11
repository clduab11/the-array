#!/usr/bin/env bash
# =============================================================================
# LiteLLM virtual-key provisioning - ILLUSTRATIVE EXAMPLE
#
# Mints teams and virtual keys against a running LiteLLM proxy using only
# curl + jq. Idempotent: re-runs SKIP existing teams and keys (it never rotates
# a key and never edits the budget of an existing key - use /key/update for
# in-place changes). Tokens are written to a chmod-600 file that MUST be
# gitignored and are NEVER printed to stdout.
#
# Every team and every key carries budget_duration "1mo". A key minted outside
# this script (admin UI, a one-off curl) must carry budget_duration too, or its
# spend counter NEVER resets and the key eventually locks itself out.
#
# Team names, key aliases, budgets and model allow-lists below are examples.
#
# Usage:
#   chmod +x provision-keys.example.sh
#   ./provision-keys.example.sh                       # ./.env, http://localhost:4000
#   PROXY_URL=http://other-host:4000 ./provision-keys.example.sh
#
# Rotation: delete the key via /key/delete first, then re-run.
# =============================================================================
set -euo pipefail

# --- Config ----------------------------------------------------------------
PROXY_URL="${PROXY_URL:-http://localhost:4000}"
ENV_FILE="${ENV_FILE:-./.env}"
OUT_FILE="${OUT_FILE:-./.virtual-keys.env}"   # gitignored; chmod 600 enforced below
HEALTH_RETRIES="${HEALTH_RETRIES:-12}"        # 12 * 5s = 60s warm-up window
SCRIPT_VERSION="example-1.0"

# --- Dependency check ------------------------------------------------------
for tool in curl jq; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "ERROR: required tool '$tool' not found in PATH" >&2
    exit 1
  }
done

# --- Load master key (scoped read - do NOT source .env wholesale) ----------
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found" >&2
  exit 1
fi
LITELLM_MASTER_KEY="$(grep -E '^LITELLM_MASTER_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
if [[ -z "$LITELLM_MASTER_KEY" ]]; then
  echo "ERROR: LITELLM_MASTER_KEY missing or empty in $ENV_FILE" >&2
  exit 1
fi
# Strip optional surrounding quotes
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY%\"}"
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY#\"}"

# --- Proxy reachability with retry -----------------------------------------
echo "==> Probing $PROXY_URL/health/liveliness ..."
attempt=0
until curl -fsS --max-time 5 "$PROXY_URL/health/liveliness" >/dev/null 2>&1; do
  attempt=$((attempt + 1))
  if [[ $attempt -ge $HEALTH_RETRIES ]]; then
    echo "ERROR: proxy not reachable after $((attempt * 5))s" >&2
    exit 1
  fi
  sleep 5
done
echo "    proxy healthy"

# --- Auth header -----------------------------------------------------------
AUTH_HEADER="Authorization: Bearer ${LITELLM_MASTER_KEY}"

# --- Team specs ------------------------------------------------------------
# format: team_id|team_alias|max_budget|rpm_limit
# The sum of team caps should sit at or below litellm_settings.max_budget in
# the proxy config, so the global ceiling is a backstop, not the enforcer.
TEAMS=(
  "research|Research|90.0|60"
  "apps|Applications|35.0|120"
  "sandbox|Sandbox|12.0|30"
)

# --- Key specs -------------------------------------------------------------
# format: key_alias|team_id|max_budget|rpm_limit|soft_budget|models_csv
#   rpm_limit   empty => omit (inherit team rpm)
#   soft_budget empty => proxy default alert threshold; explicit value alerts earlier
#   models_csv  empty => full roster (no model restriction)
# Allow-lists pin MODEL NAMES as written in the proxy config. Renaming a
# route that a key pins breaks that key: update the key FIRST, then the YAML.
#
# One key per client, not one key per person. key_alias is the only client
# label that survives the Prometheus scrape (prometheus.yml drops user_agent),
# so two tools sharing a key can never be told apart on the dashboard after
# the fact - the label was never stored. Splitting them later does not
# backfill.
#
# apps-ide-client is the lane for OpenAI-compatible coding clients - OpenCode,
# Kilo Code, Cline, Continue and similar. Give each tool its own key if you run
# several: an interactive editor assistant and an autonomous task runner are
# different workloads with different cost profiles, and one shared key collapses
# them into one series.
#
# Confirm a client can authenticate BEFORE you size its budget. Not every client
# sends the bearer token the way the proxy expects, and some surface the failure
# as a generic connection error rather than a 401. Probe /v1/models with the key,
# then send one request and read it back from the spend ledger.
KEYS=(
  "research-agent|research|45.0|60||reasoning,coding"
  "apps-frontend|apps|18.0|60|15.0|fast,coding"
  "apps-private-lane|apps|9.0|30||private"
  "apps-ide-client|apps|8.0|60||coding,reasoning"
  "sandbox-probe|sandbox|6.0|||"
)

# --- Helpers ---------------------------------------------------------------
api() {
  local method="$1" path="$2" body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -fsS -X "$method" "$PROXY_URL$path" \
      -H "$AUTH_HEADER" -H "Content-Type: application/json" \
      --data "$body"
  else
    curl -fsS -X "$method" "$PROXY_URL$path" -H "$AUTH_HEADER"
  fi
}

team_exists() {
  local team_id="$1"
  # /team/list returns either {"teams":[...]} or [...] depending on version
  api GET "/team/list" 2>/dev/null \
    | jq -e --arg t "$team_id" '
        (if type == "object" and has("teams") then .teams else . end)[]?
        | select(.team_id == $t)
      ' >/dev/null 2>&1
}

key_alias_exists() {
  local alias="$1"
  # Page size is validation-capped upstream; raise the page loop if you
  # provision more keys than one page holds.
  api GET "/key/list?return_full_object=true&size=50" 2>/dev/null \
    | jq -e --arg a "$alias" '
        (if type == "object" and has("keys") then .keys else . end)[]?
        | select(.key_alias == $a)
      ' >/dev/null 2>&1
}

# --- Provision teams -------------------------------------------------------
echo "==> Provisioning teams..."
for spec in "${TEAMS[@]}"; do
  IFS='|' read -r team_id team_alias max_budget rpm_limit <<< "$spec"
  if team_exists "$team_id"; then
    printf "    [skip]    %-12s (exists)\n" "$team_id"
    continue
  fi
  body="$(jq -nc \
    --arg id "$team_id" \
    --arg alias "$team_alias" \
    --arg ver "$SCRIPT_VERSION" \
    --argjson mb "$max_budget" \
    --argjson rpm "$rpm_limit" \
    '{
       team_id: $id,
       team_alias: $alias,
       max_budget: $mb,
       budget_duration: "1mo",
       rpm_limit: $rpm,
       metadata: {source: "provision-keys.example.sh", version: $ver}
     }')"
  if ! api POST "/team/new" "$body" >/dev/null; then
    echo "    [FAIL] team $team_id creation failed" >&2
    exit 1
  fi
  printf "    [created] %-12s (%s/mo, %s rpm)\n" "$team_id" "$max_budget" "$rpm_limit"
done

# --- Provision keys --------------------------------------------------------
echo "==> Provisioning keys..."
umask 077
tmp_out="${OUT_FILE}.tmp"
{
  echo "# =============================================================================="
  echo "# LiteLLM virtual keys"
  echo "# Generated: $(date -u +%FT%TZ)"
  echo "# Source: provision-keys.example.sh ${SCRIPT_VERSION}"
  echo "# DO NOT COMMIT. chmod 600 enforced. Rotate via /key/delete then re-run."
  echo "# =============================================================================="
  echo ""
} > "$tmp_out"

minted=0
skipped=0
for spec in "${KEYS[@]}"; do
  IFS='|' read -r alias team_id max_budget rpm_limit soft_budget models_csv <<< "$spec"
  env_name="VIRTUAL_KEY_$(echo "$alias" | tr '[:lower:]-' '[:upper:]_')"

  if key_alias_exists "$alias"; then
    printf "    [skip]    %-22s (exists - rotate manually)\n" "$alias"
    echo "# $env_name=     # already in the proxy DB; rotate via /key/delete to regenerate" >> "$tmp_out"
    skipped=$((skipped + 1))
    continue
  fi

  # Build models JSON (omit the field entirely if CSV is empty = full roster)
  if [[ -n "$models_csv" ]]; then
    models_json="$(jq -nc --arg s "$models_csv" '$s | split(",")')"
  else
    models_json="[]"
  fi

  body="$(jq -nc \
    --arg alias "$alias" \
    --arg team "$team_id" \
    --arg ver "$SCRIPT_VERSION" \
    --argjson mb "$max_budget" \
    --arg rpm "$rpm_limit" \
    --argjson models "$models_json" \
    --arg soft "$soft_budget" \
    '{
       key_alias: $alias,
       team_id: $team,
       max_budget: $mb,
       budget_duration: "1mo",
       metadata: {source: "provision-keys.example.sh", version: $ver, created: (now | todate)}
     }
     + (if $rpm   != "" then {rpm_limit: ($rpm | tonumber)} else {} end)
     + (if ($models | length) > 0 then {models: $models} else {} end)
     + (if $soft  != "" then {soft_budget: ($soft | tonumber)} else {} end)')"

  response="$(api POST "/key/generate" "$body")"
  token="$(echo "$response" | jq -r '.key // empty')"
  if [[ -z "$token" ]]; then
    echo "    [FAIL] $alias - no .key in response" >&2
    # Print the response WITHOUT the key field so a partial success never leaks a token.
    echo "$response" | jq 'del(.key)' >&2 || echo "(unparseable response)" >&2
    exit 1
  fi

  echo "$env_name=$token" >> "$tmp_out"
  printf "    [created] %-22s team=%-12s %s/mo" "$alias" "$team_id" "$max_budget"
  [[ -n "$rpm_limit"   ]] && printf ", %s rpm" "$rpm_limit"
  [[ -n "$soft_budget" ]] && printf ", soft=%s" "$soft_budget"
  printf "\n"
  minted=$((minted + 1))
done

mv "$tmp_out" "$OUT_FILE"
chmod 600 "$OUT_FILE"

echo ""
echo "==> Done. minted=$minted, skipped=$skipped"
echo "==> Tokens written to $OUT_FILE (chmod 600) - never echo this file"
if [[ -f .gitignore ]] && grep -qxF "$(basename "$OUT_FILE")" .gitignore; then
  echo "==> .gitignore covers $(basename "$OUT_FILE")"
else
  echo "==> WARNING: add $(basename "$OUT_FILE") (and .env) to .gitignore before the next commit" >&2
fi
