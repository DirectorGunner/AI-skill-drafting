"""Skill README scaffold/apply against the single-sourced standard (was the readme section)."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


# ==============================================================================
# README STANDARD — scaffold + managed-region apply (single-sourced template)
# ==============================================================================
# A skill's public README.md is part constant boilerplate and part per-skill prose. The constant
# blocks — the "Part of Agent Kaizen" intro paragraph, the full %DEVROOT% "Use it" section, the
# idle-context policy section, and the License — are single-sourced in references/readme-standard.md
# and re-applied in place. Regions are located by MARKDOWN STRUCTURE, never by HTML-comment markers:
# the intro by its leading "Part of **[Agent Kaizen](" text, the others as whole `## ` sections (the
# heading through the line before the next `## `). Shippable READMEs therefore carry NO tool markers;
# everything outside the managed regions is author-owned and never rewritten. No README prose lives here.

def _readme_store_root() -> Path:
    """The skills store this package ships inside
    (skills/skill-drafting/scripts/builder_components -> skills)."""
    return Path(__file__).resolve().parents[3]


def _readme_default_template() -> Path:
    """Path to the single-sourced README standard (skill-drafting/references/readme-standard.md)."""
    # this module lives in skills/skill-drafting/scripts/builder_components/; the standard is two
    # levels up under skill-drafting/references/.
    return Path(__file__).resolve().parents[2] / "references" / "readme-standard.md"


def _readme_skill_dirs(store: Path):
    """Return the skill directories (those containing a SKILL.md) directly under `store`, sorted."""
    return [d for d in sorted(store.iterdir()) if d.is_dir() and (d / "SKILL.md").is_file()]


def _readme_fill(text: str, *, skill=None, title=None, tagline=None, article=None) -> str:
    """Substitute the {{skill}}/{{title}}/{{tagline}}/{{article}} placeholders present in `text`."""
    for token, val in (("{{skill}}", skill), ("{{title}}", title),
                       ("{{tagline}}", tagline), ("{{article}}", article)):
        if val is not None:
            text = text.replace(token, val)
    return text


def _readme_strip(block):
    """Drop leading/trailing blank lines from a list of lines."""
    s, e = 0, len(block)
    while s < e and block[s].strip() == "":
        s += 1
    while e > s and block[e - 1].strip() == "":
        e -= 1
    return block[s:e]


#: Managed regions, in document order. Each is located by markdown structure (see _readme_region_locate);
#: their canonical content is single-sourced from the template skeletons. `intro` and `license` are
#: Pattern A only; `use-it` and `idle-context` appear in every skill (presence-driven, so absent regions
#: are simply skipped).
_README_REGIONS = ("intro", "use-it", "idle-context", "license")

#: Heading prefix that locates each `## ` section region (intro is located separately, by leading text).
_README_HEADINGS = {
    "use-it": "## Use it",
    "idle-context": "## Reducing idle context cost",
    "license": "## License",
}


def _readme_region_locate(lines, name):
    """Span (lo, hi) of a managed region located by markdown structure, or None if absent. `intro` is the
    single 'Part of **[Agent Kaizen](' paragraph; the rest are whole `## ` sections (heading through the
    line before the next `## `)."""
    if name == "intro":
        return _readme_anchor_intro(lines)
    prefix = _README_HEADINGS.get(name)
    return _readme_anchor_section(lines, prefix) if prefix else None


def _readme_strip_markers(lines):
    """Remove any leftover '<!-- ak:readme:* -->' marker lines and collapse the resulting blank runs to a
    single blank, outside fenced code blocks. Idempotent; un-migrates READMEs that still carry markers."""
    marker = re.compile(r"<!-- ak:readme:.*(START|END) -->$")
    kept, in_fence = [], False
    for ln in lines:
        s = ln.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            kept.append(ln)
            continue
        if not in_fence and marker.match(s):
            continue
        kept.append(ln)
    out, in_fence = [], False
    for ln in kept:
        s = ln.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            out.append(ln)
            continue
        if not in_fence and s == "" and out and out[-1].strip() == "":
            continue
        out.append(ln)
    return out


def _readme_parse_template(path: Path):
    """Return (regions, skeletons). The template holds the markerless Pattern A/B exemplar READMEs in its
    >=4-backtick fenced blocks; regions[name] = canonical content lines, extracted from the Pattern A
    skeleton by the SAME markdown anchors the tool uses on real READMEs (so the standard and the detection
    can never drift apart)."""
    lines = path.read_text(encoding="utf-8").split("\n")
    skel = []
    i = 0
    while i < len(lines):
        f = re.match(r"(`{4,})", lines[i])
        if f and "markdown" in lines[i]:
            fence = f.group(1)
            for j in range(i + 1, len(lines)):
                s = lines[j].strip()
                if s and set(s) == {"`"} and len(s) >= len(fence):
                    skel.append(lines[i + 1:j])
                    i = j
                    break
        i += 1
    skeletons = {}
    if skel:
        skeletons["a"] = "\n".join(skel[0])
    if len(skel) >= 2:
        skeletons["b"] = "\n".join(skel[1])
    regions = {}
    if skel:
        a = skel[0]
        for name in _README_REGIONS:
            span = _readme_region_locate(a, name)
            if span:
                lo, hi = span
                regions[name] = _readme_strip(a[lo:hi])
    return regions, skeletons


def _readme_refresh(lines, regions, skill):
    """Replace each managed region (located by markdown structure) with the canonical content from the
    template, where the region is present. Presence-driven. Returns (new_lines, changed_region_names)."""
    changed = []
    for name in _README_REGIONS:
        if name not in regions:
            continue
        span = _readme_region_locate(lines, name)
        if not span:
            continue
        lo, hi = span
        canonical = [_readme_fill(ln, skill=skill) for ln in regions[name]]
        if lines[lo:hi] != canonical:
            lines = lines[:lo] + canonical + lines[hi:]
            changed.append(name)
    return lines, changed


def _readme_anchor_intro(lines):
    """Span (lo, hi) of the single 'Part of **[Agent Kaizen]' intro paragraph, or None if absent."""
    for i, ln in enumerate(lines):
        if ln.startswith("Part of **[Agent Kaizen]"):
            return (i, i + 1)
    return None


def _readme_anchor_section(lines, prefix):
    """Span (lo, hi) of the `## ` section whose heading starts with `prefix` — heading line through
    the last non-blank line before the next `## ` heading — or None if absent."""
    for i, ln in enumerate(lines):
        if ln.startswith(prefix):
            last, j = i, i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                if lines[j].strip():
                    last = j
                j += 1
            return (i, last + 1)
    return None


def _readme_ensure_full_use_it(lines, content_lines):
    """Ensure a '## Use it' section exists (`content_lines` = the canonical use-it section, heading
    included). If the heading is already present, leave it for refresh; otherwise insert the canonical
    section right after the '## What's inside' section. Returns (new_lines, acted)."""
    if any(l.strip() == "## Use it" for l in lines):
        return lines, False
    wi = next((i for i, l in enumerate(lines) if l.strip() == "## What's inside"), None)
    if wi is None:
        return lines, False
    last, j = wi, wi + 1
    while j < len(lines) and not lines[j].startswith("## "):
        if lines[j].strip():
            last = j
        j += 1
    return lines[:last + 1] + [""] + content_lines + lines[last + 1:], True


