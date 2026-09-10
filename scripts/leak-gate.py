#!/usr/bin/env python3
"""
leak-gate.py -- BLOCKING leak gate for a public tree. Exit 1 on any hit, 0 when clean.

WHAT IT DOES
  * walks the tree (skipping .git and any --exclude-dir) and scans every text file line
    by line against scripts/leak-denylist.txt (plain substrings, case-insensitive; `re:`
    regex; `rei:` case-insensitive regex);
  * opens every zip-based archive (.zip .xlsx .xlsm .docx .pptx .odt .ods .odp .jar
    .whl .epub) and scans EVERY member at raw level, recursing into nested archives.
    This is the whole reason the gate exists as a script: private references have hidden
    inside xl/comments/*.xml and docProps/*.xml, invisible to a cell-value scan. Binary
    members (images, fonts) are scanned via their printable runs, `strings`-style;
  * flags dangerous FILE NAMES regardless of content: .env, .env.* (except .env.example),
    .virtual-keys.env (the provisioning script's token file), *.pem, *.key, id_rsa*;
  * prints `path:line  pattern` (or `archive!member:line  pattern`) for each hit and
    NEVER prints the matching text itself -- a CI log is public too.

EXCEPTIONS
  --allow FILE    one `path:pattern` per line, '#' comments. `path` is a glob against the
                  reported label (posix, relative to the root; use `archive!member` for
                  archive members). `pattern` is the denylist line verbatim, `FILENAME`
                  for a file-name rule, `TOO-LARGE` for an oversized file, or `*`.
  Exceptions are the only sanctioned way to make a scan pass. Never edit the denylist to
  quiet a hit.

USAGE
  python scripts/leak-gate.py                      # scan the repo root (parent of scripts/)
  python scripts/leak-gate.py PATH [--allow FILE]  # scan another tree
  python scripts/leak-gate.py --denylist a.txt --denylist private.txt   # layer lists
  python scripts/leak-gate.py --json               # machine-readable hits
  python scripts/leak-gate.py --self-test          # seeded-leak regression, exits 0/1
"""
import argparse
import fnmatch
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
DEFAULT_ROOT = HERE.parent
DEFAULT_DENYLIST = HERE / "leak-denylist.txt"

ARCHIVE_EXT = {".zip", ".xlsx", ".xlsm", ".docx", ".pptx", ".odt", ".ods", ".odp", ".jar", ".whl", ".epub"}
ALLOWED_ENV_NAMES = {".env.example"}
PRINTABLE_RUN = re.compile(rb"[\x20-\x7e]{8,}")
MAX_ARCHIVE_DEPTH = 4


# ----------------------------------------------------------------------------- patterns
class Pattern:
    __slots__ = ("raw", "kind", "needle", "rx")

    def __init__(self, raw):
        self.raw = raw
        if raw.startswith("rei:"):
            self.kind, self.needle, self.rx = "re", None, re.compile(raw[4:], re.I)
        elif raw.startswith("re:"):
            self.kind, self.needle, self.rx = "re", None, re.compile(raw[3:])
        else:
            self.kind, self.needle, self.rx = "sub", raw.lower(), None

    def hit(self, line):
        if self.kind == "sub":
            return self.needle in line.lower()
        return self.rx.search(line) is not None


def load_denylist(paths):
    pats = []
    for p in paths:
        for raw in Path(p).read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            # a trailing comment on a plain-substring line is stripped; regex lines are
            # taken verbatim to the end of the line (a '#' may be part of the expression)
            if not (line.startswith("re:") or line.startswith("rei:")) and " #" in line:
                line = line.split(" #", 1)[0].rstrip()
            pats.append(Pattern(line.strip()))
    return pats


def load_allow(path):
    rules = []
    if not path:
        return rules
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        p, pat = line.split(":", 1)
        rules.append((p.strip(), pat.strip()))
    return rules


def allowed(label, pattern, rules):
    return any(fnmatch.fnmatchcase(label, p) and (pat == "*" or pat == pattern) for p, pat in rules)


# ----------------------------------------------------------------------------- scanning
def filename_rule(name):
    low = name.lower()
    if low == ".env" or (low.startswith(".env.") and low not in ALLOWED_ENV_NAMES):
        return "FILENAME"
    if low.endswith(".virtual-keys.env") or low.startswith(".virtual-keys.env."):
        return "FILENAME"  # provision-keys.example.sh writes minted tokens here
    if low.endswith(".pem") or low.endswith(".key") or low.startswith("id_rsa"):
        return "FILENAME"
    return None


def looks_binary(data):
    head = data[:8192]
    return b"\x00" in head


