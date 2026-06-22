# Skill Drafting References - Index

Start here after reading `SKILL.md`. Each reference is a focused decision aid. Load only what the task needs.

| Component | Summary | Read this when |
| --- | --- | --- |
| [skill-package-anatomy.md](skill-package-anatomy.md) | Required and optional skill package pieces, trigger frontmatter, and progressive disclosure rules. | Choosing files, folder shape, or `SKILL.md` structure. |
| [interview-spec-gates.md](interview-spec-gates.md) | User collaboration gates for goal, scope, triggers, architecture, verification, and implementation. | Turning a vague request into a decision-complete skill spec. |
| [source-digestion-and-fidelity.md](source-digestion-and-fidelity.md) | How to synthesize source material without raw dumps or renamed facts. | Building skill references from PDFs, docs, repos, notes, or existing skills. |
| [quality-harnesses.md](quality-harnesses.md) | Rubrics, observation artifacts, and tests that distinguish good skill output from bad output. | Defining done or designing verification. |
| [subagents-and-forward-testing.md](subagents-and-forward-testing.md) | When and how to use independent agents for critique, source digestion, and realistic skill tests. | The skill is nontrivial, high-risk, source-heavy, or likely to drift. |
| [memory-hooks-and-environment.md](memory-hooks-and-environment.md) | Memory-file assessment, hooks, guardrails, setup, durable data, and tool enablement. | A skill needs repo policy, tools, credentials, hooks, or long-lived preferences. |
| [category-patterns.md](category-patterns.md) | The 9 skill categories and their usual anatomy, observation methods, and tests. | Selecting the primary skill type or avoiding a confused multi-job skill. |
| [gotchas-and-measurement.md](gotchas-and-measurement.md) | Recurring failure modes, iteration loops, usage measurement, and trigger tuning. | Reviewing a skill, adding gotchas, or improving an existing package. |

## Recommended Reading Paths

- **New skill from sparse request:** interview-spec-gates -> category-patterns -> skill-package-anatomy -> quality-harnesses.
- **Source-backed skill:** source-digestion-and-fidelity -> skill-package-anatomy -> quality-harnesses.
- **Complex or high-risk skill:** interview-spec-gates -> subagents-and-forward-testing -> memory-hooks-and-environment -> quality-harnesses.
- **Skill review or update:** gotchas-and-measurement -> quality-harnesses -> skill-package-anatomy.
