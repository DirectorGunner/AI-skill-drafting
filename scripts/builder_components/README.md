# `builder_components/` — the skill-drafting tooling package

This package is the **editable source of truth** for all of the skill build / maintain / validate /
recontextualize tooling. It is compiled into the single, self-contained, all-in-one
[`../skill_builder.py`](../skill_builder.py) — and each module here is also usable on its own.
Stdlib-only; no third-party dependencies.

Two ways to run the tooling, whichever fits the scenario:

- **The all-in-one:** `python skill_builder.py <subcommand> …` — every capability in one file (good for
  shipping, for running via args, and for an agent that wants the whole system in one read).
- **A single component:** `python -m builder_components.<module> …` — just that capability. Cheaper for
  an agent that only needs one tool (smaller to read/understand than the full all-in-one).

This is a developer reference for the package internals. For _using_ the tools, run any subcommand with
`--help`, or read the skill's top-level [`README.md`](../../README.md) (`## Scripts`).

## How it fits together

```
scripts/
├── skill_builder.py        ← GENERATED all-in-one (committed). Do-not-edit; rebuilt from here.
└── builder_components/      ← THIS package — the real, editable code
    ├── _assemble.py        ← the compiler: builder_components/* → ../skill_builder.py  (+ --check)
    ├── cli.py              ← dispatch for ALL subcommands (the top of the dependency graph)
    ├── <pipeline modules>  ← htmlmd, corpus, packing, build, ingest, finalize,
    │                          split_engine, split_cmd, maintain, index, lint, recontext, readme
    ├── validate.py         ← the `validate` subcommand
    ├── policy_engine.py    ← policy library      · policy_cmd.py ← the `policy` subcommand
    ├── recontext_core.py   ← recontext engine    · recontext_subagent.py ← the `recontext-subagent` cmd
    └── util/               ← single-concern helpers shared across the above
```

### The compiler (`_assemble.py`) and the contributor workflow

`skill_builder.py` is **generated**: `_assemble.py` embeds every module's verbatim source in a `_SRC`
dict (each under a `# ===MODULE <fqname>===` banner) plus a tiny bootstrap that registers each as the
matching `builder_components.*` module — in dependency order — and runs `cli.main`. Embedding the
source as data (not bare top-level code) is what lets one file hold many modules: each is exec'd in its
**own namespace**, so name collisions are impossible and the `recon`/`core` engine namespaces and all
intra-package imports keep working. The embedding is lossless, so the all-in-one behaves byte-for-byte
like the package.

To fix or extend the tooling (this is a public, contributable package):

1. Edit the module(s) under `builder_components/` (and/or test a single one with `python -m
   builder_components.<module>`).
2. Rebuild the all-in-one: `python builder_components/_assemble.py` (or `python skill_builder.py
   --rebuild`). Commit **both** the component change and the regenerated `skill_builder.py`.
3. Verify they are in sync: `python builder_components/_assemble.py --check` exits non-zero if the
   committed `skill_builder.py` is stale. (Good as a pre-commit / CI gate.)

> **`__file__`-relative paths:** the bootstrap sets each embedded module's `__file__` to its real source
> path, so the few load-time `__file__` users resolve exactly as in the package — `recontext.py`'s
> `_SCRIPTS`/`_BUILDER` (which point the drain subprocesses at `skill_builder.py recontext-subagent` /
> `skill_builder.py recontext`) and `readme.py`'s store-root / template locators.

## The `skill_builder` pipeline (dispatched by `cli.py`)

The build flow is roughly: **ingest** → **build** (corpus → packed files) → **finalize**, plus the
maintenance/utility commands **split**, **maintain**, **index**, **lint**, **recontext**, **readme**.

