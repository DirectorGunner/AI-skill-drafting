"""skill_policy engine — skill discovery, Claude/Codex settings I/O, change computation,
and audit/manifest reporting.

A pure library: no argparse and no stdout policy of its own. The CLI lives in policy_cmd.py, which
imports from here. Stdlib only. Frontmatter parsing and project-root resolution come from
builder_components.util (deduped from the former sibling scripts).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from .util.frontmatter import parse_frontmatter


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



# --------------------------------------------------------------------------- #
# Helpers (adapted from the sibling scripts' conventions)
# --------------------------------------------------------------------------- #
def _stamp() -> str:
    """Return the current local time as a human-readable 'YYYY-MM-DD HH:MM:SS' string."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp_file() -> str:
    """Return the current local time as a filename-safe 'YYYYMMDD-HHMMSS' string."""
    return datetime.now().strftime("%Y%m%d-%H%M%S")




def _work_dir(repo_root: Path) -> Path:
    """Return the AI/work/skill-policy scratch dir under `repo_root`, refusing if it is a skill package."""
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




def _read_text(path: Path) -> str:
    """Read and return the file at `path` as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def _sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of the file at `path`, or "" if it cannot be read."""
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
    """Estimate token count from a character count (~4 chars per token)."""
    return round(chars / 4)


# Minimum Claude Code version reported (community-sourced; unverified by Anthropic
# primary docs) to have working skillOverrides. Used only for an informational note.
CLAUDE_SKILLOVERRIDES_BASELINE = (2, 1, 129)


def _parse_ver(text: str):
    """Return the first 'N.N.N' version in `text` as an int tuple, or None if absent."""
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
    """Return True if `skill_dir` ships a scripts/ directory (treated as a side-effect marker)."""
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
    """Build the full per-skill record (footprint, layout, recommendation, evidence) for one skill.

    Reads SKILL.md frontmatter from `runtime_dir`, classifies the path (store/junction/real), and
    downgrades `controllable` for plugin skills. Returns the record dict.
    """
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
    """Yield each immediate subdirectory of `root` that holds a SKILL.md, skipping dotfiles/INDEX.md."""
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
    """Resolve the Claude settings file for `scope` (local/project/user), honoring `explicit` first.

    Raises ValueError on an unknown scope.
    """
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
    """Return a copy of the settings' skillOverrides map; refuse if it is present but not an object."""
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
    """Return a deep copy of `settings` with `changes` applied to skillOverrides (dropping the key if empty)."""
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
    """Copy `path` into work_dir/backups with a timestamped name; return the backup path ("" if absent)."""
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
    """Summarize surfaced (non-store) skills: count, total footprint chars, and estimated tokens."""
    surfaced = [s for s in skills if s["scope"] != "store"]
    total = sum(s["footprint_chars"] for s in surfaced)
    return {"surfaced_count": len(surfaced), "total_footprint_chars": total, "total_est_tokens": _est_tokens(total)}


def write_audit_report(work_dir: Path, skills, platform: str, settings_path) -> tuple:
    """Write timestamped Markdown and JSON audit reports for `skills` into `work_dir`.

    Returns (md_path, json_path).
    """
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
    """Build a user-editable decision manifest (Claude skills only) with unapproved recommendations."""
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
    """Load and schema-check a decision manifest at `path`; raise RuntimeError on any problem."""
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
