# Skill README standard (template + managed regions)

This one file is **both** the human-readable standard for a skill's public `README.md` **and** the
machine source that `scripts/skill_builder.py readme` parses. Edit this file to change the standard;
then run `python skill_builder.py readme apply --all` (from the store, or pass `--store <dir>`) to
propagate the change to every skill README that carries the affected region. Nothing here is specific to one skill.

## How a README is split

A skill README has two kinds of content:

- **Managed regions** — boilerplate the tool single-sources from this file and re-applies in place.
  Regions are located by **markdown structure, not by any markers** (so shippable READMEs stay clean):
  the intro by its leading "Part of Agent Kaizen" line, the rest as whole `##` sections (the heading
  through the line before the next `##`). Editing a region here and re-running `readme apply` updates
  every README that has that section.
- **Authored prose** — everything else (title, tagline, "What this skill covers", "What's inside",
  "Scripts", "Status", router sub-skill lists, and the `### Skill catalog` table). The tool never
  rewrites authored prose; the catalog table is owned separately by the publisher's `skill-catalog` tool.

The managed regions are: **Use it** (the full junction/`%DEVROOT%` instructions) and **Reducing idle
context cost** (the skill-invocation-policy section), both present in **every** skill README; plus the
**Agent Kaizen intro** paragraph and **License**, which are Pattern A only. `{{skill}}` is the only
per-skill substitution in a managed region (it appears in `skills\{{skill}}` junction paths); the rest is
constant.

## Commands

- `python skill_builder.py readme scaffold <skill> [--pattern a|b]` — write a brand-new `README.md` from
  the matching skeleton below, with placeholders filled.
- `python skill_builder.py readme apply [<skill> …|--all]` — refresh the managed regions of existing
  READMEs (presence-driven: only sections that are present). `--dry-run` previews, `--check` is CI
  (exit 1 on drift), and `--ensure-use-it` gives every skill the full "Use it" section (inserting it
  after "What's inside" where absent) so the linking instructions are identical across all skills.

## Placeholders

