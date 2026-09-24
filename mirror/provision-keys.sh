#!/usr/bin/env bash
# Sanitized structural mirror of the-array/provision-keys.sh (2026-09-23). Comments and identity values
# removed or replaced; budgets are placeholders. See mirror/README.md before restoring from it.
set -euo pipefail

PROXY_URL="${PROXY_URL:-http://localhost:4000}"
ENV_FILE="${ENV_FILE:-./.env}"
OUT_FILE="${OUT_FILE:-./.virtual-keys.env}"
HEALTH_RETRIES="${HEALTH_RETRIES:-12}"   # 12 * 5s = 60s warm-up window

for tool in curl jq; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "ERROR: required tool '$tool' not found in PATH" >&2
    exit 1
  }
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found" >&2
  exit 1
fi
LITELLM_MASTER_KEY="$(grep -E '^LITELLM_MASTER_KEY=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
if [[ -z "$LITELLM_MASTER_KEY" ]]; then
  echo "ERROR: LITELLM_MASTER_KEY missing or empty in $ENV_FILE" >&2
  exit 1
fi
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY%\"}"
LITELLM_MASTER_KEY="${LITELLM_MASTER_KEY#\"}"

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

AUTH_HEADER="Authorization: Bearer ${LITELLM_MASTER_KEY}"

TEAMS=(
  "interactive|Interactive Surface|1|200"
  "engineering|Engineering Division|1|90"
  "institute|Institute Division|1|30"
  "labs|Labs Division|1|30"
)

KEYS=(
  "front-studio-primary|interactive|1|200|1|"
  "coder-code-cloud|engineering|1|60||coding,fast,reasoning,deep-reasoning"
  "coder-code-windows|engineering|1|30||coding,fast,windows-local"
  "agent-windows-v1|engineering|1|60|1|claude-sonnet-4-6,fast,windows-local"
  "front-claw-winpc|institute|1|||claude-opus-4-8,claude-sonnet-4-6,claude-haiku-4-5,gpt-5.4,gpt-5.4-mini,gpt-5.6-sol,gpt-5.6-terra,gpt-5.6-luna,gemini-3.1-pro,gemini-2.5-flash,xai/grok-4.3-latest,grok-4.5,codestral,gemini-3.5-flash,local-gemma4-uncensored,local-qwen3.5-4b"
  "intake-app|engineering|1|60|1|intake-extract"
)

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
  api GET "/team/list" 2>/dev/null \
    | jq -e --arg t "$team_id" '
        (if type == "object" and has("teams") then .teams else . end)[]?
        | select(.team_id == $t)
      ' >/dev/null 2>&1
}

key_alias_exists() {
  local alias="$1"
  api GET "/key/list?return_full_object=true&size=100" 2>/dev/null \
    | jq -e --arg a "$alias" '
        (if type == "object" and has("keys") then .keys else . end)[]?
        | select(.key_alias == $a)
      ' >/dev/null 2>&1
}

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
    --argjson mb "$max_budget" \
    --argjson rpm "$rpm_limit" \
    '{
       team_id: $id,
       team_alias: $alias,
       max_budget: $mb,
       budget_duration: "1mo",
       rpm_limit: $rpm,
       metadata: {source: "provision-keys.sh", version: "2.0.0"}
     }')"
  if ! api POST "/team/new" "$body" >/dev/null; then
    echo "    [FAIL] team $team_id creation failed" >&2
    exit 1
  fi
  printf "    [created] %-12s (\$%s/mo, %s rpm)\n" "$team_id" "$max_budget" "$rpm_limit"
done

echo "==> Provisioning keys..."
umask 077
tmp_out="${OUT_FILE}.tmp"
{
  echo "# =============================================================================="
  echo "# PRAXEN — LiteLLM Virtual Keys"
  echo "# Generated: $(date -u +%FT%TZ)"
  echo "# Source: provision-keys.sh v2.0.0 (reconciled to live DB 2026-06-20)"
  echo "# DO NOT COMMIT. chmod 600 enforced."
  echo "# Rotate by deleting via /key/delete then re-running this script."
  echo "# =============================================================================="
  echo ""
} > "$tmp_out"

minted=0
skipped=0
for spec in "${KEYS[@]}"; do
  IFS='|' read -r alias team_id max_budget rpm_limit soft_budget models_csv <<< "$spec"
  env_name="VKEY_$(echo "$alias" | tr '[:lower:]-' '[:upper:]_')"

  if key_alias_exists "$alias"; then
    printf "    [skip]    %-22s (exists — rotate manually)\n" "$alias"
    echo "# $env_name=     # already in LiteLLM DB; rotate via /key/delete to regenerate" >> "$tmp_out"
    skipped=$((skipped + 1))
    continue
  fi

  if [[ -n "$models_csv" ]]; then
    models_json="$(jq -nc --arg s "$models_csv" '$s | split(",")')"
  else
    models_json="[]"
  fi

  body="$(jq -nc \
    --arg alias "$alias" \
    --arg team "$team_id" \
    --argjson mb "$max_budget" \
    --arg rpm "$rpm_limit" \
    --argjson models "$models_json" \
    --arg soft "$soft_budget" \
    '{
       key_alias: $alias,
       team_id: $team,
       max_budget: $mb,
       budget_duration: "1mo",
       metadata: {source: "provision-keys.sh", version: "2.0.0", created: (now | todate)}
     }
     + (if $rpm   != "" then {rpm_limit: ($rpm | tonumber)} else {} end)
     + (if ($models | length) > 0 then {models: $models} else {} end)
     + (if $soft  != "" then {soft_budget: ($soft | tonumber)} else {} end)')"

  response="$(api POST "/key/generate" "$body")"
  token="$(echo "$response" | jq -r '.key // empty')"
  if [[ -z "$token" ]]; then
    echo "    [FAIL] $alias — no .key in response" >&2
    echo "$response" | jq . >&2 || echo "$response" >&2
    exit 1
  fi

  echo "$env_name=$token" >> "$tmp_out"
  printf "    [created] %-22s team=%-12s \$%s/mo" "$alias" "$team_id" "$max_budget"
  [[ -n "$rpm_limit"  ]] && printf ", %s rpm" "$rpm_limit"
  [[ -n "$soft_budget" ]] && printf ", soft=\$%s" "$soft_budget"
  printf "\n"
  minted=$((minted + 1))
done

mv "$tmp_out" "$OUT_FILE"
chmod 600 "$OUT_FILE"

echo ""
echo "==> Done. minted=$minted, skipped=$skipped"
echo "==> Tokens written to $OUT_FILE (chmod 600)"
echo "==> CONFIRM .gitignore covers both .env AND .virtual-keys.env before next push"
