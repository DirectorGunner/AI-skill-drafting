#!/usr/bin/env python3
"""Manage skill *invocation policy* across Claude Code and (read-only) Codex.

Every installed skill costs idle context: at session start each platform injects
each skill's name + description into the model's listing before any invocation.
This tool lets you keep rarely-used skills installed and explicitly invocable while
hiding them from the model's automatic listing -- WITHOUT modifying the clean source
skill repos.

Actions (default is read-only):
  audit     Inventory skills in the selected scope(s)/platform(s); show current
            policy + an estimated idle-listing footprint; write a report. No writes.
  plan      Generate a user-editable decision manifest (JSON) pre-filled with
            recommendations. Recommendations are NEVER auto-approved.
  preview   Show the exact change `apply` would make from a manifest. No writes.
  apply     Apply ONLY approved decisions (Claude skillOverrides). Backup + atomic
            write + rollback record. An empty/zero-approval selection makes NO changes.
  restore   Revert a previous apply using its rollback record.

Platform support:
  Claude    Fully managed. Writes `skillOverrides` into a Claude settings file
            (default: <project>/.claude/settings.local.json -- what the /skills menu
            writes). States: on / name-only / user-invocable-only / off. Reverting a
            skill to default removes its key (absent => on).
  Codex     AUDIT-ONLY. Codex has no central per-skill *policy* override (config.toml
            `[[skills.config]]` is enable/disable-by-path only), and explicit-only
            local skills are currently unreliable to invoke (open bug
            https://github.com/openai/codex/issues/23454). This tool therefore reports
            Codex skills and never writes Codex config or agents/openai.yaml.

Stdlib only. Mirrors conventions of the sibling scripts (PASS/FAIL stdout, exit
0 ok / 1 failure / 2 usage; AI/work/ scratch; YYYY-MM-DD HH:mm:ss stamps).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

TOOL_VERSION = "skill_policy 0.1.0"

# Claude skillOverrides states (https://code.claude.com/docs/en/skills).
CLAUDE_STATES = ("on", "name-only", "user-invocable-only", "off")
DEFAULT_POLICY = "on"  # a skill absent from skillOverrides is treated as "on"
ABSENT = "<absent>"    # sentinel recorded when a skill has no override key

# Broadly-applicable skills: high missed-use cost -> recommend leaving them "on".
# Everything else is treated as specialized -> recommend "user-invocable-only"
# (adjust per project: keep "on" where the project actually uses that domain).
BROAD_SKILLS = frozenset(
    {"git", "github", "cli-design", "powershell-vsdevshell", "skill-drafting"}
)

WORK_SUBDIR = ("AI", "work", "skill-policy")
WORK_GITIGNORE_CONTENT = "*\n*/\n!.gitignore\n"
WORK_GITIGNORE_REQUIRED = ("*", "*/", "!.gitignore")

FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---\r?\n", re.DOTALL)


# --------------------------------------------------------------------------- #
# Helpers (adapted from the sibling scripts' conventions)
# --------------------------------------------------------------------------- #
def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp_file() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _find_repo_root(start: Path) -> Path:
    """The VS Code project root that owns `start`: the immediate child of $DEVROOT containing it
    (%DEVROOT%\\<project>), else the nearest enclosing repo/workspace that is NOT a per-skill package.
    Every skills/<name>/ is its own git repo (its root has SKILL.md), so resolving to the nearest .git
    would wrongly land inside a skill; this resolver climbs past skills to the owning project."""
    current = Path(start).resolve()
    devroot = os.environ.get("DEVROOT")
    if devroot:
        dr = Path(devroot).resolve()
        for path in (current, *current.parents):
            if path.parent == dr:
                if not (path / "SKILL.md").is_file():
                    return path
                break  # a skill sits directly under DEVROOT; fall through to the climb
    for path in (current, *current.parents):
        if (path / "SKILL.md").is_file():
            continue  # never resolve to a per-skill package
        if (path / ".git").exists() or (path / "AGENTS.md").is_file():
            return path
    return current


def _work_dir(repo_root: Path) -> Path:
    if (repo_root / "SKILL.md").is_file():  # guard: never write AI/work inside a skill package
        raise RuntimeError(f"refusing to use AI/work inside a skill package: {repo_root}")
    return repo_root.joinpath(*WORK_SUBDIR)


def _ensure_work_gitignore(work_dir: Path) -> None:
    """Keep repo-local scratch under AI/work untracked by default (codex script pattern)."""
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        gitignore = work_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(WORK_GITIGNORE_CONTENT, encoding="utf-8")
            return
        text = gitignore.read_text(encoding="utf-8")
        active = {
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        missing = [p for p in WORK_GITIGNORE_REQUIRED if p not in active]
        if missing:
            prefix = "" if not text or text.endswith(("\n", "\r")) else "\n"
            with gitignore.open("a", encoding="utf-8") as handle:
                handle.write(prefix)
                handle.write("\n# Protect local skill-policy work products.\n")
                for pattern in missing:
                    handle.write(pattern + "\n")
    except OSError as exc:
        raise RuntimeError(
            f"could not verify {work_dir}/.gitignore safety ({type(exc).__name__})"
        ) from exc


def parse_frontmatter(text: str) -> dict:
    """Minimal YAML-frontmatter reader (folded multi-line values supported).

    Adapted from validate_skill_package.py so name/description are read the same way.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}
    values: dict = {}
    current_key = None
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


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _is_link_to(path: Path):
    """Return the real target if `path` is a junction/symlink, else None."""
    try:
        real = os.path.realpath(str(path))
    except OSError:
        return None
    if os.path.normcase(os.path.abspath(str(path))) != os.path.normcase(real):
        return real
    return None


