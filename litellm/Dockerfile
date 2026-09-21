# =============================================================================
# LiteLLM tag-lock image
#
# This wrapper exists so the upstream tag is pinned in exactly ONE place and the
# build context is available for future additions. Bump the FROM line to move.
# Rollback is NOT a tag revert alone: LiteLLM runs Prisma migrations forward on
# first boot and (since v1.92.0) re-encrypts stored credentials, so take a
# pg_dump BEFORE every bump and restore it alongside the FROM revert.
# =============================================================================
# v1.100.1 is a one-fix stable patch on v1.100.0: the router kept retry breadcrumbs
# shared across requests and nested, so retry-heavy load leaked memory until the
# proxy was OOM-killed - relevant here with retries and deep fallback chains in a
# 1G container. No schema or migration change against v1.100.0, so for THIS step a
# tag revert is a complete rollback; the pg_dump rule above still governs every
# other bump.
FROM ghcr.io/berriai/litellm:v1.102.0

# hiredis 3.4.0 (still bundled in this tag) has an open segfault after Redis read
# timeouts, fixed in 3.4.1 which the tag does not ship; removing it makes
# redis-py fall back to its pure-Python parser (no package install, no network).
# Remove this step once the upstream tag ships hiredis >= 3.4.1.
# Verify after boot: `python -c "import hiredis"` inside the container must FAIL.
RUN rm -rf /app/.venv/lib/python3.13/site-packages/hiredis \
           /app/.venv/lib/python3.13/site-packages/hiredis-*.dist-info
