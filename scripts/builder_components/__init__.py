"""builder_components — the skill-drafting tooling package.

One importable home for the skill build/maintain pipeline (`skill_builder`), the package
validator, the skill-invocation-policy manager, and the recontextualization engine + locked
writer. The loose scripts in `scripts/` are thin launchers that delegate here so every
documented invocation path (and the VALIDATOR path baked into built skills' SKILL.md) keeps
working. Shared, single-concern helpers live under `builder_components.util`.

Stdlib only; no third-party dependencies.
"""