def _est_tokens(chars: int) -> int:
    return round(chars / 4)


# Minimum Claude Code version reported (community-sourced; unverified by Anthropic
# primary docs) to have working skillOverrides. Used only for an informational note.
CLAUDE_SKILLOVERRIDES_BASELINE = (2, 1, 129)


def _parse_ver(text: str):
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(g) for g in m.groups()) if m else None


def _version_ge(installed: str, baseline=CLAUDE_SKILLOVERRIDES_BASELINE):
    """True/False if comparable, else None (unparseable)."""
    parsed = _parse_ver(installed)
    if parsed is None:
        return None
    return parsed >= tuple(baseline)


def _claude_version_note() -> str:
    """Best-effort, informational only. Never blocks."""
    import subprocess  # local import: only when auditing Claude
    try:
        out = subprocess.run(
            ["claude", "--version"], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return "Claude version: not detected (skillOverrides needs >= 2.1.129; community-sourced figure)."
    ge = _version_ge(out)
    ver = (_parse_ver(out) or ("?",))
    ver_s = ".".join(str(p) for p in ver)
    if ge is True:
        return f"Claude {ver_s}: skillOverrides supported."
    if ge is False:
        return f"WARNING: Claude {ver_s} may predate working skillOverrides (>= 2.1.129)."
    return "Claude version: unparseable; assuming skillOverrides works."


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def _layout(skill_dir: Path) -> str:
    """flat | router(N): a router has immediate subdirs that each carry a SKILL.md."""
    try:
        subs = [
            d for d in skill_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()
        ]
    except OSError:
        subs = []
    return f"router({len(subs)})" if subs else "flat"


def _has_side_effects(skill_dir: Path) -> bool:
    return (skill_dir / "scripts").is_dir()


def _recommend(name: str) -> tuple:
    """Return (recommended_policy, confidence, rationale). Transparent rubric."""
    if name in BROAD_SKILLS:
        return ("on", "high", "broadly-applicable; high missed-use cost -> keep available")
    return (
        "user-invocable-only",
        "medium",
        "specialized; low missed-use cost in a mixed project -- set to 'on' if this project uses it",
    )


def _make_skill_record(
    name: str,
    runtime_dir: Path,
    platform: str,
    scope: str,
    current_policy: str,
    controllable: bool,
) -> dict:
    skill_md = runtime_dir / "SKILL.md"
    text = _read_text(skill_md) if skill_md.is_file() else ""
    fm = parse_frontmatter(text)
    display_name = fm.get("name", name)
    description = fm.get("description", "")
    name_len = len(display_name)
    desc_len = len(description)
    footprint = name_len + desc_len
    target = _is_link_to(runtime_dir)
    if scope == "store":
        path_kind = "store (not surfaced)"
        source_path = str(runtime_dir)
    elif target:
        path_kind = "junction-to-source"
        source_path = target
    else:
        path_kind = "real"
        source_path = str(runtime_dir)
    rec, conf, rationale = _recommend(name)
    warnings = []
    real = (target or str(runtime_dir)).replace("\\", "/").lower()
    if "/plugins/" in real:
        controllable = False
        warnings.append("plugin skill -- not controllable via skillOverrides; manage via /plugin")
    return {
        "id": f"{platform}::{scope}::{name}",
        "name": name,
        "display_name": display_name,
        "platform": platform,
        "scope": scope,
        "source_path": source_path,
        "runtime_path": str(runtime_dir),
        "path_kind": path_kind,
        "skill_md_chars": len(text),
        "skill_md_lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
        "name_len": name_len,
        "desc_len": desc_len,
        "footprint_chars": footprint,
        "est_tokens": _est_tokens(footprint),
        "layout": _layout(runtime_dir),
        "breadth": "broad" if name in BROAD_SKILLS else "specialized",
        "side_effects": _has_side_effects(runtime_dir),
        "current_policy": current_policy,
        "recommended_policy": rec,
        "confidence": conf,
        "rationale": rationale,
        "controllable": controllable,
        "warnings": warnings,
        "source_evidence": {
            "skill_md_sha256": _sha256_file(skill_md),
            "git_head": "(informational; NOT validated)",
        },
    }


def _iter_skill_dirs(root: Path):
    if not root.is_dir():
        return
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name == "INDEX.md":
            continue
        if (child / "SKILL.md").is_file():
            yield child


def discover_claude(
    project_dir: Path,
    extra_roots,
    overrides: dict,
    include_store,
) -> list:
    """Discover Claude skills from <project>/.claude/skills + extra roots (+ store)."""
    found = {}
    roots = [(project_dir / ".claude" / "skills", "project")]
    for r in extra_roots or []:
        roots.append((Path(r), "explicit"))
    for root, scope in roots:
        for skill_dir in _iter_skill_dirs(root):
            name = skill_dir.name
            policy = overrides.get(name, DEFAULT_POLICY)
            rec = _make_skill_record(name, skill_dir, "claude", scope, policy, True)
            found.setdefault(name, rec)
    if include_store is not None:
        store = Path(include_store)
        for skill_dir in _iter_skill_dirs(store):
            name = skill_dir.name
            if name in found:
                continue
            # Not surfaced -> no idle cost yet; policy entry (if any) is inert.
            policy = overrides.get(name, DEFAULT_POLICY)
            current = "not surfaced (0)" if policy == DEFAULT_POLICY else f"{policy} (inert until surfaced)"
            found[name] = _make_skill_record(name, skill_dir, "claude", "store", current, True)
    return list(found.values())


def discover_codex(project_dir: Path, home: Path) -> list:
    """AUDIT-ONLY discovery of Codex skills (project .agents/skills + ~/.codex/skills)."""
    out = []
    seen = set()
    roots = [
        (project_dir / ".agents" / "skills", "project"),
        (project_dir / ".codex" / "skills", "project-legacy"),
        (home / ".codex" / "skills", "user-legacy"),
        (home / ".agents" / "skills", "user"),
    ]
    for root, scope in roots:
        for skill_dir in _iter_skill_dirs(root):
            key = (scope, skill_dir.name)
            if key in seen:
                continue
            seen.add(key)
            rec = _make_skill_record(
                skill_dir.name, skill_dir, "codex", scope, "implicit (default)", False
            )
            rec["advisory"] = (
                "Codex audit-only: no central per-skill policy override; explicit-only "
                "invocation is currently unreliable (openai/codex#23454)."
            )
            out.append(rec)
    return out


# --------------------------------------------------------------------------- #
# Claude settings I/O
# --------------------------------------------------------------------------- #
def resolve_settings_path(scope: str, project_dir: Path, home: Path, explicit) -> Path:
    if explicit:
        return Path(explicit)
    if scope == "local":
        return project_dir / ".claude" / "settings.local.json"
    if scope == "project":
        return project_dir / ".claude" / "settings.json"
    if scope == "user":
        return home / ".claude" / "settings.json"
    raise ValueError(f"unknown scope: {scope}")


def load_settings(path: Path) -> dict:
    """Return parsed settings, or {} if the file is missing. Refuse malformed JSON."""
    if not path.exists():
        return {}
    raw = _read_text(path)
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"refusing to touch malformed JSON settings file: {path} ({exc})"
        )
    if not isinstance(data, dict):
        raise RuntimeError(f"settings root is not a JSON object: {path}")
    return data


