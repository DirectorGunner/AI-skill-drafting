# Gotchas And Measurement

## Purpose

Use this reference to capture failures that recur and to improve a skill after first release.

## Gotchas Section

Every nontrivial skill needs a `Gotchas` section. A gotcha is not generic caution. It is a concrete failure mode the model is likely to hit.

Good gotchas:

- Name the failure.
- Say why it happens.
- Tell the agent what to do instead.
- Point to a verifier, reference, or stop condition when possible.

Weak gotchas:

- "Be careful."
- "Do good work."
- "Remember to test."
- Generic style advice that applies to every task.

## Common Skill Failures

- Under-triggering: description omits real user phrases, file types, or tool names.
- Over-triggering: description claims too broad a domain or lacks negative triggers.
- Context bloat: `SKILL.md` includes reference-manual detail instead of routing.
- Missing setup: skill assumes credentials, tools, accounts, or paths.
- Fake verification: final report says checked without evidence.
- No bad-output test: the harness cannot reject shallow or wrong output.
- Script drift: bundled scripts are not run after edits.
- Memory drift: `AGENTS.md` and `CLAUDE.md` no longer match skill routing or permissions.
- Source drift: copied source details become stale or lose attribution.

## Measurement

Measure whether a skill improves work:

- Trigger rate: direct and paraphrased prompts activate the skill.
- False positives: adjacent tasks do not activate it.
- Completion quality: output meets the rubric more often with the skill than without it.
- Clarification quality: the agent asks fewer irrelevant questions and more key-decision questions.
- Tool reliability: scripted checks reduce repeated mistakes.
- User correction rate: recurring user fixes become gotchas or verifier checks.

Use hooks or logs only when supported and allowed. Do not add tracking silently.

## Iteration Loop

When the skill fails:

1. Classify the failure: trigger, scope, setup, workflow, reference, script, verification, or environment.
2. Add the smallest change that would have prevented it.
3. Update gotchas or verifier checks when the failure is likely to recur.
4. Run direct trigger, paraphrased trigger, negative trigger, and workflow tests again.
5. Record residual risk if a realistic test could not be run.

## Review Checklist

- Does the skill still own one coherent job?
- Does the description include concrete trigger phrases?
- Are negative triggers or overlap boundaries clear?
- Is `SKILL.md` lean enough to read quickly?
- Are references routed by task?
- Are gotchas specific and current?
- Is there an observation artifact for output quality?
- Does validation run, and is its output reported honestly?
