# Category Patterns

## Purpose

Use this reference to classify a skill before designing it. Classification prevents one skill from becoming several unrelated jobs.

## 1. Library And API Reference

Use when the agent needs exact guidance for a library, CLI, SDK, internal platform, or fragile API.

Typical resources: API examples, command patterns, gotchas, version notes, validation snippets.

Observation: import checks, sample commands, unit tests, or minimal runnable examples.

## 2. Product Verification

Use when the agent needs to prove product behavior works.

Typical resources: Playwright flows, screenshots, logs, selectors, expected states, troubleshooting.

Observation: screenshots, traces, console logs, test output, or rendered UI inspection.

## 3. Data Fetching And Analysis

Use when workflows depend on dashboards, monitoring, analytics, credentials, standard queries, or interpretation.

Typical resources: query templates, metric definitions, data caveats, access checks.

Observation: sample query output, row counts, dashboard snapshots, or reconciled totals.

## 4. Business Process And Team Automation

Use when a recurring team workflow can be made reliable through steps, templates, and prior outputs.

Typical resources: process checklist, templates, decision logs, escalation rules.

Observation: completed checklist, generated artifact, approval record, or process log.

## 5. Code Scaffolding And Templates

Use when boilerplate must follow local conventions while still accepting natural-language requirements.

Typical resources: templates, generator scripts, examples, naming conventions, verifier.

Observation: generated files, compile/test output, snapshot comparison, or smoke run.

## 6. Code Quality And Review

Use when review standards, style rules, deterministic checks, or adversarial review procedures should apply consistently.

Typical resources: review checklist, severity model, bad examples, linters, test commands.

Observation: review findings against seeded bad input, test output, or before/after diff.

## 7. CI/CD And Deployment

Use when release, deployment, cherry-pick, PR monitoring, or environment-specific operations need a safe path.

Typical resources: runbook, command order, rollback rules, required approvals, status checks.

Observation: dry-run output, CI status, deployment status, logs, or rollback evidence.

## 8. Runbooks

Use when symptoms should trigger multi-tool investigation and a structured report.

Typical resources: triage order, evidence checklist, known signatures, escalation points.

Observation: collected evidence, command traces, timeline, or incident report.

## 9. Infrastructure Operations

Use for routine maintenance, cost investigation, dependency management, resource cleanup, or operational audits.

Typical resources: inventory commands, safety gates, dry-run checks, cost metrics, cleanup rules.

Observation: dry-run plan, resource diff, metrics snapshot, or post-action verification.

## Choosing The Shape

If a skill spans categories, keep one primary category and route secondary concerns through references. Split the skill when:

- It has two different trigger surfaces.
- It serves two different users.
- It needs different tools and verification methods.
- Its references cannot be routed without loading unrelated material.