def decode_text(data):
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def scan_text(text, label, patterns, hits):
    for lineno, line in enumerate(text.splitlines(), 1):
        for p in patterns:
            if p.hit(line):
                hits.append((label, str(lineno), p.raw))


def scan_binary(data, label, patterns, hits):
    """`strings`-style: scan printable ASCII runs so a leak inside a binary member (an
    embedded object, a font, an image with EXIF text) still surfaces."""
    for m in PRINTABLE_RUN.finditer(data):
        run = m.group().decode("ascii")
        for p in patterns:
            if p.hit(run):
                hits.append((label, f"bin@{m.start()}", p.raw))


def scan_bytes(data, label, patterns, hits, depth=0):
    """Dispatch: archive -> every member (recursively); text -> lines; binary -> runs."""
    ext = PurePosixPath(label.split("!")[-1]).suffix.lower()
    if ext in ARCHIVE_EXT or (depth > 0 and zipfile.is_zipfile(io.BytesIO(data))):
        if depth >= MAX_ARCHIVE_DEPTH:
            hits.append((label, "0", "ARCHIVE-TOO-DEEP"))
            return
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    member = f"{label}!{info.filename}"
                    try:
                        blob = zf.read(info)
                    except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
                        hits.append((member, "0", "UNREADABLE-MEMBER"))
                        continue
                    scan_bytes(blob, member, patterns, hits, depth + 1)
            return
        except zipfile.BadZipFile:
            if depth == 0:
                hits.append((label, "0", "UNREADABLE-ARCHIVE"))
            # fall through: scan whatever it is as raw content
    if looks_binary(data):
        scan_binary(data, label, patterns, hits)
    else:
        scan_text(decode_text(data), label, patterns, hits)


def scan_tree(root, patterns, exclude_dirs, skip_files, max_bytes):
    hits = []
    n_files = 0
    root = Path(root).resolve()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in exclude_dirs)
        for fn in sorted(filenames):
            full = Path(dirpath) / fn
            if full.resolve() in skip_files:
                continue
            label = full.relative_to(root).as_posix()
            n_files += 1
            rule = filename_rule(fn)
            if rule:
                hits.append((label, "0", rule))
            try:
                size = full.stat().st_size
            except OSError:
                hits.append((label, "0", "UNREADABLE-FILE"))
                continue
            if size == 0:
                continue
            if size > max_bytes:
                hits.append((label, "0", "TOO-LARGE"))
                continue
            try:
                data = full.read_bytes()
            except OSError:
                hits.append((label, "0", "UNREADABLE-FILE"))
                continue
            if fn.lower().endswith(tuple(ARCHIVE_EXT)) or not looks_binary(data):
                scan_bytes(data, label, patterns, hits)
            # a plain binary file on disk (png, gguf, ...) is judged by its name only;
            # archives are the exception because that is where leaks hide
    return hits, n_files


