---
name: skill-drafting
description: >-
  Use when creating, updating, reviewing, or validating Codex or Claude skills: drafting SKILL.md
  files, trigger descriptions, references/scripts/assets, gotchas, verification checks,
  source-digestion plans, forward tests, or skill-generation prompts, even when the user does not
  say skill-drafting.
covers:
  - references
  - skill
  - skill.md
  - frontmatter
  - description
  - scripts
  - assets
  - progressive disclosure
  - interview
  - spec
  - gate
  - checkpoint
---

# Skill Drafting

Use this skill to turn a vague request for an agent skill into a focused, validated skill package. The skill applies the repo's Spec -> Verifier -> Environment method to skill design, then routes detailed guidance through references only when needed.

The authoritative framework spec — the gold-standard package shape, the end-to-end ingest -> build -> finalize -> validate pipeline, the `--verbatim` mode, and the in-place maintenance model for already-shipped skills — is [`better-skill-framework.md`](../../../better-skill-framework.md) in the repo root.

## Required Workflow

1. Read repo instructions first, especially `AGENTS.md`, `CLAUDE.md`, and the three-layer method when present.
2. Interview the user through staged gates before nontrivial writes:
   - Gate 1: goal, consumers, scope, out of scope, examples, cost of error.
   - Gate 2: skill category, positive triggers, paraphrased triggers, negative triggers, overlap boundaries.
   - Gate 3: package anatomy, reference split, scripts/assets, setup/config, memory-file impact.
   - Gate 4: quality harness, observation artifact, verifier, forward-test plan.
   - Gate 5: final implementation plan, files, acceptance criteria, and rollback or preservation rules.
3. Classify the skill using Anthropic's three skill use-case categories (Document & Asset Creation, Workflow Automation, MCP Enhancement) before drafting; if it spans categories, name the primary category and explain why.
4. Draft for progressive disclosure: frontmatter is the trigger surface, `SKILL.md` is the runtime guide, references are opened on demand, scripts/assets exist only when they change behavior or reliability.
5. Require a `Gotchas` section for recurring failure modes and a `Verification` section with observable checks.
6. Build or specify a task-specific quality harness that can distinguish good output from bad output.
7. Give the implementing agent a way to observe work while building, such as tests, logs, screenshots, traces, sample runs, or fixtures.
8. Use independent subagents for nontrivial skill architecture critique and forward-testing when the runtime supports them. If unavailable, run clearly separated self-review passes and say so.
9. Assess whether `AGENTS.md` or `CLAUDE.md` need tool, hook, guardrail, or routing updates. Propose changes only; do not edit memory files without explicit user approval.
10. Validate the finished skill before claiming success.

## Task Router

| If the task is about...                                                                                    | Read                                          |
| ---------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| required files, folder anatomy, frontmatter, trigger descriptions, references, scripts, assets             | `references/skill-package-anatomy.md`         |
| interviewing the user, staging decisions, writing a spec, checkpointing before writes                      | `references/interview-spec-gates.md`          |
| turning source material into original skill guidance while preserving names, commands, and facts           | `references/source-digestion-and-fidelity.md` |
| recontextualizing verbatim ingested docs into original publishable prose (gates, locked writer, lifecycle) | `references/recontextualization.md`           |
| output quality, tests, rubrics, observation artifacts, good-vs-bad evaluation                              | `references/quality-harnesses.md`             |
| using subagents for independent critique, forward-testing, or source digestion                             | `references/subagents-and-forward-testing.md` |
| AGENTS.md, CLAUDE.md, hooks, guardrails, setup, durable memory, environment support                        | `references/memory-hooks-and-environment.md`  |
| choosing among Anthropic's three skill use-case categories and matching package shape to category          | `references/category-patterns.md`             |
| recurring failure modes, measurement, iteration, under-triggering, over-triggering                         | `references/gotchas-and-measurement.md`       |

## Building A Reference Skill From A Corpus

When the skill is a large body of ingested documentation (many source chunks rather than hand-written guidance), build it deterministically with the pipeline instead of authoring files by hand.

1. **Ingest** live docs into a corpus JSONL with `scripts/skill_builder.py ingest <format>` (a shared HTML->Markdown converter backs the HTML formats): `ingest mdbook` (an mdBook `print.html`), `ingest html` (crawled HTML pages / a docs bundle), `ingest rustdoc` (generator-rendered API pages; content selector, dropped section ids, and stripped label are options with rustdoc defaults), `ingest pdf` (born-digital PDF via `pdftotext` + `qpdf`). Each record is `{chunk_id, title, source_url, text, tags[, subskill, section]}`.
2. **Build** with `scripts/skill_builder.py build`: it packs chunks into right-sized per-subject reference files at natural source boundaries and writes `references/INDEX.md` + `references/topics.json` + a starter `SKILL.md` — flat, or a router of sub-skills. Default mode resolves source links/images and normalizes formatting; the **`--verbatim`** preset turns that off for faithful reproduction of already-clean docs. Pass `--verify` to audit coverage, link/image residue, and file sizes.
3. **Finalize** with `scripts/skill_builder.py finalize --skill <dir> --meta <meta.json>` to write the gold `SKILL.md` sections + sibling `GOTCHA.md` (routers: every sub-skill).
4. **Validate** with `scripts/validate_skill_package.py` (`--package` for routers).

See [`better-skill-framework.md`](../../../better-skill-framework.md) for the full pipeline and the gold package spec.

## Breaking Up An Oversized Reference Doc

