"""Minimal YAML-frontmatter reader shared by the validator and the policy manager.

This is the scalar reader: folded multi-line values are space-joined and every value is a string.
It was duplicated byte-for-byte in ``validate_skill_package.py`` and ``skill_policy.py``; this is the
single canonical copy.

NOTE: the build pipeline's ``index`` module keeps its own *richer* ``parse_frontmatter`` (block
scalars + inline/block lists, so values may be lists). That parser has a single caller and is a
genuinely different function, so it is not consolidated here.
"""

from __future__ import annotations

import re

#: Frontmatter delimiter (tolerates CRLF).
FRONTMATTER_RE = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---\r?\n", re.DOTALL)


def parse_frontmatter(text: str) -> dict[str, str]:
    """Read scalar frontmatter values; fold multi-line values with a single space."""
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