# ----------------------------------------------------------------------------- self-test
def self_test():
    """Seed a temp tree with leaks in every place the gate must look; assert each is caught
    and that an allow entry suppresses exactly one. The seeded strings are assembled at
    runtime so this source file never contains a denylisted shape itself."""
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
        ok = ok and cond

    term = "test" + "leak" + "term"
    key_shape = "sk" + "-" + "SELFTEST" + "0123456789"          # matches the key regex
    deny_text = "\n".join([
        "# self-test denylist",
        term,
        "re:sk" + "-[A-Za-z0-9_-]{8,}",
        "",
    ])
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "docs").mkdir()
        (t / "docs" / "note.md").write_text(f"clean line\nmentions {term.upper()} here\n", encoding="utf-8")
        (t / "docs" / "clean.md").write_text("nothing to see\n", encoding="utf-8")
        (t / ".env").write_text("X=1\n", encoding="utf-8")
        (t / ".env.example").write_text("X=\n", encoding="utf-8")
        (t / ".virtual-keys.env").write_text("X=1\n", encoding="utf-8")
        (t / "keys").mkdir()
        (t / "keys" / "id_rsa").write_text("not really\n", encoding="utf-8")
        (t / ".git").mkdir()
        (t / ".git" / "config").write_text(f"{term}\n", encoding="utf-8")  # must be skipped
        # xlsx-shaped zip: leak lives in the comments part, cells are clean
        with zipfile.ZipFile(t / "docs" / "book.xlsx", "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("xl/worksheets/sheet1.xml", "<sheet><c><v>42</v></c></sheet>")
            zf.writestr("xl/comments/comment1.xml", f"<comments><t>see {key_shape}</t></comments>")
            zf.writestr("xl/media/image1.png", b"\x89PNG\x00\x00binary" + b"\x00" * 16 + f"EXIF {term} tag".encode() + b"\x00")
        # nested: zip -> docx -> word/comments.xml
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as zf:
            zf.writestr("word/document.xml", "<w:document/>")
            zf.writestr("word/comments.xml", f"<w:comment>{term}</w:comment>")
        with zipfile.ZipFile(t / "bundle.zip", "w") as zf:
            zf.writestr("inner.docx", inner.getvalue())
        deny = t / "deny.txt"
        deny.write_text(deny_text, encoding="utf-8")
        allow = t / "allow.txt"
        allow.write_text(f"docs/note.md:{term}\n", encoding="utf-8")

        pats = load_denylist([deny])
        hits, _ = scan_tree(t, pats, {".git"}, {deny.resolve(), allow.resolve()}, 256 * 1024 * 1024)
        labels = {(h[0], h[2]) for h in hits}

        check(("docs/note.md", term) in labels, "plain text substring (case-insensitive) caught")
        check(("docs/book.xlsx!xl/comments/comment1.xml", "re:sk" + "-[A-Za-z0-9_-]{8,}") in labels,
              "secret shape inside xlsx comments part caught (archive!member)")
        check(("docs/book.xlsx!xl/media/image1.png", term) in labels, "leak inside a binary archive member caught")
        check(("bundle.zip!inner.docx!word/comments.xml", term) in labels, "nested archive (zip -> docx) caught")
        check((".env", "FILENAME") in labels, ".env flagged by name")
        check(("keys/id_rsa", "FILENAME") in labels, "id_rsa flagged by name")
        check((".virtual-keys.env", "FILENAME") in labels, ".virtual-keys.env (provisioning token file) flagged by name")
        check(not any(h[0] == ".env.example" for h in hits), ".env.example NOT flagged")
        check(not any(h[0].startswith(".git/") for h in hits), ".git skipped")
        check(not any(h[0] == "docs/clean.md" for h in hits), "clean file produces no hit")
        rules = load_allow(allow)
        remaining = [h for h in hits if not allowed(h[0], h[2], rules)]
        check(len(remaining) == len(hits) - 1, "allow entry suppresses exactly one hit")
        check(all(len(h) == 3 for h in hits), "hit tuples well-formed")
    print(f"\n  self-test {'PASSED' if ok else 'FAILED'}")
    return 0 if ok else 1


# ----------------------------------------------------------------------------- main
def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="Blocking leak gate for a public tree. Exit 1 on any hit.")
    ap.add_argument("root", nargs="?", default=str(DEFAULT_ROOT), help="tree to scan (default: repo root)")
    ap.add_argument("--denylist", action="append", default=None,
                    help="pattern file(s); default scripts/leak-denylist.txt; repeatable to layer lists")
    ap.add_argument("--allow", default=None, help="exception file, one path:pattern per line")
    ap.add_argument("--exclude-dir", action="append", default=[".git"], help="directory names to skip (repeatable)")
    ap.add_argument("--max-bytes", type=int, default=256 * 1024 * 1024,
                    help="files larger than this are reported as TOO-LARGE instead of scanned")
    ap.add_argument("--json", action="store_true", help="machine-readable hits")
    ap.add_argument("--self-test", action="store_true", help="run the seeded-leak regression and exit")
    a = ap.parse_args()

    if a.self_test:
        return self_test()

    deny_paths = [Path(p) for p in (a.denylist or [DEFAULT_DENYLIST])]
    for p in deny_paths:
        if not p.exists():
            print(f"denylist not found: {p}", file=sys.stderr)
            return 2
    patterns = load_denylist(deny_paths)
    rules = load_allow(a.allow)
    skip = {p.resolve() for p in deny_paths}
    if a.allow:
        skip.add(Path(a.allow).resolve())

    root = Path(a.root).resolve()
    hits, n_files = scan_tree(root, patterns, set(a.exclude_dir), skip, a.max_bytes)
    kept = [h for h in hits if not allowed(h[0], h[2], rules)]
    n_allowed = len(hits) - len(kept)
    kept.sort()

    if a.json:
        print(json.dumps([{"path": h[0], "line": h[1], "pattern": h[2]} for h in kept], indent=2))
    else:
        print(f"\nLeak gate  root={root}  files={n_files}  patterns={len(patterns)}\n")
        for label, line, pat in kept:
            print(f"  {label}:{line}  {pat}")
        files_hit = len({h[0] for h in kept})
        print(f"\n  {len(kept)} hit(s) in {files_hit} file(s); {n_allowed} allowed by exception")
        print("  " + ("BLOCKED -- resolve every hit or add a reviewed exception." if kept else "CLEAN"))
    return 1 if kept else 0


if __name__ == "__main__":
    sys.exit(main())