`{{title}}` (README H1), `{{tagline}}` (one-line blockquote summary), `{{article}}` (`a`/`the`),
`{{skill}}` (the skill's folder/repo name).

## Pattern A template

Full-featured domain/reference skill: Agent Kaizen intro, full "Use it" junction instructions, and a
License section.

````markdown
# {{title}}

> {{tagline}}

Part of **[Agent Kaizen](https://github.com/DirectorGunner/agent-kaizen)** — Agent Kaizen is designed to support reliable AI agent workflows, context engineering, and AI systems engineering in VS Code, Codex, and Claude Code. Build reusable agent skills, reduce unnecessary context loading, add validation loops, and apply Spec → Verifier → Environment scaffolding to new and existing projects.

This repository is {{article}} `{{skill}}` skill: a reusable, trigger-rich task handbook that an AI coding agent (OpenAI Codex, Claude Code) loads on demand when a task matches its triggers.

## What this skill covers

<!-- TODO(authored): one paragraph — the domain/tool/API this skill handles, its scope, and the triggers that fire it (including cases where the user doesn't say the skill's name). -->

## What's inside

<!-- TODO(authored): bullet list — `SKILL.md`, `references/`, `GOTCHA.md`, and `scripts/` if any. -->

## Use it

This skill is one git repo in a **skills store** — the lowercase `skills\` folder that holds every skill as its own repo. Keep that folder wherever you like; you wire skills into a project by linking from it into the project's `.agents\skills\` and `.claude\skills\`. Link **one skill at a time** (recommended) so the agent only lists what a task needs and you don't spend idle context on skills you're not using; linking the **whole `skills\` folder at once** loads every skill and isn't recommended outside a skills-dev project.

The commands below use **`%DEVROOT%`** — the `DEVROOT` environment variable pointing at the folder that holds your projects. Set it once (no admin) by running **`SetDevRoot.cmd`** from the root of the **[Agent Kaizen](https://github.com/DirectorGunner/agent-kaizen)** project — a reusable VS Code-project template that ships the script; a new shell then resolves `%DEVROOT%` automatically. Replace `<SKILLS-PROJECT>` with whatever you named the folder that contains your `skills\` store.

Link **just this skill** (recommended) — a Windows directory junction, no admin:

```cmd
mklink /J .agents\skills\{{skill}}  "%DEVROOT%\<SKILLS-PROJECT>\skills\{{skill}}"
mklink /J .claude\skills\{{skill}}  "%DEVROOT%\<SKILLS-PROJECT>\skills\{{skill}}"
```

Or link the **whole store** at once (loads every skill — not recommended outside a skills-dev project):

```cmd
mklink /J .agents\skills  "%DEVROOT%\<SKILLS-PROJECT>\skills"
mklink /J .claude\skills  "%DEVROOT%\<SKILLS-PROJECT>\skills"
```

Remove a link (the store copy is untouched):

```cmd
rmdir .agents\skills\{{skill}}
rmdir .claude\skills\{{skill}}
```

The author keeps the `skills\` store inside its own dedicated VS Code project (the `<SKILLS-PROJECT>` folder) with local-only build and maintenance scripts, because the same skills are reused across many different projects. If you work across several repos, consider the same: one central skills project gives every skill a single home, and an improvement to the shared scripts benefits all of your projects at once.

The agent (OpenAI Codex, Claude Code) then auto-loads this skill whenever a task matches its triggers. Built and validated with **[skill-drafting](https://github.com/DirectorGunner/AI-skill-drafting)** to the Agent Kaizen gold standard.

## Reducing idle context cost (skill invocation policy)

Every installed skill costs a little context on every session: the agent sees each skill's name and description before you ever use it. If you rarely use this skill in a given project, you can keep it installed and still explicitly invocable while hiding it from the model's automatic listing.

Doing so does **not** modify this skill's source repo — the policy lives in your local agent settings. The Agent Kaizen **[skill-drafting](https://github.com/DirectorGunner/AI-skill-drafting)** repo ships the policy manager as the `policy` subcommand of its all-in-one `scripts/skill_builder.py`, which sets this for all your skills at once:

```bash
python skill_builder.py policy audit     # list every skill + its current policy + idle cost
python skill_builder.py policy plan      # write a decision file with recommendations (nothing applied)
# edit that decision file: set selected_policy + approved:true for the skills you choose
python skill_builder.py policy preview   # show the exact change
python skill_builder.py policy apply     # apply ONLY what you approved (backup + rollback recorded)
python skill_builder.py policy restore   # roll back
```

- **Claude Code (works today):** writes `skillOverrides: { "<skill>": "user-invocable-only" }` to `.claude/settings.local.json` — zero idle listing cost, still available from the `/skills` menu. Start a new session for it to take effect; invoke it any time via `/skills`.
- **Codex (currently unreliable):** explicit-only Codex skills are affected by an open bug ([openai/codex#23454](https://github.com/openai/codex/issues/23454)) where `$skill` invocation of an explicit-only local skill can fail. Until it's fixed, leave Codex skills implicit, or fully disable rarely-used ones with `[[skills.config]] enabled = false` in `config.toml`. The manager audits Codex but does not change Codex policy.

## License

Licensed under **AGPL-3.0**, matching the [Agent Kaizen](https://github.com/DirectorGunner/agent-kaizen) project.

````

## Pattern B template

Lighter or status-driven skill (e.g. a recontextualized reference): a bespoke one-line intro, a Status
section, and no License — but the **same full `use-it-full` and `idle-context` managed regions as Pattern
A**. The bespoke intro and the Status section are authored per skill.

````markdown
# {{title}}

This is {{article}} `{{skill}}` skill for Agent Kaizen: <!-- TODO(authored): one-line description (e.g. an original-prose reference package derived from upstream docs, identifiers preserved). -->

## What this skill covers

<!-- TODO(authored). -->

## What's inside

<!-- TODO(authored): `SKILL.md`, `references/`, `GOTCHA.md`. -->

## Use it

This skill is one git repo in a **skills store** — the lowercase `skills\` folder that holds every skill as its own repo. Keep that folder wherever you like; you wire skills into a project by linking from it into the project's `.agents\skills\` and `.claude\skills\`. Link **one skill at a time** (recommended) so the agent only lists what a task needs and you don't spend idle context on skills you're not using; linking the **whole `skills\` folder at once** loads every skill and isn't recommended outside a skills-dev project.

The commands below use **`%DEVROOT%`** — the `DEVROOT` environment variable pointing at the folder that holds your projects. Set it once (no admin) by running **`SetDevRoot.cmd`** from the root of the **[Agent Kaizen](https://github.com/DirectorGunner/agent-kaizen)** project — a reusable VS Code-project template that ships the script; a new shell then resolves `%DEVROOT%` automatically. Replace `<SKILLS-PROJECT>` with whatever you named the folder that contains your `skills\` store.

Link **just this skill** (recommended) — a Windows directory junction, no admin:

```cmd
mklink /J .agents\skills\{{skill}}  "%DEVROOT%\<SKILLS-PROJECT>\skills\{{skill}}"
mklink /J .claude\skills\{{skill}}  "%DEVROOT%\<SKILLS-PROJECT>\skills\{{skill}}"
```

Or link the **whole store** at once (loads every skill — not recommended outside a skills-dev project):

```cmd
mklink /J .agents\skills  "%DEVROOT%\<SKILLS-PROJECT>\skills"
mklink /J .claude\skills  "%DEVROOT%\<SKILLS-PROJECT>\skills"
```

Remove a link (the store copy is untouched):

```cmd
rmdir .agents\skills\{{skill}}
rmdir .claude\skills\{{skill}}
```

The author keeps the `skills\` store inside its own dedicated VS Code project (the `<SKILLS-PROJECT>` folder) with local-only build and maintenance scripts, because the same skills are reused across many different projects. If you work across several repos, consider the same: one central skills project gives every skill a single home, and an improvement to the shared scripts benefits all of your projects at once.

The agent (OpenAI Codex, Claude Code) then auto-loads this skill whenever a task matches its triggers. Built and validated with **[skill-drafting](https://github.com/DirectorGunner/AI-skill-drafting)** to the Agent Kaizen gold standard.

## Status

<!-- TODO(authored): recontextualization / publication status, if relevant. -->

## Reducing idle context cost (skill invocation policy)

Every installed skill costs a little context on every session: the agent sees each skill's name and description before you ever use it. If you rarely use this skill in a given project, you can keep it installed and still explicitly invocable while hiding it from the model's automatic listing.

Doing so does **not** modify this skill's source repo — the policy lives in your local agent settings. The Agent Kaizen **[skill-drafting](https://github.com/DirectorGunner/AI-skill-drafting)** repo ships the policy manager as the `policy` subcommand of its all-in-one `scripts/skill_builder.py`, which sets this for all your skills at once:

```bash
python skill_builder.py policy audit     # list every skill + its current policy + idle cost
python skill_builder.py policy plan      # write a decision file with recommendations (nothing applied)
# edit that decision file: set selected_policy + approved:true for the skills you choose
python skill_builder.py policy preview   # show the exact change
python skill_builder.py policy apply     # apply ONLY what you approved (backup + rollback recorded)
python skill_builder.py policy restore   # roll back
```

- **Claude Code (works today):** writes `skillOverrides: { "<skill>": "user-invocable-only" }` to `.claude/settings.local.json` — zero idle listing cost, still available from the `/skills` menu. Start a new session for it to take effect; invoke it any time via `/skills`.
- **Codex (currently unreliable):** explicit-only Codex skills are affected by an open bug ([openai/codex#23454](https://github.com/openai/codex/issues/23454)) where `$skill` invocation of an explicit-only local skill can fail. Until it's fixed, leave Codex skills implicit, or fully disable rarely-used ones with `[[skills.config]] enabled = false` in `config.toml`. The manager audits Codex but does not change Codex policy.

````
