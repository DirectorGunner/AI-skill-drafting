# Subagents And Forward Testing

## Purpose

Use this reference when a skill is complex enough that an independent perspective can catch weak assumptions, unclear triggers, missing verification, or brittle workflow design.

## When To Use Subagents

Use independent subagents when:

- The skill is nontrivial or source-heavy.
- The skill changes high-risk operations, deployment, data access, or review behavior.
- The skill will be reused by a team or shipped publicly.
- The trigger surface overlaps other skills.
- Quality depends on taste, judgment, or multi-step workflow.
- The first draft feels plausible but unproven.

If subagents are unavailable, run separated self-review passes and report that limitation.

Subagents are available only when the current runtime exposes an explicit spawn/manage-subagent tool, an installed plugin/connector that can run independent agents, or a user-provided mechanism for parallel agent work. If no such mechanism is visible, do not imply that forward-testing happened; state that the fallback was a separated self-review. If a subagent tool is visible and the task is nontrivial, prefer using it for at least architecture or quality review unless doing so would create unsafe side effects.

## Roles

Useful subagent roles:

- Architecture reviewer: checks category fit, scope, file split, progressive disclosure, and setup.
- Quality reviewer: checks rubric, observation artifact, verifier, and bad-output rejection.
- Source digester: handles a disjoint source batch and returns original notes with preserve terms.
- Forward-test agent: uses the finished skill on a realistic task without receiving the intended answer.

Keep roles disjoint. Do not ask every subagent the same broad question.

## Prompting Rules

For validation, pass raw artifacts and the task. Do not leak the expected answer, your diagnosis, or your intended fix unless the review explicitly needs it.

For forward-testing, frame the request like a normal user task:

```text
Use the skill at .agents/skills/example-skill to solve this task: ...
```

Avoid:

```text
Review this skill and tell me if it has the weaknesses I suspect.
```

The second prompt contaminates the test.

## Orchestration Rules

- The orchestrator owns shipped file writes and final integration.
- Subagents may produce notes, critique, test outputs, or draft suggestions.
- Assign disjoint source batches or review scopes.
- Reconcile disagreements explicitly.
- Keep a small ledger for large source or multi-agent work.
- Clean or ignore subagent scratch artifacts unless they are part of the evidence trail.

## Forward-Test Signals

Look for:

- Does the skill trigger for the realistic task?
- Does the agent load only relevant references?
- Does it ask the right missing setup questions?
- Does it follow the workflow without over-railroading?
- Does it use the quality harness?
- Does the final output differ materially from what a generic agent would produce?
- Are gotchas actually preventing failures?

Record failures as changes to triggers, workflow, references, scripts, or gotchas.
