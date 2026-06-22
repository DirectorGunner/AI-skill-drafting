# Skill Drafting — Building and Maintaining Agent Skills

Part of **[Agent Kaizen](https://github.com/DirectorGunner/agent-kaizen)** — Agent Kaizen is designed to support reliable AI agent workflows, context engineering, and AI systems engineering in VS Code, Codex, and Claude Code. Build reusable agent skills, reduce unnecessary context loading, add validation loops, and apply Spec → Verifier → Environment scaffolding to new and existing projects.

This repository is a `skill-drafting` skill: a reusable, trigger-rich task handbook that an AI coding agent (OpenAI Codex, Claude Code, etc) loads on demand when a task matches its triggers.

## What this skill covers

`skill-drafting` is the handbook for creating, updating, reviewing, and validating Codex or Claude skills. It guides the full lifecycle: staged interview gates (goal, triggers, package anatomy, quality harness, implementation plan), classification across the 9 skill categories, and progressive-disclosure drafting where the frontmatter `description` is the trigger surface, `SKILL.md` is the runtime guide, and `references/` open on demand. It documents the deterministic corpus pipeline driven by `scripts/skill_builder.py` — `ingest` (mdbook, html, rustdoc, pdf), `build` (including the `--verbatim` preset), `finalize`, `split`, `maintain`, `lint`, and a cross-skill `index` — plus the package validator `scripts/validate_skill_package.py` and Claude/Codex usage checks. Every drafted skill must end with a `Gotchas` section and an observable `Verification` section, including trigger tests, structure tests (`SKILL.md`, `references/INDEX.md`, and `references/topics.json` agreement), workflow tests, and a quality harness that can reject bad output.

## What's inside

- `SKILL.md` — frontmatter (`name` + trigger-rich `description`) and a lean body.
- `references/` — right-sized topic files the agent loads only when relevant (plus `INDEX.md` and `topics.json`).
- `GOTCHA.md` — known pitfalls and edge cases (for example: never bury trigger rules in the body — the frontmatter `description` is the main trigger surface; never claim quality from self-assessment alone — define an external or observable check before implementation).

## Use it

This skill is one git repo inside the Agent Kaizen **skills store**. The store nests two folders on purpose: the outer **`SKILLS\`** is a VS Code project for building and maintaining skills (its own workspace + tooling), and the inner lowercase **`skills\`** holds every skill as its own repo. That split lets a project pull skills two ways — the **whole `skills\` folder at once** (loads everything — **not recommended**) or **one skill at a time** (recommended: load only what a task needs and stay under Claude Code's skill-listing budget).

Paths below use **`%DEVROOT%`** — the `DEVROOT` environment variable pointing at the folder that contains `SKILLS\`. Set it once by running **`SetDevRoot.cmd`** in the SKILLS repo root (no admin); a new shell then resolves `%DEVROOT%` automatically.

Link **just this skill** (recommended) — a Windows directory junction, no admin:

```cmd
mklink /J .agents\skills\skill-drafting  "%DEVROOT%\SKILLS\skills\skill-drafting"
mklink /J .claude\skills\skill-drafting  "%DEVROOT%\SKILLS\skills\skill-drafting"
```

Or link the **whole store** at once (loads every skill — not recommended outside a skills-dev project):

```cmd
mklink /J .agents\skills  "%DEVROOT%\SKILLS\skills"
mklink /J .claude\skills  "%DEVROOT%\SKILLS\skills"
```

Remove a link (the store copy is untouched):

```cmd
rmdir .agents\skills\skill-drafting
rmdir .claude\skills\skill-drafting
```

The agent (OpenAI Codex, Claude Code) then auto-loads this skill whenever a task matches its triggers. Built and validated with **[skill-drafting](https://github.com/DirectorGunner/AI-skill-drafting)** to the Agent Kaizen gold standard.

## The linked-skills workflow

`skill-drafting` is the documentation home for how Agent Kaizen skills are stored, published, and wired into agents. The linking commands live in **Use it** above; this section is the rationale.

**Store.** Every skill lives in a private, local-only store at `%DEVROOT%\SKILLS\skills\<name>\` — each its own git repo, published individually as `github.com/DirectorGunner/AI-SKILL-<name>` (one exception: this `skill-drafting` skill publishes as `AI-skill-drafting`, to avoid doubling the word). Both agents read that one copy through **per-skill** junctions (`.agents/skills/<name>`, `.claude/skills/<name>`), so the mirrors can't drift and the framework repo carries zero skill payload. Each LLM folder also has its own generated `INDEX.md`. (`%DEVROOT%` is the `DEVROOT` env var — set it once with `SetDevRoot.cmd`.)

**Why per skill, not the whole store.** Claude Code loads every available skill's `name` + `description`, and these trigger-rich descriptions are large — linking the whole catalog (100+ skills) blows the ~1% `skillListingBudgetFraction`, truncates descriptions, and degrades routing. Link the 3–8 skills a project actually uses. A whole-store link is only for a dev/everything workspace like the `SKILLS` store project itself.

### Skill catalog

| Skill                   | Repository                                                                                         |
| ----------------------- | -------------------------------------------------------------------------------------------------- |
| `git`                   | [AI-SKILL-git](https://github.com/DirectorGunner/AI-SKILL-git)                                     |
| `github`                | [AI-SKILL-github](https://github.com/DirectorGunner/AI-SKILL-github)                               |
| `cli-design`            | [AI-SKILL-cli-design](https://github.com/DirectorGunner/AI-SKILL-cli-design)                       |
| `powershell-vsdevshell` | [AI-SKILL-powershell-vsdevshell](https://github.com/DirectorGunner/AI-SKILL-powershell-vsdevshell) |
| `chrome-extensions`     | [AI-SKILL-chrome-extensions](https://github.com/DirectorGunner/AI-SKILL-chrome-extensions)         |
| `gimp`                  | [AI-SKILL-gimp](https://github.com/DirectorGunner/AI-SKILL-gimp)                                   |
| `blender`               | [AI-SKILL-blender](https://github.com/DirectorGunner/AI-SKILL-blender)                             |
| `lumberyard`            | [AI-SKILL-lumberyard](https://github.com/DirectorGunner/AI-SKILL-lumberyard)                       |
| `adobe-products`        | [AI-SKILL-adobe-products](https://github.com/DirectorGunner/AI-SKILL-adobe-products)               |
| `skill-drafting`        | [AI-skill-drafting](https://github.com/DirectorGunner/AI-skill-drafting)               |

Main project: **[agent-kaizen](https://github.com/DirectorGunner/agent-kaizen)**.

## License

Licensed under **AGPL-3.0**, matching the [Agent Kaizen](https://github.com/DirectorGunner/agent-kaizen) project.
