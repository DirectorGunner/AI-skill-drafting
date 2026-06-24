"""Shared file-writing helper for the build pipeline.

``write_text`` forces ``\\n`` line endings and creates parent directories — the writer used across
the build/finalize/index/maintain/readme stages. Relocated verbatim from ``skill_builder.py``.

NOTE: the other ``write``/``read`` helpers in the codebase are intentionally NOT consolidated here.
``finalize`` keeps its rstrip-then-newline ``write``; the recontext engine keeps its own
platform-newline ``read``/``write``/``append_jsonl``; the locked recontext writer keeps its
confinement-aware ``_atomic_write_*``. Those differ in newline handling or safety contracts, so
merging them would change behavior.
"""

from __future__ import annotations

from pathlib import Path


def write_text(path: Path, text: str) -> None:
    """Write `text` to `path` as UTF-8 with forced ``\\n`` line endings, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
