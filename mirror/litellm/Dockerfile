# =============================================================================
# PRAXEN — LiteLLM Tag-Lock Image
# Base: v1.106.5 (2026-10-28), pinned by OCI index digest; prior: v1.106.3 (2026-10-24).
# Tag format: bare v1.x.y tags are the stable line; -rc.N / -dev.N are pre-releases.
# Pin by digest since 2026-10-24: LiteLLM's release pipeline published a backdoored v1.107.0 (and repointed `latest`,
# `main-latest`, `main-stable`) on 2026-10-21. A digest cannot be repointed; a tag can. Never float a tag.
# Rollback rule: revert the FROM line AND restore the pg_dump rung taken before the bump. Prisma migrates the DB forward on
# first boot and credentials are re-encrypted since v1.92.0, so a tag revert alone is never a rollback.
# hiredis: every tag since v1.100.0 (v1.106.3 included) ships hiredis 3.4.0, which carries an open segfault report
# (BerriAI/litellm#39767, exit 139 after Redis read timeouts; fixed in 3.4.1). The RUN below removes it so redis-py uses its
# pure-Python parser. Reversal trigger: delete the RUN once a tag ships hiredis >= 3.4.1. Verify post-boot: `docker exec
# praxen-litellm python -c "import hiredis"` must FAIL with ModuleNotFoundError. History before v1.106.0: git log.
# =============================================================================
# CURRENT: v1.106.3 -> v1.106.5 on 2026-10-28 (the operator: "pushed to v1.106.5 after we check to make sure it's secure"). Fixes
# GHSA-w4c7-34wj-hqm8 (CVSS 10; unauthenticated GCS-logger file read + exfil on Enterprise-LICENSED proxies only; this proxy
# is unlicensed, LITELLM_LICENSE unset, no GCS callback, so it was never exposed). v1.106.4: remote cost-map boot ImportError
# fix, emSign ECC root removed. 0 migrations; no hook API changed (16 commits, 27 files). Supply chain: index digest below; tag
# commit 2569eb88 = image revision label = SLSA git_ref; signature verified by hand (ECDSA-P256 against cosign.pub sha256
# e3fe3e08...c2c0, the post-incident key; cosign itself not installed). Offline scan before first run: litellm-1.106.5.dist-info
# only, the same three .pth hooks, no sitecustomize, no cook.pth / 1.107.0 dist-info / loader lock. Not staged on :4001
# (0 migrations: the rung + a FROM revert is a complete rollback). Evidence: deliverables/evidence/2026-10-28-op-litellm-v1065/.
# ROLLBACK: FROM the v1.106.3 line below (image praxen-litellm-proxy:v1.106.3-rollback) AND restore
# backup/db/litellm-db.bak.pre-v1.106.5.sql.
# PRIOR: v1.106.0 -> v1.106.3 on 2026-10-24: first post-compromise release (new cosign key, eMudhra root removed), 0
# migrations, staged on :4001 first (deliverables/evidence/2026-10-24-op-litellm-v1063/);
# FROM ghcr.io/berriai/litellm:v1.106.3@sha256:74d0696a9f0afcc993c7659d246f0c542f003368298633e852228250779f1032
# =============================================================================
FROM ghcr.io/berriai/litellm:v1.106.5@sha256:7d6ae6c8d73d1b6aea4cb75d07c4a8a953f0809b0764522b8eab693734c5e905
RUN rm -rf /app/.venv/lib/python3.13/site-packages/hiredis \
           /app/.venv/lib/python3.13/site-packages/hiredis-*.dist-info
