#!/usr/bin/env python3
"""
check-image-updates.py -- report which pinned container images are behind upstream.
REPORTS ONLY. Never pulls, never edits compose, never restarts anything.

WHY PIN EVERYTHING
  Every image in this stack is pinned to an exact tag, on purpose. A floating tag such
  as `postgres:16-alpine` does NOT keep you patched: Docker re-resolves a moving tag only
  on an explicit `docker pull`, and `docker compose up -d` reuses whatever image is
  already local. Nothing in a typical home-lab pulls on a schedule, so a floating pin
  buys nondeterministic update timing and no rollback target while delivering no
  patches. Pin the exact version, and automate the CHECK instead of the pull.

WHY REPORT-ONLY
  A database engine must not restart itself because a script saw a newer tag, and a
  LiteLLM bump walks Prisma migrations forward on first boot (take a pg_dump first --
  newer lines also re-encrypt stored credentials, so a tag revert alone is not a
  rollback). Bumping stays a human decision; this script only tells you what exists.

WHAT IT READS
  * every active `image:` line in docker-compose.yml
  * the `FROM` line of litellm/Dockerfile -- the LiteLLM pin does NOT live in compose
    because that service builds a small local wrapper image, so auditing compose alone
    misses the single most important version in the stack.

USAGE
  python scripts/check-image-updates.py                    # human-readable table
  python scripts/check-image-updates.py --json             # machine-readable
  python scripts/check-image-updates.py --github-summary   # also write a markdown table
                                                           # to $GITHUB_STEP_SUMMARY
  python scripts/check-image-updates.py --compose PATH --dockerfile PATH
                                                           # audit another tree

Exit code is 0 even when images are behind -- this is a report, not a test, and a
non-zero exit would make a scheduled run look like an outage.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COMPOSE = ROOT / "docker-compose.yml"
DEFAULT_DOCKERFILE = ROOT / "litellm" / "Dockerfile"
UA = {"User-Agent": "compose-image-audit"}

# Services that are profile-gated and never brought up in normal operation. They are
# real pins, but reporting them beside the live tier would pad the actionable list.
DEFAULT_PARKED = "qdrant,n8n"

# Per-image policy. `line` pins the comparison to a version line so a MAJOR jump is
# never reported as "behind": postgres 16->17 needs dump/restore, not a tag edit, and
# redis 7->8 is likewise a migration decision rather than a patch.
POLICY = {
    "postgres": {"line": r"^16\.", "major_warn": "MAJOR upgrade needs dump/restore, NOT a tag edit"},
    "redis":    {"line": r"^7\.",  "major_warn": "8.x is a major jump -- evaluate separately"},
    # tempo is held to the 2.10 line (the last 2.x minor): 3.x removes config sections
    # this stack's tempo-config.yaml relies on and has no downgrade path, so a move past
    # 2.10 is a config rewrite. Without a line policy the checker reported 3.x as
    # in-line and HID the 2.x patch that was actually actionable.
    "tempo":    {"line": r"^2\.10\.", "major_warn": "3.x is a config rewrite (ingester/compactor/local_blocks removed, no downgrade) - gated op"},
}

# 2- OR 3-component versions: postgres ships `16.14`, not `16.14.0`. Demanding three
# components silently demotes every postgres tag to MANUAL and hides patch status.
SEMVER = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?")
# A trailing build hash (searxng's `2026.5.21-d3deacc6d`) is NOT a variant like
# `-alpine`. Treating it as one makes every searxng tag incomparable, so a months-old
# pin reports CURRENT. A checker that under-reports is worse than no checker.
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


def parse_pins(compose, dockerfile):
    """Read active `image:` lines from compose plus the LiteLLM base from its Dockerfile."""
    pins = []
    for raw in compose.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or not line.startswith("image:"):
            continue
        ref = line.split("image:", 1)[1].split("#")[0].strip().strip('"').strip("'")
        if "/" not in ref and ":" not in ref:
            continue
        pins.append(ref)
    if dockerfile and dockerfile.exists():
        for raw in dockerfile.read_text(encoding="utf-8").splitlines():
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
    if not repo or "/" in tag:
        # no tag at all (rpartition split on a registry port or nothing)
        repo, tag = ref, "latest"
    return repo, tag


def upstream_tags(repo):
    """Newest-first tag list. ghcr.io/berriai/litellm has no public tag-list API, so it
    goes through GitHub releases instead."""
    if repo.startswith("ghcr.io/berriai/litellm"):
        out = []
        for page in (1, 2):
            d = http_json(f"https://api.github.com/repos/BerriAI/litellm/releases?per_page=100&page={page}")
            if isinstance(d, dict) and "_err" in d:
                return d
            out += [r["tag_name"] for r in d]
        # drop pre-releases -- only the stable line is ever pinned here
        return [t for t in out if not re.search(r"(dev|rc|nightly|stable)", t)]
    if repo.startswith("ghcr.io/") or repo.count("/") > 1 and not repo.startswith("docker.io/"):
        return {"_err": "no public tag API for this registry"}
    repo = repo.replace("docker.io/", "", 1)
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
        # non-semver tags only -- report newest seen, judge by eye
        newest = [t for t in tags if t != "latest"][:3]
        return {"image": repo, "current": tag, "status": "MANUAL",
                "detail": "non-semver tag; newest upstream: " + ", ".join(newest), "newer": newest}

    # Compare only within the same shape as the pin (`-alpine` stays with `-alpine`),
    # otherwise `16.14-alpine` would be judged against bare `17.2`.
    suffix = shape_of(tag)
    same_shape = [t for t in tags if key_of(t) and shape_of(t) == suffix]

    line = pol.get("line")
    in_line = [t for t in same_shape if (not line or re.match(line, t.lstrip("v")))]
    newer = sorted({t for t in in_line if key_of(t) > cur}, key=key_of, reverse=True)
    # A newer MAJOR is information, never "behind" -- crossing it is a migration.
    cross = sorted({t for t in same_shape if key_of(t)[0] > cur[0]}, key=key_of, reverse=True)

    status = "BEHIND" if newer else "CURRENT"
    detail = ""
    if newer:
        detail = f"{len(newer)} newer in line -> {newer[0]}"
    if cross and pol.get("major_warn"):
        detail += (" | " if detail else "") + f"major {cross[0]} exists: {pol['major_warn']}"
    return {"image": repo, "current": tag, "status": status, "detail": detail, "newer": newer[:5]}


def markdown_table(live, parked):
    rows = ["| Image | Pinned | Status | Detail |", "|---|---|---|---|"]
    for r in sorted(live, key=lambda x: (x["status"] != "BEHIND", x["image"])):
        rows.append(f"| `{r['image']}` | `{r['current']}` | {r['status']} | {r['detail'] or '-'} |")
    if parked:
        rows.append("| _profile-gated / never-run_ | | | |")
        for r in sorted(parked, key=lambda x: x["image"]):
            rows.append(f"| `{r['image']}` | `{r['current']}` | {r['status']} | {r['detail'] or '-'} |")
    behind = sum(1 for r in live if r["status"] == "BEHIND")
    head = f"## Image audit: {behind} live image(s) behind ({len(live) + len(parked)} pins, report only)\n"
    return head + "\n" + "\n".join(rows) + "\n"


def main():
    ap = argparse.ArgumentParser(description="Report pinned images that are behind upstream. Applies nothing.")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--github-summary", action="store_true",
                    help="write a markdown table to the file named by $GITHUB_STEP_SUMMARY (stdout if unset)")
    ap.add_argument("--compose", default=str(DEFAULT_COMPOSE), help="docker-compose.yml to audit")
    ap.add_argument("--dockerfile", default=str(DEFAULT_DOCKERFILE),
                    help="Dockerfile whose FROM line carries the LiteLLM pin (skipped if missing)")
    ap.add_argument("--parked", default=DEFAULT_PARKED,
                    help="comma-separated image-name fragments to report as profile-gated / never-run")
    args = ap.parse_args()

    compose = Path(args.compose)
    if not compose.exists():
        print(f"compose file not found: {compose}", file=sys.stderr)
        return 2
    dockerfile = Path(args.dockerfile) if args.dockerfile else None
    parked_names = {p.strip() for p in args.parked.split(",") if p.strip()}

    results = [assess(ref) for ref in parse_pins(compose, dockerfile)]

    def is_parked(r):
        return any(n in r["image"] for n in parked_names)

    for r in results:
        r["parked"] = is_parked(r)   # --json consumers can filter profile-gated pins out of "behind" counts
    live = [r for r in results if not is_parked(r)]
    parked = [r for r in results if is_parked(r)]

    if args.github_summary:
        md = markdown_table(live, parked)
        target = os.environ.get("GITHUB_STEP_SUMMARY")
        if target:
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(md)
        else:
            print(md)

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    print(f"\nImage audit -- {len(results)} pins  (REPORT ONLY, nothing applied)\n")
    print(f"  {'IMAGE':<38} {'PINNED':<24} {'STATUS':<8} DETAIL")
    print("  " + "-" * 112)
    for r in sorted(live, key=lambda x: (x["status"] != "BEHIND", x["image"])):
        print(f"  {r['image']:<38} {r['current']:<24} {r['status']:<8} {r['detail']}")
    if parked:
        print("\n  -- profile-gated / never-run (low priority) --")
        for r in sorted(parked, key=lambda x: x["image"]):
            print(f"  {r['image']:<38} {r['current']:<24} {r['status']:<8} {r['detail']}")

    behind = [r for r in live if r["status"] == "BEHIND"]
    print(f"\n  {len(behind)} live image(s) behind; {sum(1 for r in live if r['status'] == 'CURRENT')} current.")
    if behind:
        print("  Bump deliberately -- and for litellm take the pg_dump rung FIRST (Prisma")
        print("  migrates forward on boot and newer lines re-encrypt stored credentials, so")
        print("  a tag revert alone is NOT a rollback).")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
