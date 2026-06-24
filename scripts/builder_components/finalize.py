"""Finalize a gold SKILL.md + GOTCHA.md (was the finalize section of skill_builder.py)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from builder_components.util.config import VALIDATOR


# ==============================================================================
# FINALIZE — gold SKILL.md + GOTCHA.md (was finalize_gold.py)
# ==============================================================================

REF = "Recurring failure modes and what to do instead live in the sibling [GOTCHA.md](GOTCHA.md)."

DEFAULT_GOTCHAS = [
    "These reference files are reproduced verbatim from the upstream documentation and split into "
    "focused topics; a file may cover several adjacent subjects — use `references/INDEX.md` or "
    "`rg -n \"PATTERN\" references/*.md` to locate the exact one.",
    "The docs track a specific version; verify version-sensitive APIs, flags, and defaults against the "
    "actual toolchain/build in use before relying on them.",
    "Treat every identifier (API/type/function name, flag, path, enum value, number) as an exact "
    "reference fact — do not invent or paraphrase.",
]


def write(path: Path, text: str) -> None:
    """Write text to path with a single trailing newline and LF line endings."""
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def ref_count(skill_dir: Path) -> int:
    """Count the subject reference *.md files under skill_dir/references (excluding INDEX.md)."""
    refs = skill_dir / "references"
    return len([p for p in refs.glob("*.md") if p.name != "INDEX.md"]) if refs.is_dir() else 0


def gotcha_md(title: str, gotchas: list) -> str:
    """Render GOTCHA.md content for title from the given gotchas (or DEFAULT_GOTCHAS if empty)."""
    lead = (f"Recurring failure modes when relying on the {title} reference, and what to do instead. "
            f"Read alongside `SKILL.md`.")
    body = "\n".join(f"- {g}" for g in (gotchas or DEFAULT_GOTCHAS))
    return f"# {title} — Gotchas\n\n{lead}\n\n{body}\n"


def source_note(meta: dict) -> str:
    """Render the SKILL.md Source section from meta, or "" when no source_url is present."""
    if not meta.get("source_url"):
        return ""
    verb = ("Reproduced verbatim from the upstream documentation for local reference; prose is the "
            "source's own. " if meta.get("verbatim") else "")
    return (f"\n## Source\n\n{verb}Upstream: {meta['source_url']}\n")


def leaf_skill_md(meta: dict, skill_dir: Path, *, validate_path: str) -> str:
    """Render the full SKILL.md for a leaf (flat or sub-) skill from meta and its reference count."""
    title, n = meta["title"], ref_count(skill_dir)
    when = meta.get("when_to_use") or meta.get("description", "")
    return f"""---
name: {meta['name']}
description: {meta['description']}
---

# {title} Reference

Faithful reference for {title}, split into one focused file per subject across {n} reference files.
Identifiers (API/type/function names, flags, paths, enums, numbers) are preserved verbatim.

## When to use this

Use this skill when the task involves {when}

## Workflow

1. Open `references/INDEX.md` (or `references/topics.json`) and pick the one file that matches.
2. Read only that file; open another only if the task spans subjects. Grep across files when needed: `rg -n "PATTERN" references/*.md`.
3. Treat every identifier as an exact reference fact — never invent or paraphrase.

## Gotchas

{REF}

## References

All depth lives in `references/` — start at `references/INDEX.md`, metadata in `references/topics.json`. One subject per file.
{source_note(meta)}
## Verification

```powershell
python {VALIDATOR} validate {validate_path}
```
"""


def router_skill_md(meta: dict, skill_dir: Path, *, validate_path: str) -> str:
    """Render the top-level router SKILL.md from meta, with a Routes table over the sub-skill dirs."""
    title = meta["title"]
    subs = meta.get("subskills", {})
    rows = "\n".join(
        f"| {subs.get(k, {}).get('title', k)} | {subs.get(k, {}).get('when_to_use', subs.get(k, {}).get('description', k))} | `{k}/SKILL.md` |"
        for k in sub_dirs(skill_dir))
    return f"""---
name: {meta['name']}
description: >-
  {meta['description']}
---

# {title} Reference

Faithful, task-routed reference for {title}, split into one focused file per subject. Identifiers are
preserved verbatim. Routes to the area sub-skills below — open the one that matches and use its
`references/INDEX.md`.

## When to use this

Use this skill when the task involves {meta.get('when_to_use') or meta.get('description','')}

## Routes

| Area | Use for | Open |
| --- | --- | --- |
{rows}

## Workflow

1. Identify the area above and open that sub-skill's `SKILL.md` (or its `references/INDEX.md`).
2. Read the one reference file that matches.
3. Treat every identifier as an exact reference fact.

## Gotchas

{REF}

## References

Each sub-skill carries its own `references/INDEX.md`, `references/topics.json`, and per-subject files.
{source_note(meta)}
## Verification

```powershell
python {VALIDATOR} validate --package {validate_path}
```
"""


def sub_dirs(skill_dir: Path) -> list:
    """Return the sorted names of immediate sub-skill directories (those containing a SKILL.md)."""
    return sorted(d.name for d in skill_dir.iterdir() if d.is_dir() and (d / "SKILL.md").is_file())


def cmd_finalize(argv=None) -> int:
    """Parse `finalize` CLI args and write the gold SKILL.md + GOTCHA.md for a router or flat skill.

    Returns 0 on success.
    """
    global VALIDATOR
    ap = argparse.ArgumentParser(prog="skill_builder.py finalize")
    ap.add_argument("--validator", default=VALIDATOR,
                    help="validator path used in the generated SKILL.md Verification command.")
    ap.add_argument("--skill", required=True)
    ap.add_argument("--meta", required=True)
    args = ap.parse_args(argv)
    VALIDATOR = args.validator
    skill_rel = Path(args.skill).as_posix()
    skill = Path(args.skill)
    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))

    if meta.get("router"):
        write(skill / "SKILL.md", router_skill_md(meta, skill, validate_path=skill_rel))
        write(skill / "GOTCHA.md", gotcha_md(meta["title"], meta.get("gotchas")))
        for k in sub_dirs(skill):
            sm = dict(meta.get("subskills", {}).get(k, {}))
            sm.setdefault("name", k)
            sm.setdefault("title", k.replace("-", " ").title())
            sm.setdefault("description", f"Use when working with {sm['title']} ({meta['title']}).")
            sm.setdefault("source_url", meta.get("source_url"))
            sm["verbatim"] = meta.get("verbatim", False)
            write(skill / k / "SKILL.md",
                  leaf_skill_md(sm, skill / k, validate_path=f"{skill_rel}/{k}"))
            write(skill / k / "GOTCHA.md", gotcha_md(sm["title"], meta.get("gotchas")))
        print(f"finalized router '{meta['name']}' + {len(sub_dirs(skill))} sub-skills")
    else:
        write(skill / "SKILL.md", leaf_skill_md(meta, skill, validate_path=skill_rel))
        write(skill / "GOTCHA.md", gotcha_md(meta["title"], meta.get("gotchas")))
        print(f"finalized flat skill '{meta['name']}' ({ref_count(skill)} reference files)")
    return 0

def main(argv=None) -> int:
    """Standalone entry point for `python -m builder_components.finalize`; delegates to cmd_finalize."""
    return cmd_finalize(argv)


if __name__ == "__main__":
    raise SystemExit(main())
