# =============================================================================
# LiteLLM tag-lock image
#
# This wrapper exists so the upstream image is pinned in exactly ONE place and the
# build context is available for future additions. Bump the FROM line to move.
# Rollback is NOT a tag revert alone: LiteLLM runs Prisma migrations forward on
# first boot and (since v1.92.0) re-encrypts stored credentials, so take a
# pg_dump BEFORE every bump and restore it alongside the FROM revert.
# =============================================================================
# Pin by digest, never by tag alone. On 2026-10-21 LiteLLM's release pipeline
# published a backdoored v1.107.0 and repointed latest, main-latest and
# main-stable. A tag can be repointed; a digest cannot.
# v1.106.6 is the version the reference deployment runs. It includes the fix for
# GHSA-w4c7-34wj-hqm8 and the fix for v1.106.5's gzip slowdown, and it is signed
# with the post-incident key.
FROM ghcr.io/berriai/litellm:v1.108.0@sha256:c560d317136880ea92d62334d4367ab10955b1af189dd3ea24f6551290b1d6c1

# hiredis 3.4.0 (still bundled in this tag) has an open segfault after Redis read
# timeouts, fixed in 3.4.1 which the tag does not ship; removing it makes
# redis-py fall back to its pure-Python parser (no package install, no network).
# Remove this step once the upstream tag ships hiredis >= 3.4.1.
# Verify after boot: `python -c "import hiredis"` inside the container must FAIL.
RUN rm -rf /app/.venv/lib/python3.13/site-packages/hiredis \
           /app/.venv/lib/python3.13/site-packages/hiredis-*.dist-info
