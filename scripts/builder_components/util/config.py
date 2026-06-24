"""Shared constants for the build pipeline."""

from __future__ import annotations

#: Path to the all-in-one tool, used as the validator in the SKILL.md Verification command that
#: `finalize` generates and the default the `recontext` promote step runs. Callers append the
#: ``validate`` subcommand token (e.g. ``python {VALIDATOR} validate <dir>``). Repo-relative default;
#: override per-run with ``finalize --validator``.
VALIDATOR = ".agents/skills/skill-drafting/scripts/skill_builder.py"
