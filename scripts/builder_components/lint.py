"""Link / topics health check (was the lint section of skill_builder.py)."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from builder_components.util.repo_paths import _project_ai_dir
from .maintain import ref_files, subskill_dirs


# ==============================================================================
# LINT — link/topics health check (was lint_skill.py)
# ==============================================================================

_LINK = re.compile(r"(?<!!)\]\(([^)#?]+\.md)(?:#[^)]*)?\)")


def lint_subskill(sk: Path) -> dict:
    """Check one (sub)skill's references for dangling local .md links and topics.json drift, returning
    {dangling, missing_in_topics, dangling_topics} issue lists."""
    refs = sk / "references"
    issues = {"dangling": [], "missing_in_topics": [], "dangling_topics": []}
    if not refs.is_dir():
        return issues
    files = ref_files(refs)
    names = {p.name for p in files}

    # dangling local links — resolve each target relative to the SOURCE file's own directory, so a
    # SKILL.md link to GOTCHA.md (a sibling) or a reference's sibling link resolves correctly.
    for src in [refs / "INDEX.md", sk / "SKILL.md", *files]:
        if not src.is_file():
            continue
        for tgt in _LINK.findall(src.read_text(encoding="utf-8")):
            if "://" in tgt:                       # online link (e.g. https://…/x.md) — not a local file
                continue
            if not (src.parent / tgt).is_file():
                issues["dangling"].append(f"{src.name} -> {tgt}")

    # topics.json <-> files drift
    tj = refs / "topics.json"
    if tj.is_file():
        listed = set()
        try:
            listed = {Path(t.get("file", "")).name
                      for t in json.loads(tj.read_text(encoding="utf-8")).get("topics", [])}
        except Exception:
            pass
        issues["missing_in_topics"] = sorted(names - listed)
        issues["dangling_topics"] = sorted(listed - names)
    return issues


def cmd_lint(argv=None) -> int:
    """Run the `lint` subcommand: check each (sub)skill for link/topics issues, write a report to the
    out dir, and print a summary. Returns 0 when clean, 1 otherwise."""
    ap = argparse.ArgumentParser(prog="skill_builder.py lint")
    ap.add_argument("skill")
    ap.add_argument("--out", default=None,
                    help="report directory (default: <project-root>/AI/lint, resolved from $DEVROOT/CWD)")
    args = ap.parse_args(argv)
    skill = Path(args.skill)
    name = skill.name
    out_dir = Path(args.out) if args.out else _project_ai_dir(skill.resolve(), "AI", "lint")

    lines = [f"# Lint: {name}", ""]
    totals = {"dangling": 0, "missing_in_topics": 0, "dangling_topics": 0}
    for sk in subskill_dirs(skill):
        iss = lint_subskill(sk)
        label = sk.name if sk is not skill else "(flat)"
        flagged = {k: v for k, v in iss.items() if v}
        for k, v in iss.items():
            totals[k] += len(v)
        if flagged:
            lines.append(f"## {label}")
            for k, v in flagged.items():
                lines.append(f"- **{k}** ({len(v)}): " + "; ".join(v[:25]) + (" …" if len(v) > 25 else ""))
            lines.append("")
    clean = sum(totals.values()) == 0
    if clean:
        lines.append("Clean — no link/content issues found.")

    out = out_dir / f"{name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8", newline="\n")
    summary = "clean" if clean else ", ".join(f"{k}={v}" for k, v in totals.items() if v)
    print(f"{name}: {summary}  -> {out.as_posix()}")
    return 0 if clean else 1

def main(argv=None) -> int:
    """Standalone entry point for `python -m builder_components.lint`; delegates to cmd_lint."""
    return cmd_lint(argv)


if __name__ == "__main__":
    raise SystemExit(main())