def get_overrides(settings: dict) -> dict:
    ov = settings.get("skillOverrides", {})
    if ov in (None, {}):
        return {}
    if not isinstance(ov, dict):
        raise RuntimeError("existing skillOverrides is not a JSON object; refusing to edit")
    return dict(ov)


def compute_changes(current_overrides: dict, decisions) -> list:
    """decisions: iterable of (name, selected_policy). Return effective changes only."""
    changes = []
    for name, selected in decisions:
        if selected not in CLAUDE_STATES:
            raise RuntimeError(f"invalid policy '{selected}' for skill '{name}'")
        before = current_overrides.get(name, ABSENT)
        after = ABSENT if selected == "on" else selected  # "on" == default == remove key
        if before == after:
            continue
        op = "remove" if after == ABSENT else ("set" if before == ABSENT else "change")
        changes.append({"name": name, "before": before, "after": after, "op": op})
    return changes


def apply_changes_to_settings(settings: dict, changes) -> dict:
    new = json.loads(json.dumps(settings))  # deep copy, preserves unknown keys
    overrides = dict(new.get("skillOverrides", {}) or {})
    for ch in changes:
        if ch["after"] == ABSENT:
            overrides.pop(ch["name"], None)
        else:
            overrides[ch["name"]] = ch["after"]
    if overrides:
        new["skillOverrides"] = overrides
    else:
        new.pop("skillOverrides", None)
    return new


