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
import json
import os
import sys
from pathlib import Path

from .util.repo_paths import _find_repo_root
from .policy_engine import (
    ABSENT,
    TOOL_VERSION,
    _claude_version_note,
    _ensure_work_gitignore,
    _footprint_summary,
    _read_text,
    _stamp,
    _stamp_file,
    _work_dir,
    apply_changes_to_settings,
    approved_decisions,
    atomic_write_json,
    backup_file,
    build_manifest,
    compute_changes,
    discover_claude,
    discover_codex,
    get_overrides,
    load_manifest,
    load_settings,
    resolve_settings_path,
    write_audit_report,
)


# --------------------------------------------------------------------------- #
# Subcommands
# --------------------------------------------------------------------------- #
def _context(args):
    """Resolve common run context from `args`: (repo_root, project_dir, home, work_dir, settings_path)."""
    cwd = Path.cwd()
    repo_root = _find_repo_root(cwd)
    project_dir = repo_root
    home = Path(os.path.expanduser("~"))
    work_dir = _work_dir(repo_root)
    settings_path = resolve_settings_path(args.scope, project_dir, home, args.settings)
    return repo_root, project_dir, home, work_dir, settings_path


def cmd_audit(args) -> int:
    """Run the read-only `audit` action: inventory skills, write a report, print the footprint."""
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
    """Run the `plan` action: write a user-editable, unapproved decision manifest for Claude skills."""
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
    """Load the manifest and compute the effective changes shared by preview/apply.

    Returns (manifest_path, target, settings, current, decisions, changes, work_dir).
    """
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
    """Print each change as 'op name before -> after' (ABSENT rendered as 'default(on)')."""
    if not changes:
        print("  (no effective changes)")
        return
    for ch in changes:
        before = "default(on)" if ch["before"] == ABSENT else ch["before"]
        after = "default(on)" if ch["after"] == ABSENT else ch["after"]
        print(f"  {ch['op']:<7} {ch['name']:<24} {before}  ->  {after}")


def cmd_preview(args) -> int:
    """Run the read-only `preview` action: show the exact changes `apply` would make."""
    manifest_path, target, settings, current, decisions, changes, work_dir = _diff_for(args, False)
    print(f"preview: manifest {manifest_path}")
    print(f"  target settings: {target}")
    print(f"  approved decisions: {len(decisions)}")
    _print_changes(changes)
    print("PASS preview (no writes)")
    return 0


def cmd_apply(args) -> int:
    """Run the `apply` action: back up, atomically write approved Claude skillOverrides, and record rollback.

    Honors --dry-run (no writes), the user-scope C-drive guard, and interactive/--yes confirmation.
    """
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
    """Run the `restore` action: revert exactly the keys a prior apply changed, using its rollback record.

    Uses the newest rollback record when --record is omitted; honors --dry-run.
    """
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
    """Build the argparse parser with shared options and the audit/plan/preview/apply/restore subcommands."""
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--platform", choices=("claude", "codex", "both"), default="both")
    parent.add_argument("--scope", choices=("local", "project", "user"), default="local")
    parent.add_argument("--settings", default=None, help="explicit settings file (overrides --scope)")
    parent.add_argument("--skills-root", action="append", default=[], help="extra skill root(s); repeatable")
    parent.add_argument("--include-store", nargs="?", const="", default=None,
                        help="also enumerate store skills not yet surfaced (default: <repo>/skills)")
    parent.add_argument("--manifest", default=None, help="decision manifest path")
    parent.add_argument("--json", action="store_true", help="machine-readable stdout")

    ap = argparse.ArgumentParser(prog="skill_builder.py policy", description="Manage skill invocation policy (Claude apply; Codex audit-only).")
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


def cmd_policy(argv=None) -> int:
    """Run the skill-invocation-policy manager: the `policy` subcommand of `skill_builder.py`.

    Parses the policy argument vector (the `audit`/`plan`/`preview`/`apply`/`restore` subparsers from
    `build_parser`) and dispatches to the matching `cmd_*` handler. `audit` (read-only) is the default
    when no recognized subcommand is given, so a bare `policy` invocation is always safe. Returns the
    process exit code (0 ok, 1 on a handled RuntimeError, 2 on usage error). Reads ``sys.argv[1:]`` when
    ``argv`` is None.
    """
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


def main(argv=None) -> int:
    """Standalone entry point for `python -m builder_components.policy_cmd`; delegates to cmd_policy."""
    return cmd_policy(argv)


if __name__ == "__main__":
    raise SystemExit(main())
