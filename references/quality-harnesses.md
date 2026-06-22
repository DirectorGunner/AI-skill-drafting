# Quality Harnesses

## Purpose

Use this reference to define how a skill's output will be judged. A quality harness is the feedback loop that makes "good skill" observable.

## Harness Components

Define these before implementation:

- Criteria: the binary or observable claims that must pass.
- Positive trigger task: a direct request that should load the skill.
- Paraphrased trigger task: a realistic request that should load it without naming the skill.
- Negative trigger task: adjacent work that should not load it.
- Workflow task: a representative task the skill should help complete.
- Bad-output example or anti-pattern: what the harness should reject.
- Observation artifact: evidence captured while building or testing.

## Observation Artifacts

Choose an artifact the agent can inspect:

- Test output for scripts, libraries, CLIs, and scaffolds.
- Screenshots or browser traces for product verification and frontend behavior.
- Logs, dry-run output, or command traces for runbooks, CI/CD, and operations.
- Sample query results for data analysis.
- Review findings against seeded bad examples for code quality and critique skills.
- Generated files compared against expected structure for templates and scaffolding.

The artifact should change the agent's next action. If it is only ceremonial, redesign it.

## Good-Vs-Bad Rubric

Write a small rubric that rejects bad output:

- Good: the skill triggers for the intended task, routes to the right reference, asks missing setup questions, uses the verifier, and reports evidence.
- Bad: the skill triggers too broadly, skips setup, invents facts, ignores references, lacks gotchas, or claims success without evidence.

For high-risk skills, make the bad cases adversarial and include forbidden actions.

## Verifier Script Design

Prefer a script for structural checks that are easy to automate:

- Frontmatter exists and includes required fields.
- Folder names and skill names match.
- `INDEX.md` and `topics.json` agree.
- Linked reference files exist.
- Required sections exist.
- Placeholders are absent.

Do not pretend a structural verifier proves domain quality. Pair it with workflow tests and observation artifacts.

## Acceptance Report

A final verification report should list:

- Each criterion.
- Evidence used.
- Pass or fail.
- Fixes made after failures.
- Remaining risks or untested paths.

Never present unverified work as verified. If a test cannot run, say why and describe the residual risk.
