"""In-place gold maintenance of an existing skill (was the maintain section of skill_builder.py)."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from .corpus import TARGET_BYTES
from .ingest import run
from .packing import split_text_by_headings


# ==============================================================================
# MAINTAIN — in-place gold maintenance (was maintain_skill.py)
# ==============================================================================

_HEADING = re.compile(r"(?m)^#{2,3} ")


def subskill_dirs(skill: Path):
    """Return the skill's sub-skill dirs (those with a SKILL.md), or [skill] itself if it is flat."""
    subs = [d for d in sorted(skill.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file()]
    return subs if subs else [skill]


def ref_files(refs: Path):
    """Return the sorted reference .md files in a directory, excluding INDEX.md."""
    return sorted(p for p in refs.glob("*.md") if p.name != "INDEX.md")


def h1_title(text: str) -> str:
    """Return the text of the first `# ` H1 heading, or an empty string if there is none."""
    for ln in text.split("\n"):
        if ln.startswith("# "):
            return ln[2:].strip()
    return ""


def has_subheadings(text: str) -> bool:
    """Return True if the text contains any level-2 or level-3 (`## `/`### `) heading."""
    return bool(_HEADING.search(text))


def split_runs(text: str, max_bytes: int):
    """Split into <=max_bytes runs at heading/blank boundaries (fence-aware)."""
    global TARGET_BYTES
    old = TARGET_BYTES
    TARGET_BYTES = max_bytes
    try:
        pieces = split_text_by_headings(text)
    finally:
        TARGET_BYTES = old
    runs, cur, cb = [], [], 0
    for pc in pieces:
        b = len(pc.encode("utf-8"))
        if cur and cb + b > max_bytes:
            runs.append("\n".join(cur)); cur = []; cb = 0
        cur.append(pc); cb += b
    if cur:
        runs.append("\n".join(cur))
    return runs


_ENTRY_START = re.compile(r"\*\*[^*]+\*\*[)\s.:]*$")  # line ends with a bold name/label token


def _is_entry_start(line: str) -> bool:
    """A line that begins a new self-contained item: a sub-heading, or a short bold-label line such as
    '> Boolean **propertyName**' or '**someName**'. Description / prose lines are NOT entry starts, so a
    name is never separated from the description that follows it."""
    s = line.strip()
    if re.match(r"#{2,6}\s", s):
        return True
    s = s.lstrip("> ").strip()
    return len(s) <= 90 and bool(_ENTRY_START.search(s))


def split_atomic(text: str, max_bytes: int):
    """Split a list-style file into <=max_bytes pieces ONLY at entry boundaries (a sub-heading or a
    short bold-label line that starts a new item), so a name is never separated from its description and
    a table row is never cut. Returns None when it cannot split cleanly — one entry already exceeds
    max_bytes (e.g. a monolithic table), or there are fewer than two entries — so the caller leaves the
    file whole (oversize is acceptable when a clean split is not possible)."""
    entries, cur = [], []
    for l in text.split("\n"):
        if _is_entry_start(l) and cur:
            entries.append("\n".join(cur)); cur = [l]
        else:
            cur.append(l)
    if cur:
        entries.append("\n".join(cur))
    if len(entries) < 3 or any(len(e.encode("utf-8")) > max_bytes for e in entries):
        return None
    runs, run, rb = [], [], 0
    for e in entries:
        eb = len(e.encode("utf-8"))
        if run and rb + eb > max_bytes:
            runs.append("\n".join(run)); run = []; rb = 0
        run.append(e); rb += eb
    if run:
        runs.append("\n".join(run))
    return runs


def _degenerate(runs) -> bool:
    """A split is no good if it produced <2 pieces or a tiny first piece (content lost / no break)."""
    return (not runs) or len(runs) < 2 or len(runs[0].encode("utf-8")) < 256


def audit(skill: Path, max_bytes: int):
    """Survey each (sub)skill's references, reporting file counts, oversize files (with subheading
    status), and topics.json drift (files missing from / dangling in topics.json)."""
    report = []
    for sk in subskill_dirs(skill):
        refs = sk / "references"
        if not refs.is_dir():
            continue
        files = ref_files(refs)
        present = {p.name for p in files}
        listed = set()
        tj = refs / "topics.json"
        if tj.is_file():
            try:
                d = json.loads(tj.read_text(encoding="utf-8"))
                listed = {Path(t.get("file", "")).name for t in d.get("topics", [])}
            except Exception:
                listed = set()
        oversize = []
        for p in files:
            sz = p.stat().st_size
            if sz > max_bytes:
                txt = p.read_text(encoding="utf-8")
                oversize.append((p.name, sz, has_subheadings(txt)))
        report.append({
            "subskill": sk.name if sk is not skill else "(flat)",
            "files": len(files),
            "oversize": sorted(oversize, key=lambda x: -x[1]),
            "missing_in_topics": sorted(present - listed) if listed else [],
            "dangling_topics": sorted(listed - present),
        })
    return report


def _next_name(stem: str, used: set) -> str:
    """Return the next unused `{stem}-{n}.md` filename and record it in `used`."""
    n = 2
    while f"{stem}-{n}.md" in used:
        n += 1
    name = f"{stem}-{n}.md"
    used.add(name)
    return name


def patch_topics(refs: Path, orig: str, parts: list):
    """Insert topics.json entries for the new split parts of `orig`, cloning its metadata and labeling
    each with a '(part k)' topic suffix. No-op if topics.json is absent."""
    tj = refs / "topics.json"
    if not tj.is_file():
        return
    d = json.loads(tj.read_text(encoding="utf-8"))
    topics = d.get("topics", [])
    for i, t in enumerate(topics):
        if Path(t.get("file", "")).name == orig:
            new = []
            for k, pn in enumerate(parts, start=2):
                e = dict(t)
                e["file"] = f"references/{pn}"
                e["topic"] = f'{t.get("topic", orig)} (part {k})'
                new.append(e)
            topics[i + 1:i + 1] = new
            break
    tj.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def patch_index(refs: Path, orig: str, parts: list):
    """Insert INDEX.md table rows for the new split parts of `orig`, reusing its 'covers' cell with a
    '(part k)' suffix. No-op if INDEX.md is absent."""
    idx = refs / "INDEX.md"
    if not idx.is_file():
        return
    lines = idx.read_text(encoding="utf-8").split("\n")
    for i, ln in enumerate(lines):
        if f"]({orig})" in ln and ln.lstrip().startswith("|"):
            m = re.match(r"\s*\|\s*\[.*?\]\(.*?\)\s*\|(.*)\|\s*$", ln)
            covers = (m.group(1).strip() if m else "")
            rows = [f"| [{pn}]({pn}) | {covers} (part {k}) |" for k, pn in enumerate(parts, start=2)]
            lines[i + 1:i + 1] = rows
            break
    idx.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def apply_splits(skill: Path, max_bytes: int, force: bool, act_above: int):
    """Split each reference file larger than `act_above` into <=max_bytes pieces in place, patching
    INDEX/topics. Atomic (no-subheading) files are split only with `force`; unsplittable files are
    skipped. Returns (changed, skipped) lists of per-file outcomes."""
    changed, skipped = [], []
    for sk in subskill_dirs(skill):
        refs = sk / "references"
        if not refs.is_dir():
            continue
        used = {p.name for p in refs.glob("*.md")}
        for p in ref_files(refs):
            if p.stat().st_size <= act_above:           # only touch files above this; pieces target max_bytes
                continue
            text = p.read_text(encoding="utf-8")
            atomic = not has_subheadings(text)
            if atomic and not force:
                skipped.append((sk.name, p.name, "atomic; use --force")); continue
            runs = split_atomic(text, max_bytes) if atomic else split_runs(text, max_bytes)
            if _degenerate(runs):                       # primary strategy failed; try the other one
                runs = split_runs(text, max_bytes) if atomic else split_atomic(text, max_bytes)
            if _degenerate(runs):                       # genuinely unsplittable (monolithic table / one huge line)
                skipped.append((sk.name, p.name, "unsplittable (no clean break point)")); continue
            stem = p.stem
            title = re.sub(r"\s*\(part \d+\)\s*$", "", h1_title(text)) or stem
            p.write_text(runs[0].rstrip() + "\n", encoding="utf-8", newline="\n")  # part 1 keeps name + H1
            parts = []
            for k, run in enumerate(runs[1:], start=2):
                name = _next_name(stem, used)
                body = run if run.lstrip().startswith("#") else f"# {title} (part {k})\n\n{run}"
                (refs / name).write_text(body.rstrip() + "\n", encoding="utf-8", newline="\n")
                parts.append(name)
            patch_index(refs, p.name, parts)
            patch_topics(refs, p.name, parts)
            changed.append((sk.name, p.name, len(parts) + 1))
    return changed, skipped


_CAMEL = re.compile(r"[a-z][A-Z]")


def _distinctive_terms(refs: Path) -> dict:
    """{distinctive topic-name -> filename} from topics.json; skips short / common single words to
    avoid over-linking. Multi-word titles and identifier-like names qualify."""
    tj = refs / "topics.json"
    if not tj.is_file():
        return {}
    try:
        d = json.loads(tj.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out = {}
    for t in d.get("topics", []):
        name = (t.get("topic") or "").strip()
        fn = Path(t.get("file", "")).name
        if not name or not fn or len(name) < 5:
            continue
        if len(name.split()) >= 2 or _CAMEL.search(name) or "." in name or len(name) >= 10:
            out[name] = fn
    return out


def _no_code(text: str) -> str:
    """Blank out fenced + inline code so a match never lands inside code."""
    out, fence = [], False
    for l in text.split("\n"):
        if l.lstrip().startswith("```"):
            fence = not fence; out.append(""); continue
        out.append("" if fence else re.sub(r"`[^`]*`", "", l))
    return "\n".join(out)


def cross_link(skill: Path, max_links: int = 6):
    """Append/refresh a '## See also' footer on each reference file, linking other topics in the same
    (sub)skill whose distinctive name appears in the file (and isn't already linked inline). Safe and
    idempotent: only the footer is touched — prose, SKILL.md and GOTCHA.md are left alone. This is the
    lightweight, conservative cross-link capability; richer inline/curated linking is a later pass."""
    changed = []
    for sk in subskill_dirs(skill):
        refs = sk / "references"
        if not refs.is_dir():
            continue
        terms = _distinctive_terms(refs)
        if not terms:
            continue
        for p in ref_files(refs):
            text = p.read_text(encoding="utf-8")
            body = re.split(r"\n## See also\n", text, 1)[0].rstrip()
            searchable = _no_code(body)
            linked = set(re.findall(r"\]\(([^)/]+\.md)\)", body))
            related, seen = [], set()
            for name, fn in terms.items():
                if fn == p.name or fn in linked or fn in seen:
                    continue
                if re.search(r"\b" + re.escape(name) + r"\b", searchable):
                    related.append((name, fn)); seen.add(fn)
            related = related[:max_links]
            footer = ("\n\n## See also\n\n" + "\n".join(f"- [{n}]({fn})" for n, fn in related) + "\n") if related else "\n"
            new = body + footer
            if new != text:
                p.write_text(new, encoding="utf-8", newline="\n")
                if related:
                    changed.append((sk.name, p.name, len(related)))
    return changed


def cmd_maintain(argv=None) -> int:
    """Run the `maintain` subcommand: audit a skill's references and print the report, then optionally
    apply oversize splits and/or refresh 'See also' cross-link footers. Returns an exit code."""
    ap = argparse.ArgumentParser(prog="skill_builder.py maintain")
    ap.add_argument("skill")
    ap.add_argument("--apply", action="store_true", help="split oversize heading-structured files in place")
    ap.add_argument("--force", action="store_true", help="also size-split atomic (no-subheading) files")
    ap.add_argument("--max-bytes", type=int, default=TARGET_BYTES, help="target size for resulting pieces")
    ap.add_argument("--act-above", type=int, default=None,
                    help="only split files larger than this (default: --max-bytes); pieces still target --max-bytes")
    ap.add_argument("--cross-link", action="store_true",
                    help="add/refresh a 'See also' footer on each reference file (links related topics by distinctive name)")
    args = ap.parse_args(argv)
    skill = Path(args.skill)

    rep = audit(skill, args.max_bytes)
    print(f"# audit: {skill}  (max-bytes={args.max_bytes})")
    for r in rep:
        flags = []
        if r["oversize"]:
            flags.append("oversize=" + ", ".join(
                f"{n}({sz//1024}KB,{'has-headings' if hh else 'ATOMIC'})" for n, sz, hh in r["oversize"]))
        if r["missing_in_topics"]:
            flags.append("missing_in_topics=" + ",".join(r["missing_in_topics"]))
        if r["dangling_topics"]:
            flags.append("dangling_topics=" + ",".join(r["dangling_topics"]))
        status = "; ".join(flags) if flags else "clean"
        print(f"  [{r['subskill']}] files={r['files']}  {status}")

    if args.apply:
        changed, skipped = apply_splits(skill, args.max_bytes, args.force, args.act_above or args.max_bytes)
        if changed:
            print("# applied splits:")
            for sub, f, n in changed:
                print(f"  [{sub}] {f} -> {n} files")
        for sub, f, why in skipped:
            print(f"# skipped: [{sub}] {f} ({why})")
        if not changed and not skipped:
            print("# nothing eligible.")

    if args.cross_link:
        cl = cross_link(skill)
        if cl:
            print("# cross-linked (See also footers added/refreshed):")
            for sub, f, n in cl:
                print(f"  [{sub}] {f} -> {n} related")
        else:
            print("# cross-link: no distinctive cross-references found (no footers added).")
    return 0

def main(argv=None) -> int:
    """Standalone entry point for `python -m builder_components.maintain`; delegates to cmd_maintain."""
    return cmd_maintain(argv)


if __name__ == "__main__":
    raise SystemExit(main())