When a skill already has good prose but a few `references/*.md` files are too big to load efficiently, split them deterministically with `scripts/skill_builder.py split` — no LLM, no rewriting. Each input doc is parsed at a heading level (default `###`, optionally limited to one `## ` section), CONSECUTIVE same-title blocks are merged into one topic, and each topic becomes its own file (or, with `--max-bytes`, whole topics are packed up to a size). Filenames are `slug(title)`, prefixed with a source subject token only on cross-file collision. It regenerates `references/INDEX.md` (replacing just the topic-listing section, preserving the rest) and `references/topics.json`, optionally remaps a `symbols.json`'s `reference_files` (`--remap-symbols`, with `--symbols-source-map` to map each group to its source doc's topic files — far more reliable than term matching when group keys are normalized labels), and removes the originals (`--replace-inputs`). The split is VERBATIM by default (use `--clean` only for noisy source); `--verify` proves byte-for-byte coverage and INDEX/topics consistency. Drive per-file params with CLI flags or a `--legend` JSON; see `python scripts/skill_builder.py split --help`.

## Recontextualizing A Verbatim Corpus Before Publishing

When a skill's `references/*.md` were ingested **verbatim** from upstream docs, reword them into
**original prose** (identifiers/code/links/numbers/tables preserved exactly) before publishing — the
licensing gate. The engine is `scripts/recontext_core.py`; drive it with `scripts/skill_builder.py recontext`:
primitives `clean | extract | splice | gate | triage`, and the lifecycle `scan -> batch -> drain ->
integrate -> finish -> reconcile -> promote` (roots/owner from a `--config` JSON or CLI flags; nothing
hardcoded). Rewriting subagents must go through the **locked, gated writer** `scripts/recontext_subagent.py`
(`prepare`/`show`/`submit`): it derives all paths internally, confines writes to one `--work-root`, and
runs Gate A (identifiers), Gate B (~13-word residue), and Gate C (cruft) before writing — so a `PASS`
is verified. `recontext drain` generates a Workflow that drives this writer (replacing freehand
`_rw_`/`_pkt_` writing). Full details, the gate definitions, and the locked-writer contract are in
[`references/recontextualization.md`](references/recontextualization.md).

## Maintaining An Already-Shipped Skill In Place

When a skill is already built and shipped but its source corpus is gone, do not re-render it. Use `scripts/skill_builder.py maintain <skill_dir>` to AUDIT gold-standard conformance (oversize files, INDEX/topics drift) read-only; add `--apply` to split oversize, heading-structured reference files in place and surgically add the new parts to `references/INDEX.md` + `references/topics.json`, leaving the bespoke `SKILL.md` / `GOTCHA.md` untouched. It is router-aware (per sub-skill) and conservative: a file with no `##` / `###` sub-headings is reported as an ATOMIC outlier and not auto-split (use `--force` for a size-based cut between blocks, or note it as an accepted outlier). Use `--cross-link` to add/refresh a conservative `## See also` footer on each reference file (links related topics by distinctive name; already-linked files excluded). Run it against the skill in the store (or via either junction — it is the same copy); both `.agents` and `.claude` surfaces reflect the change automatically, so there is no separate mirror to update or parity to `diff`. Separately, `scripts/skill_builder.py lint <skill_dir>` is a read-only health check that reports dangling local links and INDEX/topics drift to `AI/lint/<skill>.md` (maintainer-facing; not shipped inside the skill).

## Building A Cross-Skill Master Index

To catalog every skill in a skills root, run `scripts/skill_builder.py index <skills_root> --mirror <other_root>`. It writes a top-level `INDEX.md` (skill catalog, entity -> skill map, related skills) to both mirrors. Add `--seed-covers` to seed or refresh a `covers:` frontmatter list on each `SKILL.md` (routers: sub-skill area names; flat: top derived entities); the index prefers `covers:` and otherwise derives entities from `topics.json`. This is a discovery and audit surface, not auto-routing — agents still route via each skill's `description`. The master `INDEX.md` is public (it lives in the skills area); the lint report under `AI/lint/` is maintainer-local and is not.

## Gotchas

Recurring failure modes and what to do instead live in the sibling [GOTCHA.md](GOTCHA.md).

## Verification

For this skill package, run the validator against the package you are editing:

```powershell
python "$env:DEVROOT\SKILLS\skills\skill-drafting\scripts\validate_skill_package.py" "$env:DEVROOT\SKILLS\skills\skill-drafting"
```

For long or batched skill builds, check usage after each batch. For Claude, use `scripts/claude_usage_check.py` to print utilization only. For Codex, use `scripts/codex_usage_check.py` in read-only mode. By default the Codex agent sandbox blocks direct egress to the ChatGPT usage endpoint, so an in-sandbox agent cannot read Codex usage on its own; the user must run the host-side bridge: ask them to launch the visible `scripts/codex_usage_bridge.cmd` (or `scripts/codex_usage_check.py --run-bridge --login-if-needed`), which does the auth preflight by default. Use `--login` only when the user explicitly asks to authenticate. Normal checker runs auto-detect `AI/work/codex-usage-bridge.json` or can query `--app-server-url ws://127.0.0.1:17342` explicitly. Repo-local Codex mode creates or repairs `AI/work/.gitignore` before writing local Codex state. If credentials are absent or unavailable, both scripts exit cleanly without leaking token data.

For any skill drafted with this skill, verify:

- Trigger tests: direct trigger, paraphrased trigger, and negative trigger.
- Structure tests: `SKILL.md`, `references/INDEX.md`, and `references/topics.json` agree.
- Workflow test: one representative task can be completed using the skill.
- Quality test: the harness can reject a bad or incomplete output.
- Environment test: required tools, permissions, hooks, and memory-file changes are present or explicitly proposed.

## Reference Map

Start with `references/INDEX.md`. Load only the reference that matches the current decision or failure mode.

## Inspired by

Includes original content written for this skill, informed by: the repo's three-layer method, Anthropic skill-building guidance, and the system skill-creator skill.
