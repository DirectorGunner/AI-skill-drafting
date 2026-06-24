"""Build the cross-skill master index (was the index section of skill_builder.py)."""

from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path


# ==============================================================================
# INDEX — cross-skill master index (was build_master_index.py)
# ==============================================================================

_STOP = {"and", "the", "for", "with", "use", "using", "a", "an", "to", "of", "in", "on", "or"}


def parse_frontmatter(text: str) -> dict:
    """Line-based YAML-lite parse of the SKILL.md frontmatter: handles inline scalars, folded/literal
    block scalars (`>-`, `>`, `|`), inline lists (`[a, b]`), and block lists (`- a`)."""
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    lines = m.group(1).split("\n")
    fm, i = {}, 0
    while i < len(lines):
        km = re.match(r"^(\w+):\s?(.*)$", lines[i])
        if not km:
            i += 1
            continue
        key, val = km.group(1), km.group(2).strip()
        if val in (">-", ">", ">+", "|", "|-", "|+"):                 # block scalar
            buf, i = [], i + 1
            while i < len(lines) and (lines[i].startswith((" ", "\t")) or not lines[i].strip()):
                buf.append(lines[i].strip()); i += 1
            fm[key] = " ".join(x for x in buf if x)
            continue
        if val.startswith("[") and val.endswith("]"):                # inline list
            fm[key] = [x.strip().strip("'\"") for x in val[1:-1].split(",") if x.strip()]
        elif val == "":                                              # maybe a block list follows
            buf, j = [], i + 1
            while j < len(lines) and re.match(r"^\s+-\s", lines[j]):
                buf.append(re.match(r"^\s+-\s*(.+)", lines[j]).group(1).strip().strip("'\"")); j += 1
            fm[key] = buf if buf else ""
            i = j if buf else i + 1
            continue
        else:
            fm[key] = val.strip("'\"")
        i += 1
    return fm


