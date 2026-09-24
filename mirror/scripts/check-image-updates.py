#!/usr/bin/env python3
"""
check-image-updates.py — report which pinned images are behind upstream. REPORTS ONLY.

WHY THIS EXISTS (OP VERSION-TRUEUP, 2026-08-05):
  Every image in this stack is pinned to an exact tag, deliberately. The alternative —
  floating tags like `postgres:16-alpine` — does NOT keep you patched: Docker only
  re-resolves a moving tag on an explicit `docker pull`, and `compose up -d` reuses the
  local image. Nothing here pulls on a schedule. Proof: redis sat on floating `7-alpine`
  and was STILL on 7.4.9 while 7.4.10 was published upstream. Floating bought
  nondeterministic update timing and no rollback target, and delivered no patches.
  So: pin everything, and automate the CHECK instead of the pull.

DELIBERATELY DOES NOT APPLY ANYTHING. A database engine must not silently restart
itself, and a LiteLLM bump walks Prisma migrations forward (needs a pg_dump rung first).
This prints what is available; bumping stays a decision.

USAGE
  python scripts/check-image-updates.py            # human-readable table
  python scripts/check-image-updates.py --json     # machine-readable
Exit code is 0 even when things are behind — this is a report, not a test, and a
non-zero exit would make a scheduled run look like a failure.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker-compose.yml"
LITELLM_DOCKERFILE = ROOT / "litellm" / "Dockerfile"
UA = {"User-Agent": "praxen-image-audit"}

# Services that are profile-gated and have never been brought up — real, but low
# priority, so they are reported separately rather than padding the actionable list.
NEVER_RUN = {"qdrant", "n8n", "tailscale"}

# Per-image policy. `line` pins the comparison to a version line so we never report a
# MAJOR jump as "behind": crossing postgres 16->17 needs dump/restore, not a tag edit,
# and redis 7->8 is likewise a migration decision, not a patch.
POLICY = {
    "postgres": {"line": r"^16\.", "major_warn": "MAJOR upgrade needs dump/restore, NOT a tag edit"},
    "redis":    {"line": r"^7\.",  "major_warn": "8.x is a major jump — evaluate separately"},
    # tempo is pinned to the 2.10 line (2.9 -> 2.10 executed 2026-09-10; 2.10 is the LAST 2.x minor, patched to 2027-04-26): the standing rule forbids a minor/major move without a
    # block-schema re-eval, so 3.x must surface as "major exists", never as "newer in line".
    # With line=None (2026-08-05 .. 2026-09-09) the checker reported 3.0.3 as in-line and HID
    # the 2.9.5 patch that was actually actionable.
    "tempo":    {"line": r"^2\.10\.", "major_warn": "3.x is a config REWRITE (ingester/compactor/local_blocks removed, no downgrade) — gated op, target 3.1"},
}

# 2- OR 3-component: postgres ships `16.14`, not `16.14.0`. Demanding three silently
# demoted every postgres tag to "MANUAL" and hid whether we were patched.
SEMVER = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?")
# A trailing build hash (searxng's `2026.5.21-d3deacc6d`) is NOT a variant like `-alpine`.
# Treating it as one made every searxng tag incomparable, so a 3-month-old pin reported
# CURRENT. A checker that under-reports is worse than no checker.
HASH_SUFFIX = re.compile(r"^-[0-9a-f]{7,}$")


def shape_of(tag):
    """Variant suffix used to compare like with like (`-alpine` vs bare), hash stripped."""
    m = SEMVER.match(tag)
    if not m:
        return None
    suf = tag[m.end():]
    return "" if HASH_SUFFIX.match(suf) else suf


def http_json(url, timeout=30):
    try:
        return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as e:
        return {"_err": f"{type(e).__name__}: {str(e)[:60]}"}


def parse_pins():
    """Read active `image:` lines from compose plus the LiteLLM base from its Dockerfile.

    The LiteLLM pin does NOT live in compose — that service builds a local tag-lock
    wrapper image, so compose shows `praxen-litellm-proxy` and the real version is the
    Dockerfile FROM. Missing that is an easy way to audit the stack and never notice
    the single most important version in it.
    """
    pins = []
    for raw in COMPOSE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or not line.startswith("image:"):
            continue
        ref = line.split("image:", 1)[1].split("#")[0].strip()
        if "/" not in ref and ":" not in ref:
            continue
        pins.append(ref)
    if LITELLM_DOCKERFILE.exists():
        for raw in LITELLM_DOCKERFILE.read_text(encoding="utf-8").splitlines():
            if raw.strip().startswith("FROM "):
                pins.append(raw.strip().split()[1])
    # de-dup, preserve order
    seen, out = set(), []
    for p in pins:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def split_ref(ref):
    repo, _, tag = ref.rpartition(":")
    if not repo:
        repo, tag = ref, "latest"
    return repo, tag


def upstream_tags(repo):
    """Newest-first tag list. ghcr.io/berriai/litellm has no public tag list API, so it
    goes through GitHub releases instead."""
    if repo.startswith("ghcr.io/berriai/litellm"):
        out = []
        for page in (1, 2):
            d = http_json(f"https://api.github.com/repos/BerriAI/litellm/releases?per_page=100&page={page}")
            if isinstance(d, dict) and "_err" in d:
                return d
            out += [r["tag_name"] for r in d]
        # drop pre-releases — we only ever pin the stable line
        return [t for t in out if not re.search(r"(dev|rc|nightly|stable)", t)]
    ns, _, name = repo.partition("/")
    if not name:
        ns, name = "library", ns
    tags = []
    for page in (1, 2):
        d = http_json(f"https://hub.docker.com/v2/repositories/{ns}/{name}/tags?page_size=100&page={page}&ordering=last_updated")
        if isinstance(d, dict) and "_err" in d:
            return d if page == 1 else tags
        tags += [t["name"] for t in d.get("results", [])]
    return tags


def key_of(tag):
    m = SEMVER.match(tag)
    if not m:
        return None
    return tuple(int(x) if x else 0 for x in m.groups())


def assess(ref):
    repo, tag = split_ref(ref)
    short = repo.split("/")[-1]
    pol = POLICY.get(short, {})
    tags = upstream_tags(repo)
    if isinstance(tags, dict):
        return {"image": repo, "current": tag, "status": "ERROR", "detail": tags["_err"], "newer": []}

    cur = key_of(tag)
    if cur is None:
        # date-based (searxng) or otherwise unparseable — report newest seen, judge by eye
        newest = [t for t in tags if t != "latest"][:3]
        return {"image": repo, "current": tag, "status": "MANUAL",
                "detail": "non-semver tag; newest upstream: " + ", ".join(newest), "newer": newest}

    # Compare only within the same shape as our pin (e.g. `-alpine` variants stay with
    # `-alpine`), otherwise `16.14-alpine` would be judged against bare `17.2`.
    suffix = shape_of(tag)
    same_shape = [t for t in tags if key_of(t) and shape_of(t) == suffix]

    line = pol.get("line")
    in_line = [t for t in same_shape if (not line or re.match(line, t.lstrip("v")))]
    newer = sorted({t for t in in_line if key_of(t) > cur}, key=key_of, reverse=True)
    # A newer MAJOR is information, never "behind" — crossing it is a migration.
    cross = sorted({t for t in same_shape if key_of(t)[0] > cur[0]}, key=key_of, reverse=True)

    status = "BEHIND" if newer else "CURRENT"
    detail = ""
    if newer:
        detail = f"{len(newer)} newer in line -> {newer[0]}"
    if cross and pol.get("major_warn"):
        detail += (" | " if detail else "") + f"major {cross[0]} exists: {pol['major_warn']}"
    return {"image": repo, "current": tag, "status": status, "detail": detail, "newer": newer[:5]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    results = [assess(ref) for ref in parse_pins()]
    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    def bucket(r):
        return any(n in r["image"] for n in NEVER_RUN)

    live = [r for r in results if not bucket(r)]
    parked = [r for r in results if bucket(r)]

    print(f"\nPRAXEN image audit — {len(results)} pins  (REPORT ONLY, nothing applied)\n")
    print(f"  {'IMAGE':<38} {'PINNED':<24} {'STATUS':<8} DETAIL")
    print("  " + "-" * 112)
    for r in sorted(live, key=lambda x: (x["status"] != "BEHIND", x["image"])):
        print(f"  {r['image']:<38} {r['current']:<24} {r['status']:<8} {r['detail']}")
    if parked:
        print("\n  -- profile-gated / never-run (low priority) --")
        for r in sorted(parked, key=lambda x: x["image"]):
            print(f"  {r['image']:<38} {r['current']:<24} {r['status']:<8} {r['detail']}")

    behind = [r for r in live if r["status"] == "BEHIND"]
    print(f"\n  {len(behind)} live image(s) behind; {sum(1 for r in live if r['status']=='CURRENT')} current.")
    if behind:
        print("  Bump deliberately — and for litellm take the pg_dump rung FIRST (Prisma")
        print("  migrates forward on boot; since v1.92.0 credentials are re-encrypted, so a")
        print("  tag revert alone is NOT a rollback).")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