| Module | Responsibility | Key entry points | Imports from |
| --- | --- | --- | --- |
| `cli.py` | Top-level command dispatch (`_COMMANDS`, usage, `--rebuild`) for every subcommand. | `main` | every `cmd_*` |
| `htmlmd.py` | HTML → Markdown conversion (a small `HTMLParser` subclass). A leaf. | `html_to_md`, `split_main` | (stdlib) |
| `ingest.py` | Source docs → a corpus JSONL of text chunks (HTML / mdBook / rustdoc / PDF), with PDF boilerplate heuristics. Also home to the generic `run` (subprocess) and `norm` (whitespace) helpers reused downstream. | `cmd_ingest_html/mdbook/rustdoc/pdf`, `run`, `norm` | `htmlmd` |
| `corpus.py` | The build **corpus model** (record loading/merging, sub-skill & section keys, hierarchy) **and text cleaning** (chrome strip, ref/link resolution, table compaction, identifier backticking). Merged into one module because the two halves are mutually dependent. | `load_records`, `section_of`, `subskill_of`, `clean_body`, `clean_title`, `resolve_refs`, `compact_tables`, `backtick_identifiers`, `strip_cruft` | `ingest` (`norm`) |
| `packing.py` | Pack/split cleaned content into right-sized per-subject files at natural heading boundaries; title derivation & disambiguation. | `pack`, `split_text_by_headings`, `split_oversize`, `title_for`, `slug` | `corpus` |
| `build.py` | Build orchestration: corpus → a flat or router reference skill with `INDEX.md` + `topics.json` + a starter `SKILL.md`; `--verify` coverage audit. | `cmd_build`, `build`, `write_leaf_skill`, `write_router`, `render_file`, `verify` | `corpus`, `packing`, `ingest` (`run`), `util.repo_paths`, `util.text_io` |
| `finalize.py` | Bring a built skill up to the gold `SKILL.md` / `GOTCHA.md` standard (leaf or router). | `cmd_finalize`, `leaf_skill_md`, `router_skill_md`, `gotcha_md` | `util.config` (`VALIDATOR`) |
| `split_engine.py` | Split an oversized `references/*.md` into one file per topic, and regenerate `INDEX.md` / `topics.json` / symbol maps. Deterministic; no rewriting. | `parse_source`, `group_topics`, `assign_filenames`, `render_topic`, `pack_topics`, `regen_index`, `regen_topics`, `remap_symbols`, `_split_verify` | `corpus`, `packing`, `util.text_io` |
| `split_cmd.py` | The `split` subcommand on top of `split_engine`. | `cmd_split` | `split_engine`, `packing`, `util.text_io` |
| `maintain.py` | In-place gold maintenance of an existing skill: audit conformance, split oversize files, cross-link — leaving the bespoke `SKILL.md` / `GOTCHA.md` intact. | `cmd_maintain`, `audit`, `apply_splits`, `cross_link`, `ref_files`, `subskill_dirs` | `corpus` (`TARGET_BYTES`), `packing` (`split_text_by_headings`), `ingest` (`run`) |
| `index.py` | Build the cross-skill master `INDEX.md` (with optional `covers:` seeding). Keeps its own _rich_ frontmatter parser (block scalars + lists), distinct from the simple one in `util`. | `cmd_index`, `build_master_text`, `derive_covers`, `seed_covers_in_skill` | (stdlib) |
| `lint.py` | Read-only link/topics health check → `AI/lint/<skill>.md`. | `cmd_lint`, `lint_subskill` | `maintain` (`ref_files`, `subskill_dirs`), `util.repo_paths` |
| `recontext.py` | The `recontext` command group: primitives (`clean`/`extract`/`splice`/`gate`/`triage`) and the lifecycle (`scan`→…→`promote`). Drives `recontext_core`; the drain spawns `skill_builder.py recontext-subagent` / `skill_builder.py recontext` as subprocesses. | `cmd_recontext`, `_recon_*` | `recontext_core` (`recon`), `util.config` (`VALIDATOR`) |
| `readme.py` | Scaffold a new skill `README.md`, or re-apply the single-sourced standard's managed regions (located by markdown heading, no markers) to existing READMEs. | `cmd_readme`, `_readme_apply`, `_readme_scaffold` | (stdlib) |

## Folded-in tools (now subcommands)

These were once separate scripts; they are now subcommands of `skill_builder.py`, and each is still
runnable on its own via `python -m builder_components.<module>`.

