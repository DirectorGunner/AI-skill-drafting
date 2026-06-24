"""Build a reference skill package from a corpus (was the build orchestration section of skill_builder.py)."""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from builder_components.util.text_io import write_text
from builder_components.util.repo_paths import _project_ai_dir
from .corpus import BACKTICK_IDENTIFIERS, COMPACT_TABLES, RESOLVE_REFS, RUN_PRETTIER, TARGET_BYTES, _IMG_RE, _LINK_RE, _is_fence, backtick_identifiers, body_of, clean_title, compact_tables, is_cruft, load_records, resolve_refs, section_label, section_of, subskill_meta, subskill_of
from .ingest import run
from .packing import _titlecase, build_leaves, disambiguate_titles, pack, slug, split_oversize, title_for


# ---- rendering ---------------------------------------------------------------

def render_file(skill_title: str, file_leaves: list[dict], title: str, linkmap: dict) -> str:
    """Render one reference file: H1 + attribution + (Overview for multi-topic files) + per-leaf
    sections. Link/image resolution runs per-leaf (a whole page) so fences stay balanced."""
    lines = [f"# {title}", "", f"> {skill_title} reference. Original prose; identifiers preserved verbatim.", ""]
    single = len(file_leaves) == 1
    if not single:
        covers = list(dict.fromkeys(l["title"] for l in file_leaves if l["title"]))[:18]
        lines += ["## Overview", "", "Covers: " + "; ".join(covers) + ".", ""]
    level = "##" if single else "###"
    for leaf in file_leaves:
        src = next((c.get("source_url", "") for c in leaf["chunks"] if c.get("source_url")), "")
        block: list[str] = []
        if not single and leaf["title"]:
            block += [f"## {leaf['title']}", ""]
        last = None
        for chunk in leaf["chunks"]:
            ct = clean_title(chunk.get("title") or "")
            if ct and leaf["title"] and ct != leaf["title"]:
                ct = re.sub(r"^" + re.escape(leaf["title"]) + r"\s*[—–:-]\s*", "", ct) or ct
            if ct and ct != leaf["title"] and ct != last:
                block += [f"{level} {ct}", ""]
                last = ct
            b = body_of(chunk)
            if b:
                block += [b, ""]
        text = "\n".join(block)
        lines.append(resolve_refs(text, src, linkmap) if RESOLVE_REFS else text)
    text = "\n".join(lines)
    if COMPACT_TABLES:
        text = compact_tables(text)
    if BACKTICK_IDENTIFIERS:
        text = backtick_identifiers(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"




def write_index(refs: Path, subskill: str, skill_title: str, fm: list) -> None:
    """Write references/INDEX.md: a per-section table of every file with a one-line summary."""
    lines = [f"# {skill_title} References — Index", "",
             "Each file is one focused, original-prose reference (identifiers preserved verbatim). "
             "Open only what the SKILL.md router points to.", ""]
    for sec in sorted({f[0] for f in fm}):
        lines += [f"## {section_label(subskill, sec)}", "", "| File | Covers |", "| --- | --- |"]
        for s, fname, disp, _, _ in fm:
            if s == sec:
                lines.append(f"| [{fname}]({fname}) | {disp} |")
        lines.append("")
    write_text(refs / "INDEX.md", "\n".join(lines).rstrip() + "\n")


def write_topics(refs: Path, subskill: str, fm: list) -> None:
    """Write references/topics.json (machine-readable topic -> file + keywords)."""
    topics = [{"topic": disp, "file": f"references/{fname}",
               "summary": f"{section_label(subskill, s)}: {disp}.",
               "keywords": [slug(disp), s]} for (s, fname, disp, _, _) in fm]
    write_text(refs / "topics.json", json.dumps({"schema_version": 1, "topics": topics}, ensure_ascii=False, indent=2) + "\n")


def write_leaf_skill(skill_dir: Path, name: str, title: str, purpose: str, triggers: str, subskill: str, fm: list) -> None:
    """Write a (sub)skill SKILL.md: frontmatter + workflow + a section-grouped task router."""
    by_s: dict[str, list] = {}
    for (s, fname, disp, _, _) in fm:
        by_s.setdefault(s, []).append((disp, fname))
    parts = []
    for s in sorted(by_s):
        parts += [f"### {section_label(subskill, s)}", "", "| Topic | Read |", "| --- | --- |"]
        parts += [f"| {disp} | references/{fname} |" for disp, fname in by_s[s]]
        parts.append("")
    router = "\n".join(parts).strip()
    md = f"""---
name: {name}
description: {triggers}
---

# {title} Reference

Use this skill for {purpose}

## Workflow

1. Identify the section the task touches.
2. Use the task router below or `references/INDEX.md` to open the one reference file that matches.
3. Treat every label, identifier, API/method name, endpoint, enum value, and number as an exact reference fact.

## Task router

Load only the reference the task needs. Files are grouped by section.

{router}

## Gotchas

- Stay inside these references unless the task explicitly needs other material.
- Verify implementation-sensitive claims (versions, endpoints, entitlements) against the live system before relying on them.

## References

Start at `references/INDEX.md`; metadata in `references/topics.json`. One subject per file.

## Verification

- Validate this skill with your skill-package validator and re-run the builder's `--verify`.
"""
    write_text(skill_dir / "SKILL.md", md)


def write_router(out: Path, name: str, title: str, description: str, subskills: list[tuple]) -> None:
    """Write the top-level router SKILL.md for a multi-sub-skill build."""
    rows = "\n".join(f"| {subskill_meta(k)['title']} | {subskill_meta(k)['purpose']} | `{k}/SKILL.md` |"
                     for k, _ in subskills)
    md = f"""---
name: {name}
description: {description}
---

# {title} Router

Entry point that routes to product/area sub-skills; each is a direct subdirectory with its own
`SKILL.md` and a flat `references/` folder of focused, readable reference files.

## Workflow

1. Identify the sub-skill the task belongs to.
2. Open that sub-skill's `SKILL.md` and use its task router (or `references/INDEX.md`).
3. Read the one reference file that matches.

## Routes

| Sub-skill | Use for | Open |
| --- | --- | --- |
{rows}

## Gotchas

- Treat labels, identifiers, API names, endpoints, enum values, and version numbers as exact facts.

## References

Each sub-skill carries its own `references/INDEX.md`, `references/topics.json`, and per-subject files.

## Verification

- Validate the whole package with your skill-package validator (router + sub-skills).
"""
    write_text(out / "SKILL.md", md)


# ---- build orchestration -----------------------------------------------------

def _build_one(skill_dir: Path, subskill: str, skill_title: str, records: list[dict]) -> list:
    """Build one skill's references/ + INDEX + topics from its records. Returns files_meta."""
    refs = skill_dir / "references"
    if refs.exists():
        shutil.rmtree(refs)
    refs.mkdir(parents=True, exist_ok=True)

    by_section: dict[str, list] = collections.defaultdict(list)
    for r in records:
        by_section[section_of(r)].append(r)

    # Pass A: assign every file (name + leaves), no rendering yet.
    used: set = set()
    plans: list[dict] = []
    for section in sorted(by_section):
        for file_leaves in pack(build_leaves(by_section[section], section), 0):
            if len(file_leaves) == 1 and file_leaves[0]["bytes"] > TARGET_BYTES:
                leaf = file_leaves[0]
                runs = split_oversize(leaf)
                for i, run in enumerate(runs, 1):
                    sub = [{"path": leaf["path"], "title": leaf["title"], "chunks": run,
                            "bytes": sum(len(c["text"].encode("utf-8")) for c in run)}]
                    fname, disp = title_for(section, sub, used)
                    label = f"{disp} (part {i})" if len(runs) > 1 else disp
                    plans.append({"section": section, "fname": fname, "title": label, "leaves": sub})
                continue
            fname, disp = title_for(section, file_leaves, used)
            plans.append({"section": section, "fname": fname, "title": disp, "leaves": file_leaves})

    disambiguate_titles(plans)

    linkmap: dict = {}
    for pl in plans:
        for leaf in pl["leaves"]:
            for ch in leaf["chunks"]:
                su = ch.get("source_url")
                if su:
                    linkmap.setdefault(su, pl["fname"])

    files_meta = []
    for pl in plans:
        md = render_file(skill_title, pl["leaves"], pl["title"], linkmap)
        write_text(refs / pl["fname"], md)
        files_meta.append((pl["section"], pl["fname"], pl["title"], len(pl["leaves"]), len(md.encode("utf-8"))))

    write_index(refs, subskill, skill_title, files_meta)
    write_topics(refs, subskill, files_meta)
    return files_meta


def build(records: list[dict], out: Path, skill_name: str, skill_desc: str) -> dict:
    """Build the whole skill (flat or router) under `out`. Returns a report dict."""
    records = [r for r in records if not is_cruft(r.get("source_url") or "")]
    groups: dict[str, list] = collections.defaultdict(list)
    for r in records:
        groups[subskill_of(r) or ""].append(r)
    keys = [k for k in groups if k]
    report = {"out": str(out), "records": len(records), "subskills": {}, "router": bool(keys)}

    if not keys:  # flat single skill
        fm = _build_one(out, "", _titlecase(skill_name), groups[""])
        meta = {"title": _titlecase(skill_name), "purpose": "the reference material below.",
                "triggers": skill_desc}
        write_leaf_skill(out, skill_name, meta["title"], meta["purpose"], meta["triggers"], "", fm)
        report["subskills"][""] = len(fm)
        return report

    for k in sorted(groups):  # router of sub-skills
        if not k:
            continue
        m = subskill_meta(k)
        fm = _build_one(out / k, k, m["title"], groups[k])
        write_leaf_skill(out / k, k, m["title"], m["purpose"], m["triggers"], k, fm)
        report["subskills"][k] = len(fm)
    write_router(out, skill_name, _titlecase(skill_name), skill_desc, [(k, groups[k]) for k in sorted(keys)])
    return report


def post_process(out: Path) -> None:
    """Optional whitespace normalization with prettier, then re-compact tables / re-backtick
    identifiers (prettier re-pads tables, so the deterministic passes run last). Skipped cleanly
    if prettier is unavailable."""
    if RUN_PRETTIER:
        ignore = out / ".prettierignore-empty"
        try:
            ignore.write_text("", encoding="utf-8")
            subprocess.run(f'npx --no-install prettier --write --prose-wrap preserve '
                           f'--ignore-path "{ignore.as_posix()}" "{out.as_posix()}/**/*.md"',
                           shell=True, check=False, capture_output=True, timeout=900)
            ignore.unlink(missing_ok=True)
        except Exception as exc:  # prettier is a normalizer; the passes below are the real cleanup
            print(f"  prettier skipped: {exc}")
    for f in out.rglob("*.md"):
        t = f.read_text(encoding="utf-8")
        t2 = t
        if COMPACT_TABLES:
            t2 = compact_tables(t2)
        if BACKTICK_IDENTIFIERS:
            t2 = backtick_identifiers(t2)
        if t2 != t:
            f.write_text(t2, encoding="utf-8", newline="\n")


def verify(out: Path) -> bool:
    """Self-check the built skill: report file count, size distribution, residual raw image
    embeds / broken-looking relative links, and prose HTML. Returns True if clean enough."""
    md_files = [f for f in out.rglob("*.md") if f.name != "INDEX.md" and f.name != "SKILL.md"]
    sizes = sorted(f.stat().st_size / 1024 for f in md_files)
    raw_img = raw_relpath = prose_html = 0
    htmltag = re.compile(r"</?(?:div|span|br|b|strong|td|tr|li|ul|table|script|style|p|h[1-6])\b", re.IGNORECASE)
    for f in md_files:
        in_fence = False
        for line in f.read_text(encoding="utf-8").split("\n"):
            s = line.lstrip()
            if _is_fence(s):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            raw_img += len(_IMG_RE.findall(line))
            for _, t in _LINK_RE.findall(line):
                if t.startswith("/") or "../" in t:
                    raw_relpath += 1
            outside = "".join(line.split("`")[i] for i in range(0, len(line.split("`")), 2))
            if htmltag.search(outside):
                prose_html += 1
    big = [f.name for f in md_files if f.stat().st_size > TARGET_BYTES * 1.6]
    print(f"  files={len(md_files)}  median={sizes[len(sizes)//2] if sizes else 0:.1f}KB  "
          f"max={sizes[-1] if sizes else 0:.1f}KB  over~40KB={len(big)}")
    print(f"  residual raw image embeds={raw_img}  raw relative-path links={raw_relpath}  prose-HTML lines={prose_html}")
    ok = raw_relpath == 0
    print("  VERIFY:", "OK" if ok else "review residual relative-path links")
    return ok


def _is_reparse_point(p: Path) -> bool:
    """True if p itself is a Windows junction/symlink (reparse point) — checked WITHOUT resolving, so a
    per-skill junction (.agents/skills/<s> or .claude/skills/<s> -> the store) is detected before any copy."""
    try:
        import os, stat
        return bool(os.lstat(str(p)).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except (OSError, AttributeError):
        return p.is_symlink()


def cmd_build(argv=None) -> int:
    """Parse `build` CLI args, load records, build the skill, post-process, mirror, and verify.

    Returns 0 on success (or a clean verify), 1 if --verify fails, 2 if no records load.
    """
    global TARGET_BYTES, RUN_PRETTIER, RESOLVE_REFS, COMPACT_TABLES, BACKTICK_IDENTIFIERS, \
        SECTION_PREFIX, STRIP_ORDER_PREFIX
    ap = argparse.ArgumentParser(prog="skill_builder.py build", description="Build a readable per-subject reference skill from a JSONL chunk corpus.")
    ap.add_argument("--records", action="append", required=True, metavar="GLOB",
                    help="Glob of JSONL record files (repeatable; files merged by id). "
                         "Relative globs resolve under --work-dir.")
    ap.add_argument("--out", required=True, help="Output skill directory to (re)write (relative to CWD, or absolute).")
    ap.add_argument("--mirror", action="append", default=[], metavar="DIR",
                    help="Additional PLAIN directory to copy the built skill to (repeatable). Build directly "
                         "in the store; do NOT --mirror to the .agents/.claude per-skill junctions (a junction "
                         "target is skipped with a warning).")
    ap.add_argument("--work-dir", default=None,
                    help="Base directory for relative --records globs (default: <project-root>/AI/work).")
    ap.add_argument("--name", default=None, help="Skill name (kebab). Default: the --out folder name.")
    ap.add_argument("--description", default="Use when the task needs this reference material.",
                    help="SKILL.md frontmatter description (make it trigger-rich).")
    ap.add_argument("--target-bytes", type=int, default=None,
                    help="Per-file size target in bytes (default: %d)." % TARGET_BYTES)
    ap.add_argument("--no-prettier", action="store_true", help="Skip the prettier normalization pass.")
    ap.add_argument("--verbatim", action="store_true",
                    help="Verbatim preset for ingested-doc corpora: no link rewriting, table "
                         "compaction, identifier-backticking, or prettier; filenames from the page "
                         "slug; 2+digit ordering prefixes dropped from display titles.")
    ap.add_argument("--verify", action="store_true", help="Run the built-in audit after building.")
    args = ap.parse_args(argv)

    if args.verbatim:
        RESOLVE_REFS = COMPACT_TABLES = BACKTICK_IDENTIFIERS = RUN_PRETTIER = False
        SECTION_PREFIX = False
        STRIP_ORDER_PREFIX = True
    if args.target_bytes:
        TARGET_BYTES = args.target_bytes
    if args.no_prettier:
        RUN_PRETTIER = False

    work = Path(args.work_dir) if args.work_dir else _project_ai_dir(Path.cwd(), "AI", "work")
    record_globs = [g if Path(g).is_absolute() else str(work / g) for g in args.records]
    out = Path(args.out).resolve()
    name = args.name or out.name
    records = load_records(record_globs)
    if not records:
        print("No records loaded — check --records glob(s), --work-dir, and FIELD_MAP.")
        return 2

    report = build(records, out, name, args.description)
    post_process(out)
    for m in args.mirror:
        mp = Path(m)
        if _is_reparse_point(mp):
            print(f"WARNING: --mirror target '{mp}' is a junction/symlink (a per-skill link to the store); "
                  f"skipping. Build directly in the store; the junction already surfaces this skill to both agents.",
                  file=sys.stderr)
            continue
        dst = mp.resolve()
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(out, dst)

    mode = "router" if report["router"] else "flat"
    print(f"built {mode} skill '{name}' at {out}: {report['records']} records -> "
          f"{sum(report['subskills'].values())} files across {len(report['subskills'])} (sub)skill(s)")
    if args.mirror:
        print(f"mirrored to: {', '.join(args.mirror)}")
    ok = True
    if args.verify:
        ok = verify(out)
    return 0 if ok else 1

def main(argv=None) -> int:
    """Standalone entry point for `python -m builder_components.build`; delegates to cmd_build."""
    return cmd_build(argv)


if __name__ == "__main__":
    raise SystemExit(main())
