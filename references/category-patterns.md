# Skill Use-Case Categories

## Purpose

Classify a skill before designing it: name the one primary category it serves, so the package shape and
verification match the job and the skill does not sprawl into several unrelated jobs.

These three categories are Anthropic's, from the official [Complete Guide to Building Skills for Claude](https://resources.anthropic.com/hubfs/The-Complete-Guide-to-Building-Skill-for-Claude.pdf)
(section "Common skill use case categories" — "At Anthropic, we've observed three common use cases").

## 1. Document & Asset Creation

Use when the skill's job is producing consistent, high-quality artifacts — documents, slides,
spreadsheets, designs, web frontends, or code. The work leans on Claude's built-in generation rather
than external tools.

Typical contents: embedded style guides and brand standards, reusable templates that fix the output
shape, and a quality checklist the skill runs before declaring an artifact finished.

Observation: render or build the artifact and check it against the embedded checklist and templates.

## 2. Workflow Automation

Use when the skill encodes a multi-step process that should run the same disciplined way every time —
including processes that coordinate several MCP servers. The value is a repeatable methodology, not a
one-off answer.

Typical contents: an ordered, step-by-step workflow with validation gates between steps, templates for
the structures each step emits, and built-in review or refinement loops.

Observation: run the workflow end to end and confirm each gate caught what it should before the next
step proceeded.

## 3. MCP Enhancement

Use when the skill exists to get more out of the tools an MCP server already exposes — turning raw tool
access into a guided, expert workflow.

Typical contents: the right sequence of MCP calls, the domain context a user would otherwise have to
supply by hand, and explicit handling for the server's common error cases.

Observation: exercise the MCP calls against a real or recorded server and confirm the call sequence and
error handling behave as documented.

## Choosing the shape

Name one primary category and route secondary concerns through references. Split a skill into separate
skills when it has two different trigger surfaces, serves two different users, or needs different tools
and verification for its parts.