def _readme_targets(args, store):
    """Resolve which skill dirs to act on: all of them (`--all`), the named ones, or None if neither
    was given (the caller treats None as a usage error). Unknown names are warned and skipped."""
    dirs = _readme_skill_dirs(store)
    if args.all:
        return dirs
    if args.skills:
        by_name = {d.name: d for d in dirs}
        out = []
        for s in args.skills:
            if s in by_name:
                out.append(by_name[s])
            else:
                print(f"  ! unknown skill: {s}")
        return out
    return None


def _readme_scaffold(args, store, tmpl) -> int:
    """Write a brand-new README.md for one skill from the Pattern A/B skeleton, placeholders filled.

    Refuses to overwrite an existing README without --force. Returns 0 on write, 1 if it would
    overwrite, 2 if the requested pattern has no skeleton in the template.
    """
    regions, skeletons = _readme_parse_template(tmpl)
    if args.pattern not in skeletons:
        print(f"template has no Pattern {args.pattern.upper()} skeleton")
        return 2
    skill = args.skill
    out_dir = Path(args.dir).resolve() if args.dir else (store / skill)
    readme = out_dir / "README.md"
    if readme.exists() and not args.force:
        print(f"refusing to overwrite {readme} (use --force)")
        return 1
    title = args.title if args.title is not None else skill
    tagline = args.tagline if args.tagline is not None else f"_TODO: one-line summary of the {skill} skill._"
    body = _readme_fill(skeletons[args.pattern], skill=skill, title=title,
                        tagline=tagline, article=args.article)
    if not body.endswith("\n"):
        body += "\n"
    out_dir.mkdir(parents=True, exist_ok=True)
    readme.write_text(body, encoding="utf-8", newline="\n")
    print(f"WROTE {readme} (Pattern {args.pattern.upper()})")
    return 0


