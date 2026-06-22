# Source Digestion And Fidelity

## Purpose

Use this reference when a skill is based on external docs, local notes, PDFs, code, or existing skills. The output should be original, task-organized guidance that preserves facts.

## Source Registry

Track each source with:

- Label.
- Type: official docs, API, local file, tutorial, note, example, or existing skill.
- Location or path.
- Trust level.
- License posture.
- Intended use.
- Retrieval date or commit when relevant.

Prefer official and local authoritative sources for facts. Use notes and tutorials for workflow insight, gotchas, and examples.

## Preserve List

Before drafting references, extract names and facts that must not change:

- Product and service names.
- API names, classes, methods, properties, commands, flags, environment variables.
- File paths, extensions, schemas, enum values, exit codes.
- UI labels, settings names, menu paths, shortcuts.
- Numbers with units, version requirements, limits, ordering, and defaults.

When rewriting, keep those tokens exact. Rephrase prose freely, but do not rename load-bearing identifiers.

## Digest By Task, Not Source

Do not create one reference per source unless the task itself requires it. Organize by the concerns the future agent will face:

- Setup.
- Core workflow.
- Variants.
- Error handling.
- Verification.
- Gotchas.
- Examples.

A single source can feed several references, and a single reference can synthesize several sources.

## Originality And Attribution

Use original wording unless the source license and task explicitly allow short excerpts. For restricted or unknown licenses, treat sources as inspiration and write fresh structure and prose.

Keep attribution or inspiration notes where appropriate:

- Public or permissive sources: cite source labels and license posture.
- Restricted or unknown sources: use an `Inspired by` note without copying structure or sentences.
- Internal/private sources: avoid exposing sensitive details and follow repo policy.

## Fidelity Checks

Before finishing:

- Re-read references against source notes and the preserve list.
- Confirm no commands, flags, names, numeric limits, or file paths changed.
- Confirm no direction, cause, default, or ordering flipped.
- Mark missing source facts as explicit gaps instead of inventing them.
- Verify each reference still serves a task, not just a source summary.

## Common Failure Modes

- Over-summarizing until precise commands disappear.
- Preserving source order even when it is poor runtime guidance.
- Copying examples that assume the wrong environment.
- Replacing exact terms with prettier synonyms.
- Treating unofficial notes as authoritative.
- Writing a large reference that the agent must load for every task.
