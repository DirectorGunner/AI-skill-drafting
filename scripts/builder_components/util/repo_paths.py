"""Project-root resolution for default scratch paths.

``_find_repo_root`` resolves the VS Code *project* that owns a path — deliberately climbing past
per-skill repos so default ``AI/work`` / ``AI/lint`` scratch never lands inside a skill package.
Was duplicated byte-for-byte (modulo docstring) in ``skill_builder.py`` and ``skill_policy.py``.
"""

from __future__ import annotations

import os
from pathlib import Path


def _find_repo_root(start) -> Path:
    """The VS Code project root that owns `start`: the immediate child of $DEVROOT containing it
    (%DEVROOT%\\<project>), else the nearest enclosing repo/workspace that is NOT a per-skill package.
    Every skills/<name>/ is its own git repo (its root has SKILL.md), so resolving to the nearest .git
    would wrongly land inside a skill; this climbs past skills to the owning project. Keeps default
    AI/lint and AI/work scratch at the project root, never inside a skill, regardless of CWD."""
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


def _project_ai_dir(start, *parts) -> Path:
    """Default AI/ scratch path under the owning project root; refuses to land inside a skill package."""
    root = _find_repo_root(start)
    if (root / "SKILL.md").is_file():  # guard: fail loudly rather than pollute a skill
        raise SystemExit(f"refusing to write {'/'.join(parts)} inside a skill package: {root}")
    return root.joinpath(*parts)