def _readme_apply(args, store, tmpl) -> int:
    """Refresh the managed regions of existing skill READMEs from the single-sourced standard.

    For each target: strip any legacy markers, optionally ensure a full "Use it" section
    (--ensure-use-it), then replace each present managed region with the template's canonical content.
    Honors --dry-run (no writes) and --check (exit 1 on any drift). Returns the process exit code.
    """
    regions, _ = _readme_parse_template(tmpl)
    targets = _readme_targets(args, store)
    if targets is None:
        print("specify skill name(s) or --all")
        return 2
    rc, drift = 0, False
    for d in targets:
        readme = d / "README.md"
        if not readme.is_file():
            print(f"  ! {d.name}: no README.md")
            rc = max(rc, 1)
            continue
        text = readme.read_text(encoding="utf-8")
        new_lines = _readme_strip_markers(text.split("\n"))
        acted = []
        if args.ensure_use_it and "use-it" in regions:
            canonical = [_readme_fill(ln, skill=d.name) for ln in regions["use-it"]]
            new_lines, did = _readme_ensure_full_use_it(new_lines, canonical)
            if did:
                acted.append("insert use-it")
        new_lines, changed = _readme_refresh(new_lines, regions, d.name)
        acted += changed
        new_text = "\n".join(new_lines)
        if new_text == text:
            print(f"  unchanged {d.name}")
            continue
        if not acted:
            acted = ["stripped markers"]
        if args.check:
            print(f"  DRIFT {d.name}: would update ({', '.join(acted)})")
            drift = True
            continue
        if args.dry_run:
            print(f"  [dry-run] {d.name}: would update ({', '.join(acted)})")
            continue
        readme.write_text(new_text, encoding="utf-8", newline="\n")
        print(f"  WROTE {d.name}: {', '.join(acted)}")
    return 1 if (args.check and drift) else rc


def cmd_readme(argv=None) -> int:
    """Parse the `readme` CLI (`scaffold` | `apply`) and dispatch to the matching handler.

    Resolves the store root and the README standard template, then scaffolds a new README or applies
    the standard to existing ones. Returns the process exit code.
    """
    ap = argparse.ArgumentParser(
        prog="skill_builder.py readme",
        description="Scaffold and maintain skill README.md files from the single-sourced standard "
                    "(references/readme-standard.md).")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--store", help="skills store root (default: the store this script lives in)")
    common.add_argument("--template", help="standard/template file (default: references/readme-standard.md)")
    sub = ap.add_subparsers(dest="op", required=True)

    sp = sub.add_parser("scaffold", parents=[common], help="write a brand-new README.md from the standard")
    sp.add_argument("skill")
    sp.add_argument("--pattern", choices=["a", "b"], default="a",
                    help="a = full domain/reference skill; b = lighter/status-driven (default a)")
    sp.add_argument("--article", choices=["a", "the"], default="the")
    sp.add_argument("--title", default=None)
    sp.add_argument("--tagline", default=None)
    sp.add_argument("--dir", default=None, help="output directory (default: <store>/<skill>)")
    sp.add_argument("--force", action="store_true", help="overwrite an existing README.md")

    sp = sub.add_parser("apply", parents=[common],
                        help="refresh managed regions of existing READMEs (presence-driven)")
    sp.add_argument("skills", nargs="*", help="skill names (or use --all)")
    sp.add_argument("--all", action="store_true", help="every skill in the store")
    sp.add_argument("--ensure-use-it", action="store_true",
                    help="normalize: give every target skill the full 'Use it' section — insert it after "
                         "'What's inside' where absent — then refresh")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="print what would change; write nothing")
    g.add_argument("--check", action="store_true", help="exit 1 if any README is out of date; write nothing")

    args = ap.parse_args(argv)
    store = Path(args.store).resolve() if args.store else _readme_store_root()
    tmpl = Path(args.template).resolve() if args.template else _readme_default_template()
    if not tmpl.is_file():
        print(f"template not found: {tmpl}")
        return 2
    if args.op == "scaffold":
        return _readme_scaffold(args, store, tmpl)
    if args.op == "apply":
        return _readme_apply(args, store, tmpl)
    return 2

def main(argv=None) -> int:
    """Standalone entry point for `python -m builder_components.readme`; delegates to cmd_readme."""
    return cmd_readme(argv)


if __name__ == "__main__":
    raise SystemExit(main())
