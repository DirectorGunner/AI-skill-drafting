#!/usr/bin/env python3
"""recontext_subagent.py — the locked artifact writer for recontextualization subagents.

A Claude/Codex subagent that recontextualizes a verbatim documentation file MUST go through this
script; it never writes rewrite artifacts with the Write tool. The script is the rail: it derives
every writable path internally, refuses any caller-supplied output path, confines all writes under a
single caller-declared `--work-root`, and — crucially — runs the real cleanup + Gate A/B/C verifier
before it writes anything, so a `PASS` is a *gated* PASS, never an unverified claim.

It is portable and self-contained: no hardcoded skill, owner, repo, or absolute path, and no
dependency on gitignored scratch — all algorithms come from the sibling `recontext_core` module that
ships with the skill.

Subcommands:
  prepare    (orchestrator) Build the assignment + packet under <work-root>/recontext/<skill>/<worker>.
  show       (subagent)     Print the assignment, the rewrite contract, and the work to rewrite.
  submit     (subagent)     Read the rewrite from stdin, splice/clean it, GATE it (A/B/C), and only
                            on PASS write the canonical artifacts. Refuses to write failing work.
  audit      (anyone)       Recursively report misplaced legacy `_pkt_/_rw_/_result_` artifacts.

Modes (per the rewrite contract):
  extract    sparse prose: stdin is {"items":[{"i","cell","text"}]}; spliced back at exact positions.
  full       prose-dense:  stdin is the WHOLE rewritten file text; cleaned + gated in place.

Exit codes: 0 success · 1 validation/gate/audit failure · 2 command-line usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recontext_core as core

try:  # stdin must accept any source glyph regardless of console code page (core does stdout/stderr)
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass


TOOL_NAME = "recontext_subagent"
TOOL_VERSION = "0.2.0"
SCHEMA_VERSION = 2
MIN_RUN = 13
FACTION = 2  # this tool only handles recontextualization (Faction-2) files

SKILL_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}$")
WORKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MODE_CHOICES = ("extract", "full")
ASSIGNMENT_SUBDIR = "recontext"
# Legacy hand-written misplaced-artifact names (the failure this tool exists to prevent). The new
# canonical names (packet.json/rewrite.json/work.md/result.json) deliberately do NOT match this.
LEGACY_ARTIFACT_RE = re.compile(r"^_(?:pkt|rw|result)_.+", re.IGNORECASE)

# A small style denylist of filler tics. NOT a fidelity guard — Gate A/B/C below are the real
# verifier. Kept only to reject obvious boilerplate before the gates run.
STYLE_BANNED_PHRASES = (
    "@@P", "in practice", "as applicable", "for this flow", "in that case",
    "as noted", "for reference", "specifically here", "this item this note",
)


class UsageFailure(Exception):
    """Raised for usage errors that argparse cannot express cleanly (exit 2)."""


class ValidationFailure(Exception):
    """Raised for path, schema, gate, or audit failures (exit 1)."""


def _print(message: str = "") -> None:
    print(message, flush=True)


# --------------------------------------------------------------------------- #
# Path safety — every writable path is derived internally and confined to --work-root.
# --------------------------------------------------------------------------- #
def _resolve(path_text, *, strict: bool = False) -> Path:
    return Path(path_text).resolve(strict=strict)


def _is_under(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _require_under(child: Path, parent: Path, label: str) -> Path:
    child_resolved = _resolve(child)
    parent_resolved = _resolve(parent)
    if child_resolved != parent_resolved and not _is_under(child_resolved, parent_resolved):
        raise ValidationFailure(f"{label} resolves outside the work root: {child_resolved}")
    return child_resolved


def _validate_work_root(value) -> Path:
    """The single writable sandbox, caller-declared. Must already exist (the orchestrator owns it),
    so a typo can't silently create a sandbox in the wrong place. No equality to any fixed path —
    that is what makes the tool portable to any repo."""
    root = _resolve(value)
    if not root.exists():
        raise ValidationFailure(f"--work-root does not exist: {root}")
    if not root.is_dir():
        raise ValidationFailure(f"--work-root is not a directory: {root}")
    return root


def _validate_source_root(value) -> Path:
    root = _resolve(value)
    if not root.exists():
        raise ValidationFailure(f"--source-root does not exist: {root}")
    return root


def _validate_skill(value: str) -> str:
    if not SKILL_RE.fullmatch(value):
        raise ValidationFailure(f"invalid --skill: {value!r}")
    return value


def _validate_worker(value: str) -> str:
    if not WORKER_RE.fullmatch(value) or ".." in value or "/" in value or "\\" in value:
        raise ValidationFailure(f"invalid --worker: {value!r}")
    return value


def _validate_mode(value: str) -> str:
    if value not in MODE_CHOICES:
        raise ValidationFailure(f"invalid --mode: {value!r}")
    return value


def _validate_tier(value: str) -> str:
    if not value or any(ch in value for ch in "\\/\0\r\n"):
        raise ValidationFailure(f"invalid --tier: {value!r}")
    return value


def _validate_rel(value: str, skill: str) -> str:
    normalized = value.replace("\\", "/")
    rel = PurePosixPath(normalized)
    if rel.is_absolute():
        raise ValidationFailure("--rel must be relative")
    if any(part in {"", ".", ".."} for part in rel.parts):
        raise ValidationFailure(f"--rel contains traversal or empty segments: {value!r}")
    if not rel.parts or rel.parts[0] != skill:
        raise ValidationFailure(f"--rel must begin with {skill}/: {value!r}")
    return "/".join(rel.parts)


def _rel_to_path(root: Path, rel: str) -> Path:
    return root.joinpath(*PurePosixPath(rel).parts)


def _assignment_dir(work_root: Path, skill: str, worker: str) -> Path:
    target = work_root / ASSIGNMENT_SUBDIR / skill / worker
    return _require_under(target, work_root, "assignment directory")


def _assignment_paths(adir: Path) -> dict:
    return {
        "assignment": adir / "assignment.json",
        "packet": adir / "packet.json",
        "rewrite": adir / "rewrite.json",
        "work": adir / "work.md",
        "result": adir / "result.json",
    }


def _safe_mkdir(path: Path, work_root: Path) -> None:
    _require_under(path, work_root, "directory")
    path.mkdir(parents=True, exist_ok=True)
    real = _resolve(path, strict=True)
    if real != _resolve(work_root) and not _is_under(real, _resolve(work_root)):
        raise ValidationFailure(f"directory resolves outside work root: {real}")


def _atomic_write_bytes(output: Path, data: bytes, work_root: Path) -> None:
    """Write atomically and confine the *final* landing spot: create the temp under a
    strict-resolved parent with O_EXCL, then re-assert the resolved output is under work_root
    immediately before os.replace. Any failure unlinks the temp so no orphan .tmp is left."""
    out = _require_under(output, work_root, "output path")
    _safe_mkdir(out.parent, work_root)
    tmp = out.with_name(out.name + ".tmp")
    try:
        if tmp.exists():
            tmp.unlink()
        # O_EXCL: never follow/overwrite a pre-existing temp (e.g. a planted symlink)
        fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as handle:  # fdopen owns fd; closes it on exit even on error
            handle.write(data)
        # re-assert containment at the last moment (defends against a swapped parent)
        final = _resolve(out)
        if final != _resolve(output) or (
            final != _resolve(work_root) and not _is_under(final, _resolve(work_root))
        ):
            raise ValidationFailure(f"output path moved outside work root before write: {final}")
        os.replace(tmp, out)
    except BaseException:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _atomic_write_json(output: Path, payload: Any, work_root: Path) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write_bytes(output, text.encode("utf-8"), work_root)


def _atomic_write_text(output: Path, text: str, work_root: Path) -> None:
    if not text.endswith("\n"):
        text += "\n"
    _atomic_write_bytes(output, text.encode("utf-8"), work_root)


def _reject_duplicate_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValidationFailure(f"duplicate JSON key: {key!r}")
        out[key] = value
    return out


def _load_json_file(path: Path, label: str):
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle, object_pairs_hook=_reject_duplicate_pairs)
    except FileNotFoundError as exc:
        raise ValidationFailure(f"missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationFailure(f"malformed {label}: {path}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Packet / rewrite validation (extract mode).
# --------------------------------------------------------------------------- #
def _normalize_packet_items(packet: Any) -> list:
    if not isinstance(packet, dict) or not isinstance(packet.get("items"), list):
        raise ValidationFailure("packet is missing an items list")
    items, seen = [], set()
    for raw in packet["items"]:
        if not isinstance(raw, dict) or "i" not in raw or "cell" not in raw or "text" not in raw:
            raise ValidationFailure("packet item is missing i, cell, or text")
        i, cell, text = raw["i"], raw["cell"], raw["text"]
        if isinstance(i, bool) or not isinstance(i, int):
            raise ValidationFailure(f"packet item has non-integer i: {raw!r}")
        if cell is not None and (isinstance(cell, bool) or not isinstance(cell, int)):
            raise ValidationFailure(f"packet item has malformed cell: {raw!r}")
        if not isinstance(text, str):
            raise ValidationFailure(f"packet item has non-string text: {raw!r}")
        key = (i, cell)
        if key in seen:
            raise ValidationFailure(f"packet has duplicate item key: {key}")
        seen.add(key)
        items.append({"i": i, "cell": cell, "text": text})
    return items


def _check_banned(text: str, where: str) -> None:
    lowered = text.lower()
    for phrase in STYLE_BANNED_PHRASES:
        if phrase.lower() in lowered:
            raise ValidationFailure(f"{where} contains banned filler phrase: {phrase!r}")


def _validate_rewrite_payload(rewrite: Any, packet_items: list) -> list:
    """Strict shape/key/order check of an extract-mode submission against the packet. This is the
    schema rail; fidelity is enforced separately by the gates."""
    if not isinstance(rewrite, dict) or set(rewrite) != {"items"}:
        raise ValidationFailure('rewrite JSON must be exactly {"items":[...]}')
    raw_items = rewrite["items"]
    if not isinstance(raw_items, list):
        raise ValidationFailure("rewrite items must be a list")
    if len(raw_items) != len(packet_items):
        raise ValidationFailure(
            f"rewrite item count {len(raw_items)} does not match packet count {len(packet_items)}")
    expected = [(it["i"], it["cell"]) for it in packet_items]
    seen, normalized = set(), []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict) or set(raw) != {"i", "cell", "text"}:
            raise ValidationFailure("each rewrite item must contain exactly i, cell, and text")
        i, cell, text = raw["i"], raw["cell"], raw["text"]
        if isinstance(i, bool) or not isinstance(i, int):
            raise ValidationFailure(f"rewrite item has non-integer i at offset {index}")
        if cell is not None and (isinstance(cell, bool) or not isinstance(cell, int)):
            raise ValidationFailure(f"rewrite item has malformed cell at offset {index}")
        if not isinstance(text, str):
            raise ValidationFailure(f"rewrite item has non-string text at offset {index}")
        pair = (i, cell)
        if pair in seen:
            raise ValidationFailure(f"duplicate rewrite item key: {pair}")
        seen.add(pair)
        if pair != expected[index]:
            raise ValidationFailure(
                f"rewrite item key/order mismatch at offset {index}: {pair} != {expected[index]}")
        _check_banned(text, f"rewrite item {pair}")
        normalized.append({"i": i, "cell": cell, "text": text})
    if set(expected) != seen:
        missing = sorted(set(expected) - seen)
        extra = sorted(seen - set(expected))
        raise ValidationFailure(f"rewrite keys do not match packet; missing={missing} extra={extra}")
    return normalized


# --------------------------------------------------------------------------- #
# Assignment load / validate.
# --------------------------------------------------------------------------- #
_ASSIGNMENT_KEYS = {
    "schema_version", "tool", "generated_utc", "skill", "worker", "rel",
    "source", "source_root", "work_root", "mode", "tier", "faction", "paths",
}


def _load_assignment(work_root: Path, skill: str, worker: str):
    skill = _validate_skill(skill)
    worker = _validate_worker(worker)
    adir = _assignment_dir(work_root, skill, worker)
    paths = _assignment_paths(adir)
    assignment = _load_json_file(paths["assignment"], "assignment")
    if not isinstance(assignment, dict) or set(assignment) != _ASSIGNMENT_KEYS:
        raise ValidationFailure("assignment has unexpected schema")
    if assignment["schema_version"] != SCHEMA_VERSION:
        raise ValidationFailure("unsupported assignment schema_version")
    if assignment["tool"] != TOOL_NAME:
        raise ValidationFailure("assignment was not created by this tool")
    if assignment["skill"] != skill or assignment["worker"] != worker:
        raise ValidationFailure("assignment skill/worker does not match request")
    mode = _validate_mode(str(assignment["mode"]))
    _validate_tier(str(assignment["tier"]))
    rel = _validate_rel(str(assignment["rel"]), skill)
    source_root = _validate_source_root(str(assignment["source_root"]))
    source = _resolve(str(assignment["source"]), strict=True)
    _require_under(source, source_root, "assignment source")
    expected_source = _resolve(_rel_to_path(source_root, rel), strict=True)
    if source != expected_source:
        raise ValidationFailure(f"assignment source does not match rel: {source} != {expected_source}")
    # the stored paths must be exactly the canonical derived ones (no caller-chosen output paths)
    canonical = {k: str(v) for k, v in paths.items() if k != "assignment"}
    if assignment["paths"] != canonical:
        raise ValidationFailure("assignment paths do not match the canonical derived paths")
    for label, p in paths.items():
        if label != "assignment":
            _require_under(p, work_root, f"{label} path")
    return assignment, paths, source, mode


# --------------------------------------------------------------------------- #
# Commands.
# --------------------------------------------------------------------------- #
def cmd_prepare(args: argparse.Namespace) -> int:
    work_root = _validate_work_root(args.work_root)
    source_root = _validate_source_root(args.source_root)
    skill = _validate_skill(args.skill)
    worker = _validate_worker(args.worker)
    rel = _validate_rel(args.rel, skill)
    mode = _validate_mode(args.mode)
    tier = _validate_tier(args.tier)

    source = _resolve(_require_under(_resolve(args.source), source_root, "source"), strict=True)
    expected_source = _resolve(_rel_to_path(source_root, rel), strict=True)
    if source != expected_source:
        raise ValidationFailure(f"--source must equal --source-root plus --rel: {source} != {expected_source}")

    adir = _assignment_dir(work_root, skill, worker)
    paths = _assignment_paths(adir)
    if paths["assignment"].exists() and not paths["result"].exists() and not args.force:
        raise ValidationFailure(
            f"a live (unsubmitted) assignment already exists for {skill}/{worker}; "
            f"pass --force to overwrite or use a distinct --worker")
    _safe_mkdir(adir, work_root)

    source_text = core.read(source)
    item_count = None
    if mode == "extract":
        packet = core.extract(source_text)
        packet["file"] = str(source)
        items = _normalize_packet_items(packet)
        if not items:
            raise ValidationFailure("extract mode found no prose units; this file is Faction-1 (use full or cleanup)")
        _atomic_write_json(paths["packet"], packet, work_root)
        item_count = len(items)

    assignment = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "generated_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "skill": skill,
        "worker": worker,
        "rel": rel,
        "source": str(source),
        "source_root": str(source_root),
        "work_root": str(work_root),
        "mode": mode,
        "tier": tier,
        "faction": FACTION,
        "paths": {k: str(v) for k, v in paths.items() if k != "assignment"},
    }
    _atomic_write_json(paths["assignment"], assignment, work_root)
    detail = f"items={item_count}" if mode == "extract" else "whole-file"
    _print(f"PASS prepare skill={skill} worker={worker} mode={mode} {detail} dir={adir}")
    return 0


def _contract_lines(mode: str) -> list:
    common = [
        "- Submit ONLY through `recontext_subagent submit` (stdin); never write artifacts yourself.",
        "- Preserve EXACTLY: identifiers, API/class/method names, namespaced tokens (Foo::Bar),"
        " commands/flags/env vars, file paths, numbers+units, enum values, UI labels, bold setting"
        " names, every fenced code block and inline-code span, and all link targets/URLs.",
        "- Reword narrative prose so no run of ~13+ words matches the source. Do NOT invent facts,"
        " params, or versions; do NOT add an 'Inspired by'/source line.",
        "- submit runs the real cleanup + Gate A (identifiers) + Gate B (13-word residue) +"
        " Gate C (cruft). It writes ONLY on a passing gate, so a PASS is verified, not assumed.",
    ]
    if mode == "extract":
        return [
            '- Return exactly {"items":[{"i":...,"cell":...,"text":"..."}]} with the packet item'
            " order unchanged (same i/cell keys, same count).",
        ] + common
    return [
        "- Return the WHOLE rewritten file as raw text on stdin (not JSON). Reword every prose unit"
        " in place; leave code/signatures/tables structurally intact. If the source flattened code"
        " into prose, wrap it in a fenced block or `inline code` byte-for-byte.",
    ] + common


def cmd_show(args: argparse.Namespace) -> int:
    work_root = _validate_work_root(args.work_root)
    assignment, paths, source, mode = _load_assignment(work_root, args.skill, args.worker)
    _print("PASS show")
    _print("ASSIGNMENT")
    _print(json.dumps(assignment, ensure_ascii=False, indent=2, sort_keys=True))
    _print("REWRITE CONTRACT")
    for line in _contract_lines(mode):
        _print(line)
    if mode == "extract":
        packet = _load_json_file(paths["packet"], "packet")
        _print("PACKET")
        _print(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print("SOURCE (rewrite the whole file; return raw text on stdin)")
        _print(core.read(source))
    return 0


def _verdict_fields(verdict: dict) -> dict:
    gb = verdict["gate_b"]
    return {
        "status": "up-to-standard",
        "gate_a": bool(verdict["gate_a"]["passed"]),
        "gate_b_residue": int(gb.get("runs_remaining", 0)),
        "gate_b_ratio": gb.get("ratio"),
        "gate_c": bool(verdict["gate_c"]["passed"]),
    }


def _gate_or_fail(source_text: str, work_text: str) -> dict:
    verdict = core.run_gates(source_text, work_text, faction=FACTION, min_run=MIN_RUN)
    if not verdict["passed"]:
        reasons = []
        if not verdict["gate_a"]["passed"]:
            reasons.append(f"Gate A lost identifiers: {verdict['gate_a']['hard_fail_categories']} "
                           f"{verdict['gate_a']['lost']}")
        if verdict["gate_b"]["required"] and not verdict["gate_b"]["passed"]:
            reasons.append(f"Gate B residue ({verdict['gate_b']['runs_remaining']} run(s)): "
                           f"{verdict['gate_b']['runs'][:5]}")
        if not verdict["gate_c"]["passed"]:
            reasons.append(f"Gate C cruft ({verdict['gate_c']['count']}): {verdict['gate_c']['cruft_lines'][:5]}")
        raise ValidationFailure("rewrite failed the gates; nothing was written. " + " | ".join(reasons))
    return verdict


def cmd_submit(args: argparse.Namespace) -> int:
    work_root = _validate_work_root(args.work_root)
    assignment, paths, source, mode = _load_assignment(work_root, args.skill, args.worker)
    source_text = core.read(source)

    raw_stdin = sys.stdin.read()
    if not raw_stdin.strip():
        raise ValidationFailure("submit requires the rewrite on stdin")

    rw_path = None
    if mode == "extract":
        packet_items = _normalize_packet_items(_load_json_file(paths["packet"], "packet"))
        try:
            rewrite = json.loads(raw_stdin, object_pairs_hook=_reject_duplicate_pairs)
        except json.JSONDecodeError as exc:
            raise ValidationFailure(f"rewrite JSON did not parse: {exc}") from exc
        normalized = _validate_rewrite_payload(rewrite, packet_items)
        work_text, _stats = core.splice(source_text, normalized)
        verdict = _gate_or_fail(source_text, work_text)
        _atomic_write_json(paths["rewrite"], {"items": normalized}, work_root)
        rw_path = str(paths["rewrite"])
    else:  # full
        _check_banned(raw_stdin, "submitted file")
        work_text, _actions = core.clean_text(raw_stdin, core.skill_title(assignment["skill"]))
        verdict = _gate_or_fail(source_text, work_text)
        rw_path = str(paths["work"])

    _atomic_write_text(paths["work"], work_text, work_root)

    fields = _verdict_fields(verdict)
    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL_NAME,
        "skill": assignment["skill"],
        "worker": assignment["worker"],
        "verification": {
            "gates_run": True,
            "faction": FACTION,
            "min_run": MIN_RUN,
            "checks": ["schema", "banned_phrases", "gate_a", "gate_b", "gate_c"],
        },
        "files": [{
            "rel": assignment["rel"],
            "mode": mode,
            "tier": assignment["tier"],
            "rw": rw_path,                 # extract: rewrite.json · full: work.md (the integrator key)
            "work": str(paths["work"]),    # the gated, recontextualized file
            **fields,
            "needs_review": False,
            "notes": "",
        }],
        "errors": [],
    }
    _atomic_write_json(paths["result"], result, work_root)
    _print(f"PASS submit skill={assignment['skill']} worker={assignment['worker']} mode={mode} "
           f"gate_a={fields['gate_a']} gate_b_residue={fields['gate_b_residue']} "
           f"gate_c={fields['gate_c']} result={paths['result']}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    """Recursively report misplaced legacy `_pkt_/_rw_/_result_` artifacts (case-insensitive) and
    reparse points anywhere under --root. Read-only: never deletes or moves anything."""
    root = _resolve(args.root, strict=True)
    if not root.is_dir():
        raise ValidationFailure(f"--root is not a directory: {root}")
    skip = {p.lower() for p in (args.skip or [])}
    offenders, links = [], []
    for dirpath, dirnames, filenames in os.walk(root):
        # prune skipped subtrees (e.g. .git, node_modules, the legitimate work tree)
        dirnames[:] = [d for d in dirnames if (Path(dirpath) / d).resolve().as_posix().lower() not in skip
                       and d.lower() not in {".git", "node_modules", "__pycache__"}]
        for name in filenames:
            if LEGACY_ARTIFACT_RE.match(name):
                offenders.append(Path(dirpath) / name)
        try:
            for d in dirnames:
                p = Path(dirpath) / d
                if os.path.islink(str(p)) or (
                    hasattr(os.lstat(str(p)), "st_file_attributes")
                    and os.lstat(str(p)).st_file_attributes & 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    links.append(p)
        except OSError:
            pass
    if offenders or links:
        _print(f"FAIL audit found {len(offenders)} misplaced artifact(s), {len(links)} reparse point(s):")
        for p in sorted(offenders):
            _print(f"  artifact: {p}")
        for p in sorted(links):
            _print(f"  reparse:  {p}")
        return 1
    _print(f"PASS audit: no misplaced artifacts under {root}")
    return 0


# --------------------------------------------------------------------------- #
# CLI.
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Locked, gated, portable artifact writer for recontextualization subagents.",
    )
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("--work-root", required=True,
                        help="the single writable sandbox (must already exist); all writes are confined here")
        sp.add_argument("--skill", required=True)
        sp.add_argument("--worker", required=True)

    prepare = sub.add_parser("prepare", help="build the assignment + packet")
    add_common(prepare)
    prepare.add_argument("--source", required=True, help="the read-only source file to recontextualize")
    prepare.add_argument("--source-root", required=True, help="the read-only source tree --source lives under")
    prepare.add_argument("--rel", required=True, help="source path relative to --source-root, starting with <skill>/")
    prepare.add_argument("--mode", required=True, choices=list(MODE_CHOICES))
    prepare.add_argument("--tier", required=True)
    prepare.add_argument("--force", action="store_true", help="overwrite an existing unsubmitted assignment")
    prepare.set_defaults(func=cmd_prepare)

    show = sub.add_parser("show", help="display the assignment, contract, and work to rewrite")
    add_common(show)
    show.set_defaults(func=cmd_show)

    submit = sub.add_parser("submit", help="gate the rewrite from stdin and write artifacts on PASS")
    add_common(submit)
    submit.set_defaults(func=cmd_submit)

    audit = sub.add_parser("audit", help="recursively report misplaced legacy artifacts / reparse points")
    audit.add_argument("--root", required=True, help="tree to scan")
    audit.add_argument("--skip", action="append", help="absolute subtree path to skip (repeatable)")
    audit.set_defaults(func=cmd_audit)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        return int(args.func(args))
    except UsageFailure as exc:
        _print(f"USAGE {TOOL_NAME}: {exc}")
        return 2
    except ValidationFailure as exc:
        _print(f"FAIL {args.command}: {exc}")
        return 1
    except Exception as exc:  # never surface a raw traceback that a subagent might "fix" by hand
        _print(f"FAIL {args.command}: unexpected {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
