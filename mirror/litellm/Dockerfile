# =============================================================================
# PRAXEN — LiteLLM Tag-Lock Image
# Base: v1.100.0 (OP CURRENCY-SWEEP 2026-09-09; prior: v1.95.0 OP VERSION-TRUEUP 2026-08-05; v1.86.3 Phase Coder 2026-06-03)
# NOTE on tag format: upstream retired -stable/-stable.patch suffixes at
# v1.84.0 (PEP-440 SemVer — weekly MINOR bumps, PATCH = hotfix). Bare
# v1.8x.y / v1.1xx.y tags ARE the load-tested stable line now.
# Rollback: revert the FROM line + restore backup/db/litellm-db.bak.pre-v1.100.0.sql
# (Prisma migrates the DB forward on first boot — tag revert alone is NOT
# a complete rollback). EXTRA REASON as of v1.92.0: at-rest credential
# encryption moved to AES-256-GCM with a versioned format and a re-encryption
# migration, so stored credentials are REWRITTEN — a tag revert against a
# migrated DB is not merely incomplete, it is unsupported.
#
# BUMPED v1.95.0 -> v1.100.0 on 2026-09-09 (OP CURRENCY-SWEEP, the operator "update as needed").
# 9 stable releases (v1.95.1 … v1.100.0); 20 Prisma migrations apply on first
# boot (141 -> 161), ALL additive (CREATE TABLE/ADD COLUMN IF NOT EXISTS; the only
# non-additive statements touch the brand-new, empty LiteLLM_ShadowEvalJob table).
# REASON TO MOVE — CVE-2026-84377 / GHSA-3cv6-jpf6-8222 (Medium 6.5, published
# 2026-08-26): "Any authenticated LiteLLM proxy user could redirect an outbound
# provider call to a destination they control and cause the proxy to send its own
# configured provider credentials to that destination." v1.95.0 is in the affected
# set; patched at 1.95.1 / 1.96.2 and carried forward. "Authenticated user" here
# means ANY virtual-key holder — i.e. every app behind the allowlist-free
# front-gateway-winpc key. Also in-window: wolfi-base refreshes (openssl 3.6.3-r5,
# glibc 2.44), sqlparse 0.6.0, cryptography 50.0.0.
# BEHAVIOUR CHANGES VERIFIED AGAINST THIS CONFIG (see handoffs/2026-09-09-op-currency-sweep.md):
#  - v1.99.0 routes the Anthropic ADVISOR sub-call through the proxy router. PROBED AT
#    CUTOVER (2026-09-09): NO metering change on this config — an advised call still logs
#    ONE SpendLogs row at executor rate on merged tokens (haiku $0.001057 exact), no advisor
#    row. The under-count caveat and Grafana panel 35 semantics are UNCHANGED. The
#    STREAM x ADVISED $0 hole (config v4.12.13) also persists on this tag.
#  - v1.100.0 validates complexity-router settings placement; both routers here nest
#    tiers under complexity_router_config and pass.
#  - hidden model_group_alias entries now resolve on explicit lookups but stay out of
#    GET /v1/models (net positive for the 8 hidden bare aliases).
#  - budget_duration parsing, /metrics auth gate, OTel, embedding routing: unchanged.
# NEW OPTIONAL ENV (not set): ENFORCE_PRISMA_MIGRATION_CHECK (default enforce — a
# failed migration now FAILS the boot loudly instead of limping), SMTP_TIMEOUT.
# hiredis 3.4.0 is NEW in this image (redis-py picks it up automatically) and carries
# an OPEN segfault report, BerriAI/litellm#39767 (exit 139 after Redis read timeouts;
# reporter confirms fixed in hiredis 3.4.1, which v1.100.0 does not ship). The RUN
# below REMOVES it so redis-py falls back to its pure-Python parser — no PyPI
# install, no network, no new code; only a native parser we do not need at this
# scale. Reversal trigger: delete the RUN line once an upstream tag ships hiredis
# >= 3.4.1. Verify post-boot: `docker exec praxen-litellm python -c "import hiredis"`
# must FAIL with ModuleNotFoundError.
# This wrapper exists to lock the upstream tag in one place and reserve the
# build context for future additions (ruflo OTel emitter deps, etc.).
# Slimmed in compose v1.6.0 (2026-05-24): removed mlflow pip install.
# =============================================================================
# v1.100.1 (2026-09-10, OP REPO-READY): stable patch, ONE fix — router retry-breadcrumb memory
# leak (per-request breadcrumbs capped at 4, proxy_server_request excluded). Relevant here:
# num_retries 3 + deep fallback chains in a 1 GiB container. NO schema/migration change
# (schema.prisma + 161-migration dir byte-identical to v1.100.0; litellm-proxy-extras 0.4.91
# both tags) — a tag revert is a complete rollback this time; pg_dump rung taken anyway:
# backup/db/litellm-db.bak.pre-v1.100.1.sql. Still ships hiredis 3.4.0 -> the RUN below stays.
FROM ghcr.io/berriai/litellm:v1.100.1
RUN rm -rf /app/.venv/lib/python3.13/site-packages/hiredis \
           /app/.venv/lib/python3.13/site-packages/hiredis-*.dist-info
