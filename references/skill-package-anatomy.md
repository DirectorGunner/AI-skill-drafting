# Skill Package Anatomy

## Purpose

Use this reference when deciding what files a skill package needs and how information should be split across them.

## Required Center

Every skill needs a `SKILL.md` file with YAML frontmatter:

- `name`: kebab-case, matching the folder name.
- `description`: concrete trigger text. It should say what the skill does and when to use it, including specific tasks, tools, file types, or contexts.

Keep frontmatter minimal unless the target runtime documents extra fields. The trigger description matters more than human-facing summary prose because it decides whether the skill loads.

## Frontmatter Validity

Treat frontmatter as executable routing data, not ordinary prose. A skill is not loadable if this block fails the runtime parser.

- Keep the rendered `description` at or below 1024 characters unless the target runtime documents a different limit.
- Use folded scalar YAML (`description: >-`) for multi-clause descriptions, especially when the text contains colons, quotes, commas, paths, API names, file names, or negative-trigger boundaries.
- Prefer concise trigger coverage over exhaustive domain summaries. Move long examples, API lists, troubleshooting, and edge cases into the body or references.
- Verify the frontmatter parses cleanly before claiming the skill package is usable.

## Body Shape

A strong `SKILL.md` body usually includes:

- Purpose: the one job the skill owns.
- Required workflow: ordered only where order matters.
- Task router: references to open for specific concerns.
- Inputs and setup: files, tools, credentials, permissions, or user decisions.
- Gotchas: recurring failures and how to avoid them — either inline, or moved to a sibling `GOTCHA.md` (next to `SKILL.md`) that `SKILL.md` references. The validator accepts either; if a `GOTCHA.md` exists it must be non-empty, and a `GOTCHA.md` reference in `SKILL.md` must resolve to a real sibling file.
- Verification: checks, commands, expected artifacts, and stop conditions.
- Source or attribution note when source material shaped the skill.

Keep `SKILL.md` concise. The body should orient the agent and route it, not replace a reference manual.

## Progressive Disclosure

Design three loading levels:

- Always visible: `name` and `description`.
- Loaded on trigger: `SKILL.md`.
- Loaded on demand: files under `references/`, plus scripts and assets used by the workflow.

Move long examples, API details, policy rules, category variants, and troubleshooting matrices into references. Link every reference directly from `SKILL.md` or `references/INDEX.md`.

## Optional Resources

Use `references/` for documentation the agent reads when needed, such as API usage, examples, policies, troubleshooting, category rules, or quality rubrics.

Use `scripts/` for deterministic validation, parsing, conversion, scaffolding, or checks that would otherwise be rewritten repeatedly.

Use `assets/` for reusable material the agent uses in output, such as templates, sample projects, fixtures, media, or prompt fragments.

Do not create auxiliary human docs inside the skill folder unless the runtime requires them. Avoid internal README files that duplicate `SKILL.md` and references.

## Reference File Granularity And Size

Ship readable prose, not an index. Each `references/*.md` is one digestible subject an agent can read top to bottom. Follow the one-subject-per-file model used by mature reference skills in this repo (for example `chrome-extensions` with ~33 files and `cli-design` with ~15): a flat `references/` folder, a short `# Title`, an `## Overview`, the body, and a `## See also` linking sibling files.

- One subject per file. Keep `references/` flat; avoid nested subfolders unless a runtime requires them.
- Size is set by the subject, not by a cap. Decide where to split a large topic on concept or task boundaries - how an agent would hunt for one specific solution or fix - not by a fixed line or byte count. A mechanical cap is compounding-issue-prone: it splits mid-concept and lumps unlike topics together.
- Avoid giant single-topic files. A 40-80 KB catch-all topic is expensive to load and hard to navigate; break it into focused subjects.
- Preserve load-bearing identifiers verbatim (API, method, class names, UI labels, menu paths, shortcuts, endpoints, enum values, numbers) while writing original prose.
- Never ship build or processing metadata. Do not write chunk-id indexes, per-chunk `words`/`tags`/`symbols` rows, build counters, or source URLs into shipped files. A reader who opens `references/` must be able to READ the documentation, not a manifest of how it was built.

For a large generated corpus (many source chunks), do not auto-split by size. Make the subject-to-file taxonomy and the split or merge decisions once, up front, with LLM judgment, and freeze them in a "legend" that a deterministic renderer applies. Ship per-subject prose files; include a bulk `corpus.jsonl` only when exact-identifier grep across the whole corpus is essential, and never as a substitute for readable docs.

## Reference Index Metadata

When a skill has `references/`, include both:

- `references/INDEX.md`: a human-readable table listing every reference, one-line summary, and when to read it.
- `references/topics.json`: machine-readable topic metadata.

Use this `topics.json` shape:

```json
{
  "schema_version": 1,
  "topics": [
    {
      "topic": "Short Topic Title",
      "file": "references/example.md",
      "summary": "One or two sentences on what this reference covers.",
      "keywords": ["keyword-one", "keyword-two"]
    }
  ]
}
```

Every `file` in `topics.json` must exist and be listed in `INDEX.md`. Every reference listed in `INDEX.md` should have exactly one topic entry unless it is intentionally an index or generated metadata file.

## Trigger And Boundary Design

Draft triggers in three sets:

- Positive triggers: direct phrases users say.
- Paraphrased triggers: equivalent requests that omit the skill name.
- Negative triggers: adjacent tasks that should not use the skill.

If another skill overlaps, name the boundary. Example: a CLI design skill handles argument and help design; a PowerShell skill handles shell-specific syntax and native command invocation.

## Output Shape

Before writing, define the exact output shape:

- New skill, update to existing skill, review report, verifier script, reference set, or prompt template.
- Required folders and files.
- Preservation rules for existing files.
- What evidence proves the output is ready.

## Do And Do Not

Do write instructions that change agent behavior.

Do include local conventions and recurring failure patterns.

Do use scripts when a check must be reliable.

Do not restate generic coding advice.

Do not combine unrelated jobs into one skill to avoid creating dependencies.

Do not hide required setup in references without a pointer from `SKILL.md`.