| Module | Subcommand / `-m` entry | Responsibility | Imports from |
| --- | --- | --- | --- |
| `validate.py` | `validate` · `-m builder_components.validate` | Validate a skill package (leaf or `--package` router): required files, frontmatter, and `SKILL.md` / `INDEX.md` / `topics.json` agreement. | `util.frontmatter` |
| `policy_engine.py` | _(library — no CLI)_ | Skill-invocation policy: skill discovery, Claude/Codex settings I/O, change computation, audit/manifest reporting. No argparse, no stdout policy of its own. | `util.frontmatter` |
| `policy_cmd.py` | `policy` · `-m builder_components.policy_cmd` | The policy CLI (`audit` / `plan` / `preview` / `apply` / `restore`) on top of `policy_engine`. | `policy_engine`, `util.repo_paths` |
| `recontext_core.py` | _(library — no CLI)_ | The recontextualization **engine**: prose-unit detection; Gate A (identifiers), B (~13-word residue), C (cruft); clean/extract/splice; triage. Path-agnostic leaf, shared by `recontext` and the subagent. | (stdlib) |
| `recontext_subagent.py` | `recontext-subagent` · `-m builder_components.recontext_subagent` | The **locked, gated artifact writer** a rewriting subagent must use (`prepare`/`show`/`submit`/`audit`): derives every path internally, confines writes to one `--work-root`, runs Gates A/B/C **before** writing. | `recontext_core` |

## `util/` — single-concern shared helpers

Each holds one canonical copy of a helper that was previously duplicated across the standalone scripts.

| Module | Provides | Used by |
| --- | --- | --- |
| `frontmatter.py` | `parse_frontmatter` (simple scalar reader) + `FRONTMATTER_RE`. Was byte-identical in `validate` and `policy`. | `validate`, `policy_engine` |
| `repo_paths.py` | `_find_repo_root` (the owning VS Code project, climbing **past** per-skill repos so scratch never lands in a skill) + `_project_ai_dir`. | `build`, `lint`, `policy_cmd` |
| `text_io.py` | `write_text` — the `\n`-forcing, parent-creating writer. | `build`, `split_engine`, `split_cmd` |
| `config.py` | `VALIDATOR` — the `skill_builder.py` path embedded in generated `SKILL.md` Verification commands; callers append the `validate` subcommand token. | `finalize`, `recontext` |

Deliberately **not** consolidated (different behavior, kept with their owners): `finalize`'s
rstrip-then-newline `write`; `recontext_core`'s platform-newline `read`/`write`/`append_jsonl`;
`recontext_subagent`'s confinement-aware `_atomic_write_*`; `policy_engine`'s `_work_dir` /
`_ensure_work_gitignore` (policy-specific constants); `index`'s rich frontmatter parser (a different
function from the simple one, with a single caller).

## Design rules (for anyone extending this)

- **Stdlib only.** No third-party dependencies. Every function carries a docstring.
- **≤ 800 LOC per module (≤ 500 preferred).** A few modules sit in 500–800 as justified single-concern
  units (`recontext_core`, `recontext_subagent`, `policy_engine`, `split_engine`, `corpus`).
- **No import cycles.** The dependency graph is acyclic and layered downward: `util`, `htmlmd`, and
  `recontext_core` are leaves; `cli` sits at the top. `_assemble.py` derives the build order from this.
- **Add a subcommand** by writing a `module.py` with a `cmd_<name>(argv)` (plus a `main`/`__main__`
  guard for `-m` use) and registering it in `cli.py`'s `_COMMANDS` + `_USAGE`. Pull any genuinely
  shared helper into `util/` rather than copying it. Then rebuild the all-in-one (above).
- **Edit here, then rebuild** — never hand-edit the generated `skill_builder.py`; it is overwritten by
  `_assemble.py`.
- **Provenance:** this package was carved from the former monolithic `skill_builder.py` (plus
  `validate_skill_package.py`, `skill_policy.py`, `recontext_core.py`, `recontext_subagent.py`)
  **verbatim**, so bodies — and their docstrings/comments — match the originals; cross-module imports
  were generated from a static dependency analysis and verified by import, an undefined-name scan, and
  byte-for-byte CLI-output parity between the package and the generated all-in-one.
