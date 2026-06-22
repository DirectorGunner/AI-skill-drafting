# Memory Hooks And Environment

## Purpose

Use this reference when a skill depends on repo policy, tools, hooks, credentials, setup, or durable memory. A skill works best when the environment supports it instead of making every chat rebuild the same context.

## Memory Files

Inspect `AGENTS.md` and `CLAUDE.md` before drafting a repo-local skill. Assess whether they need changes to:

- Route agents to the new skill.
- Clarify allowed work roots.
- Name required tools or MCP servers.
- Set permission tiers.
- Point to durable references.
- Explain hooks or guardrails.
- Keep Codex and Claude behavior aligned.

Propose memory-file edits when useful, but do not apply them without explicit user approval.

## Hooks And Guardrails

Use prose for low-risk preferences. Use explicit confirmation for medium-risk decisions. Use tool-level guardrails for high-risk or irreversible actions.

Possible guardrails:

- Preflight scripts.
- Validation scripts.
- Git clean/dirty checks.
- Scoped write roots.
- Hook prompts for dangerous commands.
- Dry-run requirements.
- Human approval gates for destructive, costly, or external actions.

Do not claim a guardrail exists unless it is actually installed or documented.

## Setup And Config

If a skill needs setup, decide where it belongs:

- Ask the user each time when the value is sensitive, task-specific, or rarely used.
- Store stable non-secret preferences in a config file when the repo has a convention.
- Store durable memory outside disposable skill upgrade paths when the platform supports it.
- Never store secrets in examples, references, logs, or skill files.

The skill should state what happens when setup is missing.

## Tool Enablement

For tool-backed skills, document:

- Required tools and versions.
- Authentication checks.
- Safe test command.
- Expected output or health signal.
- Failure handling and fallback.
- Stop conditions.

The skill teaches ordering, judgment, defaults, and recovery. Tool access alone is not a workflow.

## Environment Assessment Block

Before implementation, include an assessment like this in the spec:

- Existing memory files inspected: yes or no.
- New routing needed: yes or no.
- Tool or hook support needed: yes or no.
- Proposed memory edits: list or none.
- Approval required before memory/hook edits: yes.

This makes environment needs visible without silently changing repo policy.