def derive_covers(skill: Path) -> list:
    """Entities a skill covers. Router → its sub-skill area names (clean). Flat → distinctive
    topics.json keywords filtered to clean single-concept terms (drops concatenated slugs)."""
    subs = [d.name for d in sorted(skill.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file()]
    if subs:
        return subs
    terms = collections.Counter()
    tj = skill / "references" / "topics.json"
    if tj.is_file():
        try:
            d = json.loads(tj.read_text(encoding="utf-8"))
        except Exception:
            d = {"topics": []}
        for t in d.get("topics", []):
            for kw in t.get("keywords", []):
                k = str(kw).replace("_", "-").strip().lower()
                if k and k not in _STOP and 3 <= len(k) <= 30 and k.count("-") <= 3 and not k.isdigit():
                    terms[k] += 1
    return [t for t, _ in terms.most_common()]


def seed_covers_in_skill(skill: Path, covers: list) -> bool:
    """Insert/replace a `covers:` block list in a SKILL.md frontmatter, preserving the bespoke body
    byte-for-byte. Idempotent: an existing covers: block (inline or list) is stripped and rewritten."""
    p = skill / "SKILL.md"
    text = p.read_text(encoding="utf-8")
    m = re.match(r"^(---\n)(.*?)(\n---\n)", text, re.DOTALL)
    if not m:
        return False
    lines = m.group(2).split("\n")
    out, i = [], 0
    while i < len(lines):
        cm = re.match(r"^covers:\s*(\S.*)?$", lines[i])
        if cm:
            i += 1
            if not cm.group(1):                       # block list follows — drop its items too
                while i < len(lines) and re.match(r"^\s+-\s", lines[i]):
                    i += 1
            continue
        out.append(lines[i]); i += 1
    body = "\n".join(out).rstrip("\n")
    block = "covers:\n" + "\n".join(f"  - {c}" for c in covers)
    p.write_text(m.group(1) + body + "\n" + block + m.group(3) + text[m.end():],
                 encoding="utf-8", newline="\n")
    return True


def skill_info(skill: Path) -> dict:
    """Return a skill's {name, trigger, covers} summary, deriving covers when not in frontmatter and
    using the description's first sentence (capped at 200 chars) as the trigger."""
    fm = parse_frontmatter((skill / "SKILL.md").read_text(encoding="utf-8")) if (skill / "SKILL.md").is_file() else {}
    covers = fm.get("covers") or derive_covers(skill)
    desc = fm.get("description", "")
    trigger = re.split(r"(?<=[.])\s", desc, 1)[0] if desc else ""
    return {"name": fm.get("name", skill.name), "trigger": trigger[:200], "covers": covers}


def build_master_text(root: Path) -> str:
    """Build the master INDEX.md Markdown for a skills root: a skills catalog table, a related-skills
    list, and an entity->skill map for entities shared by more than one skill."""
    skills = [d for d in sorted(root.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file()]
    infos = {d.name: skill_info(d) for d in skills}

    # Catalog column shows the curated `covers:` (capped); the overlap map/related-skills use the
    # fuller derived entity set, so genuine cross-references aren't hidden by the display cap.
    ent2skill = collections.defaultdict(set)
    for d in skills:
        for e in derive_covers(d):
            ent2skill[e].add(d.name)

    related = collections.defaultdict(collections.Counter)
    for e, owners in ent2skill.items():
        if len(owners) > 1:
            for a in owners:
                for b in owners:
                    if a != b:
                        related[a][b] += 1

    out = ["# Skills — Master Index", "",
           "Catalog of every skill in this folder, with the entities/domains each covers and which "
           "skills are related. A discovery / audit entry point — agents still route via each skill's "
           "`description`. Generated by `skill-drafting/scripts/skill_builder.py index`.", "",
           "## Skills", "", "| Skill | Covers (top) | Trigger |", "| --- | --- | --- |"]
    for name in sorted(infos):
        info = infos[name]
        cov = ", ".join(info["covers"][:8]) + (" …" if len(info["covers"]) > 8 else "")
        out.append(f"| [{name}]({name}/SKILL.md) | {cov} | {info['trigger']} |")

    out += ["", "## Related skills", "", "Skills that share covered entities:", ""]
    for name in sorted(related):
        rel = ", ".join(f"{b} ({n})" for b, n in related[name].most_common(6))
        out.append(f"- **{name}** ↔ {rel}")
    if not related:
        out.append("- (no shared entities across skills)")

    shared = {e: sorted(s) for e, s in ent2skill.items() if len(s) > 1}
    out += ["", "## Entity → skill map (shared)", "",
            "Entities documented by more than one skill (where to look, and overlaps):", "",
            "| Entity | Skills |", "| --- | --- |"]
    for e in sorted(shared):
        out.append(f"| {e} | {', '.join(shared[e])} |")
    if not shared:
        out.append("| (none) | |")
    return "\n".join(out).rstrip() + "\n"


def cmd_index(argv=None) -> int:
    """Run the `index` subcommand: optionally seed each SKILL.md `covers:` frontmatter, then write the
    master INDEX.md to the root (and any --mirror root). Returns an exit code."""
    ap = argparse.ArgumentParser(prog="skill_builder.py index")
    ap.add_argument("root", help="a skills root, e.g. .agents/skills")
    ap.add_argument("--mirror", help="also write the identical index to this skills root")
    ap.add_argument("--seed-covers", action="store_true",
                    help="seed/refresh each SKILL.md `covers:` frontmatter from derived entities "
                         "(routers: all area names; flat: top 12). Also seeds --mirror for parity.")
    ap.add_argument("--flat-cap", type=int, default=12, help="max covers entries for a flat skill")
    args = ap.parse_args(argv)
    root = Path(args.root)

    if args.seed_covers:
        roots = [root] + ([Path(args.mirror)] if args.mirror else [])
        for d in sorted(root.iterdir()):
            if not (d.is_dir() and (d / "SKILL.md").is_file()):
                continue
            is_router = any(c.is_dir() and (c / "SKILL.md").is_file() for c in d.iterdir())
            covers = derive_covers(d)
            if not is_router:
                covers = covers[:args.flat_cap]
            for r in roots:
                if (r / d.name / "SKILL.md").is_file() and seed_covers_in_skill(r / d.name, covers):
                    print(f"seeded covers ({len(covers)}) -> {(r / d.name).as_posix()}/SKILL.md")

    text = build_master_text(root)
    (root / "INDEX.md").write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {root}/INDEX.md ({text.count(chr(10))} lines)")
    if args.mirror:
        mroot = Path(args.mirror)
        (mroot / "INDEX.md").write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {mroot}/INDEX.md (mirror)")
    return 0

def main(argv=None) -> int:
    """Standalone entry point for `python -m builder_components.index`; delegates to cmd_index."""
    return cmd_index(argv)


if __name__ == "__main__":
    raise SystemExit(main())
