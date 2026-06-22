#!/usr/bin/env python3
"""Validate a Codex/Claude skill package using lightweight stdlib checks.

Usage:
  python validate_skill_package.py <skill_dir>
      Validate a single (leaf) skill directory.
  python validate_skill_package.py --package <router_dir>
      Validate a router skill plus every product subskill beneath it, and
      check routing integrity, in one run. A router does not need its own
      references/ corpus; each immediate subdirectory that contains a
      SKILL.md is treated as a product subskill and validated as a leaf.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---\r?\n", re.DOTALL)
# Only flag genuine authoring placeholders. Documentation legitimately contains
# angle brackets (HTML/XML samples, code placeholders like <YOUR_CLIENT_ID>), so a
# generic <...> rule produces false positives on real reference content.
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD)\b")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_frontmatter(text: str) -> dict[str, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    values: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in match.group("body").splitlines():
        if not raw_line.strip():
            continue
        if raw_line.startswith((" ", "\t")) and current_key:
            values[current_key] = values[current_key] + " " + raw_line.strip().strip("'\"")
            continue
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        current_key = key.strip()
        values[current_key] = value.strip().strip("'\"")
    return values


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def validate_frontmatter(skill_dir: Path, errors: list[str]) -> str:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        fail(errors, "SKILL.md is missing")
        return ""
    text = read_text(skill_md)
    frontmatter = parse_frontmatter(text)
    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")
    if not name:
        fail(errors, "SKILL.md frontmatter is missing name")
    if not description:
        fail(errors, "SKILL.md frontmatter is missing description")
    if name and not NAME_RE.fullmatch(name):
        fail(errors, f"skill name is not kebab-case: {name}")
    if name and name != skill_dir.name:
        fail(errors, f"skill name does not match folder name: {name} != {skill_dir.name}")
    trigger_terms = ("use when", "when", "trigger", "fires", "asks", "working with")
    if description and not any(term in description.lower() for term in trigger_terms):
        fail(errors, "description lacks concrete trigger language")
    required_sections = ("workflow", "references", "verification")
    lower_text = text.lower()
    for section in required_sections:
        if section not in lower_text:
            fail(errors, f"SKILL.md is missing {section} guidance")
    # Gotchas may live inline in SKILL.md OR in a sibling GOTCHA.md it references.
    gotcha_path = skill_dir / "GOTCHA.md"
    has_gotcha_file = gotcha_path.is_file()
    if "gotchas" not in lower_text and not has_gotcha_file:
        fail(errors, "SKILL.md is missing gotchas guidance (inline, or a sibling GOTCHA.md)")
    if has_gotcha_file and not read_text(gotcha_path).strip():
        fail(errors, "GOTCHA.md is present but empty")
    if "gotcha.md" in lower_text and not has_gotcha_file:
        fail(errors, "SKILL.md references GOTCHA.md but no sibling GOTCHA.md exists")
    return text


def validate_references(skill_dir: Path, errors: list[str]) -> None:
    references_dir = skill_dir / "references"
    index_path = references_dir / "INDEX.md"
    topics_path = references_dir / "topics.json"
    if not references_dir.is_dir():
        fail(errors, "references/ directory is missing")
        return
    if not index_path.is_file():
        fail(errors, "references/INDEX.md is missing")
    if not topics_path.is_file():
        fail(errors, "references/topics.json is missing")
        return
    try:
        topics_doc = json.loads(read_text(topics_path))
    except json.JSONDecodeError as exc:
        fail(errors, f"references/topics.json is invalid JSON: {exc}")
        return
    topics = topics_doc.get("topics")
    if not isinstance(topics, list) or not topics:
        fail(errors, "references/topics.json has no topics array")
        return
    index_text = read_text(index_path) if index_path.is_file() else ""
    seen_files: set[str] = set()
    for idx, topic in enumerate(topics, start=1):
        if not isinstance(topic, dict):
            fail(errors, f"topic {idx} is not an object")
            continue
        file_value = topic.get("file")
        topic_name = topic.get("topic")
        summary = topic.get("summary")
        keywords = topic.get("keywords")
        if not topic_name:
            fail(errors, f"topic {idx} is missing topic")
        if not summary:
            fail(errors, f"topic {idx} is missing summary")
        if not isinstance(keywords, list) or not keywords:
            fail(errors, f"topic {idx} is missing keywords")
        if not isinstance(file_value, str) or not file_value.startswith("references/"):
            fail(errors, f"topic {idx} has invalid file value")
            continue
        if file_value in seen_files:
            fail(errors, f"duplicate topic file in topics.json: {file_value}")
        seen_files.add(file_value)
        ref_path = skill_dir / file_value
        if not ref_path.is_file():
            fail(errors, f"topic file does not exist: {file_value}")
            continue
        if file_value.replace("references/", "") not in index_text:
            fail(errors, f"topic file is not listed in references/INDEX.md: {file_value}")


def check_placeholder_text(rel: str, text: str, errors: list[str]) -> None:
    in_fence = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence or "allow-placeholder" in line:
            continue  # code samples legitimately contain TODO/TBD
        # Strip inline-code spans first: a `TODO`/`TBD` referenced in prose (e.g. the
        # instruction "mark it `TODO` — never invent") is legitimate, not an unfilled placeholder.
        if PLACEHOLDER_RE.search(re.sub(r"`[^`]*`", "", line)):
            fail(errors, f"placeholder-like text in {rel}:{line_number}")


def validate_placeholders(skill_dir: Path, errors: list[str]) -> None:
    # Placeholder/TODO checks target the AUTHORED surface (SKILL.md and the
    # references index/metadata). Ingested reference content legitimately contains
    # words like "TBD"/"TODO" (e.g. version tables, source headings), so it is exempt.
    for rel in ("SKILL.md", "references/INDEX.md", "references/topics.json"):
        path = skill_dir / rel
        if path.is_file():
            check_placeholder_text(rel, read_text(path), errors)


def validate_leaf(skill_dir: Path) -> list[str]:
    errors: list[str] = []
    if not skill_dir.exists():
        return [f"skill directory does not exist: {skill_dir}"]
    if not skill_dir.is_dir():
        return [f"skill path is not a directory: {skill_dir}"]
    validate_frontmatter(skill_dir, errors)
    validate_references(skill_dir, errors)
    validate_placeholders(skill_dir, errors)
    return errors


def discover_subskills(router_dir: Path) -> list[Path]:
    return sorted(
        d for d in router_dir.iterdir()
        if d.is_dir() and (d / "SKILL.md").is_file()
    )


def validate_router(router_dir: Path) -> tuple[list[str], list[Path]]:
    """Validate a router skill. references/ is optional; subskills are required.

    Returns (router_errors, subskill_dirs).
    """
    errors: list[str] = []
    if not router_dir.is_dir():
        return [f"router path is not a directory: {router_dir}"], []
    validate_frontmatter(router_dir, errors)
    # A router routes to product subskills and need not ship its own corpus.
    # Validate references/ only if the router chooses to keep one.
    if (router_dir / "references").is_dir():
        validate_references(router_dir, errors)
    skill_md = router_dir / "SKILL.md"
    router_text = read_text(skill_md) if skill_md.is_file() else ""
    if skill_md.is_file():
        check_placeholder_text("SKILL.md", router_text, errors)
    subskills = discover_subskills(router_dir)
    if not subskills:
        fail(errors, "router has no product subskills (no immediate subdir with a SKILL.md)")
    for sub in subskills:
        if sub.name not in router_text:
            fail(errors, f"subskill not referenced in router SKILL.md: {sub.name}")
    return errors, subskills


def validate(skill_dir: Path) -> list[str]:
    # Backward-compatible single-leaf entry point.
    return validate_leaf(skill_dir)


def _report(label: str, target: Path, errors: list[str]) -> bool:
    if errors:
        print(f"FAIL{label}: {target}")
        for error in errors:
            print(f"- {error}")
        return False
    print(f"PASS{label}: {target}")
    return True


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 2 and args[0] == "--package":
        router_dir = Path(args[1]).resolve()
        router_errors, subskills = validate_router(router_dir)
        ok = _report(" (router)", router_dir, router_errors)
        for sub in subskills:
            ok = _report("", sub, validate_leaf(sub)) and ok
        print(f"PACKAGE {'PASS' if ok else 'FAIL'}: {router_dir} ({len(subskills)} subskills)")
        return 0 if ok else 1
    if len(args) != 1:
        print("Usage: python validate_skill_package.py [--package] <skill_directory>", file=sys.stderr)
        return 2
    skill_dir = Path(args[0]).resolve()
    errors = validate(skill_dir)
    _report("", skill_dir, errors)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