def atomic_write_json(path: Path, obj: dict) -> None:
    """Write JSON atomically (temp in same dir, validate, os.replace). Strict JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2) + "\n"
    json.loads(text)  # validate before replacing the live file
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".skillpolicy-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def backup_file(path: Path, work_dir: Path) -> str:
    if not path.exists():
        return ""
    backups = work_dir / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    dest = backups / f"{path.name}.{_stamp_file()}.bak"
    dest.write_bytes(path.read_bytes())
    return str(dest)


# --------------------------------------------------------------------------- #
# Reports & manifest
# --------------------------------------------------------------------------- #
def _footprint_summary(skills) -> dict:
    surfaced = [s for s in skills if s["scope"] != "store"]
    total = sum(s["footprint_chars"] for s in surfaced)
    return {"surfaced_count": len(surfaced), "total_footprint_chars": total, "total_est_tokens": _est_tokens(total)}


def write_audit_report(work_dir: Path, skills, platform: str, settings_path) -> tuple:
    work_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp_file()
    md_path = work_dir / f"audit-{platform}-{stamp}.md"
    json_path = work_dir / f"audit-{platform}-{stamp}.json"
    fp = _footprint_summary(skills)
    lines = [
        f"# Skill invocation policy audit ({platform})",
        "",
        f"- Generated: {_stamp()}",
        f"- Tool: {TOOL_VERSION}",
        f"- Settings file: {settings_path}",
        f"- Surfaced skills: {fp['surfaced_count']} | est. idle listing ~{fp['total_est_tokens']} tokens",
        "",
        "| Skill | Platform | Scope | Current | ~tokens | Breadth | Side-fx | Recommended | Conf | Controllable |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in sorted(skills, key=lambda x: (x["platform"], x["scope"], x["name"])):
        lines.append(
            "| {name} | {platform} | {scope} | {current_policy} | {est_tokens} | {breadth} | {sfx} | {rec} | {conf} | {ctrl} |".format(
                sfx="yes" if s["side_effects"] else "-",
                rec=s["recommended_policy"] if s["platform"] == "claude" else "(audit-only)",
                conf=s["confidence"] if s["platform"] == "claude" else "-",
                ctrl="yes" if s["controllable"] else "no",
                **s,
            )
        )
    lines += [
        "",
        "Recommendations assume a general/mixed project; keep a domain skill `on` where the "
        "project uses it. Codex rows are audit-only (no central policy override; explicit-only "
        "currently unreliable per openai/codex#23454). Footprint is an estimate (name+description "
        "chars / 4), not exact token usage.",
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    json_path.write_text(
        json.dumps({"generated": _stamp(), "tool": TOOL_VERSION, "platform": platform,
                    "settings_path": str(settings_path), "footprint": fp, "skills": skills},
                   indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )
    return md_path, json_path


def build_manifest(skills, platform: str, scope: str, settings_path) -> dict:
    rows = []
    for s in skills:
        if s["platform"] != "claude":
            continue  # only Claude is appliable
        rows.append({
            "id": s["id"],
            "name": s["name"],
            "display_name": s["display_name"],
            "platform": "claude",
            "scope": s["scope"],
            "source_path": s["source_path"],
            "runtime_path": s["runtime_path"],
            "path_kind": s["path_kind"],
            "current_policy": s["current_policy"],
            "recommended_policy": s["recommended_policy"],
            "selected_policy": None,   # user fills; null = no change
            "approved": False,         # must be true to apply
            "rationale": s["rationale"],
            "warnings": s["warnings"],
            "controllable": s["controllable"],
            "expected_operations": [],
            "source_evidence": s["source_evidence"],
        })
    return {
        "schema_version": 1,
        "generated": _stamp(),
        "tool": TOOL_VERSION,
        "platform": platform,
        "scope": {"type": scope, "settings_path": str(settings_path)},
        "skills": rows,
    }


def load_manifest(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"decision manifest not found: {path} (run `plan` first)")
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"manifest is not valid JSON: {path} ({exc})")
    if data.get("schema_version") != 1:
        raise RuntimeError("unsupported manifest schema_version (expected 1)")
    if not isinstance(data.get("skills"), list):
        raise RuntimeError("manifest has no skills array")
    return data


def approved_decisions(manifest: dict) -> list:
    """Return [(name, selected_policy)] for approved, controllable Claude rows only."""
    out = []
    for row in manifest.get("skills", []):
        if row.get("platform") != "claude":
            continue
        if not row.get("approved"):
            continue
        if row.get("controllable") is False:
            print(f"  ! skipping '{row.get('name')}': {('; '.join(row.get('warnings') or [])) or 'not controllable'}")
            continue
        sel = row.get("selected_policy")
        if sel is None:
            continue
        out.append((row.get("name"), sel))
    return out


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #
def _context(args):
    cwd = Path.cwd()
    repo_root = _find_repo_root(cwd)
    project_dir = repo_root
    home = Path(os.path.expanduser("~"))
    work_dir = _work_dir(repo_root)
    settings_path = resolve_settings_path(args.scope, project_dir, home, args.settings)
    return repo_root, project_dir, home, work_dir, settings_path


def cmd_audit(args) -> int:
    repo_root, project_dir, home, work_dir, settings_path = _context(args)
    _ensure_work_gitignore(work_dir)
    settings = load_settings(settings_path)
    overrides = get_overrides(settings)
    include_store = None
    if args.include_store is not None:
        include_store = args.include_store or str(repo_root / "skills")
    skills = []
    if args.platform in ("claude", "both"):
        skills += discover_claude(project_dir, args.skills_root, overrides, include_store)
    if args.platform in ("codex", "both"):
        skills += discover_codex(project_dir, home)
    md_path, json_path = write_audit_report(work_dir, skills, args.platform, settings_path)
    fp = _footprint_summary(skills)
    if args.json:
        print(json.dumps({"footprint": fp, "skills": skills}, indent=2))
    else:
        print(f"audit: {len(skills)} skills | settings: {settings_path}")
        if args.platform in ("claude", "both"):
            print(f"  {_claude_version_note()}")
        print(f"  surfaced idle listing ~{fp['total_est_tokens']} tokens across {fp['surfaced_count']} skills")
        for s in sorted(skills, key=lambda x: (x["platform"], x["name"])):
            tag = "" if s["platform"] == "claude" else " [audit-only]"
            print(f"  - {s['platform']}/{s['scope']:<13} {s['name']:<22} cur={s['current_policy']:<28} "
                  f"~{s['est_tokens']}t rec={s['recommended_policy'] if s['platform']=='claude' else '-'}{tag}")
        print(f"  report: {md_path}")
        print(f"  report: {json_path}")
    print("PASS audit (read-only)")
    return 0


def cmd_plan(args) -> int:
    repo_root, project_dir, home, work_dir, settings_path = _context(args)
    _ensure_work_gitignore(work_dir)
    settings = load_settings(settings_path)
    overrides = get_overrides(settings)
    include_store = None
    if args.include_store is not None:
        include_store = args.include_store or str(repo_root / "skills")
    skills = discover_claude(project_dir, args.skills_root, overrides, include_store)
    manifest = build_manifest(skills, "claude", args.scope, settings_path)
    manifest_path = Path(args.manifest) if args.manifest else work_dir / f"decisions-{args.scope}.json"
    if manifest_path.exists() and not args.force:
        print(f"FAIL plan: manifest already exists: {manifest_path} (use --force to overwrite)", file=sys.stderr)
        return 1
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"plan: wrote {len(manifest['skills'])} Claude skills to {manifest_path}")
    print("  Edit it: set selected_policy + approved:true for the skills you choose, then `preview` / `apply`.")
    print("  Recommendations are NOT decisions; nothing is applied until you approve.")
    print("PASS plan")
    return 0


def _diff_for(args, require_changes_for_apply):
    repo_root, project_dir, home, work_dir, settings_path = _context(args)
    manifest_path = Path(args.manifest) if args.manifest else work_dir / f"decisions-{args.scope}.json"
    manifest = load_manifest(manifest_path)
    # The manifest records the settings file it was planned against; honor an explicit override.
    target = Path(args.settings) if args.settings else Path(manifest.get("scope", {}).get("settings_path", settings_path))
    settings = load_settings(target)
    current = get_overrides(settings)
    decisions = approved_decisions(manifest)
    changes = compute_changes(current, decisions)
    return manifest_path, target, settings, current, decisions, changes, work_dir


def _print_changes(changes) -> None:
    if not changes:
        print("  (no effective changes)")
        return
    for ch in changes:
        before = "default(on)" if ch["before"] == ABSENT else ch["before"]
        after = "default(on)" if ch["after"] == ABSENT else ch["after"]
        print(f"  {ch['op']:<7} {ch['name']:<24} {before}  ->  {after}")


def cmd_preview(args) -> int:
    manifest_path, target, settings, current, decisions, changes, work_dir = _diff_for(args, False)
    print(f"preview: manifest {manifest_path}")
    print(f"  target settings: {target}")
    print(f"  approved decisions: {len(decisions)}")
    _print_changes(changes)
    print("PASS preview (no writes)")
    return 0


def cmd_apply(args) -> int:
    manifest_path, target, settings, current, decisions, changes, work_dir = _diff_for(args, True)
    if args.dry_run:
        print(f"apply --dry-run: target {target}")
        _print_changes(changes)
        print("PASS apply --dry-run (no writes)")
        return 0
    if not decisions:
        print("apply: no approved decisions in manifest -> no changes.")
        print("PASS apply (nothing to do)")
        return 0
    if not changes:
        print("apply: approved decisions already match current settings -> no changes (idempotent).")
        print("PASS apply (nothing to do)")
        return 0
    # C-drive guard for user scope.
    if args.scope == "user" and not args.yes:
        print(f"FAIL apply: --scope user targets {target} (C: drive). Re-run with --yes to confirm.", file=sys.stderr)
        return 1
    print(f"apply: {len(changes)} change(s) to {target}")
    _print_changes(changes)
    if not args.yes and sys.stdin.isatty():
        resp = input("Proceed? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("apply: aborted by user -> no changes.")
            return 0
    elif not args.yes and not sys.stdin.isatty():
        print("FAIL apply: non-interactive run requires --yes to confirm.", file=sys.stderr)
        return 1
    backup = backup_file(target, work_dir)
    new_settings = apply_changes_to_settings(settings, changes)
    atomic_write_json(target, new_settings)
    record = {
        "stamp": _stamp(),
        "tool": TOOL_VERSION,
        "settings_path": str(target),
        "backup_path": backup,
        "manifest_path": str(manifest_path),
        "changes": changes,
    }
    rec_path = work_dir / f"rollback-{_stamp_file()}.json"
    rec_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"  backup:   {backup or '(none; file did not exist)'}")
    print(f"  rollback: {rec_path}")
    print("  NOTE: start a new Claude Code session for the change to take effect; verify via /skills and /context.")
    print("PASS apply")
    return 0


def cmd_restore(args) -> int:
    repo_root, project_dir, home, work_dir, settings_path = _context(args)
    if args.record:
        rec_path = Path(args.record)
    else:
        records = sorted(work_dir.glob("rollback-*.json"))
        if not records:
            print(f"FAIL restore: no rollback records found in {work_dir}", file=sys.stderr)
            return 1
        rec_path = records[-1]
    record = json.loads(_read_text(rec_path))
    target = Path(record["settings_path"])
    settings = load_settings(target)
    # Surgically revert exactly the keys this apply changed.
    revert = [{"name": ch["name"], "before": ch["after"], "after": ch["before"], "op": "restore"}
              for ch in record["changes"]]
    if args.dry_run:
        print(f"restore --dry-run from {rec_path} -> {target}")
        _print_changes(revert)
        print("PASS restore --dry-run (no writes)")
        return 0
    backup = backup_file(target, work_dir)
    new_settings = apply_changes_to_settings(settings, revert)
    atomic_write_json(target, new_settings)
    print(f"restore: reverted {len(revert)} key(s) in {target} (from {rec_path})")
    print(f"  pre-restore backup: {backup or '(none)'}")
    print("PASS restore")
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--platform", choices=("claude", "codex", "both"), default="both")
    parent.add_argument("--scope", choices=("local", "project", "user"), default="local")
    parent.add_argument("--settings", default=None, help="explicit settings file (overrides --scope)")
    parent.add_argument("--skills-root", action="append", default=[], help="extra skill root(s); repeatable")
    parent.add_argument("--include-store", nargs="?", const="", default=None,
                        help="also enumerate store skills not yet surfaced (default: <repo>/skills)")
    parent.add_argument("--manifest", default=None, help="decision manifest path")
    parent.add_argument("--json", action="store_true", help="machine-readable stdout")

    ap = argparse.ArgumentParser(prog="skill_policy.py", description="Manage skill invocation policy (Claude apply; Codex audit-only).")
    sub = ap.add_subparsers(dest="action")

    sub.add_parser("audit", parents=[parent], help="read-only inventory + current policy + footprint")

    p_plan = sub.add_parser("plan", parents=[parent], help="generate a decision manifest (unapproved)")
    p_plan.add_argument("--force", action="store_true", help="overwrite an existing manifest")

    sub.add_parser("preview", parents=[parent], help="show the exact change apply would make")

    p_apply = sub.add_parser("apply", parents=[parent], help="apply approved Claude decisions")
    p_apply.add_argument("--yes", action="store_true", help="non-interactive confirm")
    p_apply.add_argument("--dry-run", action="store_true", help="preview semantics; no writes")

    p_restore = sub.add_parser("restore", parents=[parent], help="roll back a previous apply")
    p_restore.add_argument("--record", default=None, help="rollback record (default: newest)")
    p_restore.add_argument("--dry-run", action="store_true", help="show revert; no writes")
    return ap


_DISPATCH = {
    "audit": cmd_audit,
    "plan": cmd_plan,
    "preview": cmd_preview,
    "apply": cmd_apply,
    "restore": cmd_restore,
}


def main(argv=None) -> int:
    ap = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    # Default action is `audit` (read-only). If the first token is not a known
    # subcommand and not a top-level help flag, treat the run as `audit ...`.
    if not raw or (raw[0] not in _DISPATCH and raw[0] not in ("-h", "--help")):
        raw = ["audit"] + raw
    args = ap.parse_args(raw)
    action = args.action or "audit"
    if action not in _DISPATCH:
        ap.print_help()
        return 2
    try:
        return _DISPATCH[action](args)
    except RuntimeError as exc:
        print(f"FAIL {action}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
