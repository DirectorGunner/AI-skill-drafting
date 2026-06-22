# Interview And Spec Gates

## Purpose

Use this reference to collaborate with the user before drafting or changing a skill. The goal is not to ask many questions. The goal is to extract the decisions that determine whether the skill will work.

## Gate 1: Goal And Scope

Confirm:

- Goal: what decision, workflow, or repeated task the skill improves.
- Consumers: who or what will use the skill.
- Scope: the smallest useful version.
- Out of scope: adjacent work to defer.
- Cost of error: low, medium, high, or irreversible.
- Existing examples: prior skills, prompts, outputs, logs, or failed attempts.

Do not proceed if the goal is only "make a good skill." Translate that into observable outcomes.

## Gate 2: Trigger Surface

Confirm:

- Primary skill category.
- Positive trigger phrases.
- Paraphrased trigger phrases.
- Negative triggers and overlap boundaries.
- Required file types, tools, products, or services that should activate the skill.
- Whether the skill should trigger for review, generation, debugging, or all of those.

If the trigger surface is broad, split the work or define a router.

## Gate 3: Package Architecture

Confirm:

- Whether this is a new skill or an update.
- Target runtime: Codex, Claude, both, plugin, or team distribution.
- Files to create or preserve.
- References to include and when to load them.
- Scripts or assets that would improve reliability.
- Setup/config that must be asked for or stored outside disposable skill files.
- Whether `AGENTS.md` or `CLAUDE.md` need proposed changes.

For updates, inspect the existing skill first and preserve unrelated behavior.

## Gate 4: Verification Design

Confirm before implementation:

- Structural checks.
- Trigger tests.
- Negative trigger tests.
- Workflow completion test.
- Quality rubric that distinguishes good output from bad output.
- Observation artifact: command output, test result, screenshot, trace, sample output, or reviewer report.
- Subagent review plan for nontrivial work.

Verification must be designed before drafting. Do not bolt it on at the end.

## Gate 5: Build Plan

Before nontrivial writes, show:

- Final spec.
- Key decisions and assumptions.
- File list.
- Acceptance criteria.
- Verification plan.
- Checkpoints.
- Any approval needed for creating folders, editing memory files, changing hooks, installing dependencies, or overwriting existing files.

Proceed only after the user has confirmed the important decisions.

## During Implementation

Continue interviewing when new facts appear:

- A source contradicts the planned structure.
- A tool, credential, or permission is missing.
- The verifier cannot judge the important quality criteria.
- The skill overlaps an existing skill more than expected.
- A safer staged output would reduce risk.

Ask precise questions with a recommendation. Do not ask the user to decide implementation details that are already clear from repo conventions.

## Planning-Only Requests

If the user asks for a plan, review, gate list, or decision discussion instead of implementation, do not block on live confirmation. Fill every discoverable field from repo context, clearly mark assumptions, and list the decisions that must be confirmed before edits. Treat the output as a decision-ready spec draft, not approval to write files.
