# Skill Drafting — Building and Maintaining Agent Skills

Part of **[Agent Kaizen](https://github.com/DirectorGunner/agent-kaizen)** — Agent Kaizen is designed to support reliable AI agent workflows, context engineering, and AI systems engineering in VS Code, Codex, and Claude Code. Build reusable agent skills, reduce unnecessary context loading, add validation loops, and apply Spec → Verifier → Environment scaffolding to new and existing projects.

This repository is a `skill-drafting` skill: a reusable, trigger-rich task handbook that an AI coding agent (OpenAI Codex, Claude Code, etc) loads on demand when a task matches its triggers.

## What this skill covers

`skill-drafting` is a thorough handbook for creating, updating, reviewing, and validating Codex or Claude skills. It guides the full lifecycle: staged interview gates (goal, triggers, package anatomy, quality harness, implementation plan), classification across Anthropic's three skill use-case categories, and progressive-disclosure drafting where the frontmatter `description` is the trigger surface, `SKILL.md` is the runtime guide, and `references/` open on demand. It documents the deterministic corpus pipeline driven by `scripts/skill_builder.py` — `ingest` (mdbook, html, rustdoc, pdf), `build` (including the `--verbatim` preset), `finalize`, `split`, `maintain`, `lint`, a cross-skill `index`, and a `recontext` group that turns verbatim ingested docs into original, publishable prose with every identifier preserved — plus the package validator `scripts/validate_skill_package.py`, the locked recontextualization writer `scripts/recontext_subagent.py`, and Claude/Codex usage checks. The bundled tools are detailed under [Scripts](#scripts) below. Every drafted skill must end with a `Gotchas` section and an observable `Verification` section, including trigger tests, structure tests (`SKILL.md`, `references/INDEX.md`, and `references/topics.json` agreement), workflow tests, and a quality harness that can reject bad output.

## What's inside

- `SKILL.md` — frontmatter (`name` + trigger-rich `description`) and a lean body.
- `references/` — right-sized topic files the agent loads only when relevant (plus `INDEX.md` and `topics.json`).
- `GOTCHA.md` — known pitfalls and edge cases (for example: never bury trigger rules in the body — the frontmatter `description` is the main trigger surface; never claim quality from self-assessment alone — define an external or observable check before implementation).
- `scripts/` — the deterministic, stdlib-only tooling that builds, validates, recontextualizes, and maintains skills (detailed under [Scripts](#scripts)).

## Scripts

Everything under `scripts/` is stdlib-only Python (plus a couple of `.cmd` wrappers) — no third-party dependencies. Run any tool with `--help` for its full options.

### `skill_builder.py` — the deterministic build engine

One generalized engine for turning documentation into a skill package. Subcommands:

- `ingest {html|mdbook|rustdoc|pdf}` — source docs → a corpus JSONL of text chunks (a shared HTML→Markdown converter backs the HTML formats).
- `build` — corpus JSONL → a flat or router reference skill, packed into right-sized per-subject files with `references/INDEX.md` + `references/topics.json` + a starter `SKILL.md`. The `--verbatim` preset reproduces already-clean docs faithfully; `--verify` audits coverage and residue.
- `finalize` — bring a built skill up to the gold `SKILL.md` / `GOTCHA.md` standard.
- `split` — split oversized `references/*.md` into one file per topic (deterministic; no rewriting).
- `maintain` — in-place gold maintenance: audit conformance, split oversize files, and cross-link, leaving the bespoke `SKILL.md` / `GOTCHA.md` intact.
- `lint` — read-only link/topics health check → `AI/lint/<skill>.md`.
- `index` — build a cross-skill master `INDEX.md` (with optional `covers:` seeding).
- `recontext {clean|extract|splice|gate|triage}` and the lifecycle `recontext {scan|batch|drain|integrate|finish|reconcile|promote}` — recontextualize verbatim ingested docs into original, publishable prose with identifiers preserved. Roots and owner come from a `--config` JSON or CLI flags; nothing is hardcoded to a skill or path. See `references/recontextualization.md`.

### `recontext_core.py` — the recontextualization engine

The shared, path-agnostic library behind recontextualization: prose-unit detection, the three gates (A identifiers, B ~13-word verbatim residue, C scrape cruft), chrome cleanup, extract/splice, and triage. Imported by the two tools below; not usually ran directly.

### `recontext_subagent.py` — the locked, gated artifact writer

The rail a rewriting subagent uses (`prepare` / `show` / `submit` / `audit`). It derives every output path internally, confines all writes to one `--work-root`, refuses caller-supplied paths, and runs Gate A/B/C **before** writing — so a `PASS` is verified, never assumed, and rewrite artifacts can never land in the wrong place. Portable: no hardcoded paths, safe to run in any repo.

### `validate_skill_package.py` — the package validator

The Verification gate for a finished skill: `python validate_skill_package.py <skill_dir>` (or `--package <router_dir>` for a router). Checks the required files, frontmatter, and `SKILL.md` / `INDEX.md` / `topics.json` agreement.

### `skill_policy.py` (+ `skill_policy.cmd`) — idle-listing policy manager

Audit and set each installed skill's invocation policy so rarely-used skills cost no idle context while staying explicitly invocable: `audit` / `plan` / `preview` / `apply` / `restore`. Full walkthrough under [Reducing idle context cost](#reducing-idle-context-cost-skill-invocation-policy).

### `claude_usage_check.py` and `codex_usage_check.py` (+ `codex_usage_bridge.cmd`) — usage checks

Read-only utilization checks for long or batched builds. `claude_usage_check.py` prints Claude's 5-hour-window utilization. Codex usage needs the host-side bridge (`codex_usage_bridge.cmd`, or `codex_usage_check.py --run-bridge`) because the Codex agent sandbox blocks the usage endpoint by default; both exit cleanly without leaking token data if credentials are absent.

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
| `skill-drafting`        | [AI-skill-drafting](https://github.com/DirectorGunner/AI-skill-drafting)                           |
| `ableton-live`          | [AI-SKILL-ableton-live](https://github.com/DirectorGunner/AI-SKILL-ableton-live)                   |
| `adobe-products`        | [AI-SKILL-adobe-products](https://github.com/DirectorGunner/AI-SKILL-adobe-products)               |
| `blender`               | [AI-SKILL-blender](https://github.com/DirectorGunner/AI-SKILL-blender)                             |
| `chrome-extensions`     | [AI-SKILL-chrome-extensions](https://github.com/DirectorGunner/AI-SKILL-chrome-extensions)         |
| `cli-design`            | [AI-SKILL-cli-design](https://github.com/DirectorGunner/AI-SKILL-cli-design)                       |
| `davinci-resolve`       | [AI-SKILL-davinci-resolve](https://github.com/DirectorGunner/AI-SKILL-davinci-resolve)             |
| `discord-developers`    | [AI-SKILL-discord-developers](https://github.com/DirectorGunner/AI-SKILL-discord-developers)       |
| `gimp`                  | [AI-SKILL-gimp](https://github.com/DirectorGunner/AI-SKILL-gimp)                                   |
| `git`                   | [AI-SKILL-git](https://github.com/DirectorGunner/AI-SKILL-git)                                     |
| `github`                | [AI-SKILL-github](https://github.com/DirectorGunner/AI-SKILL-github)                               |
| `lumberyard`            | [AI-SKILL-lumberyard](https://github.com/DirectorGunner/AI-SKILL-lumberyard)                       |
| `powershell-vsdevshell` | [AI-SKILL-powershell-vsdevshell](https://github.com/DirectorGunner/AI-SKILL-powershell-vsdevshell) |
| `pymeasure`             | [AI-SKILL-pymeasure](https://github.com/DirectorGunner/AI-SKILL-pymeasure)                         |
| `pyvisa`                | [AI-SKILL-pyvisa](https://github.com/DirectorGunner/AI-SKILL-pyvisa)                               |
| `tauri-develop`         | [AI-SKILL-tauri-develop](https://github.com/DirectorGunner/AI-SKILL-tauri-develop)                 |
| `turso-db`              | [AI-SKILL-turso-db](https://github.com/DirectorGunner/AI-SKILL-turso-db)                           |

Main project: **[agent-kaizen](https://github.com/DirectorGunner/agent-kaizen)**.

## Reducing idle context cost (skill invocation policy)

Every installed skill costs a little context on every session: the agent sees each skill's name and description before you ever use it. If you rarely use this skill in a given project, you can keep it installed and still explicitly invocable while hiding it from the model's automatic listing.

Doing so does **not** modify this skill's source repo — the policy lives in your local agent settings. The Agent Kaizen **[skill-drafting](https://github.com/DirectorGunner/AI-skill-drafting)** repo ships a manager, `scripts/skill_policy.py`, that sets this for all your skills at once:

```bash
python skill_policy.py audit     # list every skill + its current policy + idle cost
python skill_policy.py plan      # write a decision file with recommendations (nothing applied)
# edit that decision file: set selected_policy + approved:true for the skills you choose
python skill_policy.py preview   # show the exact change
python skill_policy.py apply     # apply ONLY what you approved (backup + rollback recorded)
python skill_policy.py restore   # roll back
```

- **Claude Code (works today):** writes `skillOverrides: { "<skill>": "user-invocable-only" }` to `.claude/settings.local.json` — zero idle listing cost, still available from the `/skills` menu. Start a new session for it to take effect; invoke it any time via `/skills`.
- **Codex (currently unreliable):** explicit-only Codex skills are affected by an open bug ([openai/codex#23454](https://github.com/openai/codex/issues/23454)) where `$skill` invocation of an explicit-only local skill can fail. Until it's fixed, leave Codex skills implicit, or fully disable rarely-used ones with `[[skills.config]] enabled = false` in `config.toml`. The manager audits Codex but does not change Codex policy.

## License

Licensed under **AGPL-3.0**, matching the [Agent Kaizen](https://github.com/DirectorGunner/agent-kaizen) project.
